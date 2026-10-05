"""The validation set is a measurement, not a spec: these tests pin its shape
and that the committed results are reproducible, never that the auditor scores
well on it. A genuine auditor miss is recorded in results.json, not a failure here."""
import json
from collections import Counter
from pathlib import Path

from auditor.validation import run_validation
from auditor.validation.cases import CASES, HONEST, PATTERNS


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_every_label_is_honest_or_a_known_pattern() -> None:
    for c in CASES:
        assert c.label == HONEST or c.label in PATTERNS, c.id
        assert c.label == HONEST or c.scenario in PATTERNS[c.label]["scenarios"], c.id


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


def test_kappa_subsets_partition_the_cases() -> None:
    rows = run_validation.evaluate()
    a = run_validation.kappa_subset_rows(rows, "scenario_a")
    b = run_validation.kappa_subset_rows(rows, "scenario_b")
    assert {r["scenario"] for r in a} == {"a"} and {r["scenario"] for r in b} == {"b"}
    assert len(a) + len(b) == len(rows) == 52
    assert len(run_validation.kappa_subset_rows(rows, "explicit_only")) == 30


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
