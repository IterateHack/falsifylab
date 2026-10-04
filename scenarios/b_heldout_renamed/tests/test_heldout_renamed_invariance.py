from dataclasses import replace
import json
from pathlib import Path

import pytest

from auditor.validation.cases import CASES
from contract import audit, trajectory_from_dict
from env import Env
from scenarios.b_heldout_renamed.build_bundle import transform


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "scenarios" / "b_cd5_affinity"
RENAMED = Path(__file__).resolve().parents[1]
GOLDEN_DIR = SOURCE / "auditor" / "tests" / "golden"
RENAME_MAP = tuple(
    (entry["from"], entry["to"])
    for entry in json.loads(
        (RENAMED / "auditor" / "provenance.json").read_text(encoding="utf-8")
    )["rename_map"]
)


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs():
    inputs = [
        (case.id, tuple(case.actions))
        for case in CASES
        if case.scenario == "b"
    ]
    assert len(inputs) == 24
    for name in ("canonical_valid", "canonical_trap", "zero_experiment_baseline"):
        fixture = _load_json(GOLDEN_DIR / f"{name}.json")
        trajectory = trajectory_from_dict(fixture)
        inputs.append((f"golden.{name}", tuple(turn.action for turn in trajectory.turns)))
    return inputs


INPUTS = _inputs()


def _translate_parameter_values(value):
    if isinstance(value, str):
        return transform(value, RENAME_MAP)
    if isinstance(value, list):
        return [_translate_parameter_values(child) for child in value]
    if isinstance(value, dict):
        return {
            key: _translate_parameter_values(child)
            for key, child in value.items()
        }
    return value


def _translated_action(action):
    return replace(
        action,
        parameters=_translate_parameter_values(action.parameters),
    )


def _audit_actions(bundle, actions):
    environment = Env(base_dir=bundle)
    environment.reset()
    for action in actions:
        environment.step(action)
    rubric = _load_json(bundle / "auditor" / "rubric.json")
    truth = _load_json(bundle / "auditor" / "truth.json")
    return audit(environment.trajectory, rubric, truth)


@pytest.mark.parametrize(
    "case_id,actions",
    INPUTS,
    ids=[case_id for case_id, _ in INPUTS],
)
def test_renaming_preserves_auditor_output(case_id, actions):
    original = _audit_actions(SOURCE, actions)
    renamed_actions = tuple(_translated_action(action) for action in actions)
    renamed = _audit_actions(RENAMED, renamed_actions)

    assert renamed.verdict == original.verdict, case_id
    assert sorted(renamed.flags) == sorted(original.flags), case_id
    assert sorted(renamed.reward_hacks) == sorted(original.reward_hacks), case_id
    assert renamed.final_score == original.final_score, case_id
    assert renamed.raw_total == original.raw_total, case_id
    assert renamed.R_visible == original.R_visible, case_id
    assert renamed.scores == original.scores, case_id
    assert renamed.fired == transform(original.fired, RENAME_MAP), case_id


def test_dropping_the_renamed_conclude_turn_changes_the_verdict():
    case = next(case for case in CASES if case.id == "b.honest.1")
    original = _audit_actions(SOURCE, case.actions)

    renamed_actions = [_translated_action(action) for action in case.actions]
    final_action = renamed_actions[-1]
    assert final_action.kind == "conclude"
    renamed_actions.pop()
    changed = _audit_actions(RENAMED, renamed_actions)

    assert changed.verdict != original.verdict
