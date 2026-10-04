"""Slide-asset pipeline tests with synthetic batch data."""
import csv
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest
from matplotlib.axes import Axes

from reports import slide_assets
from reports.synthetic import create_synthetic_inputs
from runner import modal_batch as batch


_REPORT = """\
# Synthetic validation report

## Per-pattern recall and false-positive rate
| pattern | provenance | detected / planted | recall | FP / honest | FPR |
|---|---|---|---|---|---|
| demo.one | explicit | 2 / 2 | 100% | 0 / 4 | 0% |
| demo.two | inferred | 1 / 2 | 50% | 1 / 4 | 25% |

## Cohen's kappa
| subset | n | observed agreement | kappa |
|---|---|---|---|
| overall | 8 | 88% | 0.750 |
| explicit patterns only | 6 | 100% | 1.000 |
"""


def _load_records(batch_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (batch_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def _stamp() -> dict:
    return {
        "git_sha": "abc123",
        "git_dirty": False,
        "models": ["synthetic"],
        "sampling": ["synthetic"],
        "source": "synthetic fixture",
        "reaudit": None,
        "synthetic": True,
    }


def test_synthetic_cli_creates_all_stamped_assets_and_manifest(tmp_path, capsys):
    output = tmp_path / "slides"
    slide_assets.main(["--synthetic", "--output", str(output)])
    capsys.readouterr()

    expected = {
        f"{label}/{name}"
        for label in ("synthetic_batch", "synthetic_reaudit")
        for name in (
            "clean_success_ci.png",
            "clean_success_ci.csv",
            "clean_success_ci.md",
            "raw_vs_clean.png",
            "frontier_regret_top3.png",
            "frontier_regret_top3.csv",
            "frontier_regret_top3.md",
        )
    } | {
        "auditor_validation.png",
        "auditor_validation.csv",
        "auditor_validation.md",
    }
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["assets"]
    assert {entry["path"] for entry in entries} == expected
    for entry in entries:
        asset = output / entry["path"]
        assert asset.is_file()
        stamp = entry["stamp"]
        assert stamp["git_sha"]
        assert stamp["synthetic"] is True
        assert "SYNTHETIC DATA" in slide_assets._stamp_line(stamp)
        assert entry["source_files"]
        if asset.suffix == ".png":
            assert asset.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        elif asset.suffix == ".md":
            assert asset.read_text(encoding="utf-8").splitlines()[-1].startswith(
                "*SYNTHETIC DATA"
            )
        elif asset.suffix == ".csv":
            rows = list(csv.DictReader(asset.open(encoding="utf-8")))
            assert rows
            assert all("SYNTHETIC DATA" in row["stamp"] for row in rows)


def test_clean_success_rows_match_grid_and_reject_tampering(tmp_path):
    batch_dir, _, _ = create_synthetic_inputs(tmp_path / "inputs")
    records = _load_records(batch_dir)
    one_model = [
        record for record in records
        if record["job"]["scenario"] == "a"
        and record["job"]["variant"] == "baseline"
        and record["job"]["model"] == "model-x"
    ]
    single_model_grid = batch.grid_summary(one_model)
    row = slide_assets._clean_success_rows(one_model, single_model_grid)[0]
    grid_row = single_model_grid[0]
    for key in (
        "n_clean_success", "n_scored", "clean_success_rate", "clean_success_ci95",
    ):
        assert row[key] == grid_row[key]

    full_grid = json.loads((batch_dir / "grid_summary.json").read_text(encoding="utf-8"))
    changed = [dict(row) for row in full_grid]
    target = next(
        row for row in changed
        if row["scenario"] == "a" and row["variant"] == "baseline"
    )
    target["n_clean_success"] += 1
    with pytest.raises(ValueError, match="scenario=a, variant=baseline"):
        slide_assets._clean_success_rows(records, changed)


def test_stamp_reflects_models_sampling_and_missing_sampling(tmp_path):
    batch_dir, _, _ = create_synthetic_inputs(tmp_path / "inputs")
    records = _load_records(batch_dir)
    summary = json.loads((batch_dir / "summary.json").read_text(encoding="utf-8"))
    stamp = slide_assets.build_batch_stamp(batch_dir, records, summary)
    assert stamp["models"] == ["model-x", "model-y", "scripted"]
    assert "T=0.5 client=synthetic max_tokens=512" in stamp["sampling"]
    assert "T=0.7 client=synthetic max_tokens=512" in stamp["sampling"]
    assert "scripted: no sampling" in stamp["sampling"]

    scripted = [record for record in records if record["job"]["variant"] in {"random", "ucb"}]
    scripted_stamp = slide_assets.build_batch_stamp(batch_dir, scripted, {})
    assert scripted_stamp["sampling"] == ["scripted: no sampling"]

    no_sampling = [{"job": {"model": "model-z", "variant": "baseline"}}]
    no_sampling_stamp = slide_assets.build_batch_stamp(batch_dir, no_sampling, {})
    assert no_sampling_stamp["sampling"] == []


def test_figure_stamp_wraps_inside_figure_bounds():
    stamp = _stamp()
    stamp["source"] = "synthetic/" + "a-long-source-directory/" * 25 + "results.jsonl"
    stamp["reaudit"] = "re-audit of " + "a-long-source-directory/" * 15 + "source.jsonl"
    figure = slide_assets._figure(stamp)
    artist = slide_assets._add_stamp_text(figure, stamp)
    figure.canvas.draw()

    extent = artist.get_window_extent()
    bounds = figure.bbox
    assert artist.get_fontsize() >= 6
    assert len(artist.get_text().splitlines()) <= 3
    assert "reaudit=" in artist.get_text()
    assert extent.x0 >= bounds.x0
    assert extent.y0 >= bounds.y0
    assert extent.x1 <= bounds.x1
    assert extent.y1 <= bounds.y1


def test_generate_assets_stamps_clean_repo_before_writing_inside_it(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    report_path = repo / "REPORT.md"
    report_path.write_text(_REPORT, encoding="utf-8")
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.name=Test",
            "-c", "user.email=test@example.com", "add", "REPORT.md",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.name=Test",
            "-c", "user.email=test@example.com", "commit", "-m", "Add report",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    batch_dir, _, _ = create_synthetic_inputs(tmp_path / "inputs")

    assets = slide_assets.generate_assets(
        [batch_dir],
        report_path,
        repo / "slides",
        repo_root=repo,
    )
    assert all(entry["stamp"]["git_dirty"] is False for entry in assets)
    assert all("-dirty" not in entry["stamp"]["git_sha"] for entry in assets)


def test_number_formatting_is_display_only(tmp_path):
    row = {
        "clean_success_rate": 5 / 6,
        "clean_success_ci95": [0.4371234567, 0.9701234567],
        "best-of-n minus mean": 0.1234567,
        "recall": "100%",
        "false-alarm rate": "25%",
    }
    headers = list(row)
    markdown = "\n".join(slide_assets._markdown_table(headers, [row]))
    assert "0.833" in markdown
    assert "[0.437, 0.970]" in markdown
    assert "0.123" in markdown
    assert "1.000" in markdown
    assert "0.250" in markdown

    csv_path = tmp_path / "numbers.csv"
    slide_assets._write_csv(csv_path, headers, [row], _stamp())
    csv_row = next(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert csv_row["clean_success_rate"] == str(5 / 6)
    assert csv_row["clean_success_ci95"] == json.dumps(
        row["clean_success_ci95"], separators=(",", ":"),
    )
    assert csv_row["best-of-n minus mean"] == str(row["best-of-n minus mean"])


def test_synthetic_success_and_raw_score_metrics_have_semantic_spread(tmp_path):
    batch_dir, _, _ = create_synthetic_inputs(tmp_path / "inputs")
    records = _load_records(batch_dir)
    grid_rows = json.loads((batch_dir / "grid_summary.json").read_text(encoding="utf-8"))
    clean_rows = slide_assets._clean_success_rows(records, grid_rows)
    score_rows = slide_assets._cell_score_rows(records, clean_rows)

    rates = [row["clean_success_rate"] for row in clean_rows]
    assert min(rates) <= 0.35
    assert max(rates) >= 0.85
    assert max(rates) - min(rates) >= 0.5
    assert len({row["raw_score_mean"] for row in score_rows}) >= 8
    high_raw_low_success = next(
        row for row in score_rows
        if row["scenario"] == "a"
        and row["model"] == "model-x"
        and row["variant"] == "alternate"
    )
    assert high_raw_low_success["clean_success_rate"] < 0.5
    assert high_raw_low_success["raw_score_mean"] > 90


def test_raw_vs_clean_jitters_duplicates_and_labels_every_point(tmp_path, monkeypatch):
    rows = [
        {
            "scenario": "a",
            "model": "model-x",
            "variant": variant,
            "clean_success_rate": 0.5,
            "clean_success_ci95": [0.2, 0.8],
            "raw_score_mean": 80.0,
        }
        for variant in ("baseline", "alternate")
    ]
    positions = []
    labels = []
    limits = []
    original_errorbar = Axes.errorbar
    original_annotate = Axes.annotate
    original_set_ylim = Axes.set_ylim

    def capture_errorbar(self, *args, **kwargs):
        positions.append(float(args[0]))
        return original_errorbar(self, *args, **kwargs)

    def capture_annotate(self, text, *args, **kwargs):
        labels.append(text)
        return original_annotate(self, text, *args, **kwargs)

    def capture_set_ylim(self, *args, **kwargs):
        limits.append(args[:2])
        return original_set_ylim(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "errorbar", capture_errorbar)
    monkeypatch.setattr(Axes, "annotate", capture_annotate)
    monkeypatch.setattr(Axes, "set_ylim", capture_set_ylim)
    slide_assets._plot_raw_vs_clean(tmp_path / "raw.png", rows, _stamp())

    assert len(set(positions)) == 2
    assert labels == ["a/model-x", "a/model-x"]
    assert (0, 100) in limits
    boundary_rows = [
        {
            **rows[0],
            "variant": variant,
            "clean_success_rate": 1.0,
            "clean_success_ci95": [0.7, 1.0],
        }
        for variant in ("baseline", "alternate")
    ]
    assert len({x for _, x in slide_assets._jittered_raw_points(boundary_rows)}) == 2


def test_validation_figure_title_is_updated(tmp_path, monkeypatch):
    from matplotlib.figure import Figure

    titles = []
    original_suptitle = Figure.suptitle

    def capture_suptitle(self, title, *args, **kwargs):
        titles.append(title)
        return original_suptitle(self, title, *args, **kwargs)

    monkeypatch.setattr(Figure, "suptitle", capture_suptitle)
    report_path = tmp_path / "REPORT.md"
    report_path.write_text(_REPORT, encoding="utf-8")
    patterns, kappas = slide_assets.parse_validation_report(report_path)
    slide_assets._plot_validation(tmp_path / "validation.png", patterns, kappas, _stamp())
    assert titles == ["Auditor recall and false alarms"]


def test_scripted_rows_are_marked_in_tables_and_chart_labels(tmp_path, monkeypatch):
    batch_dir, _, _ = create_synthetic_inputs(tmp_path / "inputs")
    labels = []
    original_errorbar = Axes.errorbar
    original_scatter = Axes.scatter

    def capture_errorbar(self, *args, **kwargs):
        labels.append(kwargs.get("label"))
        return original_errorbar(self, *args, **kwargs)

    def capture_scatter(self, *args, **kwargs):
        labels.append(kwargs.get("label"))
        return original_scatter(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "errorbar", capture_errorbar)
    monkeypatch.setattr(Axes, "scatter", capture_scatter)
    output_root = tmp_path / "assets"
    output_root.mkdir()
    slide_assets.generate_batch_assets(batch_dir, output_root / "synthetic_batch", output_root)

    rows = list(csv.DictReader(
        (output_root / "synthetic_batch" / "clean_success_ci.csv").open(encoding="utf-8"),
    ))
    scripted_rows = [row for row in rows if row["variant"] in {"random", "ucb"}]
    assert scripted_rows
    assert all(row["conclusion_metrics_meaningful"].lower() == "false" for row in scripted_rows)
    assert all("scripted baseline:" in row["note"] for row in scripted_rows)
    markdown = (output_root / "synthetic_batch" / "clean_success_ci.md").read_text(
        encoding="utf-8",
    )
    assert "conclusion metrics meaningful" in markdown
    assert "no †" in markdown
    assert (
        "† scripted baseline: beliefs, dominant cause and confidence are random; "
        "compare experiment selection only (mean_cost)." in markdown
    )
    assert ". Not meaningful: " in markdown
    assert "not_meaningful" not in markdown
    assert "| note |" not in markdown
    assert any(
        label == "random (scripted; conclusion metrics not meaningful)"
        for label in labels
    )
    assert any(
        label == "ucb (scripted; conclusion metrics not meaningful)"
        for label in labels
    )


def _grid_record(scenario: str, variant: str, index: int, success: bool) -> dict:
    return {
        "job": {
            "episode_id": f"{index:08d}",
            "scenario": scenario,
            "variant": variant,
            "model": "model-x",
        },
        "verdict": {"verdict": "VALID_SUCCESS" if success else "WRONG_CONCLUSION"},
        "metrics": {"clean_success": success, "final_score": 90 if success else 40},
        "aborted_on_refusals": False,
    }


def test_frontier_top3_excludes_scripted_and_preserves_grid_tie_order(tmp_path):
    records = []
    cells = [
        ("a", "random", 100, 1),
        ("a", "alpha", 2, 1),
        ("a", "beta", 2, 1),
        ("b", "gamma", 2, 1),
        ("b", "omega", 2, 1),
    ]
    index = 0
    for scenario, variant, n, successes in cells:
        for run in range(n):
            records.append(_grid_record(scenario, variant, index, run < successes))
            index += 1
    grid_rows = batch.grid_summary(records)
    top = slide_assets._top3_frontier(grid_rows)
    assert all(row["variant"] != "random" for row in top)
    assert [(row["scenario"], row["variant"]) for row in top] == [
        ("a", "alpha"), ("a", "beta"), ("b", "gamma"),
    ]

    markdown_path = tmp_path / "frontier.md"
    headers = [
        "scenario", "variant", "n_scored", "clean_success_rate", "best-of-n minus mean",
    ]
    slide_assets._write_markdown(
        markdown_path,
        "best-of-n minus mean",
        headers,
        slide_assets._frontier_rows(grid_rows),
        _stamp(),
        footnote=slide_assets.SCRIPTED_FOOTNOTE,
    )
    text = markdown_path.read_text(encoding="utf-8")
    assert "best-of-n minus mean" in text
    assert slide_assets.SCRIPTED_FOOTNOTE in text
    table = text.split("\n\n", 1)[1].split("\n\n", 1)[0]
    assert "| random |" not in table


def test_validation_parser_checks_headers_and_real_report_structure(tmp_path):
    report_path = tmp_path / "REPORT.md"
    report_path.write_text(_REPORT, encoding="utf-8")
    patterns, kappas = slide_assets.parse_validation_report(report_path)
    assert patterns == [
        {
            "pattern": "demo.one",
            "provenance": "explicit",
            "detected/planted": "2 / 2",
            "recall": "100%",
            "false alarms (FP / honest)": "0 / 4",
            "false-alarm rate": "0%",
        },
        {
            "pattern": "demo.two",
            "provenance": "inferred",
            "detected/planted": "1 / 2",
            "recall": "50%",
            "false alarms (FP / honest)": "1 / 4",
            "false-alarm rate": "25%",
        },
    ]
    assert [row["subset"] for row in kappas] == ["overall", "explicit patterns only"]
    assert [float(row["kappa"]) for row in kappas] == [0.75, 1.0]

    report_path.write_text(_REPORT.split("## Cohen's kappa", 1)[0], encoding="utf-8")
    with pytest.raises(ValueError, match="Cohen's kappa"):
        slide_assets.parse_validation_report(report_path)
    report_path.write_text(
        _REPORT.replace("| pattern | provenance |", "| pattern | source |"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Per-pattern recall and false-positive rate"):
        slide_assets.parse_validation_report(report_path)

    real_patterns, real_kappas = slide_assets.parse_validation_report(
        slide_assets.DEFAULT_VALIDATION,
    )
    assert len(real_patterns) >= 1
    by_subset = {row["subset"]: row for row in real_kappas}
    assert {"overall", "explicit patterns only"} <= by_subset.keys()
    assert all(float(row["kappa"]) == float(row["kappa"]) for row in real_kappas)


def test_reaudit_stamp_includes_source_and_changed_count(tmp_path):
    _, reaudit_dir, _ = create_synthetic_inputs(tmp_path / "inputs")
    records = _load_records(reaudit_dir)
    summary = json.loads((reaudit_dir / "summary.json").read_text(encoding="utf-8"))
    stamp = slide_assets.build_batch_stamp(reaudit_dir, records, summary)
    metadata = json.loads((reaudit_dir / "reaudit.json").read_text(encoding="utf-8"))
    assert stamp["reaudit"].startswith("re-audit of ")
    assert f"{len(metadata['verdicts_changed'])} verdicts changed" in stamp["reaudit"]
    assert len(metadata["verdicts_changed"]) >= 2


def test_real_dry_run_batch_format_is_supported(tmp_path, monkeypatch, capsys):
    import modal

    modal_app = Mock(side_effect=AssertionError("Modal must not be touched for a dry run"))
    monkeypatch.setattr(modal, "App", modal_app)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MODAL_TASK_ID", raising=False)
    batch_dir = tmp_path / "dry-run-batch"
    batch.main([
        "--dry-run",
        "--variants", "baseline",
        "--models", "claude-sonnet-4-5",
        "--seeds", "0", "1",
        "--scenario", "a",
        "--output", str(batch_dir),
    ])
    capsys.readouterr()
    modal_app.assert_not_called()

    output = tmp_path / "slides"
    slide_assets.main(["--batch", str(batch_dir), "--output", str(output)])
    capsys.readouterr()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    stamp = manifest["assets"][0]["stamp"]
    assert any("client=dry-run" in value for value in stamp["sampling"])


def test_output_directory_must_not_exist(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(SystemExit) as exc:
        slide_assets.main([
            "--batch", str(tmp_path / "unused"),
            "--output", str(output),
        ])
    assert exc.value.code == 2
