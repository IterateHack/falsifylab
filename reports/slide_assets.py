"""Create slide-ready tables and figures from batch and auditor validation outputs."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
import subprocess
from statistics import fmean
import textwrap

from runner.factories import scenario_dir
from runner.modal_batch import (
    HARNESS_ERROR_VERDICT,
    SCRIPTED_VARIANTS,
    split_science_records,
    wilson_interval,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALIDATION = REPO_ROOT / "auditor" / "validation" / "REPORT.md"
SCRIPTED_FOOTNOTE = (
    "Scripted baselines (random, ucb) excluded: frontier_regret is not meaningful "
    "for them (conclusion metrics random)."
)
SELECTION_CAPTION = (
    "bought = ran the experiment; parameter requirements of the evidence rules not checked"
)
CONDITIONAL_FOOTNOTE = "* scored only when the conclusion makes a target claim"
PATTERN_HEADING = "## Per-pattern recall and false-positive rate"
KAPPA_HEADING = "## Cohen's kappa"
PATTERN_HEADER = (
    "pattern", "provenance", "detected / planted", "recall", "FP / honest", "FPR",
)
KAPPA_HEADER = ("subset", "n", "observed agreement", "kappa")


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def _code_shas(value) -> set[str]:
    found = set()
    if isinstance(value, dict):
        if value.get("code_sha") is not None:
            found.add(str(value["code_sha"]))
        for nested in value.values():
            found.update(_code_shas(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_code_shas(nested))
    return found


def _git_stamp(repo_root: Path) -> tuple[str, bool]:
    sha = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=repo_root, text=True,
    ).strip()
    dirty = bool(subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repo_root, text=True,
    ).strip())
    return f"{sha}-dirty" if dirty else sha, dirty


def _sampling_summary(records: list[dict]) -> list[str]:
    values = set()
    has_scripted = False
    for record in records:
        if record.get("job", {}).get("variant") in SCRIPTED_VARIANTS:
            has_scripted = True
        sampling = record.get("sampling")
        if not isinstance(sampling, dict):
            continue
        values.add((
            str(sampling.get("temperature", "unknown")),
            str(sampling.get("client", "unknown")),
            str(sampling.get("max_tokens", "unknown")),
        ))
    rendered = [
        f"T={temperature} client={client} max_tokens={max_tokens}"
        for temperature, client, max_tokens in sorted(values)
    ]
    if has_scripted:
        rendered.append("scripted: no sampling")
    return rendered


def build_batch_stamp(
    batch_dir: Path, records: list[dict], summary: dict, *,
    repo_root: Path = REPO_ROOT, git_stamp: tuple[str, bool] | None = None,
) -> dict:
    batch_dir = Path(batch_dir)
    git_sha, dirty = git_stamp or _git_stamp(Path(repo_root))
    code_shas = _code_shas(records) | _code_shas(summary)
    results_sha = ", ".join(sorted(code_shas)) if code_shas else "not recorded"
    reaudit_path = batch_dir / "reaudit.json"
    reaudit_note = None
    if reaudit_path.is_file():
        reaudit_doc = json.loads(reaudit_path.read_text(encoding="utf-8"))
        changed = reaudit_doc.get("verdicts_changed", [])
        reaudit_note = (
            f"re-audit of {reaudit_doc.get('source', 'unknown source')}, "
            f"{len(changed)} verdicts changed"
        )
    models = sorted({
        str(record["job"]["model"])
        for record in records
        if record.get("job", {}).get("model") is not None
    })
    sampling = _sampling_summary(records)
    synthetic = any(
        isinstance(record.get("sampling"), dict)
        and record["sampling"].get("client") == "synthetic"
        for record in records
    )
    return {
        "git_sha": git_sha,
        "git_dirty": dirty,
        "models": models,
        "sampling": sampling,
        "source": f"{batch_dir} (results SHA: {results_sha})",
        "reaudit": reaudit_note,
        "synthetic": synthetic,
    }


def _last_touching_commit(path: Path, repo_root: Path) -> str:
    try:
        relative = Path(path).resolve().relative_to(repo_root.resolve())
    except ValueError:
        return "not committed"
    result = subprocess.check_output(
        ["git", "log", "-1", "--format=%h", "--", str(relative)],
        cwd=repo_root,
        text=True,
    ).strip()
    return result or "not committed"


def build_validation_stamp(
    report_path: Path, *, synthetic: bool = False, repo_root: Path = REPO_ROOT,
    git_stamp: tuple[str, bool] | None = None,
) -> dict:
    report_path = Path(report_path)
    git_sha, dirty = git_stamp or _git_stamp(Path(repo_root))
    commit = _last_touching_commit(report_path, Path(repo_root))
    return {
        "git_sha": git_sha,
        "git_dirty": dirty,
        "models": "none (scripted validation cases)",
        "sampling": "n/a",
        "source": f"{report_path} (last commit: {commit})",
        "reaudit": None,
        "synthetic": synthetic,
    }


def _stamp_line(stamp: dict) -> str:
    def render(value) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value) or "none"
        return str(value) if value is not None else "none"

    parts = [
        f"git_sha={stamp['git_sha']}",
        f"git_dirty={str(stamp['git_dirty']).lower()}",
        f"models={render(stamp['models'])}",
        f"sampling={render(stamp['sampling'])}",
        f"reaudit={render(stamp['reaudit'])}",
        f"synthetic={str(stamp['synthetic']).lower()}",
        f"source={stamp['source']}",
    ]
    prefix = "SYNTHETIC DATA — " if stamp["synthetic"] else ""
    return prefix + " | ".join(parts)


def _cell_text(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _display_cell(header: str, value) -> str:
    if value is None:
        return "—"
    if header == "clean_success_ci95":
        return f"[{float(value[0]):.3f}, {float(value[1]):.3f}]"
    rate_headers = {
        "clean_success_rate", "best-of-n minus mean", "frontier_regret",
        "recall", "false-alarm rate", "observed agreement",
    }
    if header in rate_headers:
        try:
            number = float(value[:-1]) / 100 if isinstance(value, str) and value.endswith("%") \
                else float(value)
        except (TypeError, ValueError):
            return _cell_text(value)
        return f"{number:.3f}"
    if header == "budget":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return _cell_text(value)
        return str(int(number)) if number.is_integer() else f"{number:g}"
    if header == "mean_cost" or header.startswith("bought "):
        try:
            return f"{float(value):.3f}"
        except (TypeError, ValueError):
            return _cell_text(value)
    return _cell_text(value)


def _markdown_table(headers: list[str], rows: list[dict]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [
            _display_cell(header, row.get(header)).replace("|", r"\|").replace("\n", " ")
            for header in headers
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _write_markdown(
    path: Path, title: str, headers: list[str], rows: list[dict], stamp: dict, *,
    footnote: str | None = None, extra_sections: list[str] | None = None,
) -> None:
    lines = [f"# {title}", "", *_markdown_table(headers, rows)]
    if footnote:
        lines.extend(["", footnote])
    if extra_sections:
        lines.extend(["", *extra_sections])
    lines.extend(["", f"*{_stamp_line(stamp)}*", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _write_csv(path: Path, headers: list[str], rows: list[dict], stamp: dict) -> None:
    headers_with_stamp = [*headers, "stamp"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers_with_stamp)
        writer.writeheader()
        for row in rows:
            output = {header: _csv_value(row.get(header)) for header in headers}
            output["stamp"] = _stamp_line(stamp)
            writer.writerow(output)


def _batch_groups(records: list[dict], keys: tuple[str, ...]) -> dict[tuple, list[dict]]:
    groups = defaultdict(list)
    for record in records:
        job = record["job"]
        values = tuple(
            job.get(key, "a") if key == "scenario" else job[key]
            for key in keys
        )
        groups[values].append(record)
    return groups


def _split_counted_records(records: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    non_harness_rows = [
        record for record in records
        if record["verdict"]["verdict"] != HARNESS_ERROR_VERDICT
    ]
    return split_science_records(non_harness_rows)


def _scored_success_values(records: list[dict]) -> tuple[int, int, float | None, list | None]:
    scored, _, _ = _split_counted_records(records)
    n_clean_success = sum(
        (record.get("metrics") or {}).get("clean_success") is True for record in scored
    )
    n_scored = len(scored)
    rate = n_clean_success / n_scored if n_scored else None
    ci95 = list(wilson_interval(n_clean_success, n_scored)) if n_scored else None
    return n_clean_success, n_scored, rate, ci95


def _check_grid_consistency(records: list[dict], grid_rows: list[dict]) -> None:
    pooled = _batch_groups(records, ("scenario", "variant"))
    grid_by_cell = {
        (row.get("scenario", "a"), row["variant"]): row for row in grid_rows
    }
    for cell in sorted(set(pooled) | set(grid_by_cell)):
        scenario, variant = cell
        grid_row = grid_by_cell.get(cell)
        if grid_row is None:
            raise ValueError(f"Grid summary mismatch for cell scenario={scenario}, variant={variant}")
        expected = _scored_success_values(pooled[cell])
        expected_values = {
            "n_clean_success": expected[0],
            "n_scored": expected[1],
            "clean_success_rate": expected[2],
            "clean_success_ci95": expected[3],
        }
        for field, value in expected_values.items():
            if grid_row.get(field) != value:
                raise ValueError(
                    f"Grid summary mismatch for cell scenario={scenario}, "
                    f"variant={variant}: {field}"
                )


def _clean_success_rows(records: list[dict], grid_rows: list[dict]) -> list[dict]:
    _check_grid_consistency(records, grid_rows)
    result = []
    for (model, scenario, variant), cell_records in sorted(
        _batch_groups(records, ("model", "scenario", "variant")).items()
    ):
        if variant in SCRIPTED_VARIANTS:
            continue
        scored, excluded, provider_refusals = _split_counted_records(cell_records)
        n_clean_success = sum(
            (record.get("metrics") or {}).get("clean_success") is True
            for record in scored
        )
        n_scored = len(scored)
        rate = n_clean_success / n_scored if n_scored else None
        ci95 = list(wilson_interval(n_clean_success, n_scored)) if n_scored else None
        result.append({
            "model": model,
            "scenario": scenario,
            "variant": variant,
            "n_runs": len(cell_records),
            "n_harness_error": sum(
                record["verdict"]["verdict"] == HARNESS_ERROR_VERDICT
                for record in cell_records
            ),
            "n_parse_failure": len(excluded),
            "n_provider_refusal": len(provider_refusals),
            "n_scored": n_scored,
            "n_clean_success": n_clean_success,
            "clean_success_rate": rate,
            "clean_success_ci95": ci95,
        })
    return result


def _cell_score_rows(records: list[dict], clean_rows: list[dict]) -> list[dict]:
    groups = _batch_groups(records, ("model", "scenario", "variant"))
    result = []
    for row in clean_rows:
        scored, _, _ = _split_counted_records(
            groups[(row["model"], row["scenario"], row["variant"])],
        )
        result.append({
            **row,
            "raw_score_mean": (
                fmean((record.get("metrics") or {})["final_score"] for record in scored)
                if scored else None
            ),
        })
    return result


def _figure(stamp: dict):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(10, 5.625))
    FigureCanvasAgg(figure)
    if stamp["synthetic"]:
        figure.text(
            0.5, 0.52, "SYNTHETIC DATA", fontsize=30, color="#777777",
            alpha=0.16, rotation=25, ha="center", va="center", zorder=100,
        )
    return figure


def _add_stamp_text(figure, stamp: dict):
    font_size = 6
    max_width = max(
        48,
        int((figure.get_figwidth() - 0.2) * 72 / (font_size * 0.58)),
    )
    artist = None
    for width in range(max_width, 39, -12):
        wrapped = textwrap.fill(
            _stamp_line(stamp),
            width=width,
            max_lines=3,
            placeholder="…",
        )
        if artist is not None:
            artist.remove()
        artist = figure.text(
            0.01,
            0.012,
            wrapped,
            fontsize=font_size,
            ha="left",
            va="bottom",
            linespacing=1.1,
        )
        figure.canvas.draw()
        extent = artist.get_window_extent()
        bounds = figure.bbox
        if (
            extent.x0 >= bounds.x0
            and extent.y0 >= bounds.y0
            and extent.x1 <= bounds.x1
            and extent.y1 <= bounds.y1
        ):
            return artist
    raise ValueError("Could not fit the figure stamp within the canvas")


def _save_figure(figure, path: Path, stamp: dict) -> None:
    _add_stamp_text(figure, stamp)
    figure.savefig(path, dpi=200, format="png")


def _variant_colors(variants: set[str]) -> dict[str, str]:
    from matplotlib import rcParams

    colors = rcParams["axes.prop_cycle"].by_key()["color"]
    return {
        variant: colors[index % len(colors)]
        for index, variant in enumerate(sorted(variants))
    }


def _dedupe_legend(axes) -> None:
    handles, labels = axes.get_legend_handles_labels()
    unique = {}
    for handle, label in zip(handles, labels):
        if label and label != "_nolegend_":
            unique.setdefault(label, handle)
    if unique:
        axes.legend(unique.values(), unique.keys(), fontsize=9, loc="best")


def _plot_clean_success(path: Path, rows: list[dict], stamp: dict) -> None:
    figure = _figure(stamp)
    axes = figure.subplots()
    figure.subplots_adjust(left=0.08, right=0.98, bottom=0.25, top=0.88)
    colors = _variant_colors({row["variant"] for row in rows})
    sorted_rows = sorted(
        rows, key=lambda row: (row["scenario"], row["model"], row["variant"]),
    )
    x_positions = {}
    scenario_centers = {}
    separators = []
    cursor = 0
    previous_last = None
    for scenario in sorted({row["scenario"] for row in sorted_rows}):
        scenario_rows = [row for row in sorted_rows if row["scenario"] == scenario]
        positions = list(range(cursor, cursor + len(scenario_rows)))
        if previous_last is not None:
            separators.append((previous_last + positions[0]) / 2)
        for row, position in zip(scenario_rows, positions):
            x_positions[(row["model"], row["scenario"], row["variant"])] = position
        scenario_centers[scenario] = sum(positions) / len(positions)
        previous_last = positions[-1]
        cursor += len(scenario_rows) + 1

    for separator in separators:
        axes.axvline(separator, color="#c9c9c9", linewidth=1, zorder=0)
    for scenario, center in scenario_centers.items():
        axes.text(
            center,
            -0.2,
            f"Scenario {scenario}",
            transform=axes.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=10,
        )
    for row in sorted_rows:
        index = x_positions[(row["model"], row["scenario"], row["variant"])]
        if row["clean_success_rate"] is None:
            continue
        low, high = row["clean_success_ci95"]
        color = colors[row["variant"]]
        axes.errorbar(
            index,
            row["clean_success_rate"],
            yerr=[[row["clean_success_rate"] - low], [high - row["clean_success_rate"]]],
            fmt="o",
            color=color,
            ecolor=color,
            markerfacecolor=color,
            markeredgecolor=color,
            capsize=3,
            label=row["variant"],
        )
    axes.set_title("Clean success rate with 95% Wilson intervals", fontsize=14)
    axes.set_ylabel("Clean success rate", fontsize=10)
    axes.set_ylim(-0.05, 1.05)
    axes.set_xlim(-0.6, cursor - 1.4)
    axes.set_xticks(
        [x_positions[(row["model"], row["scenario"], row["variant"])] for row in sorted_rows],
        [f"{row['model']}\n{row['variant']}" for row in sorted_rows],
        fontsize=9,
    )
    from matplotlib.ticker import FormatStrFormatter

    axes.yaxis.set_major_formatter(FormatStrFormatter("%.3f"))
    axes.grid(axis="y", alpha=0.25)
    _dedupe_legend(axes)
    _save_figure(figure, path, stamp)


def _offset_coincident_raw_points(rows: list[dict]) -> list[tuple[dict, float]]:
    grouped = defaultdict(list)
    for row in sorted(
        rows, key=lambda item: (item["scenario"], item["model"], item["variant"]),
    ):
        rate = row["clean_success_rate"]
        score = row["raw_score_mean"]
        if rate is not None and score is not None:
            grouped[(rate, score)].append(row)
    points = []
    for (rate, score), duplicates in grouped.items():
        ci = duplicates[0]["clean_success_ci95"]
        lower_spread = min(0.025, max(0.0, (rate - ci[0]) * 0.75))
        upper_spread = min(0.025, max(0.0, (ci[1] - rate) * 0.75))
        for index, row in enumerate(duplicates):
            offset = (
                0.0 if len(duplicates) == 1
                else -lower_spread
                + (lower_spread + upper_spread) * index / (len(duplicates) - 1)
            )
            points.append((row, rate + offset))
    return points


def _plot_raw_vs_clean(path: Path, rows: list[dict], stamp: dict) -> None:
    figure = _figure(stamp)
    axes = figure.subplots()
    figure.subplots_adjust(left=0.09, right=0.98, bottom=0.31, top=0.88)
    colors = _variant_colors({row["variant"] for row in rows})
    scenarios = sorted({row["scenario"] for row in rows})
    markers = ("o", "s", "^", "D", "v", "P", "X", "<", ">")
    scenario_markers = {
        scenario: markers[index % len(markers)]
        for index, scenario in enumerate(scenarios)
    }
    for row, x in _offset_coincident_raw_points(rows):
        rate = row["clean_success_rate"]
        score = row["raw_score_mean"]
        low, high = row["clean_success_ci95"]
        color = colors[row["variant"]]
        axes.errorbar(
            x,
            score,
            xerr=[[rate - low], [high - rate]],
            fmt=scenario_markers[row["scenario"]],
            color=color,
            ecolor=color,
            markerfacecolor=color,
            markeredgecolor=color,
            capsize=3,
            label="_nolegend_",
        )
    axes.set_title("Raw audited score vs clean success", fontsize=14)
    axes.set_xlabel("Clean success rate (horizontal 95% Wilson CI)", fontsize=10)
    axes.set_ylabel("Raw audited score mean", fontsize=10)
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 100)
    axes.tick_params(axis="both", labelsize=9)
    from matplotlib.ticker import FormatStrFormatter

    axes.xaxis.set_major_formatter(FormatStrFormatter("%.3f"))
    axes.grid(alpha=0.25)
    from matplotlib.lines import Line2D

    variant_handles = [
        Line2D(
            [], [], color=colors[variant], marker="o", linestyle="None", label=variant,
        )
        for variant in sorted(colors)
    ]
    scenario_handles = [
        Line2D(
            [], [], color="#444444", marker=scenario_markers[scenario],
            linestyle="None", label=scenario,
        )
        for scenario in scenarios
    ]
    figure.legend(
        handles=variant_handles,
        loc="center",
        bbox_to_anchor=(0.5, 0.20),
        ncol=max(1, len(variant_handles)),
        title="Variant",
        fontsize=9,
    )
    figure.legend(
        handles=scenario_handles,
        loc="center",
        bbox_to_anchor=(0.5, 0.095),
        ncol=max(1, len(scenario_handles)),
        title="Scenario",
        fontsize=9,
    )
    _save_figure(figure, path, stamp)


def _decisive_experiments(rubric: dict) -> list[dict]:
    experiments: dict[str, bool] = {}

    def add_ran_value(value, conditional: bool) -> None:
        if isinstance(value, str):
            if value not in experiments:
                experiments[value] = conditional
            elif not conditional:
                experiments[value] = False
        elif isinstance(value, list):
            for item in value:
                add_ran_value(item, conditional)
        elif isinstance(value, dict):
            for nested in value.values():
                add_ran_value(nested, conditional)

    def walk_predicate(value, conditional: bool) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key == "ran":
                    add_ran_value(nested, conditional)
                else:
                    walk_predicate(nested, conditional)
        elif isinstance(value, list):
            for nested in value:
                walk_predicate(nested, conditional)

    criteria = rubric["dimensions"]["evidence_sufficiency"]["criteria"]
    for criterion in criteria:
        walk_predicate(
            criterion.get("predicate"),
            "applies_only_if" in criterion,
        )
    return [
        {
            "id": experiment_id,
            "conditional": conditional,
            "label": experiment_id + ("*" if conditional else ""),
        }
        for experiment_id, conditional in experiments.items()
    ]


def _scenario_selection_data(scenario: str) -> dict:
    bundle = scenario_dir(scenario)
    briefing_path = bundle / "agent" / "briefing.json"
    rubric_path = bundle / "auditor" / "rubric.json"
    briefing = json.loads(briefing_path.read_text(encoding="utf-8"))
    rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
    return {
        "budget": briefing["budget"]["units"],
        "experiments": _decisive_experiments(rubric),
        "source_files": [briefing_path, rubric_path],
    }


def _counted_record_experiments(record: dict) -> set[str]:
    trajectory = record.get("trajectory") or {}
    bought = set()
    for turn in trajectory.get("turns", []):
        action = turn.get("action") or {}
        if (
            action.get("kind") == "run_experiment"
            and action.get("experiment_id") is not None
            and turn.get("observation") is not None
        ):
            bought.add(str(action["experiment_id"]))
    return bought


def _experiment_selection_rows(
    records: list[dict], scenario_data: dict[str, dict],
) -> list[dict]:
    rows = []
    for (model, scenario, variant), cell_records in sorted(
        _batch_groups(records, ("model", "scenario", "variant")).items()
    ):
        scored, _, _ = _split_counted_records(cell_records)
        experiments = scenario_data[scenario]["experiments"]
        bought_by_record = [
            _counted_record_experiments(record)
            for record in scored
        ]
        row = {
            "model": model,
            "scenario": scenario,
            "variant": variant,
            "n_runs": len(cell_records),
            "n_counted": len(scored),
            "mean_cost": (
                fmean(float((record.get("metrics") or {})["cost"]) for record in scored)
                if scored else None
            ),
            "budget": scenario_data[scenario]["budget"],
        }
        for experiment in experiments:
            label = experiment["label"]
            row[f"bought {label}"] = (
                sum(experiment["id"] in bought for bought in bought_by_record) / len(scored)
                if scored else None
            )
        decisive_ids = {experiment["id"] for experiment in experiments}
        row["bought all decisive"] = (
            sum(decisive_ids <= bought for bought in bought_by_record) / len(scored)
            if scored and decisive_ids else None
        )
        rows.append(row)
    return rows


def _selection_series_label(model: str, variant: str) -> str:
    return f"{variant} (scripted)" if variant in SCRIPTED_VARIANTS else f"{variant}/{model}"


def _plot_experiment_selection(
    path: Path,
    rows: list[dict],
    scenario_data: dict[str, dict],
    stamp: dict,
) -> None:
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    scenarios = sorted(scenario_data)
    figure = _figure(stamp)
    axes_grid = figure.subplots(len(scenarios), 2, squeeze=False)
    series_keys = sorted({
        (row["model"], row["variant"])
        for row in rows
    }, key=lambda item: (item[1], item[0]))
    colors = _variant_colors({row["variant"] for row in rows})
    scripted_hatches = {"random": "///", "ucb": "\\\\"}
    legend_handles = []
    legend_labels = []
    for model, variant in series_keys:
        scripted = variant in SCRIPTED_VARIANTS
        legend_handles.append(Patch(
            facecolor="#888888" if scripted else colors[variant],
            edgecolor="#444444",
            hatch=scripted_hatches.get(variant, "") if scripted else "",
        ))
        legend_labels.append(_selection_series_label(model, variant))

    for row_index, scenario in enumerate(scenarios):
        scenario_rows = [
            row for row in rows if row["scenario"] == scenario
        ]
        rows_by_series = {
            (row["model"], row["variant"]): row
            for row in scenario_rows
        }
        budget = scenario_data[scenario]["budget"]
        cost_axes, bought_axes = axes_grid[row_index]
        positions = list(range(len(series_keys)))
        for index, key in enumerate(series_keys):
            row = rows_by_series.get(key)
            if row is None:
                continue
            model, variant = key
            scripted = variant in SCRIPTED_VARIANTS
            cost_axes.barh(
                index,
                row["mean_cost"] or 0,
                color="#888888" if scripted else colors[variant],
                edgecolor="#444444",
                hatch=scripted_hatches.get(variant, "") if scripted else "",
            )
        cost_axes.axvline(budget, color="#333333", linestyle="--", linewidth=1)
        cost_axes.set_title(f"Scenario {scenario} · mean cost per episode", fontsize=12)
        cost_axes.set_xlabel("Mean cost (budget units)", fontsize=9)
        cost_axes.set_yticks(
            positions,
            [_selection_series_label(model, variant) for model, variant in series_keys],
            fontsize=9,
        )
        cost_axes.text(
            0.98, 0.94, f"Budget { _display_cell('budget', budget) }",
            transform=cost_axes.transAxes, ha="right", va="top", fontsize=9,
        )
        cost_axes.set_xlim(left=0)
        cost_axes.grid(axis="x", alpha=0.2)

        experiment_labels = [
            experiment["label"]
            for experiment in scenario_data[scenario]["experiments"]
        ] + ["all"]
        bought_headers = [
            *(f"bought {label}" for label in experiment_labels[:-1]),
            "bought all decisive",
        ]
        category_positions = list(range(len(experiment_labels)))
        width = 0.8 / max(1, len(series_keys))
        for series_index, (model, variant) in enumerate(series_keys):
            row = rows_by_series.get((model, variant))
            if row is None:
                continue
            scripted = variant in SCRIPTED_VARIANTS
            values = [
                row.get(header)
                for header in bought_headers
            ]
            bought_axes.bar(
                [
                    position + (series_index - (len(series_keys) - 1) / 2) * width
                    for position in category_positions
                ],
                [value or 0 for value in values],
                width=width,
                color="#888888" if scripted else colors[variant],
                edgecolor="#444444",
                hatch=scripted_hatches.get(variant, "") if scripted else "",
            )
        bought_axes.set_title(f"Scenario {scenario} · decisive experiments bought", fontsize=12)
        bought_axes.set_ylabel("Fraction of counted episodes", fontsize=9)
        bought_axes.set_xticks(category_positions, experiment_labels, fontsize=9)
        bought_axes.tick_params(axis="y", labelsize=9)
        bought_axes.set_ylim(0, 1)
        bought_axes.grid(axis="y", alpha=0.2)

    figure.suptitle(
        "Experiment selection (comparable across LLM and scripted agents)",
        fontsize=13,
        y=0.98,
    )
    figure.subplots_adjust(
        left=0.22, right=0.98, bottom=0.32, top=0.84, hspace=0.62, wspace=0.34,
    )
    legend_handles.append(Line2D(
        [], [], color="#333333", linestyle="--", label="Budget",
    ))
    legend_labels.append("Budget")
    figure.legend(
        handles=legend_handles,
        labels=legend_labels,
        loc="center",
        bbox_to_anchor=(0.5, 0.21),
        ncol=4,
        title="Model / variant",
        fontsize=9,
    )
    figure.text(
        0.5, 0.115, SELECTION_CAPTION,
        ha="center", va="center", fontsize=9,
    )
    figure.text(
        0.5, 0.075, CONDITIONAL_FOOTNOTE,
        ha="center", va="center", fontsize=9,
    )
    _save_figure(figure, path, stamp)


def _top3_frontier(grid_rows: list[dict]) -> list[dict]:
    candidates = [
        row for row in grid_rows
        if row.get("frontier_regret") is not None
        and row.get("variant") not in SCRIPTED_VARIANTS
    ]
    return sorted(
        candidates,
        key=lambda row: (
            row["frontier_regret"] is None,
            -row["frontier_regret"] if row["frontier_regret"] is not None else 0,
            row["scenario"],
            row["variant"],
        ),
    )[:3]


def _frontier_rows(grid_rows: list[dict]) -> list[dict]:
    return [
        {
            "scenario": row["scenario"],
            "variant": row["variant"],
            "n_scored": row["n_scored"],
            "clean_success_rate": row["clean_success_rate"],
            "best-of-n minus mean": row["frontier_regret"],
        }
        for row in _top3_frontier(grid_rows)
    ]


def _plot_table(
    path: Path, title: str, headers: list[str], rows: list[dict], stamp: dict, *,
    footnote: str | None = None,
) -> None:
    figure = _figure(stamp)
    axes = figure.subplots()
    axes.axis("off")
    axes.set_title(title, pad=8, fontsize=14)
    body = [
        [_display_cell(header, row.get(header)) for header in headers]
        for row in rows
    ]
    table = axes.table(
        cellText=body or [["—"] * len(headers)],
        colLabels=headers,
        cellLoc="center",
        bbox=[0.01, 0.04, 0.98, 0.88],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    figure.subplots_adjust(left=0.03, right=0.97, bottom=0.24, top=0.86)
    if footnote:
        width = int((figure.get_figwidth() - 0.3) * 72 / (9 * 0.58))
        figure.text(
            0.02, 0.14, textwrap.fill(footnote, width=width),
            fontsize=9, ha="left", va="center",
        )
    _save_figure(figure, path, stamp)


def _parse_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(
        cell and set(cell) <= {"-", ":"} for cell in cells
    )


def _parse_report_table(text: str, heading: str, expected_header: tuple[str, ...]) -> list[dict]:
    lines = text.splitlines()
    try:
        heading_index = next(index for index, line in enumerate(lines) if line.strip() == heading)
    except StopIteration as exc:
        raise ValueError(f"Missing heading: {heading}") from exc
    header = None
    rows = []
    for line in lines[heading_index + 1:]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if not stripped.startswith("|"):
            continue
        cells = _parse_cells(stripped)
        if _is_separator(cells):
            continue
        if header is None:
            header = tuple(cells)
            if header != expected_header:
                raise ValueError(
                    f"Unexpected table header under {heading}: {header}"
                )
            continue
        if len(cells) != len(header):
            raise ValueError(f"Malformed table row under {heading}")
        rows.append(dict(zip(header, cells)))
    if header is None:
        raise ValueError(f"Missing table header under {heading}")
    return rows


def parse_validation_report(path: Path) -> tuple[list[dict], list[dict]]:
    text = Path(path).read_text(encoding="utf-8")
    pattern_source = _parse_report_table(text, PATTERN_HEADING, PATTERN_HEADER)
    kappa_rows = _parse_report_table(text, KAPPA_HEADING, KAPPA_HEADER)
    patterns = [
        {
            "pattern": row["pattern"],
            "provenance": row["provenance"],
            "detected/planted": row["detected / planted"],
            "recall": row["recall"],
            "false alarms (FP / honest)": row["FP / honest"],
            "false-alarm rate": row["FPR"],
        }
        for row in pattern_source
    ]
    return patterns, kappa_rows


def _validation_markdown(
    patterns: list[dict], kappa_rows: list[dict], stamp: dict,
) -> str:
    pattern_headers = [
        "pattern", "provenance", "detected/planted", "recall",
        "false alarms (FP / honest)", "false-alarm rate",
    ]
    kappa_headers = ["subset", "n", "observed agreement", "kappa"]
    lines = [
        "# Auditor validation",
        "",
        *_markdown_table(pattern_headers, patterns),
        "",
        KAPPA_HEADING,
        "",
        *_markdown_table(kappa_headers, kappa_rows),
        "",
        f"*{_stamp_line(stamp)}*",
        "",
    ]
    return "\n".join(lines)


def _validation_csv_rows(patterns: list[dict], kappa_rows: list[dict]) -> list[dict]:
    rows = []
    for row in patterns:
        rows.append({"type": "pattern", **row})
    for row in kappa_rows:
        rows.append({"type": "kappa", **row})
    return rows


def _plot_validation(
    path: Path, patterns: list[dict], kappa_rows: list[dict], stamp: dict,
) -> None:
    figure = _figure(stamp)
    pattern_axes, kappa_axes = figure.subplots(
        2, 1, gridspec_kw={"height_ratios": [3, 1]},
    )
    figure.suptitle("Auditor recall and false alarms", fontsize=14, y=0.985)
    pattern_axes.axis("off")
    pattern_axes.set_title("Per-pattern recall and false-positive rate", fontsize=12, pad=3)
    pattern_headers = [
        "pattern", "provenance", "detected/planted", "recall",
        "false alarms (FP / honest)", "false-alarm rate",
    ]
    pattern_table = pattern_axes.table(
        cellText=[
            [_display_cell(header, row.get(header)) for header in pattern_headers]
            for row in patterns
        ],
        colLabels=pattern_headers,
        cellLoc="center",
        bbox=[0.01, 0.02, 0.98, 0.9],
        colWidths=[0.34, 0.14, 0.14, 0.08, 0.20, 0.12],
    )
    pattern_table.auto_set_font_size(False)
    pattern_table.set_fontsize(9)

    kappa_axes.axis("off")
    kappa_axes.set_title("Cohen's kappa", fontsize=12, pad=3)
    kappa_headers = ["subset", "n", "observed agreement", "kappa"]
    kappa_table = kappa_axes.table(
        cellText=[
            [_display_cell(header, row.get(header)) for header in kappa_headers]
            for row in kappa_rows
        ],
        colLabels=kappa_headers,
        cellLoc="center",
        bbox=[0.01, 0.02, 0.98, 0.9],
    )
    kappa_table.auto_set_font_size(False)
    kappa_table.set_fontsize(9)
    figure.subplots_adjust(
        left=0.04, right=0.96, bottom=0.2, top=0.9, hspace=0.12,
    )
    _save_figure(figure, path, stamp)


def _asset_entry(path: Path, output_root: Path, stamp: dict, source_files: list[Path]) -> dict:
    return {
        "path": path.relative_to(output_root).as_posix(),
        "stamp": stamp,
        "source_files": [str(source) for source in source_files],
    }


def generate_batch_assets(
    batch_dir: Path, output_dir: Path, output_root: Path, *,
    git_stamp: tuple[str, bool] | None = None, repo_root: Path = REPO_ROOT,
) -> list[dict]:
    batch_dir = Path(batch_dir)
    output_dir = Path(output_dir)
    output_root = Path(output_root)
    records = _read_jsonl(batch_dir / "results.jsonl")
    summary = json.loads((batch_dir / "summary.json").read_text(encoding="utf-8"))
    grid_rows = json.loads((batch_dir / "grid_summary.json").read_text(encoding="utf-8"))
    clean_rows = _clean_success_rows(records, grid_rows)
    score_rows = _cell_score_rows(records, clean_rows)
    stamp = build_batch_stamp(
        batch_dir, records, summary, repo_root=repo_root, git_stamp=git_stamp,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    source_files = [
        batch_dir / "results.jsonl",
        batch_dir / "summary.json",
        batch_dir / "grid_summary.json",
    ]
    if (batch_dir / "reaudit.json").is_file():
        source_files.append(batch_dir / "reaudit.json")

    ci_headers = [
        "model", "scenario", "variant", "n_runs", "n_harness_error",
        "n_parse_failure", "n_provider_refusal", "n_scored", "n_clean_success",
        "clean_success_rate", "clean_success_ci95",
    ]
    ci_csv = output_dir / "clean_success_ci.csv"
    ci_md = output_dir / "clean_success_ci.md"
    ci_png = output_dir / "clean_success_ci.png"
    _write_csv(ci_csv, ci_headers, clean_rows, stamp)
    _write_markdown(
        ci_md,
        "Clean success rate with Wilson intervals",
        ci_headers,
        clean_rows,
        stamp,
    )
    _plot_clean_success(ci_png, clean_rows, stamp)

    raw_png = output_dir / "raw_vs_clean.png"
    _plot_raw_vs_clean(raw_png, score_rows, stamp)

    scenarios = sorted({
        record.get("job", {}).get("scenario", "a")
        for record in records
    })
    selection_data = {
        scenario: _scenario_selection_data(scenario)
        for scenario in scenarios
    }
    selection_rows = _experiment_selection_rows(records, selection_data)
    experiment_labels = list(dict.fromkeys(
        experiment["label"]
        for scenario in scenarios
        for experiment in selection_data[scenario]["experiments"]
    ))
    selection_headers = [
        "model", "scenario", "variant", "n_runs", "n_counted",
        "mean_cost", "budget",
        *(f"bought {label}" for label in experiment_labels),
        "bought all decisive",
    ]
    selection_csv = output_dir / "experiment_selection.csv"
    selection_md = output_dir / "experiment_selection.md"
    selection_png = output_dir / "experiment_selection.png"
    _write_csv(selection_csv, selection_headers, selection_rows, stamp)
    _write_markdown(
        selection_md,
        "Experiment selection",
        selection_headers,
        selection_rows,
        stamp,
        extra_sections=[
            SELECTION_CAPTION,
            CONDITIONAL_FOOTNOTE,
        ],
    )
    _plot_experiment_selection(selection_png, selection_rows, selection_data, stamp)
    selection_source_files = list(dict.fromkeys([
        *source_files,
        *(
            path
            for scenario in scenarios
            for path in selection_data[scenario]["source_files"]
        ),
    ]))

    frontier_rows = _frontier_rows(grid_rows)
    frontier_headers = [
        "scenario", "variant", "n_scored", "clean_success_rate", "best-of-n minus mean",
    ]
    frontier_csv = output_dir / "frontier_regret_top3.csv"
    frontier_md = output_dir / "frontier_regret_top3.md"
    frontier_png = output_dir / "frontier_regret_top3.png"
    _write_csv(frontier_csv, frontier_headers, frontier_rows, stamp)
    _write_markdown(
        frontier_md,
        "best-of-n minus mean",
        frontier_headers,
        frontier_rows,
        stamp,
        footnote=SCRIPTED_FOOTNOTE,
    )
    _plot_table(
        frontier_png,
        "best-of-n minus mean",
        frontier_headers,
        frontier_rows,
        stamp,
        footnote=SCRIPTED_FOOTNOTE,
    )
    return [
        _asset_entry(path, output_root, stamp, source_files)
        for path in (ci_png, ci_csv, ci_md, raw_png, frontier_md, frontier_csv, frontier_png)
    ] + [
        _asset_entry(path, output_root, stamp, selection_source_files)
        for path in (selection_png, selection_md, selection_csv)
    ]


def generate_validation_assets(
    report_path: Path, output_root: Path, *, synthetic: bool = False,
    git_stamp: tuple[str, bool] | None = None, repo_root: Path = REPO_ROOT,
) -> list[dict]:
    report_path = Path(report_path)
    output_root = Path(output_root)
    patterns, kappa_rows = parse_validation_report(report_path)
    stamp = build_validation_stamp(
        report_path,
        synthetic=synthetic,
        repo_root=repo_root,
        git_stamp=git_stamp,
    )
    md_path = output_root / "auditor_validation.md"
    csv_path = output_root / "auditor_validation.csv"
    png_path = output_root / "auditor_validation.png"
    md_path.write_text(_validation_markdown(patterns, kappa_rows, stamp), encoding="utf-8")
    csv_headers = [
        "type", "pattern", "provenance", "detected/planted", "recall",
        "false alarms (FP / honest)", "false-alarm rate", "subset", "n",
        "observed agreement", "kappa",
    ]
    _write_csv(csv_path, csv_headers, _validation_csv_rows(patterns, kappa_rows), stamp)
    _plot_validation(png_path, patterns, kappa_rows, stamp)
    source_files = [report_path]
    return [
        _asset_entry(path, output_root, stamp, source_files)
        for path in (md_path, csv_path, png_path)
    ]


def generate_assets(
    batch_dirs: list[Path], validation_path: Path, output_root: Path, *,
    synthetic_validation: bool = False, repo_root: Path = REPO_ROOT,
    git_stamp: tuple[str, bool] | None = None,
) -> list[dict]:
    output_root = Path(output_root)
    labels = [Path(batch_dir).name for batch_dir in batch_dirs]
    if len(labels) != len(set(labels)):
        raise ValueError("Batch directory names must be unique for output labels")
    if git_stamp is None:
        git_stamp = _git_stamp(Path(repo_root))
    assets = []
    for batch_dir, label in zip(batch_dirs, labels):
        assets.extend(
            generate_batch_assets(
                batch_dir,
                output_root / label,
                output_root,
                git_stamp=git_stamp,
                repo_root=repo_root,
            )
        )
    assets.extend(
        generate_validation_assets(
            validation_path,
            output_root,
            synthetic=synthetic_validation,
            git_stamp=git_stamp,
            repo_root=repo_root,
        )
    )
    (output_root / "manifest.json").write_text(
        json.dumps({"assets": assets}, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return assets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--batch", type=Path, action="append", help="batch directory; repeat for more")
    inputs.add_argument("--synthetic", action="store_true", help="generate clearly marked synthetic inputs")
    parser.add_argument(
        "--validation", type=Path, default=None,
        help=f"validation REPORT.md (default: {DEFAULT_VALIDATION})",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.synthetic and not args.batch:
        parser.error("provide --batch at least once or use --synthetic")
    labels = [batch_dir.name for batch_dir in (args.batch or [])]
    if len(labels) != len(set(labels)):
        parser.error("Batch directory names must be unique for output labels")
    if args.output.exists():
        parser.error("Output directory already exists; choose a new directory")
    try:
        git_stamp = _git_stamp(REPO_ROOT)
        args.output.mkdir(parents=True, exist_ok=False)
        if args.synthetic:
            from reports.synthetic import create_synthetic_inputs

            batch_dir, reaudit_dir = create_synthetic_inputs(
                args.output / "_synthetic_input",
            )
            batch_dirs = [batch_dir, reaudit_dir]
            validation_path = args.validation or DEFAULT_VALIDATION
        else:
            batch_dirs = args.batch
            validation_path = args.validation or DEFAULT_VALIDATION
        assets = generate_assets(
            batch_dirs,
            validation_path,
            args.output,
            git_stamp=git_stamp,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Wrote {len(assets)} slide assets to {args.output}")


if __name__ == "__main__":
    main()
