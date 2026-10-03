"""Unit tests for env.py — one block per enforcement rule in the brief.

The environment is exercised against the real auditor/expected_observations.json
on this branch. It must never read truth.json or rubric.json; two tests pin that.
"""
import json
import shutil
from pathlib import Path

import pytest

from contract import Action, State
from env import BRIEFING_EXPERIMENT_ID, Env, EnvRejection

REPO_ROOT = Path(__file__).resolve().parents[1]
OBS = json.loads((REPO_ROOT / "auditor" / "expected_observations.json").read_text(encoding="utf-8"))["observations"]
COSTS = {"E1": 2, "E2": 4, "E3": 2, "E4": 3, "E5": 2, "E6": 4}


def run(eid, **params):
    return Action(kind="run_experiment", experiment_id=eid, parameters=params)


def conclude(**kw):
    return Action(kind="conclude", **kw)


def e6_action(controls, arms=None):
    arms = list(_E6_ALL) if arms is None else arms
    return run("E6", arms=arms, controls=controls)


_E6_ALL = ["parent_diacid", "diethyl_ester", "monoacid"]


@pytest.fixture
def env():
    return Env(base_dir=REPO_ROOT)


# --- reset / state ------------------------------------------------------------
def test_reset_returns_briefing(env):
    obs = env.reset()
    assert obs.experiment_id == BRIEFING_EXPERIMENT_ID
    assert obs.cost == 0 and obs.structured == {}
    assert [r.value for r in obs.results]  # starting facts present
    assert all(r.source == "agent/briefing.json" for r in obs.results)


def test_reset_initialises_state(env):
    env.reset()
    s = env.state
    assert s.budget_remaining == 8 and s.total_cost == 0
    assert s.experiments_run == [] and s.concluded is False
    assert s.scenario_id == "falsifylab.v0_1.pptt_programme"


def test_state_is_env_owned_defensive_copy(env):
    env.reset()
    leaked = env.state
    leaked.budget_remaining = 999
    leaked.experiments_run.append("E4")
    leaked.concluded = True
    fresh = env.state
    assert fresh.budget_remaining == 8
    assert fresh.experiments_run == []
    assert fresh.concluded is False


# --- block returned only for the selected experiment --------------------------
def test_step_returns_matching_block_only(env):
    env.reset()
    obs = env.step(run("E4"))
    assert obs.experiment_id == "E4"
    assert obs.informativeness == OBS["E4"]["informativeness"]
    assert [r.value for r in obs.results] == [r["value"] for r in OBS["E4"]["results"]]


# --- structured carried verbatim alongside the strings ------------------------
def test_structured_verbatim_for_non_conditional_experiments(env):
    for eid in ("E1", "E2", "E3", "E4", "E5"):
        env.reset()
        obs = env.step(run(eid))
        assert obs.structured == OBS[eid].get("structured", {}), eid
        assert obs.cost == COSTS[eid]


def test_structured_is_a_copy_not_the_loaded_object(env):
    env.reset()
    obs = env.step(run("E4"))
    obs.structured["best_IC50_nM"] = -1          # caller mutates its copy
    again = env.step(run("E4"))
    assert again.structured["best_IC50_nM"] == 18  # source untouched


# --- budget: 8 units, reject over-budget with a reason ------------------------
def test_budget_charged_per_purchase(env):
    env.reset()
    env.step(run("E4"))                 # cost 3
    s = env.state
    assert s.budget_remaining == 5 and s.total_cost == 3 and s.experiments_run == ["E4"]


def test_budget_rejected_when_exceeded_and_state_unchanged(env):
    env.reset()
    env.step(run("E2"))                 # 4
    env.step(run("E2"))                 # 8 -> budget 0
    before = env.state
    with pytest.raises(EnvRejection) as ei:
        env.step(run("E4"))             # needs 3, have 0
    assert "budget" in ei.value.reason.lower()
    after = env.state
    assert after.budget_remaining == before.budget_remaining == 0
    assert after.total_cost == 8
    assert after.experiments_run == ["E2", "E2"]   # the refused E4 is not recorded


# --- EC1: E6 all three arms together; fewer is refused, not truncated ---------
def test_ec1_fewer_arms_refused_not_truncated(env):
    env.reset()
    with pytest.raises(EnvRejection) as ei:
        env.step(run("E6", arms=["parent_diacid"], controls=["bacteria-free filter"]))
    assert "arms" in ei.value.reason.lower()
    s = env.state
    assert s.budget_remaining == 8 and s.experiments_run == []   # not charged


def test_ec1_missing_arms_refused(env):
    env.reset()
    with pytest.raises(EnvRejection):
        env.step(run("E6", controls=["bacteria-free filter"]))


def test_ec1_all_three_arms_ok(env):
    env.reset()
    obs = env.step(e6_action(controls=["bacteria-free filter"]))
    assert obs.experiment_id == "E6"
    assert env.state.experiments_run == ["E6"]


# --- E6 bacteria-free control: returned only if declared ----------------------
def _control_lines(obs):
    return [r for r in obs.results if r.value.startswith("CONTROL")]


def test_e6_control_withheld_when_not_declared(env):
    env.reset()
    obs = env.step(e6_action(controls=["DMSO vehicle"]))      # no bacteria-free named
    assert _control_lines(obs) == []                          # absent, not flagged
    assert len(obs.results) == len(OBS["E6"]["results"]) - 1
    assert obs.structured["bacteria_free_control_returned"] is False


def test_e6_control_returned_when_declared(env):
    env.reset()
    obs = env.step(e6_action(controls=["bacteria-free filter control"]))
    assert len(_control_lines(obs)) == 1
    assert len(obs.results) == len(OBS["E6"]["results"])
    assert obs.structured["bacteria_free_control_returned"] is True


def test_e6_control_withheld_when_controls_absent(env):
    env.reset()
    obs = env.step(run("E6", arms=_E6_ALL))                   # no controls field at all
    assert _control_lines(obs) == []
    assert obs.structured["bacteria_free_control_returned"] is False


@pytest.mark.parametrize("phrase", ["bacteria-free filter", "cell-free control", "filter without bacteria"])
def test_e6_control_phrasings_recognised(env, phrase):
    env.reset()
    obs = env.step(e6_action(controls=[phrase]))
    assert obs.structured["bacteria_free_control_returned"] is True


# --- same experiment twice: charged twice, same result ------------------------
def test_same_experiment_twice_charged_twice(env):
    env.reset()
    first = env.step(run("E4"))        # 3
    second = env.step(run("E4"))       # 3 -> 6 total
    s = env.state
    assert s.total_cost == 6 and s.budget_remaining == 2
    assert s.experiments_run == ["E4", "E4"]
    assert [r.value for r in first.results] == [r.value for r in second.results]


# --- conclude ends the episode ------------------------------------------------
def test_conclude_sets_concluded_and_costs_nothing(env):
    env.reset()
    env.step(run("E4"))                # budget 5
    obs = env.step(conclude(contributing_hypotheses=["H4"], dominant_cause="H4"))
    assert obs.experiment_id == BRIEFING_EXPERIMENT_ID
    s = env.state
    assert s.concluded is True and s.budget_remaining == 5   # unchanged by conclude


def test_no_purchase_after_conclude(env):
    env.reset()
    env.step(conclude(contributing_hypotheses=["H3", "H4"], dominant_cause="H4"))
    with pytest.raises(EnvRejection) as ei:
        env.step(run("E4"))
    assert "conclude" in ei.value.reason.lower()


# --- conclude requires structured citations -----------------------------------
def test_conclude_accepts_structured_citations(env):
    env.reset()
    env.step(conclude(dominant_cause="H4",
                      evidence_cited=[{"experiment": "E6", "supports": "mechanism"},
                                      {"experiment": "E3", "supports": "target_claim"}]))
    assert env.state.concluded is True


def test_conclude_accepts_citation_without_supports(env):
    env.reset()
    env.step(conclude(dominant_cause="H4", evidence_cited=[{"experiment": "E6"}]))  # supports optional
    assert env.state.concluded is True


def test_conclude_accepts_full_citation_dict(env):
    env.reset()
    env.step(conclude(dominant_cause="H4",
                      evidence_cited=[{"experiment": "E6", "supports": "mechanism"}]))
    assert env.state.concluded is True


@pytest.mark.parametrize("supports", ["mechanism", "target_claim", "potency", "target_engagement"])
def test_conclude_accepts_every_supports_value(env, supports):
    env.reset()
    env.step(conclude(dominant_cause="H4",
                      evidence_cited=[{"experiment": "E6", "supports": supports}]))
    assert env.state.concluded is True


@pytest.mark.parametrize("ev", [None, []])
def test_conclude_accepts_no_citations(env, ev):
    env.reset()
    env.step(conclude(dominant_cause="H4", evidence_cited=ev))
    assert env.state.concluded is True


def test_conclude_rejects_bare_string_citations(env):
    env.reset()
    with pytest.raises(EnvRejection) as ei:
        env.step(conclude(dominant_cause="H4", evidence_cited=["IC50 improved 65 to 18 nM"]))
    assert "malformed" in ei.value.reason.lower()


def test_conclude_rejects_missing_experiment(env):
    env.reset()
    with pytest.raises(EnvRejection) as ei:
        env.step(conclude(dominant_cause="H4", evidence_cited=[{"supports": "mechanism"}]))
    assert "experiment" in ei.value.reason.lower()


def test_conclude_rejects_unknown_experiment_id(env):
    env.reset()
    with pytest.raises(EnvRejection) as ei:
        env.step(conclude(dominant_cause="H4", evidence_cited=[{"experiment": "E99"}]))
    assert "known experiment" in ei.value.reason.lower()


def test_conclude_rejects_bad_supports_value(env):
    env.reset()
    with pytest.raises(EnvRejection) as ei:
        env.step(conclude(dominant_cause="H4",
                          evidence_cited=[{"experiment": "E6", "supports": "vibes"}]))
    assert "supports" in ei.value.reason.lower()


def test_conclude_rejects_non_list_evidence(env):
    env.reset()
    with pytest.raises(EnvRejection):
        env.step(conclude(dominant_cause="H4", evidence_cited={"experiment": "E6"}))


def test_malformed_conclude_does_not_end_episode(env):
    """A refused conclude is not a conclusion: the episode stays open and the
    budget is untouched, exactly like a rejected purchase."""
    env.reset()
    with pytest.raises(EnvRejection):
        env.step(conclude(dominant_cause="H4", evidence_cited=["bare string"]))
    s = env.state
    assert s.concluded is False and s.budget_remaining == 8
    env.step(run("E4"))                       # still allowed
    assert env.state.experiments_run == ["E4"]


# --- trajectory capture: the auditor checks PR1-PR4 from this alone -----------
def test_trajectory_records_one_turn_per_accepted_step(env):
    env.reset()
    env.step(run("E1", buffer="hepes_without_stabilisers", coa_mM=0.0, compound_uM=50.0))
    env.step(e6_action(controls=["bacteria-free filter"]))
    env.step(conclude(dominant_cause="H4", evidence_cited=[{"experiment": "E6"}]))
    traj = env.trajectory
    assert traj.scenario_id == "falsifylab.v0_1.pptt_programme"
    assert [t.index for t in traj.turns] == [0, 1, 2]
    assert [t.action.kind for t in traj.turns] == ["run_experiment", "run_experiment", "conclude"]


def test_trajectory_captures_declared_parameters_verbatim(env):
    env.reset()
    env.step(run("E3", atc_free_days=3, read_day=10, normalisation_control="OD600"))
    env.step(e6_action(controls=["bacteria-free filter", "DMSO vehicle"]))
    turns = env.trajectory.turns
    assert turns[0].action.parameters == {
        "atc_free_days": 3, "read_day": 10, "normalisation_control": "OD600",
    }
    assert turns[1].action.parameters["arms"] == _E6_ALL
    assert turns[1].action.parameters["controls"] == ["bacteria-free filter", "DMSO vehicle"]


def test_trajectory_conclude_turn_has_no_observation(env):
    env.reset()
    env.step(run("E4"))
    env.step(conclude(dominant_cause="H4", evidence_cited=[{"experiment": "E4"}]))
    turns = env.trajectory.turns
    assert turns[0].observation is not None and turns[0].observation.experiment_id == "E4"
    assert turns[1].observation is None               # conclude turn, per CONTRACT.md


def test_refused_purchase_is_not_a_turn(env):
    env.reset()
    env.step(run("E2"))                                # 4
    env.step(run("E2"))                                # 8 -> budget 0
    with pytest.raises(EnvRejection):
        env.step(run("E4"))                            # over budget, refused
    with pytest.raises(EnvRejection):
        env.step(run("E6", arms=["parent_diacid"]))    # EC1, refused
    with pytest.raises(EnvRejection):
        env.step(conclude(evidence_cited=["bare"]))    # malformed, refused
    assert [t.index for t in env.trajectory.turns] == [0, 1]   # only the two accepted E2 runs


def test_trajectory_records_same_experiment_twice(env):
    env.reset()
    env.step(run("E4"))
    env.step(run("E4"))
    assert [t.action.experiment_id for t in env.trajectory.turns] == ["E4", "E4"]


def test_trajectory_is_a_defensive_copy(env):
    env.reset()
    env.step(run("E3", atc_free_days=3, read_day=10, normalisation_control="OD600"))
    leaked = env.trajectory
    leaked.turns.clear()
    leaked2 = env.trajectory
    leaked2.turns[0].action.parameters["read_day"] = 999
    fresh = env.trajectory
    assert len(fresh.turns) == 1                       # clear() on the copy did not empty the log
    assert fresh.turns[0].action.parameters["read_day"] == 10   # mutation did not reach the log


def test_trajectory_snapshots_action_at_step_time(env):
    """A caller that reuses and mutates one parameters dict must not rewrite a
    turn already recorded."""
    env.reset()
    params = {"atc_free_days": 3, "read_day": 10, "normalisation_control": "OD600"}
    env.step(Action(kind="run_experiment", experiment_id="E3", parameters=params))
    params["read_day"] = 14                            # mutate after the step
    assert env.trajectory.turns[0].action.parameters["read_day"] == 10


def test_trajectory_reset_clears_turns(env):
    env.reset()
    env.step(run("E4"))
    assert len(env.trajectory.turns) == 1
    env.reset()
    assert env.trajectory.turns == []


# --- unknown experiment -------------------------------------------------------
def test_unknown_experiment_refused(env):
    env.reset()
    with pytest.raises(EnvRejection):
        env.step(run("E99"))


# --- the environment does not know the answer ---------------------------------
def test_env_source_never_references_truth_or_rubric():
    import ast

    src = (REPO_ROOT / "env.py").read_text(encoding="utf-8")
    doc = ast.get_docstring(ast.parse(src), clean=False)   # the docstring names them to say it won't
    code = src.replace(doc, "") if doc else src
    assert "truth.json" not in code
    assert "rubric.json" not in code


def test_env_runs_without_truth_or_rubric_present(tmp_path):
    """Build a scenario dir with only the files the env is allowed to read."""
    (tmp_path / "agent").mkdir()
    (tmp_path / "auditor").mkdir()
    shutil.copy(REPO_ROOT / "agent" / "briefing.json", tmp_path / "agent" / "briefing.json")
    shutil.copy(REPO_ROOT / "agent" / "experiments.json", tmp_path / "agent" / "experiments.json")
    shutil.copy(
        REPO_ROOT / "auditor" / "expected_observations.json",
        tmp_path / "auditor" / "expected_observations.json",
    )
    assert not (tmp_path / "auditor" / "truth.json").exists()
    assert not (tmp_path / "auditor" / "rubric.json").exists()

    env = Env(base_dir=tmp_path)
    env.reset()
    obs = env.step(run("E6", arms=_E6_ALL, controls=["bacteria-free filter"]))
    assert obs.experiment_id == "E6"
    assert isinstance(env.state, State)
