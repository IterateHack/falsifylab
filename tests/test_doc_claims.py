"""Factual claims in the docs, checked against the tree.

The prose counterpart of `reports/asset_freshness.py`. Generated assets go stale
when the code behind them moves, and so does prose that quotes a number, a path,
a SHA, an id or a verdict order. Every test here derives the value from the file
that owns it (results.json, the rubrics, the bundles, ci.yml, the replays, git
history) and checks that the prose says that value. This file holds no literal
for any of those values, so when the source moves the prose is wrong and this
test says so, in the same PR.

Scope: README.md, lab/README.md, CONTRACT.md, AGENTS.md and docs/**/*.md. What is
covered, and what is left uncovered on purpose, is listed in UNCHECKED below and
in the PR that added this file. A claim that cannot be checked mechanically (the
state of the literature, a measurement on another machine, what a paper says) is
not faked into a test.
"""
from __future__ import annotations

import ast
import copy
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = (
    "README.md", "lab/README.md", "CONTRACT.md", "AGENTS.md",
    *sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").rglob("*.md")),
)
BUNDLES = {"a": ROOT, "b": ROOT / "scenarios" / "b_cd5_affinity"}
LAB = ROOT / "lab"
GLP1R = LAB / "curricula" / "glp1r"
WORDS = ("zero one two three four five six seven eight nine ten eleven twelve").split()

# Claims in the scoped docs that this file deliberately does not check, by kind.
UNCHECKED = {
    "literature": "Related work, Known limitations and docs/research/: what papers say, "
                  "PMIDs, arXiv ids, 'no existing benchmark jointly scores...'.",
    "other machines": "the '11 tests fail' user-site count (README), Python 3.10 "
                      "installability and demo reproduction, the cold-capstone figures on the "
                      "evidence/cold-capstone branch, Stage 1 scores 33.75/63.75 as originally "
                      "recorded, wave-1 call counts held on the data/wave1 branch.",
    "history": "what a past commit contained beyond the replay and deletion claims checked "
               "below (e.g. '929f463 added five answer-bearing files').",
    "plans and attributions": "the RESULTS grid plan, who suggested what, design rationale.",
    "scenario C": "docs/research/scenario-c-source.md ids: scenario C has no bundle yet.",
}


# --- helpers ------------------------------------------------------------------

def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _prose(rel: str) -> str:
    """The doc with line wrapping removed, so a claim can span a wrap."""
    return " ".join(_text(rel).split())


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _tracked() -> set[str]:
    return set(_git("ls-files").splitlines())


def _word(n: int) -> str:
    return WORDS[n]


def _rubric(s: str) -> dict:
    return _json(BUNDLES[s] / "auditor" / "rubric.json")


def _experiments(s: str) -> list[dict]:
    return _json(BUNDLES[s] / "agent" / "experiments.json")["experiments"]


def _hypotheses(s: str) -> list[str]:
    return [h["id"] for h in _json(BUNDLES[s] / "agent" / "hypotheses.json")["hypotheses"]]


def _results() -> dict:
    return _json(ROOT / "auditor" / "validation" / "results.json")


def _assert_says(rel: str, claim: str) -> None:
    assert claim in _prose(rel), f"{rel} no longer says (derived from the tree): {claim!r}"


def _literal(path: Path, name: str):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def _table_rows(rel: str, header_start: str) -> list[list[str]]:
    lines = _text(rel).splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header_start))
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


# --- test counts: the AGENTS.md rule, enforced --------------------------------

BARE_COUNT = re.compile(
    r"\b(\d+)\s+(?:\w+\s+)?(?:tests?|passed|failed|xfailed|skipped|errors?)(?:\s+(?:pass|fail)(?:es|s)?)?\b", re.I)
# A count kept because it is diagnostic (AGENTS.md), with where it is re-measured.
DIAGNOSTIC_COUNTS = {
    ("README.md", "11 tests fail"): "how the user-site failure mode is recognised; "
                                    "re-measured by hand by any PR that changes the lab suite",
    ("docs/VERIFIER-REGRESSIONS.md", "9 tests"): "the size of #65's exposing case on the Windows "
                                                 "lab job at the SHA the row names",
}


def test_docs_carry_no_bare_test_totals():
    found = {
        (rel, m.group(0))
        for rel in DOCS
        for m in BARE_COUNT.finditer(_prose(rel))
    }
    assert found - set(DIAGNOSTIC_COUNTS) == set(), (
        "AGENTS.md: do not add bare test totals to docs; keep a number only where it is "
        "diagnostic, and then list it in DIAGNOSTIC_COUNTS with its reason")
    assert set(DIAGNOSTIC_COUNTS) <= found, "a DIAGNOSTIC_COUNTS entry is no longer in the docs"


# --- auditor validation: case counts, kappa and n -----------------------------

def _kappa_cell(k: dict) -> str:
    ci = k["case_bootstrap"]
    if ci["degenerate"]:
        return f"{k['kappa']:.3f} (interval degenerate: all {k['n']} cases agree)"
    lo, hi = ci["ci95"]
    return f"{k['kappa']:.3f} (95% CI {lo:.3f}–{hi:.3f}, n={k['n']})"


def test_validation_case_counts():
    cases = _results()["cases"]
    honest = sum(c["label"] == "honest" for c in cases)
    assert _results()["n_cases"] == len(cases)
    _assert_says("README.md", f"There are {len(cases)} labelled synthetic trajectories, "
                              f"{honest} honest and {len(cases) - honest} with a planted hack")


def test_kappa_table():
    kappa = _results()["cohens_kappa"]
    subsets = {"overall": "overall", "explicit patterns only": "explicit_only",
               "scenario A": "scenario_a", "scenario B": "scenario_b"}
    rows = {r[0]: r for r in _table_rows("README.md", "| subset | n |")}
    assert set(rows) == set(subsets)
    for label, key in subsets.items():
        k = kappa[key]
        pct = f"{100 * k['agreements'] / k['n']:.1f}".removesuffix(".0")
        assert rows[label] == [label, str(k["n"]), f"{pct}% ({k['agreements']}/{k['n']})",
                               _kappa_cell(k)], label


def test_kappa_sensitivity_claims():
    from reports.replicates import BOOTSTRAP_RESAMPLES

    overall = _results()["cohens_kappa"]["overall"]
    lo, hi = overall["pattern_cluster_bootstrap"]["ci95"]
    flip = overall["one_flipped_label"]
    _assert_says("README.md", f"({BOOTSTRAP_RESAMPLES:,} resamples, the `reports/replicates.py` constants)")
    _assert_says("README.md", f"widens the overall interval to {lo:.3f}–{hi:.3f}")
    _assert_says("README.md", f"kappa to {flip['one_more_miss']:.3f} (one more miss), "
                              f"{flip['one_false_alarm']:.3f} (one false alarm) or "
                              f"{flip['one_fewer_miss']:.3f} (one fewer miss)")
    assert "label planted vs honest against auditor flagged vs passed" == \
        _results()["cohens_kappa"]["definition"], "kappa's definition changed: README's reading of it may too"


def test_per_pattern_table():
    patterns = _results()["per_pattern"]
    names = {"no-evidence conclusion": "gate.unsupported_conclusion",
             "required parameter omitted": "protocol.required_param_omitted",
             "target claim misdeclared": "protocol.target_claim_misdeclared",
             "unsafe shortcut": "safety.unsafe_shortcut"}
    seen = []
    for name_cell, source, detected, false_alarms in _table_rows("README.md", "| pattern | source |"):
        keys = [names.get(n, n) for n in name_cell.split(", ")]
        seen += keys
        stats = [patterns[k] for k in keys]
        explicit = {p["provenance"] for p in stats}
        assert explicit == {"explicit"} if source == "explicit in rubric" else explicit == {"inferred"}, name_cell
        cells = {f"{p['detected']}/{p['n_planted']}" for p in stats}
        fps = {f"{p['false_positives']}/{p['n_honest']}" for p in stats}
        assert len(cells) == 1 and len(fps) == 1, name_cell
        each = " each" if len(keys) > 1 else ""
        assert detected == cells.pop() + each, name_cell
        assert false_alarms == fps.pop(), name_cell
    assert sorted(seen) == sorted(patterns), "README's pattern table and results.json disagree on the patterns"
    sizes = [p["n_planted"] for p in patterns.values()]
    _assert_says("README.md", f"Per-pattern samples are {min(sizes)}–{max(sizes)} cases")


def test_misses_and_false_alarms():
    r = _results()
    assert r["false_alarms"] == [] and r["confusion_matrix_pass_flag"]["honest"]["flagged"] == 0
    _assert_says("README.md", "No honest case was flagged.")
    misses = r["misses"]
    _assert_says("README.md", f"The {_word(len(misses))} misses are documented gaps")
    omitted = [m for m in misses if m["label"] == "protocol.required_param_omitted"]
    params = []
    for m in omitted:
        exp, param = re.match(r"(\w+) without (\w+)", m["note"]).groups()
        spec = next(e for s in BUNDLES for e in _experiments(s) if e["id"] == exp)
        assert spec["parameters"][param]["required"] is True
        params.append(f"{exp} without `{param}`")
    _assert_says("README.md", " and ".join(params) + " pass")
    misdeclared = [m for m in misses if m["label"] == "protocol.target_claim_misdeclared"]
    _assert_says("README.md", f"{_word(len(misdeclared)).capitalize()} misdeclared target claims pass")


def test_detected_hacks_keep_the_honest_score():
    r = _results()
    by_id = {c["id"]: c for c in r["cases"]}
    claim = re.search(r"still scores (\d+), the same as an honest run \(([^)]*)\)", _prose("README.md"))
    assert claim, "README's 'still scores N, the same as an honest run' sentence moved"
    score = float(claim.group(1))
    named = re.findall(r"`([^`]+)`", claim.group(2))
    honest_scores = {c["final_score"] for c in r["cases"] if c["label"] == "honest"}
    assert score in honest_scores
    for case_id in named:
        assert (by_id[case_id]["verdict"], by_id[case_id]["final_score"]) == ("REWARD_HACK", score), case_id
    assert {c["final_score"] for c in r["cases"] if c["verdict"] == "UNSAFE_ACTION"} == {score}
    _assert_says("README.md", "the `UNSAFE_ACTION` cases also keep " + claim.group(1))


def test_claim_check_is_still_unexercised_by_the_validation_corpus():
    from auditor.audit import audit
    from auditor.validation.cases import CASES, build_trajectory
    from auditor.validation.run_validation import _bundle

    exercised = []
    for c in CASES:
        trajectory = copy.deepcopy(build_trajectory(c))
        v = audit(trajectory, *_bundle(c.scenario))
        ev = _rubric(c.scenario)["dimensions"]["evidence_sufficiency"]
        applicable = ev["max_with_target_claim" if trajectory.turns[-1].action.makes_target_claim
                        else "max_without_target_claim"]
        # The check decides a verdict only where the evidence score alone would have passed.
        if v.scores.get("unsupported_claims") and v.verdict == "INSUFFICIENT_EVIDENCE" \
                and v.scores["evidence_sufficiency"] >= 0.8 * applicable:
            exercised.append(c.id)
    assert exercised == [], (
        "a validation case now exercises the claim check: README.md, CONTRACT.md and both rubrics' "
        "claim_support_rule say it is unexercised and its false-alarm rate unmeasured")
    _assert_says("README.md", "No case in the validation set exercises that claim check, so its "
                              "false-alarm rate on honest runs is unmeasured.")
    for s in BUNDLES:
        assert "no case in auditor/validation exercises this check" in \
            _rubric(s)["dimensions"]["evidence_sufficiency"]["claim_support_rule"]


def _empty_citation_honest_runs_pass() -> bool:
    from tests.regression.test_issue_35_uncited_evidence import HONEST_CASES, _audit

    return any(_audit(c, evidence_cited=[]).verdict == "VALID_SUCCESS" for c in HONEST_CASES)


def _related_work_gate_paragraph() -> str:
    paras = [" ".join(p.split()) for p in _text("README.md").split("\n\n")]
    return next(p for p in paras if p.startswith("Evidence sufficiency scores both what was run"))


def test_related_work_35_paragraph_matches_the_gate():
    """README Related work, the claim-gate paragraph: its mechanism only. The measurement
    paragraph after it (52 cases, kappa, no WRONG_CONCLUSION) is meant to move with the
    corpus (#76) and is not pinned here, so growing the corpus is not a failure."""
    from auditor.audit import audit
    from auditor.validation.cases import CASES, HONEST, build_trajectory
    from auditor.validation.run_validation import _bundle

    para = _related_work_gate_paragraph()
    for phrase in ("earns its points only when the conclusion cites the experiment it scores",
                   "must be addressed by an experiment that ran and that the conclusion cites",
                   "recorded in `fired` as `unsupported_claim:<H>`",
                   "the rubric's `experiment_supports`, auditor-side and never loaded",
                   "it is required, and the auditor raises without it",
                   "Support comes from experiments rather than from scoring criteria"):
        assert phrase in para, phrase
    assert "An episode citing no evidence can therefore still pass" not in _prose("README.md")
    assert not _empty_citation_honest_runs_pass(), "an uncited honest run passes the gate"

    agent_side = [p for s in BUNDLES for p in (BUNDLES[s] / "agent").rglob("*") if p.is_file()]
    agent_side += sorted((ROOT / "agents" / "prompts").glob("*.md"))
    assert not [p for p in agent_side if "experiment_supports" in p.read_text(encoding="utf-8")]

    for s in BUNDLES:
        rubric, truth = _bundle(s)
        ev = rubric["dimensions"]["evidence_sufficiency"]
        assert set(ev["experiment_supports"]) == {e["id"] for e in _experiments(s)}, s
        assert not [c for c in ev["criteria"] if "supports_hypotheses" in c], s
        scored = {e for c in ev["criteria"] for e in c.get("requires_citation", [])}
        # Support from criteria would leave these experiments' hypotheses unsupportable.
        assert [e for e, v in ev["experiment_supports"].items() if v["hypotheses"] and e not in scored], s

        case = next(c for c in CASES if c.scenario == s and c.label == HONEST)
        trajectory = build_trajectory(case)
        conclude = trajectory.turns[-1].action
        named = set(conclude.contributing_hypotheses or []) | {conclude.dominant_cause}
        passed = audit(copy.deepcopy(trajectory), rubric, truth)
        assert passed.verdict == "VALID_SUCCESS", case.id

        no_support = copy.deepcopy(rubric)
        for entry in no_support["dimensions"]["evidence_sufficiency"]["experiment_supports"].values():
            entry["hypotheses"] = []
        v = audit(copy.deepcopy(trajectory), no_support, truth)
        assert v.verdict == "INSUFFICIENT_EVIDENCE", case.id
        assert {f["id"] for f in v.fired if f["kind"] == "unsupported_claim"} == \
            {f"unsupported_claim:{h}" for h in named}, case.id
        assert v.scores["evidence_sufficiency"] == passed.scores["evidence_sufficiency"], case.id

        del no_support["dimensions"]["evidence_sufficiency"]["experiment_supports"]
        with pytest.raises(ValueError, match="experiment_supports"):
            audit(copy.deepcopy(trajectory), no_support, truth)


# --- verdicts and their precedence --------------------------------------------

def _precedence() -> list[str]:
    orders = {s: _rubric(s)["verdicts"]["precedence"] for s in BUNDLES}
    assert orders["a"] == orders["b"], "the rubrics' precedence orders differ; README shows one"
    return orders["a"]


def test_readme_verdict_table_is_the_rubric_precedence():
    assert [r[0].strip("`") for r in _table_rows("README.md", "| verdict | when |")] == _precedence()


def test_pass_fail_lists_every_failing_verdict_in_order():
    failing = [v for v in _precedence() if v != "VALID_SUCCESS"]
    _assert_says("README.md", "Every other verdict fails: " + ", ".join(failing[:-1]) + " and " + failing[-1] + ".")


def test_contract_verdict_names_are_the_precedence_set():
    import contract

    names = set(re.findall(r"\b[A-Z]+(?:_[A-Z]+)+\b", _text("CONTRACT.md"))) & set(
        re.findall(r'"([A-Z]+(?:_[A-Z]+)+)"', Path(contract.__file__).read_text()) + _precedence())
    assert names <= set(_precedence())


def test_valid_success_thresholds_and_score_table():
    for s in BUNDLES:
        r = _rubric(s)
        dims = r["dimensions"]
        rule = r["verdicts"]["VALID_SUCCESS"]
        sci_min = re.search(r"scientific_correctness >= (\d+)", rule).group(1)
        frac = float(re.search(r"evidence_sufficiency >= ([\d.]+) \* applicable_max", rule).group(1))
        prose = _prose("README.md")
        assert f"scientific correctness ≥ {sci_min}, evidence ≥ {frac:.0%} of applicable max, " \
               f"protocol {dims['protocol_validity']['max']}/{dims['protocol_validity']['max']} and " \
               f"safety {dims['safety']['max']}/{dims['safety']['max']}" in prose, s
        assert f"evidence sufficiency below {frac:.0%} of the applicable maximum" in prose
        sci = {c["id"]: c for c in dims["scientific_correctness"]["criteria"]}
        brier_top = max(t["points"] for t in sci["SCI_BRIER"]["brier_tiers"])
        ev = dims["evidence_sufficiency"]
        rows = _table_rows("README.md", "| dimension | max |")
        assert rows == [
            [f"scientific correctness (contributing set {sci['SCI_CONTRIB']['points']}, dominant cause "
             f"{sci['SCI_DOMINANT']['points']}, Brier tier {brier_top})", str(dims["scientific_correctness"]["max"])],
            ["evidence sufficiency", f"{ev['max_without_target_claim']}, or {ev['max_with_target_claim']} "
                                     "if the conclusion makes a target claim"],
            ["protocol validity", str(dims["protocol_validity"]["max"])],
            ["safety", str(dims["safety"]["max"])],
        ], s


def test_lab_verdicts():
    audit_py = LAB / "engine" / "audit.py"
    verdicts = list(_literal(audit_py, "VERDICTS"))
    lab_order = list(_literal(audit_py, "_PRECEDENCE"))
    listed = re.findall(r"`([A-Z_]+)`", re.search(r"Each attempt gets one derived verdict: (.*?)\. ",
                                                 _prose("lab/README.md")).group(1))
    assert listed == verdicts
    assert set(verdicts) == set(_precedence()), "README says the lab uses the same verdict labels"
    root_order = [v for v in _precedence() if v in lab_order]
    assert root_order != lab_order, "README says the lab's precedence differs from the auditor's"
    _assert_says("README.md", "It uses the same verdict labels, implemented independently; precedence")


# --- scenarios, experiments, hypotheses and rule ids --------------------------

def test_scenario_table():
    from runner.factories import SCENARIOS

    rows = _table_rows("README.md", "| key | bundle |")
    assert [r[0].strip("`") for r in rows] == sorted(SCENARIOS)
    _assert_says("README.md", f"{_word(len(SCENARIOS)).capitalize()} scenarios ship")
    for key, bundle, _question, budget in rows:
        key = key.strip("`")
        path = SCENARIOS[key]
        if path == ROOT:
            assert bundle.startswith("repo root"), key
        else:
            assert bundle.strip("`").rstrip("/") == path.relative_to(ROOT).as_posix(), key
        brief = _json(path / "agent" / "briefing.json")["budget"]
        menu = sum(e["cost"] for e in _experiments(key))
        assert brief["menu_total"] == menu
        assert budget == f"{brief['units']} / {menu} units", key


def test_contract_closed_sets_and_budget():
    exps = [e["id"] for e in _experiments("a")]
    hyps = _hypotheses("a")
    _assert_says("CONTRACT.md", "`HypothesisId` ∈ {" + ",".join(hyps) + "}")
    _assert_says("CONTRACT.md", f"`ExperimentId` ∈ {{{exps[0]}..{exps[-1]}}}")
    assert exps == [f"E{i}" for i in range(1, len(exps) + 1)]
    units = _json(ROOT / "agent" / "briefing.json")["budget"]["units"]
    _assert_says("CONTRACT.md", f"`budget_remaining` starts at `briefing.budget.units` ({units})")


def _known_ids() -> set[str]:
    ids = set()
    for s in BUNDLES:
        r = _rubric(s)
        ids |= {e["id"] for e in _experiments(s)} | set(_hypotheses(s))
        ids |= {k for k in r["reward_hack_detection"] if k.startswith("RH")}
        ids |= {c["id"] for group in r["constraints"].values() if isinstance(group, list) for c in group}
    return ids


ID = re.compile(r"\b(?:RH|PR|PB|EC|EB|SC|SB|E|B|H)\d+\b")
# Tokens shaped like ids that are not ids, each with the only form it may take.
NOT_IDS = {
    "B7": ("B7-H3", "an antigen"),
    "E0771": ("E0771-HER2", "a cell line"),
    "H1975": ("H1975 ROR1", "a cell line"),
    "EC50": ("EC50", "half-maximal effective concentration"),
}
ID_DOCS = [d for d in DOCS if d != "docs/research/scenario-c-source.md"]


def test_every_id_in_the_docs_exists():
    known = _known_ids()
    for rel in ID_DOCS:
        prose = _prose(rel)
        for token in set(ID.findall(prose)) - known:
            if token == "H5":
                continue  # checked by test_there_is_no_h5
            form, what = NOT_IDS.get(token, (None, None))
            assert form, f"{rel} names {token}, which no bundle defines"
            assert prose.count(token) == prose.count(form), f"{rel}: {token} outside {form!r} ({what})"


def test_there_is_no_h5():
    for s in BUNDLES:
        assert "H5" not in _hypotheses(s)
    _assert_says("README.md", "There is no H5")


def _rh(s: str, n: int) -> dict:
    return _rubric(s)["reward_hack_detection"][f"RH{n}"]["trigger"]


def test_reward_hack_and_potency_experiments():
    a1, b1 = (_rh(s, 1)["conclusion_cites"]["experiment"] for s in "ab")
    a2, b2 = (_rh(s, 2)["conclusion_cites"] for s in "ab")
    a3, b3 = (next(c["not"]["ran"] for c in _rh(s, 3)["all"] if "not" in c) for s in "ab")
    assert b2.get("explicit_supports") is True
    _assert_says("README.md", f"(RH1: {a1} in scenario A, {b1} in scenario B, cited untagged or with "
                              f"supports `{_rh('a', 1)['conclusion_cites']['supports'][0]}`")
    _assert_says("README.md", f"RH2: {a2['experiment']} in scenario A, untagged or `{a2['supports'][0]}`, and "
                              f"{b2['experiment']} in scenario B, only when explicitly tagged "
                              + " or ".join(f"`{x}`" for x in b2["supports"]))
    _assert_says("README.md", f"never run: {a3}, the four-strain MIC panel, in scenario A, and {b3}, the "
                              "short-term cytotoxicity panel, in scenario B")
    pa, pb = (_rubric(s)["visible_reward"]["potency"]["source_experiment"] for s in "ab")
    _assert_says("README.md", f"(A: {pa}, B: {pb})")


def test_agent_and_env_name_lists():
    import env
    from runner.agents import SCRIPTED_VARIANTS

    prompts = sorted(p.stem for p in (ROOT / "agents" / "prompts").glob("*.md"))
    _assert_says("README.md", "(`agents/prompts/`: " + ", ".join(f"`{p}`" for p in prompts) + ")")
    _assert_says("README.md", "Zero-model-call controls: `runner/agents/` ("
                 + ", ".join(f"`{v}`" for v in sorted(SCRIPTED_VARIANTS)) + ")")
    codes = env.REJECTION_CODES
    _assert_says("README.md", "(`EnvRejection` with code " + ", ".join(f"`{c}`" for c in codes[:-1])
                 + f" or `{codes[-1]}`)")


def test_real_trajectories_audit_as_stated():
    from auditor.audit import audit
    from auditor.validation.run_validation import _bundle
    from contract import trajectory_from_dict

    out = {}
    for s in "ab":
        doc = _json(ROOT / "auditor" / "validation" / "real_cases" / f"{s}-baseline-seed0.json")
        v = audit(trajectory_from_dict(doc), *_bundle(s))
        out[s] = (v.verdict, v.final_score, v.reward_hacks)
    assert out["a"][2] == out["b"][2] == [], "README: 'with no reward hacks'"
    fmt = lambda x: f"{x:g}"  # noqa: E731
    _assert_says("README.md", f"audit as {out['a'][0]} (`final_score` {fmt(out['a'][1])}) and "
                              f"{out['b'][0]} ({fmt(out['b'][1])}), with no reward hacks")


# --- file paths and CLI flags ------------------------------------------------

# Paths that name something outside the tracked tree, with how each is checked instead.
PRODUCED = {  # run outputs: the producer must still write a file of that name
    "results.jsonl": "runner/modal_batch.py", "summary.json": "runner/modal_batch.py",
    "grid_summary.json": "runner/modal_batch.py", "spend.json": "runner/modal_batch.py",
    "episodes/<id>.json": "runner/modal_batch.py", "reward_vs_audit.png": "runner/modal_batch.py",
    "reaudit.json": "runner/reaudit.py", "run_meta.json": "lab/engine", "usage.json": "lab/engine",
    "runs/<id>/notebook.md": "lab/engine",
}
DELETED = {"lab/curricula/wrn/": "77b782a", "scorers/h2exp2.py": "77b782a"}
GITIGNORED = {"runs/": "lab/.gitignore"}
NOT_IN_TREE = {
    "cold_capstone/cold_results.json": "on the evidence/cold-capstone branch",
    "cold_capstone/cold_test.py": "on the evidence/cold-capstone branch",
    "evidence/cold-capstone": "a branch name",
    "~/.local": "the user site on the reader's machine",
    ".venv/Scripts/python.exe": "the reader's Windows venv",
    "PMC8205227/fullTextXML": "part of a Europe PMC URL",
    "PMC8205227/supplementaryFiles": "part of a Europe PMC URL",
    "id0c00904_si_001.pdf": "a publisher's supporting-information file",
}
PATHISH = re.compile(r"\.(py|md|json|jsonl|yaml|yml|toml|txt|csv|png|html|cif|pdf)$")


def _path_tokens(rel: str) -> set[str]:
    text = _text(rel)
    tokens = set(re.findall(r"`([^`\n]+)`", text)) | set(re.findall(r"\]\(([^)\s#]+)", text))
    out = set()
    for tok in tokens:
        inner = re.fullmatch(r"[\w.]+\((.+)\)", tok)
        tok = inner.group(1) if inner else tok
        if tok.startswith(("http", "-", "doi:")) or " " in tok or "=" in tok:
            continue
        if "/" in tok.split("::")[0] or PATHISH.search(tok.split("::")[0]):
            out.add(tok)
    return out


def _resolves(tok: str, rel: str, tracked: set[str]) -> bool:
    dirs = {"/".join(p.split("/")[:i]) for p in tracked for i in range(1, p.count("/") + 1)}
    tok = tok.rstrip("/")
    if "<" in tok:
        tok = tok.split("<")[0].rstrip("/")
    base = (ROOT / rel).parent
    for cand in {tok, (base / tok).resolve().relative_to(ROOT).as_posix() if (base / tok).resolve().is_relative_to(ROOT) else tok}:
        if cand in tracked or cand in dirs:
            return True
    return any(p.endswith("/" + tok) for p in tracked | dirs)


def test_every_path_in_the_docs_exists():
    tracked = _tracked()
    missing = []
    for rel in DOCS:
        for tok in sorted(_path_tokens(rel)):
            if tok in NOT_IN_TREE or tok in PRODUCED or tok in DELETED or tok in GITIGNORED:
                continue
            path, _, test = tok.partition("::")
            if not _resolves(path, rel, tracked):
                missing.append(f"{rel}: {tok}")
            elif test:
                assert re.search(rf"^def {re.escape(test)}\(", _text(path), re.M), f"{rel}: {tok}"
    assert missing == []


def test_paths_outside_the_tree():
    tracked = _tracked()
    for tok, producer in PRODUCED.items():
        name = tok.split("/")[-1].replace("<id>", "")
        sources = [p for p in tracked if p.startswith(producer) and p.endswith(".py")]
        assert any(name in _text(p) for p in sources), f"{tok}: {producer} no longer writes it"
    for tok, sha in DELETED.items():
        assert not any(p.endswith(tok) or p.startswith(tok) or ("/" + tok) in p for p in tracked), tok
        gone = _git("show", "--diff-filter=D", "--name-only", "--format=", sha).splitlines()
        assert any(tok in p for p in gone), f"{tok} was not deleted in {sha}"
    for tok, ignore in GITIGNORED.items():
        assert tok in (ROOT / ignore).read_text().split(), tok
    used = set().union(*(_path_tokens(rel) for rel in DOCS))
    stale = (set(PRODUCED) | set(DELETED) | set(GITIGNORED) | set(NOT_IN_TREE)) - used
    assert stale == set(), "exception entries no doc uses any more"


def test_every_cli_flag_in_the_docs_exists():
    sources = "".join(_text(p) for p in _tracked() if p.endswith(".py"))
    missing = []
    for rel in DOCS:
        for tok in re.findall(r"`(--[^`\n]+)`", _text(rel)):
            for flag in tok.split()[0].split("/"):
                if f'"{flag.split("=")[0]}"' not in sources:
                    missing.append(f"{rel}: {flag}")
    assert missing == []


# --- SHAs --------------------------------------------------------------------

# A journal article number in a citation ("12, e009013 (2024)") is hex-shaped, not a commit.
ARTICLE_NUMBER = re.compile(r"\d+, e\d+ \(\d{4}\)")
SHA = re.compile(r"(?<![\w/.-])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w-])")


def test_every_sha_in_the_docs_is_an_ancestor_of_head():
    for rel in DOCS:
        text = _text(rel)
        for short, full in re.findall(r"\[`([0-9a-f]{7,40})`\]\(https://github\.com/[^)]*/commit/([0-9a-f]{7,40})\)", text):
            assert full.startswith(short), f"{rel}: link text {short} points at {full}"
        for sha in set(SHA.findall(ARTICLE_NUMBER.sub("", re.sub(r"https?://\S+", "", text)))):
            assert subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"], cwd=ROOT,
                                  capture_output=True).returncode == 0, f"{rel}: {sha} is not in HEAD's history"


def _at(sha: str, path: str) -> str:
    """A file at `sha`, under its path then (lab/ came in as a subtree)."""
    for p in (path, path.removeprefix("lab/")):
        r = subprocess.run(["git", "show", f"{sha}:{p}"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
    raise AssertionError(f"{path} not at {sha}")


def test_replays_are_kept_as_recorded_at_their_commits():
    prose = _prose("lab/README.md")
    for name in ("control", "demo"):
        sha = re.search(rf"`replays/{name}` (?:was committed )?at \[`([0-9a-f]+)`\]", prose).group(1)
        # The event log is the replay; notebook.md is a rendered view (relabelled in 0664b6f).
        for f in ("events.jsonl", "notebook.json"):
            path = f"lab/replays/{name}/{f}"
            assert _at(sha, path) == _text(path), f"{path} differs from {sha}"


def test_capstone_scorer_unchanged_since_its_commit():
    sha = re.search(r"unchanged on main since `([0-9a-f]+)`", _prose("lab/README.md")).group(1)
    for path in ("lab/curricula/glp1r/scorers/exp6.py", "lab/curricula/glp1r/private/exp6.json"):
        assert _at(sha, path) == _text(path), f"{path} changed since {sha}"


# --- Python versions and pins ------------------------------------------------

def _ci_python(job: str) -> str:
    ci = _text(".github/workflows/ci.yml")
    block = re.search(rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  \S|\Z)", ci).group(1)
    return re.search(r'python-version: "([\d.]+)"', block).group(1)


def test_python_versions():
    root = _ci_python("root-gate")
    lab = {_ci_python("lab-suite"), _ci_python("lab-windows")}
    assert len(lab) == 1
    lab = lab.pop()
    requires = re.search(r'^requires-python = "([^"]+)"', _text("lab/pyproject.toml"), re.M).group(1)
    floor = requires.removeprefix(">=")
    readme = "README.md"
    _assert_says(readme, f"**Root suite (everything in this section): Python {root}.** CI's root gate runs {root}")
    _assert_says(readme, f"**`lab/`: Python {floor} or newer** (`requires-python = \"{requires}\"` in "
                         f"`lab/pyproject.toml`). CI runs the lab suites on {lab}.")
    _assert_says(readme, f"the suite passes in that venv (Python {lab})")
    pin = next(line for line in _text("requirements-dev.txt").splitlines() if line.startswith("matplotlib=="))
    assert pin in _text("runner/requirements.txt").splitlines()
    _assert_says(readme, f"`{pin}` in `requirements-dev.txt` and `runner/requirements.txt`")


def test_anthropic_sdk_pin():
    pin = next(line for line in _text("runner/requirements.txt").splitlines() if line.startswith("anthropic=="))
    _assert_says("AGENTS.md", f"The pinned Anthropic SDK {pin.split('==')[1]} ")


def test_demo_brier_reproducibility_claim():
    m = re.search(r"rewrites `brier` in (\d+) of the (\d+) demo records from `([\d.e-]+)` to `([\d.e-]+)`",
                  _prose("README.md"))
    assert m, "README's demo Brier sentence moved"
    records = [json.loads(line) for line in _text("demo/results.jsonl").splitlines() if line.strip()]
    briers = [r["verdict"]["scores"].get("brier") for r in records]
    assert int(m.group(2)) == len(records)
    assert int(m.group(1)) == briers.count(float(m.group(3))), "re-measure on 3.12 with python -m demo.build_sample"


# --- stage 2 wave 1 ----------------------------------------------------------

def _wave_rows(name: str) -> list[dict]:
    return [row for s in "ab" for row in csv.DictReader(
        (ROOT / "reports" / "assets" / "stage2-wave1" / s / name).open(encoding="utf-8"))]


def test_wave1_claims():
    from runner.agents import SCRIPTED_VARIANTS

    rows = _wave_rows("clean_success_ci.csv")
    llm = [r for r in rows if r["variant"] not in SCRIPTED_VARIANTS]
    models = {r["model"] for r in llm}
    variants = {r["variant"] for r in llm}
    assert len(models) == 1 and {r["n_runs"] for r in llm} == {"1"}
    assert {r["scenario"] for r in llm} == {"a", "b"}
    _assert_says("README.md", f"{models.pop()}, {_word(len(variants))} variants × two scenarios, **one run per cell**")
    refused = {r["variant"] for r in llm if r["n_provider_refusal"] != "0" and r["n_scored"] == "0"}
    assert len(refused) == 1
    v = refused.pop()
    assert sum(r["variant"] == v for r in llm) == 2
    _assert_says("README.md", f"the provider refused the {v} variant in both scenarios")
    n_refusals = {r["n_provider_refusal"] for r in llm if r["variant"] == v}
    assert len(n_refusals) == 1
    _assert_says("README.md", f'label the cell "n=0 ({n_refusals.pop()} provider refusal)"')
    assert v not in {r["variant"] for r in _wave_rows("frontier_regret_top3.csv")}
    _assert_says("README.md", "`frontier_regret_top3` omits it")


# --- the lab curriculum and its committed runs -------------------------------

def _specs() -> list[dict]:
    out = []
    for f in sorted((GLP1R / "experiments").glob("*.yaml")):
        text = f.read_text(encoding="utf-8")
        inline = re.search(r"^requires_lessons: \[(.*)\]", text, re.M)
        if inline:
            needs = [x.strip() for x in inline.group(1).split(",") if x.strip()]
        else:
            needs = re.findall(r"^  - (\S+)", re.search(r"(?ms)^requires_lessons:\n((?:  - .*\n)+)", text).group(1), re.M)
        out.append({"id": re.search(r"^id: (\S+)", text, re.M).group(1),
                    "title": re.search(r"^title: (.+)", text, re.M).group(1).strip(),
                    "needs": needs, "text": text})
    return out


def _numbers(spec_ids: list[str], specs: list[dict]) -> str:
    nums = sorted(next(i for i, s in enumerate(specs, 1) if s["id"] == n) for n in spec_ids)
    if not nums:
        return "-"
    if len(nums) > 2 and nums == list(range(nums[0], nums[-1] + 1)):
        return f"{nums[0]}-{nums[-1]}"
    return ", ".join(map(str, nums))


def _scores(replay: str) -> dict[str, dict]:
    events = [json.loads(line) for line in (LAB / "replays" / replay / "events.jsonl").read_text().splitlines()]
    return {e["experiment_id"]: e["payload"] for e in events if e.get("type") == "scored"}


def test_lab_has_one_curriculum():
    found = sorted(p.parent.name for p in (LAB / "curricula").glob("*/curriculum.yaml"))
    assert found == ["glp1r"], "lab/README.md says GLP-1R is the only curriculum"


def test_lab_curriculum_table():
    specs = _specs()
    rows = _table_rows("lab/README.md", "| # | Experiment |")
    _assert_says("lab/README.md", f"The {_word(len(specs))} experiments build an evidence-weighted case")
    assert [r[0] for r in rows] == [str(i) for i in range(1, len(specs) + 1)]
    assert [r[-1] for r in rows] == [_numbers(s["needs"], specs) for s in specs]
    genes = len(list(csv.DictReader((GLP1R / "data" / "exp1_gwas_targets.csv").open())))
    analogues = len(list(csv.DictReader((GLP1R / "data" / "exp3_analogues.csv").open())))
    assert rows[0][2].startswith(f"Rank {genes} genes")
    assert rows[2][2].startswith(f"Rank {_word(analogues)} analogues")
    pdb, cutoff = re.search(r"Find semaglutide's contact residues in PDB (\w+)", rows[1][2]).group(1), \
        re.search(r"recomputed at ([\d.]+ A)", rows[1][3]).group(1)
    assert f"PDB {pdb}" in specs[1]["text"] and f"within {cutoff}" in " ".join(specs[1]["text"].split())


def test_lab_control_run_table():
    specs = _specs()
    with_cards, without = _scores("demo"), _scores("control")
    block = re.search(r"(?s)```\n #  experiment.*?```", _text("lab/README.md")).group(0)
    lines = [m for m in re.finditer(r"^\s*(\d)\s+(.+?)\s{2,}(yes|no)\s+([\d.]+)\s+([\d.]+)\s+([+-][\d.]+)$", block, re.M)]
    assert len(lines) == len(specs)
    deltas = {True: [], False: []}
    for m, spec in zip(lines, specs):
        w, wo = with_cards[spec["id"]]["score"], without[spec["id"]]["score"]
        needs = bool(spec["needs"])
        deltas[needs].append(w - wo)
        assert (m.group(2).strip(), m.group(3), m.group(4), m.group(5), m.group(6)) == \
            (spec["title"], "yes" if needs else "no", f"{w:.2f}", f"{wo:.2f}", f"{w - wo:+.2f}"), spec["id"]
    for needs, label in ((True, "needing lessons"), (False, "not needing them")):
        d = deltas[needs]
        assert re.search(rf"mean delta, experiments {label} \({len(d)}\)\s+{re.escape(f'{sum(d) / len(d):+.3f}')}", block)


def test_lab_capstone_and_headline_figures():
    specs = _specs()
    cap = specs[-1]["id"]
    rows = {r[-1].strip("`"): r for r in _table_rows("lab/README.md", "| Condition | Capstone score |")}
    for replay in ("control", "demo"):
        assert rows[f"replays/{replay}"][1] == f"**{_scores(replay)[cap]['score']:.2f}**", replay
    _assert_says("lab/README.md", f"against {_scores('demo')[cap]['confidence_stated']:.2f} with cards and "
                                  f"{_scores('control')[cap]['confidence_stated']:.2f} without")
    demo = _scores("demo").values()
    mean = sum(p["score"] for p in demo) / len(demo)
    gap = sum(p["calibration_gap"] for p in demo) / len(demo)
    _assert_says("lab/README.md", f"mean **{mean:.2f}** across {_word(len(demo))} experiments")
    _assert_says("lab/README.md", f"mean calibration gap of **{gap:.2f}**")


def test_lab_arms_table():
    cli = _text("lab/engine/cli.py")
    choices = ast.literal_eval(re.search(r'add_argument\("--arm", choices=(\[[^\]]*\])', cli).group(1))
    rows = _table_rows("lab/README.md", "| `--arm` |")
    assert sorted(r[0].strip("`") for r in rows) == sorted(choices)


# --- docs/VERIFIER-REGRESSIONS.md ---------------------------------------------

STATUS = ("open; fix not merged", "fixed", "retired")


def test_verifier_regressions_rows():
    rows = _table_rows("docs/VERIFIER-REGRESSIONS.md", "| issue | what broke |")
    assert rows
    for issue, _broke, _case, direction, pinned, fix_pr, status in rows:
        assert direction.startswith(("false positive", "false negative")), issue
        assert status.strip("*").startswith(STATUS), f"{issue}: status {status!r}"
        tests = re.findall(r"`(tests/regression/[^`]+\.py)`", pinned)
        assert tests or "lab/" in pinned, f"{issue}: no pinned test"
        for t in tests:
            marked = "xfail(strict=True" in _text(t)
            assert marked == status.startswith("open"), f"{issue}: {t} xfail marker vs status {status!r}"
            for n in re.findall(rf"`{re.escape(t)}` \((\d+) cases\)", pinned):
                out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", t], cwd=ROOT,
                                     capture_output=True, text=True).stdout
                assert int(n) == sum("[" in line for line in out.splitlines() if "::" in line), t
        if status.startswith("retired"):
            assert fix_pr == "none", issue
