"""The aggregator on runs whose true difference we know, and the cold arm."""
from __future__ import annotations

import json
import random
from types import SimpleNamespace as NS

import pytest

from engine.aggregate import Run, compare_arms, load_runs, summarise
from engine.cold import parse_reply, run_cold_curriculum
from engine.provider import ScriptedProvider

EXPS = ["e1", "e2", "e3"]


def _runs(arm, mean, sd, n, rng):
    return [Run(f"{arm}{i}", arm, {e: min(1.0, max(0.0, rng.gauss(mean, sd)))
                                   for e in EXPS}) for i in range(n)]


def test_a_known_difference_is_recovered_and_the_interval_covers_it():
    rng = random.Random(1)
    runs = _runs("a", 0.50, 0.10, 20, rng) + _runs("b", 0.65, 0.10, 20, rng)
    res = compare_arms(runs, "a", "b", n_boot=2000)
    assert res["diff"] == pytest.approx(0.15, abs=0.06)
    lo, hi = res["ci95"]
    assert lo < 0.15 < hi and lo > 0
    assert res["p_permutation"] < 0.01
    assert res["cohens_d"] > 0.8


def test_the_same_arm_against_itself_rarely_looks_significant():
    """A single null comparison excludes zero about 1 time in 20 by construction,
    so check the rate over many: both the interval and the p-value should
    flag a difference in roughly 5% of identical-arm comparisons."""
    rng = random.Random(2)
    trials, ci_flags, p_flags = 100, 0, 0
    for _ in range(trials):
        runs = _runs("a", 0.5, 0.1, 15, rng) + _runs("b", 0.5, 0.1, 15, rng)
        res = compare_arms(runs, "a", "b", n_boot=300, seed=rng.randrange(10**6))
        ci_flags += not (res["ci95"][0] < 0 < res["ci95"][1])
        p_flags += res["p_permutation"] < 0.05
    assert ci_flags <= 15 and p_flags <= 15, (ci_flags, p_flags)


def test_few_runs_carry_a_warning():
    rng = random.Random(3)
    runs = _runs("a", 0.5, 0.1, 2, rng) + _runs("b", 0.6, 0.1, 2, rng)
    assert "not a measurement of the noise" in compare_arms(runs, "a", "b",
                                                             n_boot=200)["warning"]


def test_only_experiments_scored_in_every_run_are_compared():
    runs = [Run("a0", "a", {"e1": 0.5, "e2": 0.5}), Run("b0", "b", {"e1": 0.9})]
    assert compare_arms(runs, "a", "b", n_boot=100)["experiments"] == ["e1"]


def test_a_missing_arm_is_an_error():
    with pytest.raises(ValueError, match="both arms"):
        compare_arms([Run("a0", "a", {"e1": 1.0})], "a", "b")


def _write_run(root, name, arm, scores):
    d = root / name
    d.mkdir()
    (d / "run_meta.json").write_text(json.dumps({"arm": arm}))
    (d / "notebook.json").write_text(json.dumps({"run_id": name, "entries": [
        {"experiment_id": k, "score": v, "score_max": 2.0} for k, v in scores.items()]}))


def test_runs_load_from_a_directory_and_scores_are_normalised(tmp_path):
    _write_run(tmp_path, "r1", "cold", {"e1": 1.0})
    _write_run(tmp_path, "r2", "lessons", {"e1": 2.0})
    runs = load_runs([tmp_path])
    assert {r.arm: r.scores["e1"] for r in runs} == {"cold": 0.5, "lessons": 1.0}
    assert summarise(runs)["lessons"]["mean"] == 1.0


def test_a_run_without_an_arm_is_refused(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "notebook.json").write_text(json.dumps({"entries": []}))
    with pytest.raises(ValueError, match="arm is unknown"):
        load_runs([tmp_path])


# --- cold arm -----------------------------------------------------------
def test_parse_reply_takes_the_first_object_with_an_answer():
    text = 'Sure.\n{"confidence": 0.7, "answer": {"x": 1}}\n{"other": 2}'
    assert parse_reply(text) == ({"x": 1}, 0.7)
    assert parse_reply("no json here") == (None, None)
    assert parse_reply('{"answer": [1], "confidence": 3}') == ([1], None)


def test_parse_reply_tolerates_a_literal_newline_inside_a_string():
    text = '{"confidence": 0.6, "answer": {"reasoning": "line one\nline two"}}'
    assert parse_reply(text) == ({"reasoning": "line one\nline two"}, 0.6)


def test_the_cold_arm_scores_with_the_real_scorers_and_sees_no_task_text(tmp_path):
    reply = NS(content=[NS(type="text", text=json.dumps(
        {"confidence": 0.5, "answer": {"ranking": ["a", "b", "c"]}}))], usage=None)
    provider = ScriptedProvider([reply] * 6)
    res = run_cold_curriculum(provider=provider, run_id="cold1", runs_dir=tmp_path)
    nb = json.loads((res.run_dir / "notebook.json").read_text())
    assert len(nb["entries"]) == 6
    assert all(e["score"] is not None for e in nb["entries"])
    assert json.loads((res.run_dir / "run_meta.json").read_text())["arm"] == "cold"
    for call in provider.calls:
        assert call["tools"] == []
        prompt = call["messages"][0]["content"]
        assert "data/" not in prompt            # no dataset is named
