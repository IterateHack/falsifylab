"""Synthetic and real-bundle checks for re-auditing saved batch results."""
from dataclasses import asdict
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from contract import Action, Observation, Result, State, Verdict
from runner import modal_batch as batch
from runner import reaudit as reaudit_module

TRUTH = {"contribution_labels": {"a": 0, "b": 0, "c": 1, "d": 1}, "dominant_cause": "d"}
RUBRIC = {"synthetic": True}


class FakeEnv:
    def __init__(self, *, seed):
        self.state = State("synthetic", 8, 0, [], False)
        self.observation = Observation("briefing", [Result("opaque string", "source")], "LOW", 0)

    def reset(self):
        return self.observation

    def step(self, action):
        if action.kind == "conclude":
            self.state.concluded = True
            return self.observation
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


def verdict(name="VALID_SUCCESS", *, visible=0.8, score=90, flags=None, protocol=20, hacks=None):
    return Verdict(name, flags or [], {
        "scientific_correctness": 40,
        "evidence_sufficiency": 20,
        "protocol_validity": protocol,
        "safety": 10,
        "brier": 0.3125,
        "applicable_max_evidence": 20,
    }, 90, visible, score, hacks or [])


def _synthetic_trajectory(seed, *, experiment_id="opaque-1", truncated=False):
    job = batch.build_jobs(["synthetic"], ["model"], [seed], 1)[0]
    trajectory = batch.run_episode(job, FakeEnv, FakeAgent).trajectory
    trajectory.turns[0].action.experiment_id = experiment_id
    trajectory.turns[0].observation.experiment_id = experiment_id
    if truncated:
        trajectory.turns = trajectory.turns[:1]
    return trajectory


def _identity_audit(trajectory, rubric, truth):
    if trajectory.turns[0].action.experiment_id == "parse":
        return verdict("PARSE_FAILURE", score=0)
    return verdict()


def _create_synthetic_batch(output: Path) -> list[dict]:
    jobs = batch.build_jobs(["baseline", "other"], ["model"], [0, 1], 1)
    results = []
    for index, job in enumerate(jobs):
        aborted = index == 1
        tag = "parse" if index == 2 else ("aborted" if aborted else "opaque-1")
        results.append({
            "job": asdict(job),
            "trajectory": asdict(_synthetic_trajectory(
                job.seed, experiment_id=tag, truncated=aborted,
            )),
            "refusals": [{"reason": "synthetic refusal"}] if aborted else [],
            "aborted_on_refusals": aborted,
            "sampling": {"client": "synthetic"},
            "model_call_log": [],
            "worker": {"on_modal": False},
        })
    batch.collect_results(results, output, RUBRIC, TRUTH, _identity_audit)
    return results


def _snapshot(directory: Path) -> dict:
    return {
        path.relative_to(directory): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_synthetic_identity_preserves_records_summaries_and_source(tmp_path):
    source = tmp_path / "source"
    _create_synthetic_batch(source)
    results_path = source / "results.jsonl"
    original_results = results_path.read_bytes()
    original_summary = (source / "summary.json").read_bytes()
    original_grid = (source / "grid_summary.json").read_bytes()
    source_snapshot = _snapshot(source)

    output = tmp_path / "reaudited"
    metadata = reaudit_module.reaudit(
        results_path, output, audit_fn=_identity_audit, rubric=RUBRIC, truth=TRUTH,
    )

    assert (output / "results.jsonl").read_bytes() == original_results
    assert (output / "summary.json").read_bytes() == original_summary
    assert (output / "grid_summary.json").read_bytes() == original_grid
    assert metadata["verdicts_changed"] == []
    assert json.loads((output / "reaudit.json").read_text()) == metadata
    assert _snapshot(source) == source_snapshot


@pytest.mark.parametrize("scenario", ["a", "b"])
def test_real_bundle_dry_run_reaudits_with_default_auditor(
    tmp_path, monkeypatch, capsys, scenario,
):
    import modal

    modal_app = Mock(side_effect=AssertionError("Modal must not be touched for a dry run"))
    monkeypatch.setattr(modal, "App", modal_app)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MODAL_TASK_ID", raising=False)
    source = tmp_path / f"batch-{scenario}"
    batch.main([
        "--dry-run",
        "--variants", "baseline",
        "--models", "claude-sonnet-4-5",
        "--seeds", "0", "1",
        "--scenario", scenario,
        "--output", str(source),
    ])
    capsys.readouterr()
    modal_app.assert_not_called()

    output = tmp_path / f"reaudited-{scenario}"
    reaudit_module.main([str(source / "results.jsonl"), "--output", str(output)])

    assert (output / "summary.json").read_bytes() == (source / "summary.json").read_bytes()
    assert (output / "grid_summary.json").read_bytes() == (source / "grid_summary.json").read_bytes()
    metadata = json.loads((output / "reaudit.json").read_text())
    assert metadata["episodes"] == 2
    assert metadata["audit"] == "auditor.audit:audit"
    assert metadata["verdicts_changed"] == []
    assert "0 verdicts changed" in capsys.readouterr().out


def test_output_must_be_new_and_separate_from_results_directory(tmp_path):
    source = tmp_path / "source"
    _create_synthetic_batch(source)
    results_path = source / "results.jsonl"
    existing = tmp_path / "existing"
    existing.mkdir()

    with pytest.raises(SystemExit) as existing_error:
        reaudit_module.main([str(results_path), "--output", str(existing)])
    assert existing_error.value.code == 2
    with pytest.raises(SystemExit) as same_directory_error:
        reaudit_module.main([str(results_path), "--output", str(source)])
    assert same_directory_error.value.code == 2


def test_legacy_results_fall_back_to_episode_files_and_report_missing_id(tmp_path):
    source = tmp_path / "source"
    _create_synthetic_batch(source)
    results_path = source / "results.jsonl"
    records = [json.loads(line) for line in results_path.read_text().splitlines()]
    for record in records:
        record.pop("trajectory")
    legacy_path = source / "legacy.jsonl"
    legacy_path.write_text("".join(json.dumps(record) + "\n" for record in records))

    output = tmp_path / "legacy-reaudited"
    reaudit_module.reaudit(
        legacy_path, output, audit_fn=_identity_audit, rubric=RUBRIC, truth=TRUTH,
    )
    assert (output / "summary.json").read_bytes() == (source / "summary.json").read_bytes()
    assert (output / "grid_summary.json").read_bytes() == (source / "grid_summary.json").read_bytes()

    missing_id = records[0]["job"]["episode_id"]
    (source / "episodes" / f"{missing_id}.json").unlink()
    with pytest.raises(FileNotFoundError, match=missing_id):
        reaudit_module.reaudit(
            legacy_path, tmp_path / "missing-episode", audit_fn=_identity_audit,
            rubric=RUBRIC, truth=TRUTH,
        )


def test_changed_auditor_reports_ids_and_keeps_original_summary(tmp_path):
    source = tmp_path / "source"
    _create_synthetic_batch(source)
    original_summary = (source / "summary.json").read_bytes()
    records = [json.loads(line) for line in (source / "results.jsonl").read_text().splitlines()]

    def changed_audit(trajectory, rubric, truth):
        return verdict("REWARD_HACK", visible=0.1, score=1, hacks=["RH1"])

    output = tmp_path / "changed"
    metadata = reaudit_module.reaudit(
        source / "results.jsonl", output, audit_fn=changed_audit, rubric=RUBRIC, truth=TRUTH,
    )

    assert metadata["verdicts_changed"] == [record["job"]["episode_id"] for record in records]
    assert (output / "summary.json").read_bytes() != original_summary
    assert (source / "summary.json").read_bytes() == original_summary


def test_cli_rejects_asset_overrides_for_multiple_scenarios(tmp_path):
    jobs = [
        batch.EpisodeJob("1", "v", "m", 0, 0, 0, "a"),
        batch.EpisodeJob("2", "v", "m", 1, 0, 1, "b"),
    ]
    results = [
        {
            "job": asdict(job),
            "trajectory": asdict(_synthetic_trajectory(job.seed)),
        }
        for job in jobs
    ]
    source = tmp_path / "source"
    batch.collect_results(results, source, RUBRIC, TRUTH, _identity_audit)

    with pytest.raises(SystemExit) as exc:
        reaudit_module.main([
            str(source / "results.jsonl"),
            "--output", str(tmp_path / "reaudited"),
            "--rubric", str(tmp_path / "rubric.json"),
        ])
    assert exc.value.code == 2
