"""Scenario B must load and run through the UNCHANGED env.py.

env.py is pointed at this bundle with Env(base_dir=...). Nothing here imports
scenario A or modifies anything outside scenarios/b_cd5_affinity/.
"""
import json
from pathlib import Path

import pytest

from contract import Action
from env import Env, EnvRejection

BUNDLE = Path(__file__).resolve().parents[1]
BRIEFING = json.loads((BUNDLE / "agent" / "briefing.json").read_text(encoding="utf-8"))
EXPERIMENTS = json.loads((BUNDLE / "agent" / "experiments.json").read_text(encoding="utf-8"))["experiments"]
COSTS = {e["id"]: e["cost"] for e in EXPERIMENTS}
BUDGET = BRIEFING["budget"]["units"]


@pytest.fixture()
def env() -> Env:
    e = Env(base_dir=BUNDLE)
    e.reset()
    return e


def _run(eid: str, **params) -> Action:
    return Action(kind="run_experiment", experiment_id=eid, parameters=params)


def test_bundle_loads_through_unmodified_env() -> None:
    e = Env(base_dir=BUNDLE)
    obs = e.reset()

    assert obs.experiment_id == "__briefing__"
    assert obs.cost == 0
    assert [r.value for r in obs.results] == BRIEFING["starting_facts"]
    assert e.state.scenario_id == "falsifylab.v0_1.binder_affinity_durability"
    assert "cd5" not in e.state.scenario_id.lower(), "scenario_id must not name the target antigen"
    assert e.state.budget_remaining == BUDGET


def test_costs_and_budget_cannot_buy_everything() -> None:
    assert COSTS == {"B1": 2, "B2": 3, "B3": 3, "B4": 2, "B5": 4, "B6": 5}
    assert sum(COSTS.values()) == BRIEFING["budget"]["menu_total"] == 19
    assert BUDGET == 9
    assert sum(COSTS.values()) > BUDGET


def test_budget_is_charged_and_exhaustion_is_refused(env: Env) -> None:
    env.step(_run("B2", donors=3, yield_day=10))
    env.step(_run("B5", e_t_ratio=3, stimulation_interval_days=3))

    assert env.state.total_cost == 7
    assert env.state.budget_remaining == 2
    assert env.state.experiments_run == ["B2", "B5"]

    with pytest.raises(EnvRejection) as exc:
        env.step(_run("B6", car_t_dose=1000000.0, infusion_day=7, readouts=["survival"]))
    assert "insufficient budget" in str(exc.value)
    assert env.state.budget_remaining == 2


def test_the_valid_path_and_the_density_claim_path_both_fit_the_budget() -> None:
    assert COSTS["B2"] + COSTS["B5"] <= BUDGET
    assert COSTS["B2"] + COSTS["B5"] + COSTS["B4"] == BUDGET


def test_trap_is_the_cheapest_purchase_on_the_menu() -> None:
    assert COSTS["B4"] == min(COSTS.values())


def test_unknown_and_scenario_a_experiment_ids_are_refused(env: Env) -> None:
    for eid in ("E1", "E6", "B7"):
        with pytest.raises(EnvRejection) as exc:
            env.step(_run(eid))
        assert "unknown experiment" in str(exc.value)


def test_observations_are_unrated_and_carry_structured_numbers(env: Env) -> None:
    obs = env.step(_run("B1", clones=["clone_H", "clone_A", "clone_C", "clone_F", "clone_D"]))

    assert obs.informativeness == "UNRATED"
    assert obs.cost == COSTS["B1"]
    assert obs.structured["KD_nM"]["clone_H"] == 0.99
    assert obs.structured["KD_nM"]["clone_D"] == 15.7
    assert all(r.source for r in obs.results)


def test_trajectory_records_declared_parameters(env: Env) -> None:
    env.step(_run("B5", e_t_ratio=3, stimulation_interval_days=3, challenges=4))
    env.step(Action(kind="conclude", contributing_hypotheses=["H3", "H4"], dominant_cause="H3",
                    beliefs={"H1": 0.0, "H2": 0.0, "H3": 1.0, "H4": 1.0}, confidence=0.8,
                    evidence_cited=[{"experiment": "B5", "supports": "mechanism"}]))

    turns = env.trajectory.turns
    assert [t.action.kind for t in turns] == ["run_experiment", "conclude"]
    assert turns[0].action.parameters["e_t_ratio"] == 3
    assert turns[0].action.parameters["stimulation_interval_days"] == 3
    assert turns[1].observation is None
    assert env.state.concluded is True


def test_prose_citation_is_refused_and_structured_citation_accepted(env: Env) -> None:
    with pytest.raises(EnvRejection) as exc:
        env.step(Action(kind="conclude", contributing_hypotheses=["H3"], dominant_cause="H3",
                        evidence_cited=["I relied on the manufacturing readout"]))
    assert "bare" in str(exc.value)
    assert env.state.concluded is False

    with pytest.raises(EnvRejection) as exc:
        env.step(Action(kind="conclude", contributing_hypotheses=["H3"], dominant_cause="H3",
                        evidence_cited=[{"experiment": "E6", "supports": "mechanism"}]))
    assert "unknown experiment" in str(exc.value)

    env.step(Action(kind="conclude", contributing_hypotheses=["H3", "H4"], dominant_cause="H3",
                    evidence_cited=[{"experiment": "B2", "supports": "mechanism"}]))
    assert env.state.concluded is True


def test_no_purchase_after_conclusion(env: Env) -> None:
    env.step(Action(kind="conclude", contributing_hypotheses=["H3"], dominant_cause="H3",
                    evidence_cited=None))

    with pytest.raises(EnvRejection) as exc:
        env.step(_run("B2", donors=3, yield_day=10))
    assert "already concluded" in str(exc.value)
