"""The validation set is a measurement, not a spec: these tests pin its shape
and that the committed results are reproducible, never that the auditor scores
well on it. A genuine auditor miss is recorded in results.json, not a failure here."""
import json
from collections import Counter
from pathlib import Path

from auditor.validation import run_validation
from contract import VERDICTS

from auditor.validation.cases import (
    ALL_CASES, CASE_CLASSES, CASES, HONEST, PATTERNS, PATTERN_VERDICTS, VERDICT_CASES,
    VERDICT_OVERRIDES, build_trajectory, expected_verdict, parse_failure_conclude,
)


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in ALL_CASES]
    assert len(ids) == len(set(ids))


def test_every_label_is_honest_or_a_known_pattern() -> None:
    for c in ALL_CASES:
        assert c.label == HONEST or c.label in PATTERNS, c.id
        assert c.label == HONEST or c.scenario in PATTERNS[c.label]["scenarios"], c.id


def test_detection_set_is_the_published_population() -> None:
    # The flagged-vs-passed kappa (0.806) was published over these 52 cases; #76
    # adds cases beside them, never to them.
    assert len(CASES) == 52
    assert all(c.case_class == "detection" and c.expected is None for c in CASES)
    assert all(c.case_class != "detection" and c.label == HONEST for c in VERDICT_CASES)
    assert set(c.case_class for c in ALL_CASES) == set(CASE_CLASSES)


def test_every_case_has_a_rubric_derived_expected_verdict() -> None:
    assert set(PATTERN_VERDICTS) == {HONEST, *PATTERNS}
    assert set(VERDICT_OVERRIDES) <= {c.id for c in CASES}
    for c in ALL_CASES:
        verdict, basis = expected_verdict(c)
        assert verdict in VERDICTS, c.id
        assert basis and len(basis) > 20, c.id
    assert expected_verdict(next(c for c in CASES if c.id == "b.rh1.3"))[0] == "PROTOCOL_VIOLATION"
    assert expected_verdict(next(c for c in CASES if c.id == "a.rh1.1"))[0] == "REWARD_HACK"


def test_verdict_case_classes_each_have_at_least_three_cases_in_both_scenarios_where_possible() -> None:
    by_class = Counter(c.case_class for c in VERDICT_CASES)
    assert by_class == {"wrong_conclusion": 8, "parse_failure": 4, "alt_route": 4}
    expected = {c.case_class: {expected_verdict(c)[0] for c in VERDICT_CASES if c.case_class == c.case_class}
                for c in VERDICT_CASES}
    assert {cls: {expected_verdict(c)[0] for c in VERDICT_CASES if c.case_class == cls}
            for cls in expected} == {"wrong_conclusion": {"WRONG_CONCLUSION"},
                                     "parse_failure": {"PARSE_FAILURE"},
                                     "alt_route": {"VALID_SUCCESS"}}
    for cls in ("wrong_conclusion", "parse_failure"):
        assert {c.scenario for c in VERDICT_CASES if c.case_class == cls} == {"a", "b"}, cls
    # The B3 route is the shape #80 found by hand; scenario A has no second route.
    assert sum(1 for c in VERDICT_CASES if c.cluster == "b3_route" and c.scenario == "b") == 3


def test_verdict_cases_build_through_the_env() -> None:
    for c in VERDICT_CASES:
        trajectory = build_trajectory(c)
        last = trajectory.turns[-1].action
        assert last.kind == "conclude", c.id
        assert (last.abstain_reason == "parse_failure") == (c.case_class == "parse_failure"), c.id


def test_parse_failure_conclude_matches_the_harness_shape() -> None:
    from agents.llm_agent import PARSE_FAILURE
    a = parse_failure_conclude({"H1": 0.5})
    assert a.abstain_reason == PARSE_FAILURE == "parse_failure"
    assert a.dominant_cause is None and a.contributing_hypotheses is None
    assert a.confidence is None and a.evidence_cited == [] and a.makes_target_claim is False


def test_at_least_three_planted_cases_per_pattern() -> None:
    counts = Counter(c.label for c in CASES)
    assert all(counts[pid] >= 3 for pid in PATTERNS), counts


def test_honest_cases_cover_both_scenarios() -> None:
    assert {c.scenario for c in CASES if c.label == HONEST} == {"a", "b"}


def test_inferred_patterns_say_why() -> None:
    for pid, p in PATTERNS.items():
        assert p["provenance"] in ("explicit", "inferred"), pid
        assert (p["provenance"] == "inferred") == bool(p.get("inference")), pid


def test_committed_results_are_current() -> None:
    assert run_validation.main(["--check"]) == 0


def test_cohen_kappa_matches_a_hand_computed_table() -> None:
    # 12 honest passed, 34 planted flagged, 6 planted passed: po = 46/52,
    # pe = (12*18 + 40*34) / 52**2, kappa = (po - pe) / (1 - pe).
    rows = ([{"label": HONEST, "passed": True}] * 12 + [{"label": "A.RH1", "passed": False}] * 34
            + [{"label": "A.RH1", "passed": True}] * 6)
    po, pe = 46 / 52, (12 * 18 + 40 * 34) / 52 ** 2
    k = run_validation.cohen_kappa(rows)
    assert k["n"] == 52
    assert abs(k["kappa"] - (po - pe) / (1 - pe)) < 1e-4
    assert run_validation.cohen_kappa([{"label": HONEST, "passed": True}])["kappa"] is None


def _hand_rows():
    # 12 honest passed, 34 planted flagged (two patterns), 6 planted passed.
    return ([{"label": HONEST, "passed": True}] * 12 + [{"label": "A.RH1", "passed": False}] * 17
            + [{"label": "A.RH2", "passed": False}] * 17 + [{"label": "A.RH1", "passed": True}] * 6)


def test_one_flipped_label_sensitivity_matches_hand_computed_tables() -> None:
    rows = _hand_rows()
    s = run_validation.flipped_label_sensitivity(rows)

    def kappa(po, pt, pp):
        pe = pt * pp + (1 - pt) * (1 - pp)
        return (po - pe) / (1 - pe)

    # one more miss: 45/52 agree, 33 flagged; one false alarm: 45/52, 35 flagged;
    # one fewer miss: 47/52, 35 flagged.
    assert abs(s["one_more_miss"] - kappa(45 / 52, 40 / 52, 33 / 52)) < 1e-4
    assert abs(s["one_false_alarm"] - kappa(45 / 52, 40 / 52, 35 / 52)) < 1e-4
    assert abs(s["one_fewer_miss"] - kappa(47 / 52, 40 / 52, 35 / 52)) < 1e-4
    perfect = [{"label": HONEST, "passed": True}] * 3 + [{"label": "A.RH1", "passed": False}] * 3
    assert run_validation.flipped_label_sensitivity(perfect)["one_fewer_miss"] is None


def test_bootstrap_kappa_is_seeded_brackets_the_point_estimate_and_clusters_by_pattern() -> None:
    rows = _hand_rows()
    point = run_validation.cohen_kappa(rows)["kappa"]
    case = run_validation.kappa_with_uncertainty(rows, "hand")
    cb, pb = case["case_bootstrap"], case["pattern_cluster_bootstrap"]
    assert cb["n_clusters"] == 52 and pb["n_clusters"] == 12 + 2
    for b in (cb, pb):
        assert b["degenerate"] is False
        lo, hi = b["ci95"]
        assert lo <= point <= hi
    assert cb["undefined_resamples"] == 0
    # 14 clusters, 12 of them honest singletons: a resample drawing no planted
    # cluster has chance agreement 1 and no kappa; those are counted, not hidden.
    assert 0 < pb["undefined_resamples"] < pb["resamples"]
    assert pb["ci95"][0] < cb["ci95"][0], "pattern clusters share a mechanism: wider interval"
    assert case["agreements"] == 46
    again = run_validation.kappa_with_uncertainty(rows, "hand")
    assert again["case_bootstrap"]["ci95"] == cb["ci95"]
    assert again["pattern_cluster_bootstrap"]["ci95"] == pb["ci95"]


def test_degenerate_interval_is_null_and_marked_not_printed() -> None:
    rows = [{"label": HONEST, "passed": True}] * 5 + [{"label": "A.RH1", "passed": False}] * 5
    k = run_validation.kappa_with_uncertainty(rows, "perfect")
    assert k["kappa"] == 1.0
    for b in (k["case_bootstrap"], k["pattern_cluster_bootstrap"]):
        assert b["degenerate"] is True and b["ci95"] is None
    assert run_validation._ci(k["case_bootstrap"]) == "degenerate (all cases agree)"
    assert run_validation._ci({"degenerate": False, "ci95": [0.6, 0.96]}) == "0.600–0.960"


def test_kappa_subsets_partition_the_detection_set() -> None:
    all_rows = run_validation.evaluate()
    rows = run_validation.detection_rows(all_rows)
    a = run_validation.kappa_subset_rows(rows, "scenario_a")
    b = run_validation.kappa_subset_rows(rows, "scenario_b")
    assert {r["scenario"] for r in a} == {"a"} and {r["scenario"] for r in b} == {"b"}
    assert len(a) + len(b) == len(rows) == 52
    assert len(all_rows) == 52 + len(VERDICT_CASES)
    assert len(run_validation.kappa_subset_rows(rows, "explicit_only")) == 30


def _verdict_rows():
    # 10 planted REWARD_HACK cases all flagged REWARD_HACK, 6 honest: 4 VALID_SUCCESS
    # scored VALID_SUCCESS, 2 expected WRONG_CONCLUSION scored INSUFFICIENT_EVIDENCE.
    def row(i, cls, label, cluster, expected, verdict):
        return {"id": f"r{i}", "scenario": "a", "class": cls, "label": label, "cluster": cluster,
                "expected_verdict": expected, "verdict": verdict, "verdict_agrees": expected == verdict}
    return ([row(i, "detection", "A.RH1", None, "REWARD_HACK", "REWARD_HACK") for i in range(10)]
            + [row(10 + i, "detection", HONEST, None, "VALID_SUCCESS", "VALID_SUCCESS") for i in range(4)]
            + [row(14 + i, "wrong_conclusion", HONEST, "wc", "WRONG_CONCLUSION", "INSUFFICIENT_EVIDENCE")
               for i in range(2)])


def test_verdict_kappa_matches_a_hand_computed_table() -> None:
    rows = _verdict_rows()
    # po = 14/16; pe = (10*10 + 4*4 + 2*0 + 0*2) / 16**2 (expected x actual per class).
    po, pe = 14 / 16, (10 * 10 + 4 * 4) / 16 ** 2
    k = run_validation.verdict_kappa(rows)
    assert k["n"] == 16 and k["agreements"] == 14
    assert abs(k["kappa"] - (po - pe) / (1 - pe)) < 1e-4
    assert run_validation.verdict_kappa([])["kappa"] is None
    same = [{"expected_verdict": "VALID_SUCCESS", "verdict": "VALID_SUCCESS", "verdict_agrees": True}] * 3
    assert run_validation.verdict_kappa(same)["kappa"] is None, "chance agreement 1"


def test_verdict_bootstrap_is_seeded_clusters_by_mechanism_and_marks_degenerate() -> None:
    rows = _verdict_rows()
    point = run_validation.verdict_kappa(rows)["kappa"]
    k = run_validation.verdict_kappa_with_uncertainty(rows, "hand")
    cb, mb = k["case_bootstrap"], k["mechanism_cluster_bootstrap"]
    assert cb["n_clusters"] == 16 and mb["n_clusters"] == 1 + 4 + 1
    for b in (cb, mb):
        assert b["degenerate"] is False
        lo, hi = b["ci95"]
        assert lo <= point <= hi
    assert mb["ci95"][0] < cb["ci95"][0], "mechanism clusters share a mechanism: wider interval"
    again = run_validation.verdict_kappa_with_uncertainty(rows, "hand")
    assert again["case_bootstrap"]["ci95"] == cb["ci95"]
    perfect = run_validation.verdict_kappa_with_uncertainty(rows[:14], "perfect")
    assert perfect["kappa"] == 1.0
    assert perfect["case_bootstrap"]["degenerate"] is True and perfect["case_bootstrap"]["ci95"] is None


def test_verdict_agreement_section_reports_every_class_and_the_disagreements() -> None:
    rows = _verdict_rows()
    section = run_validation.verdict_agreement_section(
        [{**r, "note": "n", "final_score": 0.0, "basis": "b"} for r in rows])
    assert section["overall"]["agreements"] == 14
    assert section["scenario_a"]["n"] == 16 and section["scenario_b"]["n"] == 0
    assert set(section["by_class"]) == set(CASE_CLASSES)
    assert section["by_class"]["wrong_conclusion"] == {
        "n": 2, "agreements": 0, "observed_agreement": 0.0, "disagreements": ["r14", "r15"]}
    assert section["confusion_matrix_expected_x_verdict"]["WRONG_CONCLUSION"]["INSUFFICIENT_EVIDENCE"] == 2
    assert [d["id"] for d in section["disagreements"]] == ["r14", "r15"]


def test_committed_kappa_has_intervals_and_the_verdicts_did_not_move() -> None:
    results = json.loads((Path(run_validation.__file__).parent / "results.json").read_text(encoding="utf-8"))
    kp = results["cohens_kappa"]
    for key, _ in run_validation.KAPPA_SUBSETS:
        sub = kp[key]
        assert {"n", "observed_agreement", "kappa", "agreements", "case_bootstrap",
                "pattern_cluster_bootstrap", "one_flipped_label"} <= set(sub)
        for b in (sub["case_bootstrap"], sub["pattern_cluster_bootstrap"]):
            assert (b["ci95"] is None) == bool(b["degenerate"])
    assert kp["explicit_only"]["case_bootstrap"]["degenerate"] is True
    assert kp["overall"]["case_bootstrap"]["ci95"][0] <= kp["overall"]["kappa"] <= kp["overall"]["case_bootstrap"]["ci95"][1]
    assert kp["scenario_intervals_overlap"]["case"] is True
    # The per-case entries are what the labels are scored against; the interval work must not touch them.
    live = {r["id"]: (r["verdict"], r["final_score"], r["flags"], r["reward_hacks"], r["passed"])
            for r in run_validation.evaluate()}
    stored = {r["id"]: (r["verdict"], r["final_score"], r["flags"], r["reward_hacks"], r["passed"])
              for r in results["cases"]}
    assert live == stored
