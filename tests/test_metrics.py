"""metrics.summarise: PARSE_FAILURE episodes are held out of every science
metric and reported per model on their own. Episodes are driven through the
live Env with a stub model client; verdicts are hand-built."""
import json
from pathlib import Path

import pytest

from agents.llm_agent import LLMAgent
from contract import Verdict
from env import Env
from metrics import SCIENCE_METRICS, Episode, format_report, summarise

REPO = Path(__file__).resolve().parents[1]
E1 = next(e for e in json.loads((REPO / "agent/experiments.json").read_text())["experiments"] if e["id"] == "E1")
E1_PARAMS = {n: s["values"][0] if "values" in s else s["range"][1] for n, s in E1["parameters"].items()}
B = {"H1": 0.5, "H2": 0.5, "H3": 0.5, "H4": 0.5}


class StubClient:
    def __init__(self, *replies):
        self.replies = list(replies)

    def complete(self, system, messages):
        return self.replies.pop(0)


def _reply(**doc):
    return json.dumps({"beliefs": B, "dominant_cause": None, **doc})


RUN_E1 = _reply(kind="run_experiment", experiment_id="E1", parameters=E1_PARAMS)


def _conclude(cause):
    return _reply(kind="conclude", dominant_cause=cause, contributing_hypotheses=[cause] if cause else [],
                  confidence=0.6 if cause else None, evidence_cited=[], makes_target_claim=False)


def _episode(model, replies, verdict, brier=None):
    agent = LLMAgent("prompt", StubClient(*replies), model_name=model)
    env = Env()
    obs = env.reset()
    while True:
        action = agent.act(obs, env.state)
        obs = env.step(action)
        if action.kind == "conclude":
            break
    scores = {} if brier is None else {"brier": brier}
    v = Verdict(verdict=verdict, flags=[], scores=scores, raw_total=0.0, R_visible=0.0, final_score=0.0)
    return Episode(agent, env.trajectory, v)


def _sweep():
    return [
        _episode("m", [RUN_E1, _conclude("H1")], "VALID_SUCCESS", brier=0.1),
        _episode("m", [_conclude("H2")], "REWARD_HACK", brier=0.3),
        _episode("m", [_conclude(None)], "INSUFFICIENT_EVIDENCE", brier=0.2),
        _episode("m", ["not json", "still not json"], "PARSE_FAILURE"),
        _episode("other", [_conclude("H1")], "VALID_SUCCESS", brier=0.0),
    ]


def test_parse_failure_episodes_are_excluded_from_every_science_metric():
    row = summarise(_sweep())["m"]
    assert (row["episodes"], row["scored_episodes"], row["parse_failure_episodes"]) == (4, 3, 1)
    for name in SCIENCE_METRICS:
        assert row[name]["n"] == 3 and row[name]["excluded"] == 1, name
    assert row["valid_success_rate"]["value"] == pytest.approx(1 / 3)
    assert row["reward_hack_rate"]["value"] == pytest.approx(1 / 3)
    assert row["mean_brier"]["value"] == pytest.approx(0.2)
    assert row["mean_cost"]["value"] == pytest.approx(E1["cost"] / 3)


def test_a_parse_failure_is_not_an_abstention():
    row = summarise(_sweep())["m"]
    assert row["abstention_rate"]["value"] == pytest.approx(1 / 3)   # only the chosen abstain


def test_parse_failure_rate_comes_from_the_harness_per_model():
    report = summarise(_sweep())
    m = report["m"]
    assert (m["parse_failures"], m["model_calls"]) == (2, 6)
    assert m["parse_failure_rate"] == pytest.approx(2 / 6)
    assert m["parse_failure_episode_rate"] == pytest.approx(1 / 4)
    assert report["other"]["parse_failure_rate"] == 0.0
    assert report["other"]["valid_success_rate"]["excluded"] == 0


def test_a_harness_parse_failure_scored_as_anything_else_raises():
    ep = _episode("m", ["x", "y"], "INSUFFICIENT_EVIDENCE")
    with pytest.raises(ValueError, match="parse_failure"):
        summarise([ep])


def test_formatted_report_shows_excluded_count_beside_every_rate():
    text = format_report(summarise(_sweep()))
    for name in SCIENCE_METRICS:
        assert any(name in line and "excluded=1 PARSE_FAILURE" in line for line in text.splitlines())
    assert "parse_failure_rate 0.333 (2/6 replies)" in text
