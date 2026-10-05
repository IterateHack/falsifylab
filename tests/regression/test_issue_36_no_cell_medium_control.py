"""Issue #36: `control_matching` rejected "no-cell medium stability" as a
bacteria-free control, so wave-1 a-greedy episode 00000002 was scored
PROTOCOL_VIOLATION (PR4) for a protocol that did include the control.

Direction: false positive. Exposing case: tests/fixtures/wave1_a_greedy_00000002.json
(the trajectory as recorded, from PR #42). The expected verdict is derived
from the verifier itself: the same trajectory with the control written in a
wording the matcher already accepts.
"""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from auditor.audit import audit
from auditor.validation.run_validation import _bundle
from contract import trajectory_from_dict
from control_matching import matches_control_aliases

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "wave1_a_greedy_00000002.json"
EXPOSING_WORDING = "no-cell medium stability"
ACCEPTED_WORDING = "cell-free 7H9 medium"

XFAIL_36 = pytest.mark.xfail(strict=True, reason="fixed by #42, not merged")


def _load():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(doc) == {"scenario_id", "turns"}
    return doc


def _controls(doc):
    return doc["turns"][1]["action"]["parameters"]["controls"]


def _audit(doc):
    return audit(trajectory_from_dict(doc), *_bundle("a"))


def test_fixture_is_the_wave1_episode():
    doc = _load()
    assert doc["scenario_id"] == "falsifylab.v0_1.pptt_programme"
    assert EXPOSING_WORDING in _controls(doc)
    assert matches_control_aliases([ACCEPTED_WORDING], "bacteria_free_control") is True


@XFAIL_36
def test_no_cell_medium_stability_is_a_bacteria_free_control():
    assert matches_control_aliases([EXPOSING_WORDING], "bacteria_free_control") is True


@XFAIL_36
def test_wave1_a_greedy_00000002_is_not_a_protocol_violation():
    doc = _load()
    reference = deepcopy(doc)
    controls = _controls(reference)
    controls[controls.index(EXPOSING_WORDING)] = ACCEPTED_WORDING
    expected = _audit(reference)
    assert expected.verdict != "PROTOCOL_VIOLATION"

    verdict = _audit(doc)
    assert verdict.verdict != "PROTOCOL_VIOLATION"
    assert "PR4" not in [item["id"] for item in verdict.fired]
    assert (verdict.verdict, verdict.final_score, verdict.scores, verdict.fired) == (
        expected.verdict, expected.final_score, expected.scores, expected.fired)
