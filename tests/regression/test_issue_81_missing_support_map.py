"""Issue #81: the claim check ran only if some evidence criterion carried
supports_hypotheses, so a rubric without the key switched the check off with
no signal. Exposing case: the #35 Arm B fixture with its mapping removed went
from INSUFFICIENT_EVIDENCE back to WRONG_CONCLUSION.

Direction: false negative. The mapping is now experiment_supports, required in
every rubric: audit() raises without it, on a stale per-criterion
supports_hypotheses, and on a run experiment the map does not cover. Each
bundle's map must cover its catalogue exactly.
"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from auditor.audit import audit, load_rubric
from auditor.validation.cases import BUNDLES

ARM_B = Path(__file__).with_name("test_issue_35_arm_b_unsupported_claim.py")


def _arm_b():
    spec = importlib.util.spec_from_file_location("arm_b_fixture", ARM_B)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_map_raises_instead_of_skipping():
    arm_b = _arm_b()
    rubric = arm_b._arm_b_rubric()
    del rubric["dimensions"]["evidence_sufficiency"]["experiment_supports"]
    with pytest.raises(ValueError, match="experiment_supports"):
        audit(arm_b._trajectory(["H4"], "H4"), rubric, arm_b.ARM_B_TRUTH)


def test_missing_map_raises_even_without_a_named_hypothesis():
    arm_b = _arm_b()
    rubric = arm_b._arm_b_rubric()
    del rubric["dimensions"]["evidence_sufficiency"]["experiment_supports"]
    with pytest.raises(ValueError, match="experiment_supports"):
        audit(arm_b._trajectory([], None), rubric, arm_b.ARM_B_TRUTH)


def test_stale_criterion_mapping_raises():
    arm_b = _arm_b()
    rubric = arm_b._arm_b_rubric()
    rubric["dimensions"]["evidence_sufficiency"]["criteria"][0]["supports_hypotheses"] = []
    with pytest.raises(ValueError, match="supports_hypotheses"):
        audit(arm_b._trajectory(["H4"], "H4"), rubric, arm_b.ARM_B_TRUTH)


def test_run_experiment_missing_from_map_raises():
    arm_b = _arm_b()
    rubric = arm_b._arm_b_rubric()
    del rubric["dimensions"]["evidence_sufficiency"]["experiment_supports"]["E6"]
    with pytest.raises(ValueError, match="E6"):
        audit(arm_b._trajectory(["H4"], "H4"), rubric, arm_b.ARM_B_TRUTH)


@pytest.mark.parametrize("scenario", sorted(BUNDLES))
def test_map_covers_the_catalogue_with_a_basis_per_entry(scenario):
    base = BUNDLES[scenario]
    rubric = load_rubric(base / "auditor" / "rubric.json")
    catalogue = json.loads((base / "agent" / "experiments.json").read_text(encoding="utf-8"))
    hypotheses = json.loads((base / "agent" / "hypotheses.json").read_text(encoding="utf-8"))
    mapping = rubric["dimensions"]["evidence_sufficiency"]["experiment_supports"]
    assert list(mapping) == [e["id"] for e in catalogue["experiments"]]
    known = {h["id"] for h in hypotheses["hypotheses"]}
    for entry in mapping.values():
        assert set(entry) == {"hypotheses", "basis"}
        assert set(entry["hypotheses"]) <= known
        assert entry["basis"].startswith("question: ")


@pytest.mark.parametrize("scenario", sorted(BUNDLES))
def test_map_never_reaches_the_agent(scenario):
    for path in (BUNDLES[scenario] / "agent").rglob("*"):
        if path.is_file():
            assert "experiment_supports" not in path.read_text(encoding="utf-8", errors="ignore")
