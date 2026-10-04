import json
from pathlib import Path

import pytest

from contract import Action
from env import Env, EnvRejection, REJECTION_CODES

ROOT = Path(__file__).resolve().parents[1]


def test_overspend_rejection_code_uses_root_bundle_costs():
    experiments = json.loads((ROOT / "agent" / "experiments.json").read_text())["experiments"]
    experiment = next(item for item in experiments if item["id"] == "E2")
    action = Action("run_experiment", experiment_id=experiment["id"])
    env = Env()
    env.reset()

    while env.state.budget_remaining >= experiment["cost"]:
        env.step(action)

    with pytest.raises(EnvRejection) as exc:
        env.step(action)
    assert exc.value.code == "overspend"


def test_malformed_conclude_rejection_code():
    env = Env()
    env.reset()

    with pytest.raises(EnvRejection) as exc:
        env.step(Action("conclude", evidence_cited=["E1"]))
    assert exc.value.code == "malformed_conclude"


def test_unknown_experiment_rejection_code():
    env = Env()
    env.reset()

    with pytest.raises(EnvRejection) as exc:
        env.step(Action("run_experiment", experiment_id="E_NOPE"))
    assert exc.value.code == "unknown_experiment"


def test_other_rejection_code_for_purchase_after_conclude():
    env = Env()
    env.reset()
    env.step(Action("conclude"))

    with pytest.raises(EnvRejection) as exc:
        env.step(Action("run_experiment", experiment_id="E2"))
    assert exc.value.code == "other"


def test_default_rejection_code_and_allowed_codes():
    assert EnvRejection("x").code == "other"
    assert REJECTION_CODES == ("overspend", "malformed_conclude", "unknown_experiment", "other")
