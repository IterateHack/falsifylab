"""Slide-asset pipeline tests with synthetic batch data."""
import csv
import json
from copy import deepcopy
from pathlib import Path
import shutil
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
            "cost_of_pass.png",
            "experiment_selection.png",
            "experiment_selection.csv",
            "experiment_selection.md",
            "frontier_regret_top3.png",
            "frontier_regret_top3.csv",
            "frontier_regret_top3.md",
        )
    } | {
        "auditor_validation.png",
        "auditor_validation.csv",
        "auditor_validation.md",
        "replicates/replicate_summary.json",
        "replicates/replicate_summary.csv",
        "replicates/replicate_summary.md",
    }
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["assets"]
    assert {entry["path"] for entry in entries} == expected
    assert not (output / "_synthetic_input" / "REPORT.md").exists()
    replicate_entry = next(
        entry for entry in entries
        if entry["path"] == "replicates/replicate_summary.json"
    )
    replicate_records = _load_records(Path(replicate_entry["source_files"][0]).parent)
    replicate_summary = json.loads(
        (output / "replicates" / "replicate_summary.json").read_text(
            encoding="utf-8",
        ),
    )
    assert replicate_summary["stamp"]["synthetic"] is True
    assert replicate_summary["stamp"]["wave"] is False
    assert replicate_summary["excluded_scripted_variants"] == ["random", "ucb"]
    assert sum(row["n_runs"] for row in replicate_summary["rows"]) == sum(
        record["job"]["variant"] not in batch.SCRIPTED_VARIANTS
        for record in replicate_records
    )
    for label in ("synthetic_batch", "synthetic_reaudit"):
        ci_csv = output / label / "clean_success_ci.csv"
        headers = next(csv.reader(ci_csv.open(encoding="utf-8")))
        assert {
            "mean_cost", "cost_of_pass", "pass^1", "pass^3", "pass^5",
            "n_valid_success", "n_refusal_abort", "n_spend_cap_stop",
        } <= set(headers)
        ci_rows = list(csv.DictReader(ci_csv.open(encoding="utf-8")))
        for row in ci_rows:
            n = int(row["n_scored"])
            if n:
                assert float(row["pass^1"]) == int(row["n_valid_success"]) / n
            else:
                assert row["pass^1"] == ""
    assert "n = science runs" in slide_assets.PASS_K_CAPTION
    assert "pass^1 therefore equals clean_success_rate" in slide_assets.PASS_K_CAPTION
    assert "aborted on refusals" not in slide_assets.PASS_K_CAPTION
    for entry in entries:
        asset = output / entry["path"]
        assert asset.is_file()
        stamp = entry["stamp"]
        assert stamp["git_sha"]
        assert entry["source_files"]
        is_validation = entry["path"].startswith("auditor_validation.")
        assert stamp["synthetic"] is not is_validation
        if is_validation:
            assert str(slide_assets.DEFAULT_VALIDATION) in stamp["source"]
            assert str(slide_assets.DEFAULT_VALIDATION) in entry["source_files"]
            assert "SYNTHETIC DATA" not in slide_assets._stamp_line(stamp)
        else:
            assert "SYNTHETIC DATA" in slide_assets._stamp_line(stamp)
            assert stamp["wave"] is False
        if entry["path"].endswith("experiment_selection.png") or \
                entry["path"].endswith("experiment_selection.md") or \
                entry["path"].endswith("experiment_selection.csv"):
            assert any(path.endswith("auditor/rubric.json") for path in entry["source_files"])
        if asset.suffix == ".png":
            assert asset.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        elif asset.suffix == ".md":
            content = asset.read_text(encoding="utf-8")
            last_line = content.splitlines()[-1]
            assert last_line.startswith("*")
            assert ("SYNTHETIC DATA" in last_line) is not is_validation
            if entry["path"].endswith("clean_success_ci.md"):
                assert slide_assets.PASS_K_CAPTION in content
                assert slide_assets.COST_OF_PASS_CAPTION in content
                assert slide_assets.SCIENCE_DENOMINATOR_CAPTION in content
                assert slide_assets.GRID_DENOMINATOR_NOTE in content
        elif asset.suffix == ".csv":
            rows = list(csv.DictReader(asset.open(encoding="utf-8")))
            assert rows
            assert all(("SYNTHETIC DATA" in row["stamp"]) is not is_validation for row in rows)


def test_synthetic_accepts_and_honors_explicit_validation_path(tmp_path, monkeypatch, capsys):
    validation_path = tmp_path / "REPORT.md"
    validation_path.write_text(_REPORT, encoding="utf-8")
    output = tmp_path / "slides"
    captured = {}

    def fake_generate(batch_dirs, validation, output_root, **kwargs):
        captured["batch_dirs"] = batch_dirs
        captured["validation"] = validation
        return []

    monkeypatch.setattr(
        "reports.synthetic.create_synthetic_inputs",
        lambda input_root: (tmp_path / "batch", tmp_path / "reaudit"),
    )
    monkeypatch.setattr(slide_assets, "generate_assets", fake_generate)
    slide_assets.main([
        "--synthetic",
        "--validation", str(validation_path),
        "--output", str(output),
    ])
    capsys.readouterr()

    assert captured["validation"] == validation_path
    assert len(captured["batch_dirs"]) == 2


def _non_synthetic_batch_copy(tmp_path):
    source_dir, _ = create_synthetic_inputs(tmp_path / "source")
    batch_dir = tmp_path / "dry-run-batch"
    shutil.copytree(source_dir, batch_dir)
    records = _load_records(batch_dir)
    for record in records:
        sampling = record.get("sampling")
        if isinstance(sampling, dict):
            sampling["client"] = "dry-run"
    (batch_dir / "results.jsonl").write_text(
        "".join(json.dumps(record, allow_nan=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return batch_dir


def test_wave_cli_stamps_wave_and_batch_mode_watermarks_non_wave(tmp_path, capsys):
    batch_dir = _non_synthetic_batch_copy(tmp_path)
    wave_output = tmp_path / "wave-slides"
    slide_assets.main([
        "--wave", str(batch_dir),
        "--output", str(wave_output),
    ])
    capsys.readouterr()
    wave_summary_path = wave_output / "replicates" / "replicate_summary.json"
    wave_summary = json.loads(wave_summary_path.read_text(encoding="utf-8"))
    assert wave_summary["stamp"]["wave"] is True
    assert wave_summary["stamp"]["synthetic"] is False
    assert "NOT WAVE DATA" not in slide_assets._stamp_line(wave_summary["stamp"])
    wave_figure = slide_assets._figure(wave_summary["stamp"])
    assert not any("DATA" in text.get_text() for text in wave_figure.texts)
    wave_manifest = json.loads(
        (wave_output / "manifest.json").read_text(encoding="utf-8"),
    )
    assert {
        "replicates/replicate_summary.json",
        "replicates/replicate_summary.csv",
        "replicates/replicate_summary.md",
    } <= {entry["path"] for entry in wave_manifest["assets"]}
    assert all(
        entry["stamp"]["wave"] is True
        for entry in wave_manifest["assets"]
        if not entry["path"].startswith("auditor_validation.")
    )

    batch_output = tmp_path / "batch-slides"
    slide_assets.main([
        "--batch", str(batch_dir),
        "--output", str(batch_output),
    ])
    capsys.readouterr()
    batch_summary = json.loads(
        (batch_output / "replicates" / "replicate_summary.json").read_text(
            encoding="utf-8",
        ),
    )
    assert batch_summary["stamp"]["wave"] is False
    assert "NOT WAVE DATA" in slide_assets._stamp_line(batch_summary["stamp"])
    assert slide_assets._watermark(batch_summary["stamp"]) == "NOT WAVE DATA"


def test_clean_success_rows_match_grid_and_reject_tampering(tmp_path):
    batch_dir, _ = create_synthetic_inputs(tmp_path / "inputs")
    records = _load_records(batch_dir)
    one_model = [
        record for record in records
        if record["job"]["scenario"] == "a"
        and record["job"]["variant"] == "baseline"
        and record["job"]["model"] == "model-x"
        and slide_assets.classify(record) == "science"
    ]
    single_model_grid = batch.grid_summary(one_model)
    slide_assets._check_grid_consistency(one_model, single_model_grid)
    row = slide_assets._clean_success_rows(one_model, single_model_grid)[0]
    grid_row = single_model_grid[0]
    assert grid_row["n_scored"] >= row["n_scored"]
    science = slide_assets.science_records(one_model)
    assert row["n_scored"] == len(science)
    assert row["n_clean_success"] == sum(
        (record.get("metrics") or {}).get("clean_success") is True
        for record in science
    )

    full_grid = json.loads((batch_dir / "grid_summary.json").read_text(encoding="utf-8"))
    changed = [dict(row) for row in full_grid]
    target = next(
        row for row in changed
        if row["scenario"] == "a" and row["variant"] == "baseline"
    )
    target["n_clean_success"] += 1
    with pytest.raises(ValueError, match="scenario=a, variant=baseline"):
        slide_assets._clean_success_rows(records, changed)

    changed_scripted = [dict(row) for row in full_grid]
    scripted_target = next(
        row for row in changed_scripted
        if row["scenario"] == "a" and row["variant"] == "random"
    )
    scripted_target["n_clean_success"] += 1
    with pytest.raises(ValueError, match="scenario=a, variant=random"):
        slide_assets._clean_success_rows(records, changed_scripted)


def test_pass_k_combinatorics_follow_counted_run_trials():
    assert slide_assets._pass_k(5, 3, 1) == 0.6
    assert slide_assets._pass_k(5, 3, 3) == 0.1
    assert slide_assets._pass_k(5, 3, 5) == 0.0
    assert [slide_assets._pass_k(10, 10, k) for k in (1, 3, 5)] == [1.0] * 3
    assert slide_assets._pass_k(4, 3, 5) is None
    assert [slide_assets._pass_k(5, 0, k) for k in (1, 3, 5)] == [0.0] * 3


def test_science_metrics_are_invariant_to_refusal_abort_and_spend_cap_stop(tmp_path):
    batch_dir, _ = create_synthetic_inputs(tmp_path / "inputs")
    records = _load_records(batch_dir)
    template = next(
        record for record in records
        if record["job"]["scenario"] == "a"
        and record["job"]["variant"] == "baseline"
        and record["job"]["model"] == "model-x"
    )

    refusal_abort = deepcopy(template)
    refusal_abort["job"]["seed"] = 900001
    refusal_abort["job"]["repeat"] = 900001
    refusal_abort["job"]["episode_id"] = "90000001"
    refusal_abort["aborted_on_refusals"] = True
    refusal_abort["outcome"] = "aborted_on_refusals"
    refusal_abort["verdict"] = {"verdict": "VALID_SUCCESS"}
    refusal_abort["metrics"]["clean_success"] = True

    spend_cap_stop = deepcopy(template)
    spend_cap_stop["job"]["seed"] = 900002
    spend_cap_stop["job"]["repeat"] = 900002
    spend_cap_stop["job"]["episode_id"] = "90000002"
    spend_cap_stop["spend_cap_stop"] = True
    spend_cap_stop["outcome"] = "spend_cap_stop"
    spend_cap_stop["verdict"] = {"verdict": batch.HARNESS_ERROR_VERDICT}
    spend_cap_stop["metrics"] = None

    combined = [*records, refusal_abort, spend_cap_stop]
    base_ci = slide_assets._clean_success_rows(records, batch.grid_summary(records))
    combined_grid = batch.grid_summary(combined)
    combined_ci = slide_assets._clean_success_rows(combined, combined_grid)
    ci_fields = (
        "n_scored", "n_clean_success", "clean_success_rate", "pass^1",
        "pass^3", "pass^5", "n_valid_success", "clean_success_ci95",
        "mean_cost", "cost_of_pass",
    )
    ci_key = lambda row: (row["model"], row["scenario"], row["variant"])
    base_ci_by_key = {ci_key(row): row for row in base_ci}
    combined_ci_by_key = {ci_key(row): row for row in combined_ci}
    assert set(base_ci_by_key) == set(combined_ci_by_key)
    for key, row in base_ci_by_key.items():
        for field in ci_fields:
            assert combined_ci_by_key[key][field] == row[field]
    target_ci = combined_ci_by_key[("model-x", "a", "baseline")]
    assert target_ci["n_refusal_abort"] == 1
    assert target_ci["n_spend_cap_stop"] == 1

    base_scores = slide_assets._cell_score_rows(records, base_ci)
    combined_scores = slide_assets._cell_score_rows(combined, combined_ci)
    score_key = lambda row: (row["model"], row["scenario"], row["variant"])
    base_scores_by_key = {score_key(row): row for row in base_scores}
    combined_scores_by_key = {score_key(row): row for row in combined_scores}
    assert set(base_scores_by_key) == set(combined_scores_by_key)
    assert {
        key: row["raw_score_mean"] for key, row in base_scores_by_key.items()
    } == {
        key: row["raw_score_mean"] for key, row in combined_scores_by_key.items()
    }

    scenario_data = {
        scenario: slide_assets._scenario_selection_data(scenario)
        for scenario in ("a", "b")
    }
    base_selection = slide_assets._experiment_selection_rows(records, scenario_data)
    combined_selection = slide_assets._experiment_selection_rows(combined, scenario_data)
    selection_key = lambda row: (row["model"], row["scenario"], row["variant"])
    base_selection_by_key = {
        selection_key(row): row for row in base_selection
    }
    combined_selection_by_key = {
        selection_key(row): row for row in combined_selection
    }
    for key, row in base_selection_by_key.items():
        selection_fields = [
            field for field in row
            if field == "n_counted" or field == "mean_cost" or field.startswith("bought ")
        ]
        for field in selection_fields:
            assert combined_selection_by_key[key][field] == row[field]

    assert slide_assets._frontier_rows(records) == slide_assets._frontier_rows(combined)
    base_replicates, _ = slide_assets.replicate_rows(records)
    combined_replicates, _ = slide_assets.replicate_rows(combined)
    replicate_fields = (
        "n", "clean_success_mean", "clean_success_ci95", "mean_cost",
        "cost_of_pass", "cost_of_pass_ci95", "cost_of_pass_unbounded_share",
    )
    base_replicates_by_key = {
        (row["model"], row["scenario"], row["variant"]): row
        for row in base_replicates
    }
    combined_replicates_by_key = {
        (row["model"], row["scenario"], row["variant"]): row
        for row in combined_replicates
    }
    for key, row in base_replicates_by_key.items():
        for field in replicate_fields:
            assert combined_replicates_by_key[key][field] == row[field]

    changed_grid = [dict(row) for row in combined_grid]
    target_grid = next(
        row for row in changed_grid
        if row["scenario"] == "a" and row["variant"] == "baseline"
    )
    target_grid["n_clean_success"] += 1
    with pytest.raises(ValueError, match="scenario=a, variant=baseline"):
        slide_assets._clean_success_rows(combined, changed_grid)


def test_pass_k_uses_valid_verdicts_and_cost_of_pass_uses_clean_success(
    tmp_path, monkeypatch,
):
    def record(index, scenario, verdict, clean_success, cost, *, aborted=False, variant="baseline"):
        return {
            "job": {
                "episode_id": f"{index:08d}",
                "scenario": scenario,
                "variant": variant,
                "model": "model-x",
            },
            "verdict": {"verdict": verdict},
            "metrics": {
                "clean_success": clean_success,
                "cost": cost,
                "final_score": 80,
            },
            "aborted_on_refusals": aborted,
        }

    records = [
        record(0, "a", "VALID_SUCCESS", True, 2),
        record(1, "a", "WRONG_CONCLUSION", False, 4),
        record(2, "a", "VALID_SUCCESS", False, 6, aborted=True),
        record(3, "b", "WRONG_CONCLUSION", False, 2),
        record(4, "b", "WRONG_CONCLUSION", False, 4),
        record(5, "b", "WRONG_CONCLUSION", False, 6),
        {
            **record(9, "a", "HARNESS_ERROR", False, 0),
            "metrics": None,
            "spend_cap_stop": True,
            "outcome": "spend_cap_stop",
        },
    ]
    rows = slide_assets._clean_success_rows(records, batch.grid_summary(records))
    by_scenario = {row["scenario"]: row for row in rows}
    successful = by_scenario["a"]
    assert successful["n_runs"] == 4
    assert successful["n_scored"] == 2
    assert successful["n_clean_success"] == 1
    assert successful["n_valid_success"] == 1
    assert successful["n_refusal_abort"] == 1
    assert successful["n_spend_cap_stop"] == 1
    assert successful["pass^1"] == 0.5
    assert successful["pass^3"] is None
    assert successful["pass^5"] is None
    assert successful["mean_cost"] == 3.0
    assert successful["clean_success_rate"] == 0.5
    assert successful["cost_of_pass"] == 6.0

    zero_rate = by_scenario["b"]
    assert zero_rate["clean_success_rate"] == 0
    assert zero_rate["cost_of_pass"] is None

    plotted = []
    texts = []
    legend_titles = []
    axis_limits = []
    annotations = []
    original_errorbar = Axes.errorbar
    from matplotlib.figure import Figure

    original_figure_text = Figure.text
    original_legend = Figure.legend
    original_set_ylim = Axes.set_ylim
    original_annotate = Axes.annotate

    def capture_errorbar(self, *args, **kwargs):
        plotted.append((args[0], args[1], kwargs.get("fmt")))
        return original_errorbar(self, *args, **kwargs)

    def capture_text(self, x, y, text, *args, **kwargs):
        texts.append(text)
        return original_figure_text(self, x, y, text, *args, **kwargs)

    def capture_legend(self, *args, **kwargs):
        legend_titles.append(kwargs.get("title"))
        return original_legend(self, *args, **kwargs)

    def capture_set_ylim(self, *args, **kwargs):
        axis_limits.append(kwargs.get("bottom"))
        return original_set_ylim(self, *args, **kwargs)

    def capture_annotate(self, *args, **kwargs):
        annotations.append(args)
        return original_annotate(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "errorbar", capture_errorbar)
    monkeypatch.setattr(Figure, "text", capture_text)
    monkeypatch.setattr(Figure, "legend", capture_legend)
    monkeypatch.setattr(Axes, "set_ylim", capture_set_ylim)
    monkeypatch.setattr(Axes, "annotate", capture_annotate)
    slide_assets._plot_cost_of_pass(
        tmp_path / "cost_of_pass.png",
        [*rows, {**successful, "variant": "random"}],
        _stamp(),
    )

    assert plotted == [(0.5, 6.0, "o")]
    figure_copy = " ".join(text.replace("\n", " ") for text in texts)
    assert slide_assets.COST_OF_PASS_CAPTION in figure_copy
    assert slide_assets.SCIENCE_DENOMINATOR_CAPTION in figure_copy
    assert "1 cell(s) with clean success 0 omitted (cost_of_pass undefined)" in texts
    assert legend_titles == ["Variant", "Scenario"]
    assert 0 in axis_limits
    assert annotations == []


def test_selection_rows_count_scored_cost_and_charged_purchases():
    def record(
        index,
        *,
        verdict="VALID_SUCCESS",
        cost=2,
        purchases=(),
        provider_refusal=False,
        aborted=False,
    ):
        return {
            "job": {
                "episode_id": f"{index:08d}",
                "scenario": "a",
                "variant": "baseline",
                "model": "model-x",
            },
            "verdict": {"verdict": verdict},
            "metrics": None if provider_refusal or verdict == "HARNESS_ERROR" else {
                "cost": cost,
                "clean_success": verdict == "VALID_SUCCESS",
            },
            "provider_refusal": provider_refusal,
            "aborted_on_refusals": aborted,
            "trajectory": {
                "turns": [
                    {
                        "action": {"kind": "run_experiment", "experiment_id": experiment_id},
                        "observation": {"cost": 1} if charged else None,
                    }
                    for experiment_id, charged in purchases
                ],
            },
        }

    records = [
        record(0, cost=2, purchases=(("E6", True), ("E3", True))),
        record(1, cost=4, purchases=(("E6", False), ("E3", True))),
        record(2, cost=6, purchases=(("E6", True),), aborted=True),
        record(3, verdict="PARSE_FAILURE", cost=100, purchases=(("E6", True),)),
        record(4, provider_refusal=True, purchases=(("E3", True),)),
        record(5, verdict="HARNESS_ERROR", purchases=(("E6", True),)),
    ]
    scenario_data = {
        "a": {
            "budget": 8,
            "experiments": [
                {"id": "E6", "conditional": False, "label": "E6"},
                {"id": "E3", "conditional": True, "label": "E3*"},
            ],
        },
    }

    row = slide_assets._experiment_selection_rows(records, scenario_data)[0]
    assert row["n_runs"] == 6
    assert row["n_counted"] == 2
    assert row["mean_cost"] == 3
    assert row["budget"] == 8
    assert row["bought E6"] == 0.5
    assert row["bought E6 w/ params"] == 0.5
    assert row["bought E3*"] == 1.0
    assert row["bought E3* w/ params"] == 1.0
    assert row["bought all decisive"] == 0.5
    assert row["bought all decisive w/ params"] == 0.5


def test_selection_cost_plot_uses_horizontal_bars_and_integer_budget(tmp_path, monkeypatch):
    plot_titles = []
    horizontal_bars = []
    figure_texts = []
    figure_legend_labels = []
    original_set_title = Axes.set_title
    original_barh = Axes.barh
    from matplotlib.figure import Figure

    original_figure_text = Figure.text
    original_legend = Figure.legend

    def capture_title(self, title, *args, **kwargs):
        plot_titles.append(title)
        return original_set_title(self, title, *args, **kwargs)

    def capture_barh(self, *args, **kwargs):
        horizontal_bars.append(args)
        return original_barh(self, *args, **kwargs)

    def capture_figure_text(self, x, y, text, *args, **kwargs):
        figure_texts.append(text)
        return original_figure_text(self, x, y, text, *args, **kwargs)

    def capture_legend(self, *args, **kwargs):
        figure_legend_labels.extend(kwargs.get("labels", []))
        return original_legend(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "set_title", capture_title)
    monkeypatch.setattr(Axes, "barh", capture_barh)
    monkeypatch.setattr(Figure, "text", capture_figure_text)
    monkeypatch.setattr(Figure, "legend", capture_legend)
    rows = [{
        "model": "model-x",
        "scenario": "a",
        "variant": "baseline",
        "mean_cost": 2.0,
        "bought E6": 1.0,
        "bought all decisive": 1.0,
    }]
    scenario_data = {
        "a": {
            "budget": 8,
            "experiments": [{"id": "E6", "conditional": False, "label": "E6"}],
        },
    }

    slide_assets._plot_experiment_selection(
        tmp_path / "selection.png", rows, scenario_data, _stamp(),
    )

    assert len(horizontal_bars) == 1
    assert any("mean cost (budget 8)" in title for title in plot_titles)
    figure_caption = " ".join(
        " ".join(str(text).splitlines()) for text in figure_texts
    )
    normalized_caption = " ".join(figure_caption.split())
    assert " ".join(slide_assets.SELECTION_CAPTION.split()) in normalized_caption
    assert " ".join(slide_assets.SELECTION_LEGEND_CAPTION.split()) in normalized_caption
    assert " ".join(slide_assets.SCIENCE_DENOMINATOR_CAPTION.split()) in normalized_caption
    assert {"bought (pale)", "w/ params (solid)"} <= set(figure_legend_labels)


def test_decisive_experiment_extraction_is_recursive_ordered_and_conditional():
    rubric = {
        "dimensions": {
            "evidence_sufficiency": {
                "criteria": [
                    {
                        "predicate": {
                            "all": [
                                {"ran": "E6"},
                                {"any": [{"not": {"ran": "E3"}}, {"ran": "E6"}]},
                            ],
                        },
                    },
                    {
                        "applies_only_if": {"conclusion": "target_claim"},
                        "predicate": {"not": {"all": [{"ran": "E4"}]}},
                    },
                ],
            },
        },
    }
    assert slide_assets._decisive_experiments(rubric) == [
        {"id": "E6", "conditional": False, "label": "E6"},
        {"id": "E3", "conditional": False, "label": "E3"},
        {"id": "E4", "conditional": True, "label": "E4*"},
    ]


def test_evidence_rule_mapping_tracks_nested_experiment_arguments_and_guards_ops():
    rubric = {
        "dimensions": {
            "evidence_sufficiency": {
                "criteria": [
                    {"id": "EV_RUN", "predicate": {"all": [{"ran": "E6"}]}},
                    {
                        "id": "EV_PARAMETER",
                        "predicate": {
                            "not": {
                                "all": [{
                                    "param_ge": {
                                        "experiment": "E6",
                                        "param": "donors",
                                        "value": 2,
                                    },
                                }],
                            },
                        },
                    },
                ],
            },
        },
    }
    mapping = slide_assets._evidence_rule_mapping(rubric)
    assert [criterion["id"] for criterion in mapping["E6"]] == [
        "EV_RUN", "EV_PARAMETER",
    ]

    real_rules = {
        scenario: {
            experiment["id"]: set(experiment["rule_ids"])
            for experiment in slide_assets._scenario_selection_data(scenario)["experiments"]
        }
        for scenario in ("a", "b")
    }
    assert real_rules["a"] == {"E6": {"EV1", "EV2"}, "E3": {"EV3"}}
    assert real_rules["b"] == {
        "B2": {"EVB1"},
        "B5": {"EVB2"},
        "B4": {"EVB3"},
    }

    guarded = {
        "dimensions": {
            "evidence_sufficiency": {
                "criteria": [{
                    "id": "EV_BLOCKED",
                    "predicate": {
                        "all": [
                            {"ran": "E6"},
                            {
                                "conclude_field": {
                                    "field": "confidence",
                                    "equals": 0.5,
                                },
                            },
                        ],
                    },
                }],
            },
        },
    }
    with pytest.raises(ValueError, match="EV_BLOCKED"):
        slide_assets._evidence_rule_mapping(guarded)


def test_selection_parameter_rules_use_real_scenario_a_rubric():
    def find_parameter_predicate(predicate, operator, parameter):
        if not isinstance(predicate, dict) or len(predicate) != 1:
            return None
        current_operator, argument = next(iter(predicate.items()))
        if (
            current_operator == operator
            and isinstance(argument, dict)
            and argument.get("param") == parameter
        ):
            return argument
        if current_operator in ("all", "any"):
            for nested in argument:
                found = find_parameter_predicate(nested, operator, parameter)
                if found is not None:
                    return found
        elif current_operator == "not":
            return find_parameter_predicate(argument, operator, parameter)
        return None

    scenario_data = slide_assets._scenario_selection_data("a")
    experiments = scenario_data["experiments"]
    e6 = next(experiment for experiment in experiments if experiment["id"] == "E6")
    criteria_by_id = {criterion["id"]: criterion for criterion in e6["criteria"]}
    arms_rule = find_parameter_predicate(
        criteria_by_id["EV1"]["predicate"], "param_contains_all", "arms",
    )
    controls_rule = find_parameter_predicate(
        criteria_by_id["EV2"]["predicate"], "param_text_contains_any", "controls",
    )
    all_arms = list(arms_rule["values"])
    assert len(all_arms) == 3
    controls_arg = controls_rule["aliases"]
    bacteria_free_control = (
        controls_arg[0] if isinstance(controls_arg, list) else controls_arg
    )

    def turn(index, experiment_id, parameters, *, charged=True):
        observation = (
            {
                "experiment_id": experiment_id,
                "results": [{"value": "Synthetic result", "source": "synthetic"}],
                "informativeness": "LOW",
                "cost": 1,
                "structured": {},
            }
            if charged else None
        )
        return {
            "index": index,
            "action": {
                "kind": "run_experiment",
                "experiment_id": experiment_id,
                "parameters": parameters,
            },
            "observation": observation,
        }

    def record(index, arms, *, e6_charged=True):
        return {
            "job": {
                "episode_id": f"{index:08d}",
                "scenario": "a",
                "variant": "baseline",
                "model": "model-x",
            },
            "verdict": {"verdict": "WRONG_CONCLUSION"},
            "metrics": {
                "clean_success": False,
                "cost": 2,
                "final_score": 40,
            },
            "trajectory": {
                "scenario_id": "a",
                "turns": [
                    turn(
                        0,
                        "E6",
                        {"arms": list(arms), "controls": [bacteria_free_control]},
                        charged=e6_charged,
                    ),
                    turn(1, "E3", {}),
                ],
            },
        }

    records = [
        record(0, all_arms),
        record(1, all_arms[:-1]),
        record(2, all_arms, e6_charged=False),
    ]
    bought = slide_assets._counted_record_experiments(records[0])
    assert {"E6", "E3"} <= bought
    assert {"E6", "E3"} <= slide_assets._parameter_bought_experiments(
        records[0], bought, experiments,
    )

    missing_arm_bought = slide_assets._counted_record_experiments(records[1])
    assert "E6" in missing_arm_bought
    assert "E6" not in slide_assets._parameter_bought_experiments(
        records[1], missing_arm_bought, experiments,
    )

    refused_bought = slide_assets._counted_record_experiments(records[2])
    assert "E6" not in refused_bought
    assert "E6" not in slide_assets._parameter_bought_experiments(
        records[2], refused_bought, experiments,
    )

    row = slide_assets._experiment_selection_rows(
        records, {"a": {"budget": 8, "experiments": experiments}},
    )[0]
    assert row["bought E6"] == 2 / 3
    assert row["bought E6 w/ params"] == 1 / 3
    assert row["bought all decisive"] == 2 / 3
    assert row["bought all decisive w/ params"] == 1 / 3


def test_real_decisive_experiments_are_in_each_scenario_catalog():
    def experiment_ids(value):
        found = []
        if isinstance(value, dict):
            if isinstance(value.get("id"), str):
                found.append(value["id"])
            for nested in value.values():
                found.extend(experiment_ids(nested))
        elif isinstance(value, list):
            for nested in value:
                found.extend(experiment_ids(nested))
        return found

    from runner.factories import scenario_dir

    for scenario in ("a", "b"):
        info = slide_assets._scenario_selection_data(scenario)
        bundle = scenario_dir(scenario)
        catalog = set(experiment_ids(json.loads(
            (bundle / "agent" / "experiments.json").read_text(encoding="utf-8"),
        )))
        ids = [experiment["id"] for experiment in info["experiments"]]
        assert ids
        assert set(ids) <= catalog


def test_synthetic_trajectories_buy_real_budget_safe_experiments(tmp_path):
    batch_dir, _ = create_synthetic_inputs(tmp_path / "inputs")
    records = _load_records(batch_dir)
    from runner.factories import scenario_dir

    def ids_in(value):
        if isinstance(value, dict):
            return (
                ([value["id"]] if isinstance(value.get("id"), str) else [])
                + [identifier for nested in value.values() for identifier in ids_in(nested)]
            )
        if isinstance(value, list):
            return [identifier for nested in value for identifier in ids_in(nested)]
        return []

    catalog_ids = {}
    for scenario in ("a", "b"):
        experiment_doc = json.loads(
            (scenario_dir(scenario) / "agent" / "experiments.json").read_text(
                encoding="utf-8",
            ),
        )
        catalog_ids[scenario] = set(ids_in(experiment_doc))

    choices_by_cell = {}
    first_choice_by_cell = {}
    for record in records:
        scenario = record["job"]["scenario"]
        bundle = scenario_dir(scenario)
        briefing = json.loads(
            (bundle / "agent" / "briefing.json").read_text(encoding="utf-8"),
        )
        budget = briefing["budget"]["units"]
        turns = record["trajectory"]["turns"]
        run_turns = [turn for turn in turns if turn["action"]["kind"] == "run_experiment"]
        charged_turns = [
            turn for turn in run_turns
            if turn["observation"] is not None
        ]
        assert charged_turns
        assert {
            turn["action"]["experiment_id"] for turn in run_turns
        } <= catalog_ids[scenario]
        assert sum(turn["observation"]["cost"] for turn in charged_turns) <= budget
        if record["aborted_on_refusals"]:
            assert any(turn["observation"] is None for turn in run_turns)
        assert record["sampling"] is None if record["job"]["variant"] in {"random", "ucb"} \
            else record["sampling"]["client"] == "synthetic"
        key = (
            record["job"]["scenario"],
            record["job"]["variant"],
            record["job"]["model"],
        )
        choices_by_cell.setdefault(key, set()).add(tuple(
            turn["action"]["experiment_id"] for turn in charged_turns
        ))
        first_choice_by_cell.setdefault(
            key,
            charged_turns[0]["action"]["experiment_id"],
        )
    assert all(len(choices) > 1 for choices in choices_by_cell.values())
    assert any(record["aborted_on_refusals"] for record in records)
    assert any(record["verdict"]["verdict"] == "PARSE_FAILURE" for record in records)
    assert len({
        first_choice_by_cell[("a", variant, model)]
        for variant, model in (
            ("baseline", "model-x"),
            ("baseline", "model-y"),
            ("alternate", "model-x"),
            ("random", "scripted"),
            ("ucb", "scripted"),
        )
    }) > 1

def test_stamp_reflects_models_sampling_and_missing_sampling(tmp_path):
    batch_dir, _ = create_synthetic_inputs(tmp_path / "inputs")
    records = _load_records(batch_dir)
    summary = json.loads((batch_dir / "summary.json").read_text(encoding="utf-8"))
    stamp = slide_assets.build_batch_stamp(batch_dir, records, summary)
    assert stamp["wave"] is False
    assert "wave=false" in slide_assets._stamp_line(stamp)
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


def test_batch_stamp_reads_results_code_sha_from_records(tmp_path):
    stamp = slide_assets.build_batch_stamp(
        tmp_path,
        [{"code_sha": "source-commit-sha"}],
        {},
        git_stamp=("report-commit-sha", False),
    )
    assert "results SHA: source-commit-sha" in stamp["source"]


def test_readme_documents_selection_evaluator():
    readme = Path(slide_assets.__file__).with_name("README.md").read_text(
        encoding="utf-8",
    )
    assert slide_assets.SELECTION_CAPTION in readme
    assert "private `_Ctx` and `eval_pred`" in readme


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
    batch_dir, _ = create_synthetic_inputs(tmp_path / "inputs")

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
        "pass^1": 1 / 3,
        "pass^3": None,
        "pass^5": 0.01234567,
        "n_valid_success": 2,
        "mean_cost": 4.1234567,
        "cost_of_pass": 6.1234567,
        "best-of-n minus mean": 0.1234567,
        "recall": "100%",
        "false-alarm rate": "25%",
        "budget": 8.0,
    }
    headers = list(row)
    markdown = "\n".join(slide_assets._markdown_table(headers, [row]))
    assert "0.833" in markdown
    assert "[0.437, 0.970]" in markdown
    assert "0.333" in markdown
    assert "0.012" in markdown
    assert "6.123" in markdown
    assert "0.123" in markdown
    assert "1.000" in markdown
    assert "0.250" in markdown
    assert "| 8 |" in markdown
    assert "8.000" not in markdown

    csv_path = tmp_path / "numbers.csv"
    slide_assets._write_csv(csv_path, headers, [row], _stamp())
    csv_row = next(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert csv_row["clean_success_rate"] == str(5 / 6)
    assert csv_row["clean_success_ci95"] == json.dumps(
        row["clean_success_ci95"], separators=(",", ":"),
    )
    assert csv_row["pass^1"] == str(row["pass^1"])
    assert csv_row["pass^3"] == ""
    assert csv_row["pass^5"] == str(row["pass^5"])
    assert csv_row["mean_cost"] == str(row["mean_cost"])
    assert csv_row["cost_of_pass"] == str(row["cost_of_pass"])
    assert csv_row["best-of-n minus mean"] == str(row["best-of-n minus mean"])
    assert csv_row["budget"] == str(row["budget"])


def test_synthetic_success_and_raw_score_metrics_have_semantic_spread(tmp_path):
    batch_dir, _ = create_synthetic_inputs(tmp_path / "inputs")
    records = _load_records(batch_dir)
    grid_rows = json.loads((batch_dir / "grid_summary.json").read_text(encoding="utf-8"))
    clean_rows = slide_assets._clean_success_rows(records, grid_rows)
    score_rows = slide_assets._cell_score_rows(records, clean_rows)
    scenario_data = {
        scenario: slide_assets._scenario_selection_data(scenario)
        for scenario in ("a", "b")
    }
    selection_rows = slide_assets._experiment_selection_rows(records, scenario_data)
    assert all(
        row["pass^1"] == row["n_valid_success"] / row["n_scored"]
        for row in clean_rows
    )
    strict_parameter_purchases = []
    for row in selection_rows:
        for experiment in scenario_data[row["scenario"]]["experiments"]:
            label = experiment["label"]
            bought = row[f"bought {label}"]
            with_params = row[f"bought {label} w/ params"]
            assert with_params <= bought
            strict_parameter_purchases.append(0 < with_params < bought)
        assert row["bought all decisive w/ params"] <= row["bought all decisive"]
    assert any(strict_parameter_purchases)

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


def test_raw_vs_clean_offsets_coincident_points_and_uses_two_legends(tmp_path, monkeypatch):
    rows = [
        *[
            {
                "scenario": "a",
                "model": "model-x",
                "variant": variant,
                "clean_success_rate": 0.5,
                "clean_success_ci95": [0.2, 0.8],
                "raw_score_mean": 80.0,
            }
            for variant in ("baseline", "alternate")
        ],
        {
            "scenario": "b",
            "model": "model-y",
            "variant": "baseline",
            "clean_success_rate": 0.7,
            "clean_success_ci95": [0.4, 0.9],
            "raw_score_mean": 60.0,
        },
    ]
    positions = []
    markers = []
    annotations = []
    legend_titles = []
    limits = []
    figure_texts = []
    original_errorbar = Axes.errorbar
    original_annotate = Axes.annotate
    original_set_ylim = Axes.set_ylim
    from matplotlib.figure import Figure

    original_legend = Figure.legend
    original_text = Figure.text

    def capture_errorbar(self, *args, **kwargs):
        positions.append(float(args[0]))
        markers.append(kwargs["fmt"])
        return original_errorbar(self, *args, **kwargs)

    def capture_annotate(self, text, *args, **kwargs):
        annotations.append(text)
        return original_annotate(self, text, *args, **kwargs)

    def capture_set_ylim(self, *args, **kwargs):
        limits.append(args[:2])
        return original_set_ylim(self, *args, **kwargs)

    def capture_legend(self, *args, **kwargs):
        legend_titles.append(kwargs.get("title"))
        return original_legend(self, *args, **kwargs)

    def capture_text(self, x, y, text, *args, **kwargs):
        figure_texts.append(text)
        return original_text(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Axes, "errorbar", capture_errorbar)
    monkeypatch.setattr(Axes, "annotate", capture_annotate)
    monkeypatch.setattr(Axes, "set_ylim", capture_set_ylim)
    monkeypatch.setattr(Figure, "legend", capture_legend)
    monkeypatch.setattr(Figure, "text", capture_text)
    slide_assets._plot_raw_vs_clean(tmp_path / "raw.png", rows, _stamp())

    assert positions[0] != positions[1]
    assert positions[2] == 0.7
    assert markers[0] == markers[1]
    assert markers[0] != markers[2]
    assert annotations == []
    assert legend_titles == ["Variant", "Scenario"]
    assert (0, 100) in limits
    assert slide_assets.SCIENCE_DENOMINATOR_CAPTION in " ".join(
        str(text).replace("\n", " ") for text in figure_texts
    )
    boundary_rows = [
        {
            **rows[0],
            "variant": variant,
            "clean_success_rate": 1.0,
            "clean_success_ci95": [0.7, 1.0],
        }
        for variant in ("baseline", "alternate")
    ]
    assert len({
        x for _, x in slide_assets._offset_coincident_raw_points(boundary_rows)
    }) == 2


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


def test_scripted_rows_are_filtered_from_success_assets_and_in_selection(tmp_path, monkeypatch):
    batch_dir, _ = create_synthetic_inputs(tmp_path / "inputs")
    errorbar_labels = []
    figure_legend_labels = []
    original_errorbar = Axes.errorbar
    from matplotlib.figure import Figure

    def capture_errorbar(self, *args, **kwargs):
        errorbar_labels.append(kwargs.get("label"))
        return original_errorbar(self, *args, **kwargs)

    original_legend = Figure.legend

    def capture_legend(self, *args, **kwargs):
        figure_legend_labels.extend(kwargs.get("labels", []))
        return original_legend(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "errorbar", capture_errorbar)
    monkeypatch.setattr(Figure, "legend", capture_legend)
    output_root = tmp_path / "assets"
    output_root.mkdir()
    slide_assets.generate_batch_assets(batch_dir, output_root / "synthetic_batch", output_root)

    clean_rows = list(csv.DictReader(
        (output_root / "synthetic_batch" / "clean_success_ci.csv").open(encoding="utf-8"),
    ))
    assert clean_rows
    assert all(row["variant"] not in {"random", "ucb"} for row in clean_rows)
    markdown = (output_root / "synthetic_batch" / "clean_success_ci.md").read_text(
        encoding="utf-8",
    )
    assert "random" not in markdown
    assert "ucb" not in markdown
    assert "conclusion metrics meaningful" not in markdown
    assert "†" not in markdown
    assert all(
        label not in {"random", "ucb"} and "scripted" not in str(label)
        for label in errorbar_labels
    )

    selection_rows = list(csv.DictReader(
        (output_root / "synthetic_batch" / "experiment_selection.csv").open(
            encoding="utf-8",
        ),
    ))
    assert {row["variant"] for row in selection_rows} >= {"random", "ucb"}
    assert "bought E6 w/ params" in selection_rows[0]
    assert "bought all decisive w/ params" in selection_rows[0]
    selection_markdown = (
        output_root / "synthetic_batch" / "experiment_selection.md"
    ).read_text(encoding="utf-8")
    assert slide_assets.SELECTION_CAPTION in selection_markdown
    assert slide_assets.CONDITIONAL_FOOTNOTE in selection_markdown
    assert slide_assets.SCIENCE_DENOMINATOR_CAPTION in selection_markdown
    assert "bought E3*" in selection_markdown
    assert "E6 w/ params = EV1 + EV2" in selection_markdown
    assert "random (scripted)" in figure_legend_labels
    assert "ucb (scripted)" in figure_legend_labels
    assert {"bought (pale)", "w/ params (solid)"} <= set(figure_legend_labels)
    assert all("not meaningful" not in str(label) for label in figure_legend_labels)


def _grid_record(
    scenario: str, variant: str, index: int, success: bool, *, model="model-x",
) -> dict:
    return {
        "job": {
            "episode_id": f"{index:08d}",
            "scenario": scenario,
            "variant": variant,
            "model": model,
        },
        "verdict": {"verdict": "VALID_SUCCESS" if success else "WRONG_CONCLUSION"},
        "metrics": {"clean_success": success, "final_score": 90 if success else 40},
        "aborted_on_refusals": False,
    }


def test_frontier_top3_excludes_scripted_and_preserves_tie_order(tmp_path):
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
    for run in range(2):
        records.append(_grid_record(
            "a", "alpha", index, run == 0, model="model-y",
        ))
        index += 1
    top = slide_assets._frontier_rows(records)
    assert all(row["variant"] != "random" for row in top)
    assert [(row["scenario"], row["variant"]) for row in top] == [
        ("a", "alpha"), ("a", "beta"), ("b", "gamma"),
    ]
    alpha = next(row for row in top if row["variant"] == "alpha")
    assert alpha["n_scored"] == 4
    assert alpha["clean_success_rate"] == 0.5
    assert alpha["best-of-n minus mean"] == 0.5

    markdown_path = tmp_path / "frontier.md"
    headers = [
        "scenario", "variant", "n_scored", "clean_success_rate", "best-of-n minus mean",
    ]
    slide_assets._write_markdown(
        markdown_path,
        "best-of-n minus mean",
        headers,
        slide_assets._frontier_rows(records),
        _stamp(),
        footnote=slide_assets.SCRIPTED_FOOTNOTE,
        extra_sections=[slide_assets.SCIENCE_DENOMINATOR_CAPTION],
    )
    text = markdown_path.read_text(encoding="utf-8")
    assert "best-of-n minus mean" in text
    assert slide_assets.SCRIPTED_FOOTNOTE in text
    assert slide_assets.SCIENCE_DENOMINATOR_CAPTION in text
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
    _, reaudit_dir = create_synthetic_inputs(tmp_path / "inputs")
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
