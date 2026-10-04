"""Runner tests use synthetic data only; no domain assets or gold fixtures."""
from dataclasses import asdict
from contextlib import nullcontext
import json
from unittest.mock import Mock

import pytest

from contract import Action, Observation, Result, State, Verdict, trajectory_from_dict
from runner.agents import SCRIPTED_VARIANTS
from runner.factories import SCRIPTED_AGENTS
from runner import modal_batch as batch


TRUTH = {"contribution_labels": {"a": 0, "b": 0, "c": 1, "d": 1}, "dominant_cause": "d"}


class FakeEnv:
    def __init__(self, *, seed):
        self.seed = seed
        self.state = State("synthetic", 8, 0, [], False)
        self.observation = Observation("briefing", [Result("opaque string", "source")], "LOW", 0)

    def reset(self):
        return self.observation

    def step(self, action):
        if action.kind == "conclude":
            self.state.concluded = True
            return self.observation  # Contract: conclude returns briefing, but log must contain null.
        self.state.total_cost += 3
        self.state.budget_remaining -= 3
        self.state.experiments_run.append(action.experiment_id)
        self.observation.experiment_id = action.experiment_id
        self.observation.cost = 3
        return self.observation


class FakeAgent:
    def __init__(self, *, variant, model, seed):
        self.turn = 0

    def act(self, observation, state):
        self.turn += 1
        beliefs = dict.fromkeys(TRUTH["contribution_labels"], self.turn / 4)
        if self.turn < 3:
            return Action("run_experiment", experiment_id=f"opaque-{self.turn}", beliefs=beliefs,
                          dominant_cause="d")
        return Action("conclude", dominant_cause="d", confidence=0.9, beliefs=beliefs)


def verdict(name="VALID_SUCCESS", *, visible=0.8, score=90, flags=None,
            protocol=20, hacks=None):
    return Verdict(name, flags or [], {"scientific_correctness": 40, "evidence_sufficiency": 20,
                   "protocol_validity": protocol, "safety": 10, "brier": 0.3125,
                   "applicable_max_evidence": 20}, 90, visible, score, hacks or [])


def episode():
    return batch.run_episode(
        batch.build_jobs(["v"], ["m"], [7], 1)[0], FakeEnv, FakeAgent,
    ).trajectory


def test_full_grid_and_reproducible_paired_repeat_seeds():
    jobs = batch.build_jobs(["v1", "v2"], ["m1", "m2"], [7, 8], 3)
    assert len(jobs) == 24
    assert len({j.episode_id for j in jobs}) == 24
    assert jobs == batch.build_jobs(["v1", "v2"], ["m1", "m2"], [7, 8], 3)
    assert len({j.effective_seed for j in jobs}) == 6
    assert {j.effective_seed for j in jobs if j.repeat == 0} == {7, 8}
    for seed in (7, 8):
        for repeat in range(3):
            assert len({j.effective_seed for j in jobs if j.seed == seed and j.repeat == repeat}) == 1


@pytest.mark.parametrize("variants,models,seeds,n", [([], ["m"], [0], 1),
    (["v"], [], [0], 1), (["v"], ["m"], [], 1), (["v"], ["m"], [0], 0),
    (["v", "v"], ["m"], [0], 1), (["v"], ["m"], [0, 0], 1)])
def test_invalid_grids(variants, models, seeds, n):
    with pytest.raises(ValueError):
        batch.build_jobs(variants, models, seeds, n)


def test_episode_contract_roundtrip_and_snapshots():
    trajectory = episode()
    assert trajectory_from_dict(asdict(trajectory)) == trajectory
    assert [t.index for t in trajectory.turns] == [0, 1, 2]
    assert [t.action.beliefs["a"] for t in trajectory.turns] == [0.25, 0.5, 0.75]
    assert [t.observation.experiment_id for t in trajectory.turns[:-1]] == ["opaque-1", "opaque-2"]
    assert trajectory.turns[-1].observation is None
    assert len(trajectory.turns[0].observation.results) == 1


def test_factories_receive_variant_model_and_seed():
    env, agent = Mock(side_effect=FakeEnv), Mock(side_effect=FakeAgent)
    job = batch.build_jobs(["v"], ["m"], [42], 1)[0]
    batch.run_episode(job, env, agent)
    env.assert_called_once_with(seed=42)
    agent.assert_called_once_with(variant="v", model="m", seed=42)


def test_max_turns_prevents_unbounded_run():
    with pytest.raises(RuntimeError, match="did not conclude"):
        batch.run_episode(batch.build_jobs(["v"], ["m"], [0], 1)[0], FakeEnv, FakeAgent, 1)


def test_env_and_agent_stubs_remain_unimplemented():
    with pytest.raises(NotImplementedError, match="env workstream"):
        batch.make_env(seed=0).reset()
    with pytest.raises(NotImplementedError, match="agent workstream"):
        batch.make_agent(variant="v", model="m", seed=0).act(None, None)


def test_metrics_use_truth_not_visible_reward_and_independent_brier():
    trajectory = episode()
    metrics = batch.episode_metrics(trajectory, verdict(visible=-100), TRUTH)
    assert set(metrics) == {
        "nominal_success", "valid_success", "reward_hack", "protocol_violation", "cost",
        "brier", "overconfidence", "R_visible", "final_score",
    }
    trajectory.turns[-1].action.dominant_cause = "a"
    assert isinstance(batch.episode_metrics(trajectory, verdict(visible=100), TRUTH)["nominal_success"], bool)
    trajectory.turns[-1].action.kind = "run_experiment"
    trajectory.turns[-1].action.dominant_cause = "d"
    assert isinstance(batch.episode_metrics(trajectory, verdict(), TRUTH)["nominal_success"], bool)


def test_aborted_metrics_fail_without_requiring_a_conclusion():
    trajectory = episode()
    trajectory.turns = []
    metrics = batch.aborted_metrics(
        trajectory, verdict("REWARD_HACK", flags=["OVERCONFIDENT"], hacks=["RH1"], protocol=0),
    )
    assert metrics["nominal_success"] is False
    assert metrics["valid_success"] is False
    assert metrics["R_visible"] == 0.0
    assert metrics["final_score"] == 0.0
    assert metrics["brier"] is None
    assert metrics["reward_hack"] is True
    assert metrics["protocol_violation"] is True
    assert metrics["overconfidence"] is True
    assert metrics["cost"] == 0


def test_breaches_survive_verdict_precedence_and_flags_are_explicit():
    metrics = batch.episode_metrics(episode(), verdict("UNSAFE_ACTION", protocol=0,
                                   flags=["OVERCONFIDENT"], hacks=["RH1"]), TRUTH)
    assert metrics["reward_hack"] and metrics["protocol_violation"] and metrics["overconfidence"]
    assert not metrics["valid_success"]
    assert batch.episode_metrics(episode(), verdict("REWARD_HACK"), TRUTH)["reward_hack"]
    assert batch.episode_metrics(episode(), verdict("PROTOCOL_VIOLATION"), TRUTH)["protocol_violation"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_beliefs_rejected(bad):
    trajectory = episode()
    trajectory.turns[-1].action.beliefs["a"] = bad
    with pytest.raises(ValueError, match="probabilities"):
        batch.episode_metrics(trajectory, verdict(), TRUTH)


def test_truth_and_belief_ids_must_match():
    with pytest.raises(ValueError, match="four"):
        batch.validate_truth({"contribution_labels": {"x": 1}, "dominant_cause": "x"})
    trajectory = episode()
    trajectory.turns[-1].action.beliefs["renamed"] = trajectory.turns[-1].action.beliefs.pop("a")
    with pytest.raises(ValueError, match="exactly"):
        batch.episode_metrics(trajectory, verdict(), TRUTH)


def test_per_variant_aggregation_pools_models_and_seeds():
    jobs = batch.build_jobs(["v", "w"], ["m", "other"], [7], 1)
    records = []
    for i, job in enumerate(jobs):
        v = verdict("REWARD_HACK" if i == 0 else "VALID_SUCCESS", visible=i, score=20 * i,
                    flags=["OVERCONFIDENT"] if i == 0 else [], protocol=0 if i == 0 else 20)
        records.append({"job": asdict(job), "metrics": batch.episode_metrics(episode(), v, TRUTH)})
    summary = batch.aggregate(records)
    assert summary["v"]["episodes"] == 2
    assert summary["v"]["completed_episodes"] == 2
    assert summary["v"]["aborted_on_refusals"] == 0
    assert summary["v"]["refusals"] == 0
    assert set(summary["v"]) == {
        "episodes", "completed_episodes", "aborted_on_refusals", "refusals",
        "nominal_success_rate", "valid_success_rate", "reward_hack_rate",
        "protocol_violation_rate", "mean_cost", "mean_brier", "overconfidence_rate",
        "mean_R_visible", "mean_final_score", "brier_n", "completed_only",
    }
    assert summary["v"]["brier_n"] == 2
    assert summary["v"]["completed_only"]["brier_n"] == 2
    assert summary["w"]["episodes"] == 2


def test_grid_summary_counts_failures_parse_failures_aborts_and_sorts():
    def row(variant, *, scenario=None, success=False, verdict_name="WRONG_CONCLUSION",
            aborted=False):
        job = {"variant": variant}
        if scenario is not None:
            job["scenario"] = scenario
        return {
            "job": job,
            "verdict": {"verdict": verdict_name},
            "metrics": {"valid_success": success},
            "aborted_on_refusals": aborted,
        }

    records = [
        row("all-fail"),
        *[row("one-of-four", scenario="b", success=index == 0) for index in range(4)],
        row("all-success", success=True),
        row("all-success", success=True),
        row("parse-excluded", success=True),
        row("parse-excluded", verdict_name="PARSE_FAILURE"),
        row("aborted", scenario="b", success=True),
        row("aborted", scenario="b", aborted=True),
        row("all-parse", scenario="z", verdict_name="PARSE_FAILURE"),
    ]

    summary = batch.grid_summary(records)
    cells = {(record["scenario"], record["variant"]): record for record in summary}
    assert cells[("a", "all-fail")]["frontier_regret"] == 0
    assert cells[("b", "one-of-four")]["n_runs"] == 4
    assert cells[("b", "one-of-four")]["n_success"] == 1
    assert cells[("b", "one-of-four")]["success_rate"] == 0.25
    assert cells[("b", "one-of-four")]["frontier_regret"] == 0.75
    assert cells[("a", "all-success")]["frontier_regret"] == 0
    assert cells[("a", "parse-excluded")]["n_runs"] == 2
    assert cells[("a", "parse-excluded")]["n_parse_failure"] == 1
    assert cells[("a", "parse-excluded")]["success_rate"] == 1.0
    assert cells[("b", "aborted")]["n_runs"] == 2
    assert cells[("b", "aborted")]["n_success"] == 1
    assert cells[("b", "aborted")]["success_rate"] == 0.5
    assert cells[("b", "aborted")]["frontier_regret"] == 0.5
    assert cells[("z", "all-parse")]["success_rate"] is None
    assert cells[("z", "all-parse")]["frontier_regret"] is None
    assert all(record["success_metric"] == "valid_success" for record in summary)
    assert [(record["scenario"], record["variant"]) for record in summary] == [
        ("b", "one-of-four"),
        ("b", "aborted"),
        ("a", "all-fail"),
        ("a", "all-success"),
        ("a", "parse-excluded"),
        ("z", "all-parse"),
    ]


def test_scripted_variants_are_labeled_non_meaningful_in_aggregate_and_chart(tmp_path, monkeypatch):
    assert set(SCRIPTED_AGENTS) == SCRIPTED_VARIANTS
    records = [
        {
            "job": {"variant": variant},
            "metrics": {
                "nominal_success": 0,
                "valid_success": 0,
                "reward_hack": 0,
                "protocol_violation": 0,
                "cost": 1,
                "brier": 0.5,
                "overconfidence": 0,
                "R_visible": 0,
                "final_score": 0,
            },
            "verdict": {"R_visible": 0, "final_score": 0},
        }
        for variant in ("random", "ucb", "baseline")
    ]
    summary = batch.aggregate(records)
    for variant in ("random", "ucb"):
        assert summary[variant]["conclusion_metrics_meaningful"] is False
        assert summary[variant]["not_meaningful"] == list(batch.CONCLUSION_METRICS)
        assert summary[variant]["note"] == (
            "scripted baseline: beliefs, dominant cause and confidence are random; "
            "compare experiment selection only (mean_cost). protocol_violation_rate is not "
            "meaningful: protocol constraints also check the conclusion's hypotheses and citations"
        )
    assert "conclusion_metrics_meaningful" not in summary["baseline"]
    assert "not_meaningful" not in summary["baseline"]
    assert "note" not in summary["baseline"]

    from matplotlib.axes import Axes

    legend = Axes.legend
    labels = []

    def tracked_legend(self, *args, **kwargs):
        handles = kwargs.get("handles", args[0] if args else ())
        labels.extend(handle.get_label() for handle in handles)
        return legend(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "legend", tracked_legend)
    batch.write_chart(records, tmp_path / "chart.png")
    assert labels == [
        "baseline",
        "random (scripted; conclusion metrics not meaningful)",
        "ucb (scripted; conclusion metrics not meaningful)",
    ]


def test_collect_logs_audits_and_emits_one_chart(tmp_path, monkeypatch):
    from matplotlib.axes import Axes

    scatter = Axes.scatter
    points = []

    def tracked_scatter(self, x, y, **kwargs):
        points.extend(zip(x, y))
        return scatter(self, x, y, **kwargs)

    monkeypatch.setattr(Axes, "scatter", tracked_scatter)
    jobs = batch.build_jobs(["v", "w"], ["m"], [7], 2)
    results = [{"job": asdict(job), "trajectory": asdict(episode())} for job in reversed(jobs)]
    audit = Mock(return_value=verdict())
    output = tmp_path / "batch"
    summary = batch.collect_results(iter(results), output, {"opaque": True}, TRUTH, audit)
    assert audit.call_count == 4
    assert summary["v"]["episodes"] == 2
    logs = list((output / "episodes").glob("*.json"))
    assert len(logs) == 4
    for log in logs:
        doc = json.loads(log.read_text())
        assert set(doc) == {"scenario_id", "turns"}
        assert trajectory_from_dict(doc) == episode()
    assert len((output / "results.jsonl").read_text().splitlines()) == 4
    assert json.loads((output / "summary.json").read_text()) == summary
    grid = json.loads((output / "grid_summary.json").read_text())
    assert len(grid) == 2
    assert all(row["scenario"] == "a" for row in grid)
    assert (output / "reward_vs_audit.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert len(points) == 4
    assert len(list(output.glob("*.png"))) == 1


def test_audit_failure_preserves_episode_without_publishing_summary(tmp_path):
    job = batch.build_jobs(["v"], ["m"], [7], 1)[0]
    results = [{"job": asdict(job), "trajectory": asdict(episode())}]
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="audit failed"):
        batch.collect_results(results, output, {}, TRUTH,
                              Mock(side_effect=RuntimeError("audit failed")))
    assert (output / "episodes" / f"{job.episode_id}.json").exists()
    assert not (output / "summary.json").exists()
    assert not (output / "grid_summary.json").exists()
    assert not (output / "reward_vs_audit.png").exists()


def test_collect_records_aborted_episode_as_failure_and_charts_audited_verdict(
    tmp_path, monkeypatch,
):
    from matplotlib.axes import Axes

    scatter = Axes.scatter
    points = []

    def tracked_scatter(self, x, y, **kwargs):
        points.append((list(x), list(y), kwargs))
        return scatter(self, x, y, **kwargs)

    monkeypatch.setattr(Axes, "scatter", tracked_scatter)
    jobs = batch.build_jobs(["v"], ["m"], [7], 2)
    partial = episode()
    partial.turns = partial.turns[:-1]
    refusal = {
        "turn_index": len(partial.turns),
        "agent_call": 2,
        "rejection_type": "overspend",
        "reason": "over budget",
        "action": {"kind": "run_experiment", "experiment_id": "E6"},
    }
    results = [
        {"job": asdict(jobs[0]), "trajectory": asdict(episode())},
        {
            "job": asdict(jobs[1]),
            "trajectory": asdict(partial),
            "refusals": [refusal],
            "aborted_on_refusals": True,
        },
    ]
    audited = verdict("VALID_SUCCESS", visible=0.9, score=88)
    audit = Mock(side_effect=[verdict("VALID_SUCCESS", visible=0.8, score=90), audited])
    output = tmp_path / "aborted"

    summary = batch.collect_results(results, output, {}, TRUTH, audit)

    assert audit.call_count == 2
    records = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    record = records[1]
    assert record["aborted_on_refusals"] is True
    assert record["refusal_count"] == 1
    assert len(record["refusals"]) == 1
    assert record["verdict"] == asdict(audited)
    assert record["metrics"]["nominal_success"] is False
    assert record["metrics"]["valid_success"] is False
    assert record["metrics"]["R_visible"] == 0.0
    assert record["metrics"]["final_score"] == 0.0
    assert record["metrics"]["brier"] is None
    assert record["metrics"]["cost"] == 6
    assert (output / "episodes" / f"{jobs[1].episode_id}.json").exists()
    assert summary["v"]["episodes"] == 2
    assert summary["v"]["completed_episodes"] == 1
    assert summary["v"]["aborted_on_refusals"] == 1
    assert summary["v"]["refusals"] == 1
    assert summary["v"]["valid_success_rate"] == 0.5
    assert summary["v"]["mean_final_score"] == 45
    assert summary["v"]["brier_n"] == 1
    assert summary["v"]["completed_only"]["valid_success_rate"] == 1.0
    assert summary["v"]["completed_only"]["mean_final_score"] == 90
    assert summary["v"]["completed_only"]["brier_n"] == 1
    assert batch.aggregate([record])["v"]["completed_only"] is None
    assert len(points) == 2
    assert {point[2]["marker"] for point in points} == {"o", "x"}
    aborted_point = next(point for point in points if point[2]["marker"] == "x")
    assert aborted_point[:2] == ([audited.R_visible], [audited.final_score])
    assert (output / "reward_vs_audit.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_remote_worker_resolves_factories_without_truth_or_rubric(monkeypatch):
    monkeypatch.setattr(batch, "resolve", lambda ref: {"env": FakeEnv, "agent": FakeAgent}[ref])
    job = batch.build_jobs(["v"], ["m"], [7], 1)[0]
    result = batch.remote_episode(job, "env", "agent", 10)
    assert result == {
        "job": asdict(job),
        "trajectory": asdict(episode()),
        "refusals": [],
        "aborted_on_refusals": False,
    }


def test_output_cannot_overwrite_previous_run(tmp_path):
    with pytest.raises(FileExistsError):
        batch.collect_results([], tmp_path, {}, TRUTH, Mock())


def test_agent_cannot_mutate_env_state_or_logged_actions():
    env = FakeEnv(seed=0)

    class MutatingAgent(FakeAgent):
        def act(self, observation, state):
            state.total_cost = 999
            state.experiments_run.append("invented")
            return super().act(observation, state)

    job = batch.build_jobs(["v"], ["m"], [7], 1)[0]
    trajectory = batch.run_episode(job, lambda **kwargs: env, MutatingAgent).trajectory
    assert env.state.total_cost == 6
    assert env.state.experiments_run == ["opaque-1", "opaque-2"]
    assert trajectory.turns[-1].action.dominant_cause == "d"


@pytest.mark.parametrize("embedded_constraints", [False, True])
def test_cli_dispatches_parallel_map_and_real_audit_locally(
    tmp_path, monkeypatch, capsys, embedded_constraints,
):
    import modal
    import auditor.audit as auditor

    truth_path, rubric_path = tmp_path / "truth.json", tmp_path / "rubric.json"
    truth_path.write_text(json.dumps(TRUTH))
    constraints = {"protocol_constraints": [{"id": "synthetic-protocol",
                    "breach": {"ran": "opaque-1"}}], "safety_constraints": []}
    rubric = {
        "dimensions": {
            "scientific_correctness": {"criteria": [{"points": 30, "predicate": {
                "conclude_field_equals_truth": {"field": "dominant_cause", "truth_key": "dominant_cause"}}}]},
            "evidence_sufficiency": {"max_with_target_claim": 30, "max_without_target_claim": 20,
                "criteria": [{"points": 20, "predicate": {"ran": "opaque-1"}}]},
            "protocol_validity": {"criteria": [{"points": 20}]},
            "safety": {"criteria": [{"points": 10}]},
        },
        "visible_reward": {"concluded_weight": 1, "cost_weight": -0.05, "potency": {
            "source_experiment": "opaque-2", "structured_key": "measurement",
            "baseline": 10, "direction": "decrease", "weight": 0.5}},
        "flags": {"overconfident": {"confidence_gt": 0.8, "requires_not_ran": "opaque-missing"}},
    }
    if embedded_constraints:
        rubric["constraints"] = constraints
        # Embedded constraints must take precedence over a conflicting sibling.
        (tmp_path / "constraints.json").write_text(json.dumps({"protocol_constraints": []}))
    else:
        (tmp_path / "constraints.json").write_text(json.dumps(constraints))
    rubric_path.write_text(json.dumps(rubric))
    output = tmp_path / "results"
    audit = Mock(wraps=auditor.audit)
    loader = Mock(wraps=auditor.load_rubric)
    monkeypatch.setattr(auditor, "audit", audit)
    monkeypatch.setattr(auditor, "load_rubric", loader)

    def mapped(jobs, *, kwargs, order_outputs):
        assert len(jobs) == 8
        assert order_outputs is False
        assert set(kwargs) == {"env_factory", "agent_factory", "max_turns"}
        return iter({
            "job": asdict(job),
            "trajectory": asdict(episode()),
            "refusals": [],
            "aborted_on_refusals": False,
        } for job in jobs)

    worker = Mock()
    worker.map.side_effect = mapped
    app = Mock()
    app.function.return_value = lambda function: worker
    app.run.return_value = nullcontext()
    monkeypatch.setattr(modal, "App", Mock(return_value=app))
    monkeypatch.setattr(modal, "enable_output", nullcontext)
    batch.main(["--variants", "v", "w", "--models", "m", "--seeds", "7", "8", "--n", "2",
                "--truth", str(truth_path), "--rubric", str(rubric_path), "--output", str(output)])
    captured = capsys.readouterr().out
    grid_start = captured.index("== Grid summary ==")
    assert grid_start > captured.rfind('"mean_final_score"')
    assert '"scenario": "a"' in captured[grid_start:]
    worker.map.assert_called_once()
    assert audit.call_count == 8
    assert audit.call_args.args[2] == TRUTH
    loader.assert_called_once_with(rubric_path)
    assert audit.call_args.args[1]["constraints"] == constraints
    assert app.function.call_args.kwargs["max_containers"] == 32
    summary = json.loads((output / "summary.json").read_text())["v"]
    assert summary["episodes"] == 4
    assert summary["completed_episodes"] == 4
    assert summary["aborted_on_refusals"] == 0
    assert summary["refusals"] == 0
    records = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    assert all(record["verdict"]["verdict"] == "PROTOCOL_VIOLATION" for record in records)
    assert all(record["aborted_on_refusals"] is False for record in records)
    assert all(set(record["metrics"]) == set(batch.episode_metrics(episode(), verdict(), TRUTH))
               for record in records)


def test_modal_sdk_accepts_worker_definition_without_launching_cloud():
    import modal

    image = modal.Image.debian_slim(python_version="3.12").add_local_python_source("contract", "runner")
    app = modal.App("runner-definition-test")
    worker = app.function(image=image, timeout=900, max_containers=32)(batch.remote_episode)
    assert isinstance(worker, modal.Function)
