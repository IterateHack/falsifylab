"""Tests for scripted agents using real bundles and synthetic UCB observations."""
from dataclasses import asdict
import io
import json
import math
from functools import partial
from pathlib import Path
import random

import pytest

from contract import Observation, Result, State, VERDICTS, trajectory_from_dict
from runner import run_one
from runner.agents.random_agent import RandomAgent
from runner.agents.ucb import UCBAgent
from runner.factories import make_env, make_scripted_agent, scenario_dir
from runner.modal_batch import EpisodeJob, REFUSAL_EXPERIMENT_ID, run_episode


@pytest.mark.parametrize("kind", ["random", "ucb"])
@pytest.mark.parametrize("scenario", ["a", "b"])
@pytest.mark.parametrize("seed", range(5))
def test_real_env_scripted_episodes(kind, scenario, seed):
    _run_real_env_episode(kind, scenario, seed)


@pytest.mark.parametrize(
    "argv,kind,scenario,seed",
    [
        (["--agent", "random", "--scenario", "a", "--budget", "8", "--seed", "1"], "random", "a", 1),
        (["--agent", "ucb", "--scenario", "b", "--seed", "2"], "ucb", "b", 2),
    ],
)
def test_run_one_scripted_cli(argv, kind, scenario, seed, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def reject_client(*args, **kwargs):
        raise AssertionError("scripted agents must not create a model client")

    monkeypatch.setattr(run_one, "AnthropicClient", reject_client)
    record_path = tmp_path / f"{kind}.json"
    output = io.StringIO()
    code = run_one.main([*argv, "--out", str(record_path)], out=output)
    record = json.loads(record_path.read_text())
    assert code == 0
    assert record["job"]["variant"] == kind
    assert record["tokens"]["model_calls"] == 0
    assert record["agent_stats"]["model_calls"] == 0
    assert record["verdict"]["verdict"] in VERDICTS
    assert record["trajectory"]["turns"][-1]["action"]["kind"] == "conclude"
    assert "== Decision log" in output.getvalue()
    assert record["job"]["seed"] == seed
    assert record["scenario_dir"] == str(scenario_dir(scenario))


def test_run_one_rejects_scripted_model_options_and_missing_llm_model():
    with pytest.raises(SystemExit):
        run_one.main(["--agent", "ucb", "--variant", "baseline"])
    with pytest.raises(SystemExit):
        run_one.main(["--agent", "llm", "--variant", "baseline"])


def _synthetic_agent_dir(tmp_path: Path) -> Path:
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "briefing.json").write_text(json.dumps({"scenario_id": "synthetic"}))
    (agent_dir / "hypotheses.json").write_text(
        json.dumps({"hypotheses": [{"id": "H1"}, {"id": "H2"}]})
    )
    (agent_dir / "experiments.json").write_text(
        json.dumps(
            {
                "experiments": [
                    {"id": "X1", "cost": 1},
                    {"id": "X2", "cost": 1},
                    {"id": "X3", "cost": 9},
                ]
            }
        )
    )
    return agent_dir


def _synthetic_state() -> State:
    return State("synthetic", 2, 0, [], False)


def _briefing() -> Observation:
    return Observation("__briefing__", [], "UNRATED", 0, {})


def _seed_starting_with_x1() -> int:
    return next(seed for seed in range(100) if random.Random(seed).choice(["X1", "X2"]) == "X1")


def test_ucb_pulls_each_affordable_arm_before_repeating_and_skips_unaffordable(tmp_path):
    agent = UCBAgent(base_dir=_synthetic_agent_dir(tmp_path), seed=0)
    state = _synthetic_state()
    first = agent.act(_briefing(), state)
    second = agent.act(Observation(first.experiment_id, [], "UNRATED", 1, {}), state)
    third = agent.act(Observation(second.experiment_id, [], "UNRATED", 1, {}), state)
    assert first.experiment_id in {"X1", "X2"}
    assert second.experiment_id in {"X1", "X2"}
    assert second.experiment_id != first.experiment_id
    assert third.experiment_id in {"X1", "X2"}
    assert "X3" not in {first.experiment_id, second.experiment_id, third.experiment_id}


def test_ucb_reward_updates_indices_and_selects_highest_index(tmp_path):
    agent = UCBAgent(base_dir=_synthetic_agent_dir(tmp_path), seed=_seed_starting_with_x1(), c=2.0)
    state = _synthetic_state()
    first = agent.act(_briefing(), state)
    assert first.experiment_id == "X1"
    second = agent.act(Observation("X1", [Result("novel", "source")], "UNRATED", 1, {}), state)
    assert second.experiment_id == "X2"
    third = agent.act(Observation("X2", [], "UNRATED", 1, {}), state)
    assert third.experiment_id == "X1"
    entry = agent.transcript[-1]
    assert entry["reward"] == 0.0
    assert entry["counts"] == {"X1": 1, "X2": 1, "X3": 0}
    assert entry["means"] == {"X1": 1.0, "X2": 0.0, "X3": None}
    bonus = 2.0 * math.sqrt(math.log(2) / 1)
    assert entry["index"]["X1"] == pytest.approx(1.0 + bonus)
    assert entry["index"]["X2"] == pytest.approx(bonus)
    assert entry["index"]["X3"] is None


def test_ucb_zero_exploration_exploits_higher_mean(tmp_path):
    agent = UCBAgent(base_dir=_synthetic_agent_dir(tmp_path), seed=_seed_starting_with_x1(), c=0)
    state = _synthetic_state()
    first = agent.act(_briefing(), state)
    second = agent.act(Observation(first.experiment_id, [Result("novel", "source")], "UNRATED", 1, {}), state)
    third = agent.act(Observation(second.experiment_id, [], "UNRATED", 1, {}), state)
    assert first.experiment_id == "X1"
    assert second.experiment_id == "X2"
    assert third.experiment_id == "X1"


def test_ucb_identical_entries_have_zero_novelty(tmp_path):
    agent = UCBAgent(base_dir=_synthetic_agent_dir(tmp_path))
    observation = Observation("X1", [Result("repeat", "source")], "UNRATED", 1, {})
    assert agent.reward(observation, 1) == 1.0
    assert agent.reward(observation, 1) == 0.0


def test_ucb_refusal_excludes_last_arm_without_crediting_pull(tmp_path):
    agent = UCBAgent(base_dir=_synthetic_agent_dir(tmp_path), seed=0)
    first = agent.act(_briefing(), _synthetic_state())
    refusal = Observation(REFUSAL_EXPERIMENT_ID, [], "UNRATED", 0, {})
    second = agent.act(refusal, _synthetic_state())
    assert second.experiment_id != first.experiment_id
    assert first.experiment_id in agent.refused
    assert agent.counts == {"X1": 0, "X2": 0, "X3": 0}
    assert agent.transcript[-1]["reward"] is None


@pytest.mark.parametrize("agent_type", [RandomAgent, UCBAgent])
def test_scripted_agents_conclude_when_nothing_is_affordable_and_respect_cap(
    tmp_path, agent_type
):
    agent_dir = _synthetic_agent_dir(tmp_path / agent_type.__name__)
    agent = agent_type(base_dir=agent_dir, seed=0)
    conclusion = agent.act(_briefing(), State("synthetic", 0, 0, [], False))
    assert conclusion.kind == "conclude"
    capped = agent_type(base_dir=agent_dir, seed=0, budget=0)
    conclusion = capped.act(_briefing(), State("synthetic", 2, 0, [], False))
    assert conclusion.kind == "conclude"


def _assert_valid_parameters(parameters, schema):
    required = {name for name, spec in schema.items() if spec.get("required")}
    assert set(parameters) == required
    for name in required:
        spec = schema[name]
        value = parameters[name]
        kind = spec["type"]
        if kind == "enum":
            assert value in spec["values"]
        elif kind == "float":
            low, high = spec["range"]
            assert type(value) is float and low <= value <= high
        elif kind == "int":
            low, high = spec["range"]
            assert type(value) is int and low <= value <= high
        elif kind == "multi_enum":
            assert value == spec["values"]
        elif kind == "string":
            assert value == "unspecified"
        elif kind == "free_list":
            assert value == ["unspecified"]
        else:
            pytest.fail(f"unexpected required schema type: {kind}")


@pytest.mark.parametrize("scenario", ["a", "b"])
def test_random_agent_uses_affordable_experiments_and_schema_parameters(scenario):
    generator = make_scripted_agent(kind="random", seed=19, scenario=scenario, budget=8)
    for experiment in generator.experiments:
        _assert_valid_parameters(
            generator._parameters_for(experiment["id"]),
            experiment.get("parameters") or {},
        )

    for seed in range(5):
        agent = make_scripted_agent(kind="random", seed=seed, scenario=scenario, budget=8)
        state = State(scenario, 8, 0, [], False)
        observation = _briefing()
        for _ in range(20):
            action = agent.act(observation, state)
            if action.kind == "conclude":
                assert agent.affordable(state) == []
                break
            experiment = next(item for item in agent.experiments if item["id"] == action.experiment_id)
            available = min(state.budget_remaining, 8 - state.total_cost)
            assert experiment["cost"] <= available
            _assert_valid_parameters(action.parameters, experiment.get("parameters") or {})
            state.budget_remaining -= experiment["cost"]
            state.total_cost += experiment["cost"]
            state.experiments_run.append(action.experiment_id)
            observation = Observation(action.experiment_id, [], "UNRATED", experiment["cost"], {})
        else:
            pytest.fail("random agent did not conclude")


@pytest.mark.parametrize("kind,scenario,seed", [
    (kind, scenario, seed)
    for kind in ("random", "ucb")
    for scenario in ("a", "b")
    for seed in range(5)
])
def test_real_env_scripted_episodes_are_reproducible(kind, scenario, seed):
    _run_real_env_episode(kind, scenario, seed)


def _run_real_env_episode(kind, scenario, seed):
    agent_instances = []

    def agent_factory(*, variant, model, seed):
        agent = make_scripted_agent(kind=kind, seed=seed, scenario=scenario, budget=8)
        agent_instances.append(agent)
        return agent

    job = EpisodeJob(f"{seed:08d}", kind, "none", seed, 0, seed)
    trajectory = run_episode(
        job,
        partial(make_env, scenario=scenario),
        agent_factory,
    )
    hypothesis_ids = {item["id"] for item in agent_instances[0].hypotheses}
    menu_costs = [item["cost"] for item in agent_instances[0].experiments]
    assert trajectory.turns[-1].action.kind == "conclude"
    assert trajectory.turns[-1].action.abstain_reason is None
    total_cost = sum(
        turn.observation.cost
        for turn in trajectory.turns
        if turn.action.kind == "run_experiment" and turn.observation is not None
    )
    assert total_cost <= 8
    assert 8 - total_cost < min(menu_costs)
    run_ids = {
        turn.action.experiment_id
        for turn in trajectory.turns
        if turn.action.kind == "run_experiment"
    }
    for turn in trajectory.turns:
        assert set(turn.action.beliefs) == hypothesis_ids
        assert all(0 <= belief <= 1 for belief in turn.action.beliefs.values())
        citations = turn.action.evidence_cited or []
        assert {citation["experiment"] for citation in citations} <= run_ids
    assert trajectory_from_dict(asdict(trajectory)) == trajectory
    assert agent_instances[0].model_calls == 0

    repeat = run_episode(
        job,
        partial(make_env, scenario=scenario),
        agent_factory,
    )
    assert asdict(repeat) == asdict(trajectory)
    assert agent_instances[1].model_calls == 0
