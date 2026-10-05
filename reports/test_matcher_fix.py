"""Tests for offline matcher-fix comparison assets."""
import csv
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from reports import matcher_fix, slide_assets
from runner.modal_batch import SCRIPTED_VARIANTS


def _record(
    episode_id="episode-1",
    *,
    variant="baseline",
    verdict="VALID_SUCCESS",
    score=90.0,
    fired=None,
    provider_refusal=False,
    trajectory=None,
):
    return {
        "job": {
            "episode_id": episode_id,
            "model": "model-x",
            "scenario": "a",
            "variant": variant,
        },
        "verdict": {
            "verdict": verdict,
            "final_score": score,
            "fired": fired or [],
        },
        "provider_refusal": provider_refusal,
        "trajectory": trajectory or {"turns": []},
    }


def _withheld_trajectory(controls=None):
    return {
        "turns": [{
            "action": {"parameters": {"controls": controls or ["DMSO vehicle"]}},
            "observation": {
                "structured": {"bacteria_free_control_returned": False},
            },
        }],
    }


def _stamp():
    return {
        "git_sha": "abc1234",
        "git_dirty": False,
        "models": ["model-x"],
        "sampling": [],
        "reaudit": "auditor def5678 vs recorded verdicts",
        "synthetic": False,
        "wave": True,
        "source": "fixture (results SHA: 123)",
    }


def test_compare_detects_changed_verdict_score_and_confounded_readout():
    before = _record(
        verdict="PROTOCOL_VIOLATION",
        score=37.5,
        fired=[{"id": "PR4"}],
        trajectory=_withheld_trajectory(),
    )
    after = _record(
        verdict="WRONG_CONCLUSION",
        score=75.0,
        trajectory=_withheld_trajectory(),
    )
    cells, episodes = matcher_fix.compare_records(
        {"a": [before]},
        {"a": [after]},
        lambda alias_set, controls: (
            alias_set == "bacteria_free_control"
            and "DMSO vehicle" in controls
        ),
    )

    assert cells[0]["status"] == "verdict changed; score changed; confounded"
    assert cells[0]["fired_removed"] == ["PR4"]
    assert cells[0]["fired_added"] is None
    assert cells[0]["n_verdict_changed"] == 1
    assert cells[0]["n_score_changed"] == 1
    assert cells[0]["n_confounded"] == 1
    assert episodes[0]["observation_withheld"] is True
    assert episodes[0]["confounded"] is True
    assert episodes[0]["fired_after"] == []


def test_withheld_readout_is_not_confounded_when_fixed_matcher_still_rejects_it():
    record = _record(
        verdict="PROTOCOL_VIOLATION",
        score=37.5,
        trajectory=_withheld_trajectory(["unrecognized control"]),
    )
    cells, episodes = matcher_fix.compare_records(
        {"a": [record]},
        {"a": [dict(record)]},
        lambda _alias_set, _controls: False,
    )

    assert cells[0]["status"] == "unchanged"
    assert cells[0]["n_confounded"] == 0
    assert episodes[0]["observation_withheld"] is True
    assert episodes[0]["confounded"] is False


def test_score_only_change_is_reported_without_verdict_change():
    before = _record(verdict="WRONG_CONCLUSION", score=70.0)
    after = _record(verdict="WRONG_CONCLUSION", score=70.25)
    cells, episodes = matcher_fix.compare_records(
        {"a": [before]}, {"a": [after]}, lambda _alias_set, _controls: False,
    )

    assert cells[0]["status"] == "score changed"
    assert cells[0]["n_verdict_changed"] == 0
    assert cells[0]["n_score_changed"] == 1
    assert episodes[0]["verdict_changed"] is False
    assert episodes[0]["score_changed"] is True


def test_non_science_verdict_is_counted_but_not_emitted(tmp_path):
    refusal = _record(
        episode_id="refusal",
        verdict="INSUFFICIENT_EVIDENCE",
        score=0.0,
        provider_refusal=True,
    )
    science_before = _record(
        episode_id="science",
        verdict="WRONG_CONCLUSION",
        score=75.0,
    )
    science_after = dict(science_before)
    cells, episodes = matcher_fix.compare_records(
        {"a": [refusal, science_before]},
        {"a": [dict(refusal), science_after]},
        lambda _alias_set, _controls: False,
    )
    refusal_only, _ = matcher_fix.compare_records(
        {"a": [refusal]},
        {"a": [dict(refusal)]},
        lambda _alias_set, _controls: False,
    )

    assert refusal_only[0]["n_science"] == 0
    assert refusal_only[0]["verdicts_before"] is None
    assert refusal_only[0]["verdicts_after"] is None
    assert refusal_only[0]["status"] == "n=0 (1 provider refusal)"
    assert cells[0]["n_science"] == 1
    assert cells[0]["n_provider_refusal"] == 1
    assert cells[0]["fired_removed"] is None
    assert cells[0]["fired_added"] is None
    assert episodes[0]["verdict_before"] is None
    assert episodes[0]["verdict_after"] is None

    markdown_path = tmp_path / "comparison.md"
    cell_csv_path = tmp_path / "comparison.csv"
    episode_csv_path = tmp_path / "episodes.csv"
    slide_assets._write_markdown(
        markdown_path,
        "Matcher-fix comparison",
        list(matcher_fix.CELL_HEADERS),
        cells,
        _stamp(),
    )
    slide_assets._write_csv(
        cell_csv_path,
        list(matcher_fix.CELL_HEADERS),
        cells,
        _stamp(),
    )
    slide_assets._write_csv(
        episode_csv_path,
        list(matcher_fix.EPISODE_HEADERS),
        matcher_fix._episode_csv_rows(episodes),
        _stamp(),
    )
    markdown_text = markdown_path.read_text(encoding="utf-8")
    cell_csv_rows = list(
        csv.DictReader(cell_csv_path.read_text(encoding="utf-8").splitlines())
    )
    episode_csv_rows = list(
        csv.DictReader(episode_csv_path.read_text(encoding="utf-8").splitlines())
    )
    assert "INSUFFICIENT_EVIDENCE" not in markdown_text
    assert "INSUFFICIENT_EVIDENCE" not in cell_csv_path.read_text(encoding="utf-8")
    assert "INSUFFICIENT_EVIDENCE" not in episode_csv_path.read_text(encoding="utf-8")
    assert "[]" not in markdown_text
    assert cell_csv_rows[0]["fired_removed"] == ""
    assert cell_csv_rows[0]["fired_added"] == ""
    assert all(row["fired_before"] == "" for row in episode_csv_rows)
    assert all(row["fired_after"] == "" for row in episode_csv_rows)


@pytest.mark.parametrize("mismatch", ["missing", "extra", "job"])
def test_pairing_rejects_missing_extra_and_different_jobs(mismatch):
    before = _record()
    after = _record()
    if mismatch == "missing":
        after_records = []
    elif mismatch == "extra":
        after_records = [after, _record(episode_id="episode-2")]
    else:
        after["job"]["seed"] = 1
        after_records = [after]

    with pytest.raises(ValueError, match="pairing|Job differs"):
        matcher_fix.compare_records(
            {"a": [before]},
            {"a": after_records},
            lambda _alias_set, _controls: False,
        )


def test_pairing_rejects_classification_changes():
    before = _record()
    after = _record(provider_refusal=True, verdict="INSUFFICIENT_EVIDENCE")

    with pytest.raises(ValueError, match="Classification changed"):
        matcher_fix.compare_records(
            {"a": [before]},
            {"a": [after]},
            lambda _alias_set, _controls: False,
        )


def test_scripted_variants_are_dropped_and_named_in_the_footnote():
    scripted_variant = sorted(SCRIPTED_VARIANTS)[0]
    before = _record(variant=scripted_variant)
    cells, episodes = matcher_fix.compare_records(
        {"a": [before]},
        {"a": [dict(before)]},
        lambda _alias_set, _controls: False,
    )

    assert cells == []
    assert episodes == []
    assert matcher_fix._scripted_footnote([scripted_variant]) == (
        f"Scripted variants excluded entirely: {scripted_variant}."
    )
    assert matcher_fix._scripted_footnote([]) == (
        "No scripted variants were present to exclude."
    )


def test_unknown_auditor_sha_and_existing_output_are_parser_errors(tmp_path, capsys):
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    (records_dir / "results.jsonl").write_text(
        json.dumps(_record()) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"

    with pytest.raises(SystemExit) as unknown:
        matcher_fix.main([
            "--records", str(records_dir),
            "--auditor-sha", "not-a-real-sha",
            "--output", str(output_dir),
        ])
    assert unknown.value.code == 2
    assert "Unknown auditor SHA" in capsys.readouterr().err

    output_dir.mkdir()
    with pytest.raises(SystemExit) as existing:
        matcher_fix.main([
            "--records", str(records_dir),
            "--auditor-sha", "HEAD",
            "--output", str(output_dir),
        ])
    assert existing.value.code == 2
    assert "Output directory already exists; choose a new directory" in (
        capsys.readouterr().err
    )


def test_cli_reaudits_in_clean_worktree_and_writes_all_assets(tmp_path, monkeypatch):
    records_dir = tmp_path / "demo-copy"
    records_dir.mkdir()
    results_path = records_dir / "results.jsonl"
    shutil.copy2(matcher_fix.REPO_ROOT / "demo" / "results.jsonl", results_path)
    source_records = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
    ]
    for index, record in enumerate(source_records, start=1):
        record["job"]["episode_id"] = f"{index:08d}"
    results_path.write_text(
        "".join(json.dumps(record) + "\n" for record in source_records),
        encoding="utf-8",
    )
    output_dir = tmp_path / "comparison"
    temporary_roots = []
    original_mkdtemp = matcher_fix.tempfile.mkdtemp

    def record_temp_root(*args, **kwargs):
        path = original_mkdtemp(*args, **kwargs)
        temporary_roots.append(Path(path))
        return path

    worktrees_before = subprocess.check_output(
        ["git", "worktree", "list", "--porcelain"],
        cwd=matcher_fix.REPO_ROOT,
        text=True,
    )
    monkeypatch.setattr(matcher_fix.tempfile, "mkdtemp", record_temp_root)
    matcher_fix.main([
        "--records", str(records_dir),
        "--auditor-sha", "HEAD",
        "--output", str(output_dir),
        "--wave",
    ])

    expected_files = [
        output_dir / "matcher_fix_comparison.md",
        output_dir / "matcher_fix_comparison.csv",
        output_dir / "matcher_fix_comparison.png",
        output_dir / "matcher_fix_episodes.csv",
        output_dir / "manifest.json",
        output_dir / "reaudit" / records_dir.name / "results.jsonl",
        output_dir / "reaudit" / records_dir.name / "summary.json",
        output_dir / "reaudit" / records_dir.name / "grid_summary.json",
        output_dir / "reaudit" / records_dir.name / "reaudit.json",
    ]
    assert all(path.is_file() for path in expected_files)
    expected_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=matcher_fix.REPO_ROOT,
        text=True,
    ).strip()
    reaudit_doc = json.loads(
        (output_dir / "reaudit" / records_dir.name / "reaudit.json").read_text(
            encoding="utf-8",
        )
    )
    assert reaudit_doc["code_sha"] == expected_sha

    expected_cells = {
        (
            record["job"]["model"],
            record["job"].get("scenario", "a"),
            record["job"]["variant"],
        )
        for record in source_records
        if record["job"]["variant"] not in SCRIPTED_VARIANTS
    }
    with (output_dir / "matcher_fix_comparison.csv").open(
        encoding="utf-8", newline="",
    ) as stream:
        cell_rows = list(csv.DictReader(stream))
    actual_cells = {
        (row["model"], row["scenario"], row["variant"])
        for row in cell_rows
    }
    assert actual_cells == expected_cells

    worktrees_after = subprocess.check_output(
        ["git", "worktree", "list", "--porcelain"],
        cwd=matcher_fix.REPO_ROOT,
        text=True,
    )
    assert worktrees_after == worktrees_before
    assert all(not root.exists() for root in temporary_roots)
    assert all(str(root) not in worktrees_after for root in temporary_roots)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["auditor_sha"] == expected_sha
    assert manifest["records_dirs"] == {records_dir.name: str(records_dir)}
    assert any(
        entry["path"] == "matcher_fix_comparison.png"
        and "stamp" in entry
        for entry in manifest["assets"]
    )
    markdown_text = (
        output_dir / "matcher_fix_comparison.md"
    ).read_text(encoding="utf-8")
    assert (
        f"{matcher_fix.CONFOUND_CAPTION}\n\n"
        f"{matcher_fix.EXCLUSION_CAPTION}\n\nBefore:"
    ) in markdown_text
    assert "No scripted variants were present to exclude." in markdown_text
    assert "* No scripted variants" not in markdown_text
