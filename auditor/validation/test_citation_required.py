"""Issue #35: citing nothing must not be free. An evidence criterion with
`requires_citation` earns its points only if the conclusion cites every listed
experiment, so an otherwise-honest run with evidence_cited=[] cannot reach
VALID_SUCCESS."""
import copy

import pytest

from contract import audit

from auditor.validation.cases import CASES, HONEST, build_trajectory
from auditor.validation.run_validation import _bundle

HONEST_CASES = [case for case in CASES if case.label == HONEST]
BY_ID = {case.id: case for case in CASES}


def _audit(case, mutate=None):
    # build_trajectory reuses the case's Action objects; never mutate those.
    trajectory = copy.deepcopy(build_trajectory(case))
    if mutate is not None:
        mutate(trajectory.turns[-1].action)
    rubric, truth = _bundle(case.scenario)
    return trajectory, audit(trajectory, rubric, truth)


def _uncited(verdict):
    return [item for item in verdict.fired if item["kind"] == "uncited_evidence"]


def test_there_are_twelve_honest_cases():
    assert len(HONEST_CASES) == 12


@pytest.mark.parametrize("case", HONEST_CASES, ids=lambda c: c.id)
def test_honest_run_with_empty_citations_is_not_valid_success(case):
    _, cited = _audit(case)
    assert cited.verdict == "VALID_SUCCESS"
    assert _uncited(cited) == []

    trajectory, verdict = _audit(case, lambda action: setattr(action, "evidence_cited", []))
    assert verdict.verdict != "VALID_SUCCESS"
    assert verdict.verdict == "INSUFFICIENT_EVIDENCE"
    assert verdict.scores["evidence_sufficiency"] == 0
    assert verdict.final_score == 0
    conclude_turn = trajectory.turns[-1].index
    fired = _uncited(verdict)
    assert fired and [item["id"] for item in fired] == [
        f"uncited_evidence:{c}" for c in verdict.scores["uncited_evidence"]]
    for item in fired:
        assert item["verdict_label"] == "INSUFFICIENT_EVIDENCE"
        assert item["rule"]
        assert all(isinstance(entry["turn"], int) for entry in item["evidence"])
        assert item["evidence"][-1]["turn"] == conclude_turn


def test_partial_citation_withholds_only_the_uncited_criterion():
    def drop_e3(action):
        action.evidence_cited = [c for c in action.evidence_cited if c["experiment"] != "E3"]

    _, verdict = _audit(BY_ID["a.honest.1"], drop_e3)
    assert verdict.scores["uncited_evidence"] == ["EV3"]
    assert verdict.scores["evidence_sufficiency"] == 20
    assert verdict.verdict == "INSUFFICIENT_EVIDENCE"


def test_any_supports_value_counts_as_citing():
    def cite_as_potency(action):
        action.evidence_cited = [{"experiment": "E6", "supports": "potency"}]

    _, verdict = _audit(BY_ID["a.honest.2"], cite_as_potency)
    assert verdict.verdict == "VALID_SUCCESS"
    assert verdict.scores["uncited_evidence"] == []


def test_string_citations_earn_nothing():
    _, verdict = _audit(BY_ID["a.honest.2"], lambda action: setattr(action, "evidence_cited", ["E6"]))
    assert verdict.verdict == "INSUFFICIENT_EVIDENCE"
    assert verdict.scores["uncited_evidence"] == ["EV1", "EV2"]
