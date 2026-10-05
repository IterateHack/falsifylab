"""Issue #35: conclusion citations never affect the verdict or score, so an
otherwise-honest run that cites nothing (evidence_cited=[]) still reaches
VALID_SUCCESS.

Direction: false negative. Exposing cases: the 12 honest validation cases in
auditor/validation/cases.py with their citations emptied.
"""
import copy

import pytest

from auditor.audit import audit
from auditor.validation.cases import CASES, HONEST, build_trajectory
from auditor.validation.run_validation import _bundle

HONEST_CASES = [case for case in CASES if case.label == HONEST]


def _audit(case, evidence_cited=None):
    # build_trajectory reuses the case's Action objects; mutate a copy only.
    trajectory = copy.deepcopy(build_trajectory(case))
    if evidence_cited is not None:
        trajectory.turns[-1].action.evidence_cited = evidence_cited
    return audit(trajectory, *_bundle(case.scenario))


def test_twelve_honest_cases_pass_as_recorded():
    assert len(HONEST_CASES) == 12
    for case in HONEST_CASES:
        verdict = _audit(case)
        assert (verdict.verdict, verdict.reward_hacks) == ("VALID_SUCCESS", []), case.id


@pytest.mark.xfail(strict=True, reason="fixed by #55, not merged")
@pytest.mark.parametrize("case", HONEST_CASES, ids=lambda c: c.id)
def test_honest_case_with_empty_citations_is_not_valid_success(case):
    assert _audit(case, evidence_cited=[]).verdict != "VALID_SUCCESS"
