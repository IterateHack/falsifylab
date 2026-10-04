"""Real-fixture checks for human labelling and agreement reporting."""
import hashlib
import io
import json
from pathlib import Path

import pytest

from auditor.audit import audit, load_rubric
from auditor.validation.real import agreement as agreement_module
from auditor.validation.real import label as label_module
from contract import trajectory_from_dict
from runner import modal_batch


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = (
    ("auditor/tests/golden/canonical_valid.json", "a", "VALID_SUCCESS", []),
    ("auditor/tests/golden/canonical_hack.json", "a", "REWARD_HACK", ["RH1"]),
    ("auditor/tests/golden/parse_failure_abstain.json", "a", "PARSE_FAILURE", []),
    (
        "scenarios/b_cd5_affinity/auditor/tests/golden/canonical_valid.json",
        "b",
        "VALID_SUCCESS",
        [],
    ),
    (
        "scenarios/b_cd5_affinity/auditor/tests/golden/canonical_trap.json",
        "b",
        "REWARD_HACK",
        ["RH1"],
    ),
)


def _build_results(path: Path) -> list[dict]:
    records = []
    for index, (relative_path, scenario, expected_verdict, expected_hacks) in enumerate(FIXTURES):
        fixture = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
        trajectory = trajectory_from_dict(fixture)
        bundle = ROOT if scenario == "a" else ROOT / "scenarios" / "b_cd5_affinity"
        rubric = load_rubric(bundle / "auditor" / "rubric.json")
        truth = json.loads((bundle / "auditor" / "truth.json").read_text(encoding="utf-8"))
        verdict = audit(trajectory, rubric, truth)
        assert verdict.verdict == expected_verdict
        assert verdict.reward_hacks == expected_hacks
        job = modal_batch.EpisodeJob(
            f"{index:08d}", "baseline", "fixture-model", index, 0, index, scenario,
        )
        record = modal_batch.build_record(
            job,
            trajectory,
            verdict,
            truth,
            refusals=[],
            aborted_on_refusals=expected_verdict == "PARSE_FAILURE",
            extra={},
        )
        if expected_verdict == "PARSE_FAILURE":
            record["aborted_on_refusals"] = False
            record["metrics"] = {}
        records.append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, allow_nan=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return records


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _scripted(values: list[str]):
    iterator = iter(values)
    return lambda: next(iterator)


def test_session_labels_every_scored_fixture_and_excludes_parse_failure(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    labels_path = tmp_path / "labels.jsonl"
    out = io.StringIO()
    session = label_module.label_session(
        results_path, labels_path, labeller="Ada", input_fn=_scripted(["honest", ""] * 4), out=out,
    )

    rows = _read_rows(labels_path)
    assert session == {
        "labelled": 4,
        "skipped": 0,
        "remaining": 0,
        "excluded_parse_failure": 1,
    }
    assert set(rows[0]) == {
        "episode_id", "scenario", "results_sha256", "labels", "note", "labeller",
        "saw_verdict", "auditor_verdict", "labelled_at",
    }
    assert rows[0]["saw_verdict"] is True
    assert rows[0]["results_sha256"] == hashlib.sha256(results_path.read_bytes()).hexdigest()
    assert "turn 0:" in out.getvalue()
    assert out.getvalue().index("verdict") < out.getvalue().index("Label (comma-separated")
    assert "Excluded 1 PARSE_FAILURE" in out.getvalue()


def test_resume_quit_leaves_written_row_and_prompts_only_for_remaining(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    labels_path = tmp_path / "labels.jsonl"
    first = label_module.label_session(
        results_path, labels_path, labeller="Ada", input_fn=_scripted(["honest", "", "q"]),
        out=io.StringIO(),
    )
    original = labels_path.read_bytes()
    assert first["labelled"] == 1
    assert first["remaining"] == 3
    second = label_module.label_session(
        results_path, labels_path, labeller="Ada", input_fn=_scripted(["honest", ""] * 3),
        out=io.StringIO(),
    )
    assert second["labelled"] == 3
    assert labels_path.read_bytes().startswith(original)
    assert len(_read_rows(labels_path)) == 4


def test_invalid_labels_reprompt_and_do_not_write_until_valid(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    labels_path = tmp_path / "labels.jsonl"
    out = io.StringIO()
    label_module.label_session(
        results_path,
        labels_path,
        labeller="Ada",
        input_fn=_scripted(["RH9", "honest,RH1", "other_hack", "", "rh1", "", "q"]),
        out=out,
    )
    rows = _read_rows(labels_path)
    assert len(rows) == 1
    assert rows[0]["labels"] == ["RH1"]
    assert rows[0]["note"] is None
    assert out.getvalue().count("Invalid label:") == 3


def test_blind_hides_verdict_until_after_first_row_is_written(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    labels_path = tmp_path / "labels.jsonl"
    out = io.StringIO()
    before_first_input = []

    def input_fn():
        if not before_first_input:
            before_first_input.append(out.getvalue())
        input_fn.calls += 1
        return "honest" if input_fn.calls % 2 == 1 else ""

    input_fn.calls = 0
    result = label_module.label_session(
        results_path, labels_path, labeller="Ada", blind=True, input_fn=input_fn, out=out,
    )
    assert result["labelled"] == 4
    assert "== Audit ==" not in before_first_input[0]
    assert "== Audit ==" in out.getvalue()
    assert all(not row["saw_verdict"] for row in _read_rows(labels_path))


def test_foreign_results_hash_is_rejected_by_label_and_agreement(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(json.dumps({
        "episode_id": "00000000", "results_sha256": "different",
    }) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="one results file"):
        label_module.label_session(
            results_path, labels_path, labeller="Ada", input_fn=_scripted([]), out=io.StringIO(),
        )
    with pytest.raises(ValueError, match="one results file"):
        agreement_module.agreement(results_path, labels_path)


def test_agreement_rejects_labels_for_missing_episode_ids(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(json.dumps({
        "episode_id": "missing", "results_sha256": hashlib.sha256(
            results_path.read_bytes(),
        ).hexdigest(), "labels": ["honest"],
    }) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="absent from results"):
        agreement_module.agreement(results_path, labels_path)


def test_relabel_appends_and_agreement_uses_last_row(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    labels_path = tmp_path / "labels.jsonl"
    label_module.label_session(
        results_path, labels_path, labeller="Ada", input_fn=_scripted(["honest", "", "q"]),
        out=io.StringIO(),
    )
    prior = _read_rows(labels_path)[0]
    relabelled = label_module.label_session(
        results_path,
        labels_path,
        labeller="Bea",
        relabel=[prior["episode_id"]],
        input_fn=_scripted(["RH1", "changed my mind", "q"]),
        out=io.StringIO(),
    )
    assert relabelled["labelled"] == 1
    assert len(_read_rows(labels_path)) == 2
    assert _read_rows(labels_path)[-1]["labeller"] == "Bea"
    report = agreement_module.agreement(results_path, labels_path)
    assert report["disagreements"][0]["human"] == ["RH1"]


def test_kappa_hand_computed_perfect_and_all_same():
    result = agreement_module.cohen_kappa([
        (True, True), (True, False), (False, False), (False, False),
    ])
    assert result == {"n": 4, "observed_agreement": 0.75, "kappa": 0.5}
    assert agreement_module.cohen_kappa([(True, True), (False, False)])["kappa"] == 1.0
    assert agreement_module.cohen_kappa([(True, True), (True, True)])["kappa"] is None
    assert agreement_module.cohen_kappa([]) == {
        "n": 0, "observed_agreement": None, "kappa": None,
    }


def test_per_category_reward_hacks_are_scenario_qualified(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    records = _read_rows(results_path)
    labels_path = tmp_path / "labels.jsonl"
    results_sha = hashlib.sha256(results_path.read_bytes()).hexdigest()
    rows = []
    for record in records:
        episode_id = record["job"]["episode_id"]
        labels = ["honest"]
        if episode_id == "00000000":  # A valid episode
            labels = ["honest"]
        elif episode_id == "00000001":  # A RH1 auditor hit, but human says honest
            labels = ["honest"]
        elif episode_id in {"00000003", "00000004"}:  # B labels are scored within B only
            labels = ["RH1"]
        rows.append({
            "episode_id": episode_id,
            "scenario": record["job"]["scenario"],
            "results_sha256": results_sha,
            "labels": labels,
            "note": None,
            "labeller": "Ada",
            "saw_verdict": True,
            "auditor_verdict": record["verdict"]["verdict"],
            "labelled_at": "2025-01-01T00:00:00+00:00",
        })
    labels_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
    )
    report = agreement_module.agreement(results_path, labels_path)
    assert report["per_category"]["a:RH1"]["fn"] == 1
    assert report["per_category"]["a:RH1"]["fp"] == 0
    assert report["per_category"]["b:RH1"]["fp"] == 1
    assert report["per_category"]["b:RH1"]["fn"] == 0
    assert "RH1" not in report["per_category"]


def test_dry_run_batch_label_cli_and_agreement_cli_never_launch_modal(tmp_path, monkeypatch):
    import modal
    from unittest.mock import Mock

    app = Mock(side_effect=AssertionError("Modal must not be touched for a dry run"))
    monkeypatch.setattr(modal, "App", app)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    batch_dir = tmp_path / "batch"
    modal_batch.main([
        "--dry-run", "--variants", "baseline", "--models", "claude-sonnet-4-5",
        "--seeds", "0", "1", "--scenario", "a", "--output", str(batch_dir),
    ])
    app.assert_not_called()
    inputs = iter(["honest", ""] * 2)
    monkeypatch.setattr("builtins.input", lambda: next(inputs))
    labels_path = tmp_path / "labels.jsonl"
    label_module.main([
        str(batch_dir / "results.jsonl"), "--labels", str(labels_path), "--labeller", "CLI",
    ], out=io.StringIO())
    agreement_path = tmp_path / "agreement.json"
    markdown_path = tmp_path / "agreement.md"
    agreement_module.main([
        str(batch_dir / "results.jsonl"), str(labels_path), "--out", str(agreement_path),
        "--markdown", str(markdown_path),
    ], out=io.StringIO())
    assert batch_dir.joinpath("results.jsonl").exists()
    assert json.loads(agreement_path.read_text(encoding="utf-8"))["n_scored"] == 2
    assert markdown_path.exists()
    app.assert_not_called()
