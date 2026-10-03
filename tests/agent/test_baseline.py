"""Spec for the baseline agent's `act`.

Every observation here is synthetic, written for the test. The point of the
counterfactual cases is that the policy is an inference procedure and not a
stored answer: feed it readouts that point at H1 or H2, or at a compound that
enters intact and is not modified, and the conclusion follows the readout.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.baseline import BRIEFING_ID, BaselineAgent  # noqa: E402
from contract import Observation, Result, State  # noqa: E402

BUDGET = 8


def make_state(**overrides) -> State:
    base = dict(
        scenario_id="falsifylab.v0_1.pptt_programme",
        budget_remaining=BUDGET,
        total_cost=0,
        experiments_run=[],
        beliefs={"H1": 0.5, "H2": 0.5, "H3": 0.5, "H4": 0.5},
        dominant_cause=None,
        concluded=False,
    )
    base.update(overrides)
    return State(**base)


def briefing() -> Observation:
    return Observation(experiment_id=BRIEFING_ID, results=[], informativeness="LOW", cost=0)


def obs(experiment_id: str, *values: str, informativeness: str = "HIGH", cost: int = 2) -> Observation:
    return Observation(
        experiment_id=experiment_id,
        results=[Result(value=v, source="synthetic") for v in values],
        informativeness=informativeness,
        cost=cost,
    )


def run(agent: BaselineAgent, state: State, observation: Observation):
    """One turn: act, then charge the budget the way Env.step would."""
    action = agent.act(observation, state)
    if action.kind == "run_experiment":
        cost = int(agent.experiments[action.experiment_id]["cost"])
        state.experiments_run.append(action.experiment_id)
        state.budget_remaining -= cost
        state.total_cost += cost
    return action


# --- the shape of what act returns -------------------------------------------
def test_first_action_is_an_experiment_never_a_conclusion():
    action = BaselineAgent().act(briefing(), make_state())
    assert action.kind == "run_experiment"
    assert action.experiment_id in {f"E{i}" for i in range(1, 7)}


def test_never_concludes_without_having_observed_anything():
    """The zero-experiment path is INSUFFICIENT_EVIDENCE by construction, so the
    agent must not take it while it can still buy something."""
    action = BaselineAgent().act(briefing(), make_state())
    assert action.kind != "conclude"


def test_concludes_when_budget_cannot_buy_anything():
    agent, state = BaselineAgent(), make_state(budget_remaining=1)
    agent.act(briefing(), state)
    action = agent.act(obs("E1", "Delta T_m 15 C with coenzyme A present"), state)
    assert action.kind == "conclude"
    assert action.confidence is not None and 0.0 <= action.confidence <= 0.8


def test_parameters_are_filled_for_every_declared_field():
    agent = BaselineAgent()
    for eid, experiment in agent.experiments.items():
        declared = set((experiment.get("parameters") or {}).keys())
        assert set(agent._parameters(eid)) == declared, eid


def test_e6_requests_all_three_arms_and_names_a_cell_free_control():
    params = BaselineAgent()._parameters("E6")
    assert sorted(params["arms"]) == ["diethyl_ester", "monoacid", "parent_diacid"]
    assert any("bacteria-free" in c for c in params["controls"])


def test_e1_saturates_substrate_because_that_is_the_question_it_asks():
    params = BaselineAgent()._parameters("E1")
    assert params["coa_mM"] == 2


def test_budget_is_never_overspent_across_a_whole_episode():
    agent, state = BaselineAgent(), make_state()
    observation = briefing()
    for _ in range(10):
        action = run(agent, state, observation)
        if action.kind == "conclude":
            break
        observation = obs(action.experiment_id, "uninformative readout")
    assert state.total_cost <= BUDGET
    assert state.budget_remaining >= 0
    assert action.kind == "conclude"


def test_no_experiment_is_bought_twice():
    agent, state = BaselineAgent(), make_state()
    observation = briefing()
    bought = []
    for _ in range(10):
        action = run(agent, state, observation)
        if action.kind == "conclude":
            break
        bought.append(action.experiment_id)
        observation = obs(action.experiment_id, "uninformative readout")
    assert len(bought) == len(set(bought))


def test_beliefs_are_published_on_the_state_each_turn():
    agent, state = BaselineAgent(), make_state()
    agent.act(briefing(), state)
    agent.act(obs("E6", "Only 1.0 percent recovered from cells; the rest is lost to efflux",
                  "Compound is metabolised by progressive demethylation"), state)
    assert state.beliefs == agent.beliefs
    assert set(state.beliefs) == {"H1", "H2", "H3", "H4"}
    assert all(0.0 <= p <= 1.0 for p in state.beliefs.values())


# --- the readout drives the conclusion, in either direction -------------------
def test_entry_failure_readout_raises_the_access_hypothesis():
    agent, state = BaselineAgent(), make_state()
    agent.act(briefing(), state)
    agent.act(obs("E6", "Only 1.2 percent recovered from cells; free compound lost to efflux",
                  informativeness="DECISIVE", cost=4), state)
    assert agent.beliefs["H3"] > 0.8


def test_intact_compound_inside_the_cell_lowers_both_pharmacokinetic_hypotheses():
    """The counterfactual: it gets in and stays whole, so neither access nor
    biotransformation explains the failure."""
    agent, state = BaselineAgent(), make_state()
    agent.act(briefing(), state)
    agent.act(obs("E6", "Parent: 80.0 percent uptake; 95 percent remains unmodified intracellularly",
                  informativeness="DECISIVE", cost=4), state)
    assert agent.beliefs["H3"] < 0.5
    assert agent.beliefs["H4"] < 0.5


def test_absent_thermal_shift_points_at_the_assay_artefact_hypothesis():
    agent, state = BaselineAgent(), make_state()
    agent.act(briefing(), state)
    agent.act(obs("E1", "No detectable shift in melting temperature at any compound concentration"), state)
    assert agent.beliefs["H1"] > 0.6


def test_substrate_abolishing_the_shift_points_at_substrate_competition():
    agent, state = BaselineAgent(), make_state()
    agent.act(briefing(), state)
    agent.act(obs("E1", "Delta T_m 15 C in substrate-free buffer; no shift once coenzyme A is present"), state)
    assert agent.beliefs["H2"] > 0.6


def test_substrate_displaced_in_the_structure_disfavours_substrate_competition():
    agent, state = BaselineAgent(), make_state()
    agent.act(briefing(), state)
    agent.act(obs("E2", "2.4 A resolution; coenzyme A completely displaced from the active site",
                  informativeness="MEDIUM", cost=4), state)
    assert agent.beliefs["H2"] < 0.3
    assert agent.beliefs["H1"] < 0.3


def test_conclusion_asserts_only_hypotheses_above_threshold():
    agent, state = BaselineAgent(), make_state(budget_remaining=0)
    agent.act(briefing(), state)
    agent.beliefs = {"H1": 0.05, "H2": 0.1, "H3": 0.9, "H4": 0.7}
    action = agent.act(briefing(), state)
    assert action.kind == "conclude"
    assert sorted(action.contributing_hypotheses) == ["H3", "H4"]
    assert action.dominant_cause == "H3"


def test_dominant_cause_is_none_when_two_hypotheses_tie():
    agent, state = BaselineAgent(), make_state(budget_remaining=0)
    agent.beliefs = {"H1": 0.0, "H2": 0.0, "H3": 0.9, "H4": 0.9}
    action = agent.act(briefing(), state)
    assert action.dominant_cause is None


def test_target_claim_only_after_running_a_strain_panel():
    agent, state = BaselineAgent(), make_state(budget_remaining=0)
    agent.act(briefing(), state)
    without_panel = agent.act(briefing(), state)
    assert without_panel.makes_target_claim is False

    agent.act(obs("E3", "No meaningful MIC shift on target depletion in any strain"), state)
    with_panel = agent.act(briefing(), state)
    assert with_panel.makes_target_claim is True


def test_evidence_cited_is_only_what_was_actually_observed():
    agent, state = BaselineAgent(), make_state(budget_remaining=0)
    agent.act(briefing(), state)
    agent.act(obs("E3", "No meaningful MIC shift on target depletion in any strain"), state)
    action = agent.act(briefing(), state)
    assert action.evidence_cited == ["E3: No meaningful MIC shift on target depletion in any strain [synthetic]"]


def test_evidence_cited_is_empty_when_nothing_was_run():
    agent, state = BaselineAgent(), make_state(budget_remaining=0)
    action = agent.act(briefing(), state)
    assert action.evidence_cited == []


def test_confidence_is_capped_below_certainty():
    agent, state = BaselineAgent(), make_state(budget_remaining=0)
    agent.beliefs = {"H1": 0.0, "H2": 0.0, "H3": 1.0, "H4": 1.0}
    action = agent.act(briefing(), state)
    assert action.confidence == pytest.approx(0.8)


# --- value of information: cost is not the only axis ---------------------------
def test_prefers_the_intrabacterial_measurement_over_the_cheaper_potency_run():
    """E4 is cheaper than E6 and nominally touches the same two hypotheses, but
    it only ever reports IC50 against purified enzyme, so it cannot see what
    happens inside a cell. The policy must not be bought off by its price."""
    agent, state = BaselineAgent(), make_state()
    agent.act(briefing(), state)
    # H1/H2 already settled, so only the pharmacokinetic pair is still open.
    agent.beliefs.update({"H1": 0.05, "H2": 0.05})
    action = agent.act(briefing(), state)
    assert action.experiment_id == "E6"


def test_whole_episode_spends_the_budget_on_the_discriminating_experiments():
    agent, state = BaselineAgent(), make_state()
    readouts = {
        "E1": ["Melting temperature rises from 40 to 55 degrees C with coenzyme A present"],
        "E2": ["2.4 A structure; coenzyme A displaced from the active site"],
        "E3": ["No meaningful MIC shift on target depletion in any strain"],
        "E4": ["17 analogues more potent, 3.6-fold; all remain inactive whole-cell"],
        "E5": ["Two analogues inhibit an unrelated enzyme at similar IC50"],
        "E6": ["Parent: only 1.2 percent recovered from cells; free compound lost to efflux",
               "Ester: 74.6 percent uptake, 93.6 percent metabolised by progressive demethylation"],
    }
    observation, bought = briefing(), []
    for _ in range(10):
        action = run(agent, state, observation)
        if action.kind == "conclude":
            break
        bought.append(action.experiment_id)
        observation = obs(action.experiment_id, *readouts[action.experiment_id],
                          cost=int(agent.experiments[action.experiment_id]["cost"]))
    assert "E6" in bought and "E4" not in bought
    assert state.total_cost <= BUDGET
    assert action.dominant_cause is not None


# --- reading its own readout in the light of its own conditions ----------------
def test_shift_under_saturating_substrate_settles_both_tube_hypotheses():
    """No prose about competition is needed: the agent set coa_mM itself, so a
    shift measured under saturating substrate answers H2 on its own."""
    agent, state = BaselineAgent(), make_state()
    action = agent.act(briefing(), state)
    assert action.experiment_id == "E1" and action.parameters["coa_mM"] >= 1.0
    agent.act(obs("E1", "Melting temperature 40 to 55 degrees C"), state)
    assert agent.beliefs["H1"] < 0.2
    assert agent.beliefs["H2"] < 0.2


def test_a_shift_within_noise_is_not_treated_as_binding():
    agent, state = BaselineAgent(), make_state()
    agent.act(briefing(), state)
    agent.act(obs("E1", "Delta T_m of 0.4 degrees C at the top compound concentration"), state)
    assert agent.beliefs["H1"] > 0.6
    assert agent.beliefs["H2"] > 0.6


# --- which of two supported hypotheses dominates ------------------------------
def test_an_arm_that_enters_and_is_destroyed_makes_destruction_dominant():
    agent, state = BaselineAgent(), make_state()
    agent.act(briefing(), state)
    agent.act(obs("E6",
                  "Parent: only 1.2 percent recovered from cells; free compound lost to efflux",
                  "Ester: 74.6 percent uptake, 93.6 percent metabolised by demethylation",
                  informativeness="DECISIVE", cost=4), state)
    assert agent.beliefs["H4"] > agent.beliefs["H3"] > 0.6
    assert state.dominant_cause == "H4"


def test_nothing_entering_anywhere_makes_access_dominant():
    agent, state = BaselineAgent(), make_state()
    agent.act(briefing(), state)
    agent.act(obs("E6",
                  "All three arms: only 1.0 percent recovered from cells, no uptake above background",
                  "What little is recovered is found unmodified",
                  informativeness="DECISIVE", cost=4), state)
    assert agent.beliefs["H3"] > 0.6
    assert state.dominant_cause == "H3"
