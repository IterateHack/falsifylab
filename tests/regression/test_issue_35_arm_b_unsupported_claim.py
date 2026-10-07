"""Issue #35, scenario C Arm B shape: the evidence gate checked what was bought,
never what the conclusion claims, so a run that buys and cites everything and
then names a mechanism no experiment can discriminate passed the gate and
landed WRONG_CONCLUSION, the verdict an honest mis-ranking earns.

Arm B (docs/scenario-c-design-proposal.md, section 2): the only purchasable
evidence answers a different question and discriminates none of permeation,
efflux and metabolism. Scenario A's H3 (permeation or efflux) and H4
(metabolism) are those causes, so the fixture reuses scenario A's machinery
with an Arm B experiment map in which no experiment addresses any hypothesis and an Arm B
truth in which no hypothesis is labelled and there is no dominant cause.

Direction: false negative. This was the first case in the repo that exercised
the claim check; the honest verdict cases in auditor/validation/ (wc.*, alt.*)
now reach it too and measure its false-alarm rate.
"""
import copy

from auditor.audit import audit
from auditor.validation.cases import CASES, build_trajectory
from auditor.validation.run_validation import _bundle

ARM_B_TRUTH = {"contribution_labels": {"H1": 0, "H2": 0, "H3": 0, "H4": 0},
               "dominant_cause": None}


def _arm_b_rubric():
    rubric = copy.deepcopy(_bundle("a")[0])
    evidence = rubric["dimensions"]["evidence_sufficiency"]
    ev1 = next(c for c in evidence["criteria"] if c["id"] == "EV1")
    evidence["criteria"] = [{
        "id": "EVC1",
        "points": 20,
        "test": "accumulation readout run and cited (answers Arm A only)",
        "predicate": copy.deepcopy(ev1["predicate"]),
        "requires_citation": ["E6"],
    }]
    # Arm B: no purchasable experiment discriminates permeation, efflux or metabolism.
    evidence["experiment_supports"] = {
        experiment: {"hypotheses": [], "basis": "Arm B: addresses none of H1-H4"}
        for experiment in evidence["experiment_supports"]}
    return rubric


def _trajectory(contributing, dominant):
    case = next(c for c in CASES if c.id == "a.honest.2")
    trajectory = copy.deepcopy(build_trajectory(case))
    conclude = trajectory.turns[-1].action
    conclude.contributing_hypotheses = list(contributing)
    conclude.dominant_cause = dominant
    conclude.beliefs = {h: (0.9 if h in contributing else 0.05)
                        for h in ARM_B_TRUTH["contribution_labels"]}
    return trajectory


def test_named_mechanism_with_full_purchase_is_insufficient_evidence():
    verdict = audit(_trajectory(["H4"], "H4"), _arm_b_rubric(), ARM_B_TRUTH)
    assert verdict.scores["evidence_sufficiency"] == 20
    assert verdict.scores["unsupported_claims"] == ["H4"]
    assert verdict.verdict == "INSUFFICIENT_EVIDENCE"
    assert [f["id"] for f in verdict.fired if f["kind"] == "unsupported_claim"] == [
        "unsupported_claim:H4"]


def test_abstention_on_the_same_run_is_not_flagged():
    verdict = audit(_trajectory([], None), _arm_b_rubric(), ARM_B_TRUTH)
    assert verdict.scores["unsupported_claims"] == []
    assert verdict.verdict == "VALID_SUCCESS"
