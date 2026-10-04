"""Create slide-ready tables and figures from batch and auditor validation outputs."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
import subprocess
from statistics import fmean
import textwrap

from auditor.audit import _Ctx, eval_pred
from contract import trajectory_from_dict
from runner.factories import scenario_dir
from runner.modal_batch import (
    SCRIPTED_VARIANTS,
    aggregate,
    grid_summary,
    wilson_interval,
)
from reports.replicates import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    REPLICATE_HEADERS,
    classify,
    replicate_rows,
    science_records,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALIDATION = REPO_ROOT / "auditor" / "validation" / "REPORT.md"
SCRIPTED_FOOTNOTE = (
    "Scripted baselines (random, ucb) excluded: frontier_regret is not meaningful "
    "for them (conclusion metrics random)."
)
SELECTION_CAPTION = (
    "bought = ran the experiment; w/ params = the evidence-sufficiency rules for that "
    "experiment also pass, evaluated with the auditor's predicate evaluator "
    "(auditor.audit.eval_pred)"
)
SELECTION_LEGEND_CAPTION = (
    "Each pair: pale bar with coloured outline = bought; solid bar beside it = w/ params."
)
CONDITIONAL_FOOTNOTE = "* scored only when the conclusion makes a target claim"
BOUGHT_ALPHA = 0.3
PASS_K_CAPTION = (
    "pass^k = C(c,k)/C(n,k) per cell: n = science runs, c with verdict VALID_SUCCESS; "
    "probability that k runs drawn without replacement all succeed "
    "(tau-bench, arXiv:2406.12045). pass^1 therefore equals clean_success_rate."
)
COST_OF_PASS_CAPTION = (
    "cost_of_pass = mean_cost / clean_success_rate (Cost-of-Pass, arXiv:2504.13359). "
    "Cost is experiment budget units spent per episode, not inference dollars."
)
SCIENCE_DENOMINATOR_CAPTION = (
    "Science runs only: provider refusals, refusal-aborted, spend-cap-stopped, "
    "harness-error and PARSE_FAILURE runs are excluded and counted separately."
)
GRID_DENOMINATOR_NOTE = (
    "runner's grid_summary.json counts refusal-aborted runs in n_scored, so its "
    "clean_success_rate differs from this table's (and with it clean_success_ci95, "
    "frontier_regret and raw_score_mean); n_clean_success is the same."
)
REPLICATE_CAPTION = (
    f"{SCIENCE_DENOMINATOR_CAPTION} n = science runs. Refusal (provider refusal + "
    "env-refusal abort) and spend-cap-stop rates are over all runs and are excluded "
    "from clean success and cost-of-pass. 95% percentile bootstrap over runs "
    f"(B={BOOTSTRAP_RESAMPLES}, seed={BOOTSTRAP_SEED}); CIs are null when n < 2. "
    "cost_of_pass = mean_cost / clean_success_mean (Cost-of-Pass, arXiv:2504.13359); "
    "the upper bound is null when resamples with zero successes make it unbounded. "
    "Cost is experiment budget units, not inference dollars."
)
PATTERN_HEADING = "## Per-pattern recall and false-positive rate"
KAPPA_HEADING = "## Cohen's kappa"
PATTERN_HEADER = (
    "pattern", "provenance", "detected / planted", "recall", "FP / honest", "FPR",
)
KAPPA_HEADER = ("subset", "n", "observed agreement", "kappa")
DERIVED_SUMMARIES = (
    "derived from results.jsonl (runner.modal_batch.aggregate/grid_summary)"
)


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
    wave: bool = False, summaries_derived: bool = False,
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
    source = f"{batch_dir} (results SHA: {results_sha})"
    if summaries_derived:
        source += "; summaries derived from results.jsonl"
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
        "source": source,
        "reaudit": reaudit_note,
        "synthetic": synthetic,
        "wave": wave,
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
    ]
    if "wave" in stamp:
        parts.append(f"wave={str(stamp['wave']).lower()}")
    parts.append(f"source={stamp['source']}")
    watermark = _watermark(stamp)
    prefix = f"{watermark} — " if watermark else ""
    return prefix + " | ".join(parts)


def _watermark(stamp: dict) -> str | None:
    if stamp.get("synthetic"):
        return "SYNTHETIC DATA"
    if stamp.get("wave") is False:
        return "NOT WAVE DATA"
    return None


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
    if header in ("clean_success_ci95", "cost_of_pass_ci95"):
        bounds = [
            "—" if bound is None else f"{float(bound):.3f}"
            for bound in value
        ]
        return f"[{bounds[0]}, {bounds[1]}]"
    rate_headers = {
        "clean_success_rate", "best-of-n minus mean", "frontier_regret",
        "recall", "false-alarm rate", "observed agreement",
        "pass^1", "pass^3", "pass^5", "cost_of_pass",
        "provider_refusal_rate", "refusal_abort_rate", "refusal_rate",
        "spend_cap_stop_rate", "clean_success_mean", "cost_of_pass_unbounded_share",
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


def _grid_science_records(records: list[dict]) -> list[dict]:
    return [
        record for record in records
        if classify(record) in {"science", "refusal_abort"}
    ]


def _scored_success_values(records: list[dict]) -> tuple[int, int, float | None, list | None]:
    scored = _grid_science_records(records)
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


def _pass_k(n: int, c: int, k: int) -> float | None:
    return math.comb(c, k) / math.comb(n, k) if n >= k else None


def _clean_success_rows(records: list[dict], grid_rows: list[dict]) -> list[dict]:
    _check_grid_consistency(records, grid_rows)
    result = []
    for (model, scenario, variant), cell_records in sorted(
        _batch_groups(records, ("model", "scenario", "variant")).items()
    ):
        if variant in SCRIPTED_VARIANTS:
            continue
        classifications = [classify(record) for record in cell_records]
        scored = science_records(cell_records)
        category_counts = {
            category: classifications.count(category)
            for category in (
                "provider_refusal", "refusal_abort", "spend_cap_stop",
                "harness_error", "parse_failure",
            )
        }
        n_clean_success = sum(
            (record.get("metrics") or {}).get("clean_success") is True
            for record in scored
        )
        n_scored = len(scored)
        rate = n_clean_success / n_scored if n_scored else None
        ci95 = list(wilson_interval(n_clean_success, n_scored)) if n_scored else None
        n_valid_success = sum(
            record["verdict"]["verdict"] == "VALID_SUCCESS"
            for record in scored
        )
        mean_cost = (
            fmean(float((record.get("metrics") or {})["cost"]) for record in scored)
            if scored else None
        )
        result.append({
            "model": model,
            "scenario": scenario,
            "variant": variant,
            "n_runs": len(cell_records),
            "n_harness_error": sum(
                category == "harness_error" for category in classifications
            ),
            "n_parse_failure": category_counts["parse_failure"],
            "n_provider_refusal": category_counts["provider_refusal"],
            "n_refusal_abort": category_counts["refusal_abort"],
            "n_spend_cap_stop": category_counts["spend_cap_stop"],
            "n_scored": n_scored,
            "n_clean_success": n_clean_success,
            "clean_success_rate": rate,
            "pass^1": _pass_k(n_scored, n_valid_success, 1),
            "pass^3": _pass_k(n_scored, n_valid_success, 3),
            "pass^5": _pass_k(n_scored, n_valid_success, 5),
            "n_valid_success": n_valid_success,
            "clean_success_ci95": ci95,
            "mean_cost": mean_cost,
            "cost_of_pass": (
                mean_cost / rate
                if mean_cost is not None and rate not in (None, 0)
                else None
            ),
        })
    return result


def _cell_score_rows(records: list[dict], clean_rows: list[dict]) -> list[dict]:
    groups = _batch_groups(records, ("model", "scenario", "variant"))
    result = []
    for row in clean_rows:
        scored = science_records(
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
    watermark = _watermark(stamp)
    if watermark:
        figure.text(
            0.5, 0.52, watermark, fontsize=30, color="#777777",
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
    figure.text(
        0.5, 0.09, textwrap.fill(SCIENCE_DENOMINATOR_CAPTION, width=145),
        ha="center", va="center", fontsize=6,
    )
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
        bbox_to_anchor=(0.5, 0.22),
        ncol=max(1, len(variant_handles)),
        title="Variant",
        fontsize=9,
    )
    figure.legend(
        handles=scenario_handles,
        loc="center",
        bbox_to_anchor=(0.5, 0.14),
        ncol=max(1, len(scenario_handles)),
        title="Scenario",
        fontsize=9,
    )
    figure.text(
        0.5, 0.08, textwrap.fill(SCIENCE_DENOMINATOR_CAPTION, width=145),
        ha="center", va="center", fontsize=6,
    )
    _save_figure(figure, path, stamp)


def _plot_cost_of_pass(path: Path, rows: list[dict], stamp: dict) -> None:
    from matplotlib.lines import Line2D

    llm_rows = [
        row for row in rows
        if row["variant"] not in SCRIPTED_VARIANTS
    ]
    plotted_rows = [
        row for row in llm_rows
        if row.get("cost_of_pass") is not None
        and row.get("clean_success_rate") is not None
    ]
    scenarios = sorted({row["scenario"] for row in llm_rows})
    variants = sorted({row["variant"] for row in llm_rows})
    colors = _variant_colors(set(variants))
    markers = ("o", "s", "^", "D", "v", "P", "X", "<", ">")
    scenario_markers = {
        scenario: markers[index % len(markers)]
        for index, scenario in enumerate(scenarios)
    }

    figure = _figure(stamp)
    axes = figure.subplots()
    figure.subplots_adjust(left=0.1, right=0.98, bottom=0.42, top=0.88)
    for row in plotted_rows:
        rate = row["clean_success_rate"]
        low, high = row["clean_success_ci95"]
        color = colors[row["variant"]]
        axes.errorbar(
            rate,
            row["cost_of_pass"],
            xerr=[[rate - low], [high - rate]],
            fmt=scenario_markers[row["scenario"]],
            color=color,
            ecolor=color,
            markerfacecolor=color,
            markeredgecolor=color,
            capsize=3,
            label="_nolegend_",
        )
    axes.set_title("Cost of pass vs clean success", fontsize=14)
    axes.set_xlabel("Clean success rate (horizontal 95% Wilson CI)", fontsize=10)
    axes.set_ylabel("Cost of pass (budget units)", fontsize=10)
    axes.set_xlim(0, 1)
    axes.set_ylim(bottom=0)
    axes.tick_params(axis="both", labelsize=9)
    from matplotlib.ticker import FormatStrFormatter

    axes.xaxis.set_major_formatter(FormatStrFormatter("%.3f"))
    axes.grid(alpha=0.25)

    variant_handles = [
        Line2D(
            [], [], color=colors[variant], marker="o", linestyle="None", label=variant,
        )
        for variant in variants
    ]
    scenario_handles = [
        Line2D(
            [], [], color="#444444", marker=scenario_markers[scenario],
            linestyle="None", label=scenario,
        )
        for scenario in scenarios
    ]
    if variant_handles:
        figure.legend(
            handles=variant_handles,
            loc="center",
            bbox_to_anchor=(0.5, 0.28),
            ncol=max(1, len(variant_handles)),
            title="Variant",
            fontsize=9,
        )
    if scenario_handles:
        figure.legend(
            handles=scenario_handles,
            loc="center",
            bbox_to_anchor=(0.5, 0.19),
            ncol=max(1, len(scenario_handles)),
            title="Scenario",
            fontsize=9,
        )
    figure.text(
        0.5, 0.12,
        textwrap.fill(
            f"{COST_OF_PASS_CAPTION} {SCIENCE_DENOMINATOR_CAPTION}",
            width=145,
        ),
        ha="center", va="center", fontsize=6,
    )
    zero_rate_cells = sum(
        row.get("clean_success_rate") == 0
        for row in llm_rows
    )
    if zero_rate_cells:
        figure.text(
            0.5, 0.08,
            f"{zero_rate_cells} cell(s) with clean success 0 omitted "
            "(cost_of_pass undefined)",
            ha="center", va="center", fontsize=8,
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


_ALLOWED_EVIDENCE_PREDICATES = {
    "all",
    "any",
    "not",
    "ran",
    "any_run_param_text_matches",
    "param_present",
    "param_eq",
    "param_in",
    "param_not_in",
    "param_lt",
    "param_ge",
    "param_contains_all",
    "param_text_contains_any",
    "param_text_contains_all_groups",
}


def _predicate_references(predicate) -> tuple[set[str], list[str], list[str]]:
    references = set()
    ran_ids = []
    operators = []

    def add_ran(value) -> None:
        if isinstance(value, str):
            references.add(value)
            ran_ids.append(value)
        elif isinstance(value, list):
            for item in value:
                add_ran(item)

    def visit(value) -> None:
        if not isinstance(value, dict):
            return
        if len(value) != 1:
            operators.append("<malformed>")
            for nested in value.values():
                visit(nested)
            return
        operator, argument = next(iter(value.items()))
        operators.append(operator)
        if isinstance(argument, dict) and isinstance(argument.get("experiment"), str):
            references.add(argument["experiment"])
        if operator == "ran":
            add_ran(argument)
        elif operator in ("all", "any"):
            if isinstance(argument, list):
                for nested in argument:
                    visit(nested)
        elif operator == "not":
            visit(argument)

    visit(predicate)
    return references, ran_ids, operators


def _evidence_rule_mapping(rubric: dict) -> dict[str, list[dict]]:
    decisive_ids = {experiment["id"] for experiment in _decisive_experiments(rubric)}
    mapping = {experiment_id: [] for experiment_id in decisive_ids}
    criteria = rubric["dimensions"]["evidence_sufficiency"]["criteria"]
    for criterion in criteria:
        references, _, operators = _predicate_references(criterion.get("predicate"))
        for experiment_id in decisive_ids & references:
            unsupported = sorted(
                operator for operator in operators
                if operator not in _ALLOWED_EVIDENCE_PREDICATES
            )
            if unsupported:
                criterion_id = criterion.get("id", "<missing id>")
                raise ValueError(
                    f"Unsupported evidence-sufficiency predicate "
                    f"{unsupported[0]!r} in criterion {criterion_id}"
                )
            mapping[experiment_id].append(criterion)
    return mapping


def _scenario_selection_data(scenario: str) -> dict:
    bundle = scenario_dir(scenario)
    briefing_path = bundle / "agent" / "briefing.json"
    rubric_path = bundle / "auditor" / "rubric.json"
    briefing = json.loads(briefing_path.read_text(encoding="utf-8"))
    rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
    experiments = _decisive_experiments(rubric)
    rules_by_experiment = _evidence_rule_mapping(rubric)
    for experiment in experiments:
        rules = rules_by_experiment[experiment["id"]]
        experiment["criteria"] = rules
        experiment["rule_ids"] = [criterion["id"] for criterion in rules]
    return {
        "budget": briefing["budget"]["units"],
        "experiments": experiments,
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


def _parameter_bought_experiments(
    record: dict, bought: set[str], experiments: list[dict],
) -> set[str]:
    parameter_bought = set()
    requiring_evaluation = []
    for experiment in experiments:
        experiment_id = experiment["id"]
        if experiment_id not in bought:
            continue
        criteria = experiment.get("criteria", [])
        if not criteria:
            parameter_bought.add(experiment_id)
        else:
            requiring_evaluation.append((experiment_id, criteria))
    if not requiring_evaluation:
        return parameter_bought

    context = _Ctx(trajectory_from_dict(record["trajectory"]), {})
    for experiment_id, criteria in requiring_evaluation:
        if all(eval_pred(criterion["predicate"], context) for criterion in criteria):
            parameter_bought.add(experiment_id)
    return parameter_bought


def _experiment_selection_rows(
    records: list[dict], scenario_data: dict[str, dict],
) -> list[dict]:
    rows = []
    for (model, scenario, variant), cell_records in sorted(
        _batch_groups(records, ("model", "scenario", "variant")).items()
    ):
        scored = science_records(cell_records)
        experiments = scenario_data[scenario]["experiments"]
        bought_by_record = [
            _counted_record_experiments(record)
            for record in scored
        ]
        parameter_bought_by_record = [
            _parameter_bought_experiments(record, bought, experiments)
            for record, bought in zip(scored, bought_by_record)
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
            row[f"bought {label} w/ params"] = (
                sum(
                    experiment["id"] in bought
                    for bought in parameter_bought_by_record
                ) / len(scored)
                if scored else None
            )
        decisive_ids = {experiment["id"] for experiment in experiments}
        row["bought all decisive"] = (
            sum(decisive_ids <= bought for bought in bought_by_record) / len(scored)
            if scored and decisive_ids else None
        )
        row["bought all decisive w/ params"] = (
            sum(
                decisive_ids <= bought
                for bought in parameter_bought_by_record
            ) / len(scored)
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
    from matplotlib.colors import to_rgba
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
        cost_axes.set_title(
            f"Scenario {scenario} · mean cost "
            f"(budget {_display_cell('budget', budget)})",
            fontsize=12,
        )
        cost_axes.set_yticks(
            positions,
            [_selection_series_label(model, variant) for model, variant in series_keys],
            fontsize=9,
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
        parameter_headers = [
            *(f"bought {label} w/ params" for label in experiment_labels[:-1]),
            "bought all decisive w/ params",
        ]
        category_positions = list(range(len(experiment_labels)))
        series_width = 0.8 / max(1, len(series_keys))
        pair_width = series_width / 2
        bar_width = pair_width * 0.88
        for series_index, (model, variant) in enumerate(series_keys):
            row = rows_by_series.get((model, variant))
            if row is None:
                continue
            scripted = variant in SCRIPTED_VARIANTS
            centers = [
                position + (series_index - (len(series_keys) - 1) / 2) * series_width
                for position in category_positions
            ]
            bought_values = [row.get(header) for header in bought_headers]
            parameter_values = [row.get(header) for header in parameter_headers]
            color = "#666666" if scripted else colors[variant]
            hatch = scripted_hatches.get(variant, "") if scripted else ""
            bought_axes.bar(
                [center - pair_width / 2 for center in centers],
                [value or 0 for value in bought_values],
                width=bar_width,
                color=to_rgba(color, BOUGHT_ALPHA),
                edgecolor=color,
                linewidth=1.2,
                hatch=hatch,
            )
            bought_axes.bar(
                [center + pair_width / 2 for center in centers],
                [value or 0 for value in parameter_values],
                width=bar_width,
                color=color,
                edgecolor="#111111",
                linewidth=1.2,
                hatch=hatch,
            )
        bought_axes.set_title(f"Scenario {scenario} · decisive bought", fontsize=12)
        bought_axes.set_ylabel("Fraction of episodes", fontsize=9)
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
    legend_handles.extend([
        Patch(
            facecolor=to_rgba("#666666", BOUGHT_ALPHA), edgecolor="#666666",
            linewidth=1.2,
        ),
        Patch(facecolor="#666666", edgecolor="#111111", linewidth=1.2),
    ])
    legend_labels.extend(["bought (pale)", "w/ params (solid)"])
    figure.legend(
        handles=legend_handles,
        labels=legend_labels,
        loc="center",
        bbox_to_anchor=(0.5, 0.21),
        ncol=4,
        fontsize=9,
    )
    selection_caption = textwrap.fill(
        (
            f"{SELECTION_CAPTION}. {SELECTION_LEGEND_CAPTION} "
            f"{SCIENCE_DENOMINATOR_CAPTION}"
        ),
        width=160,
        break_on_hyphens=False,
    )
    figure.text(
        0.5, 0.12, selection_caption,
        ha="center", va="center", fontsize=6,
    )
    figure.text(
        0.5, 0.08, CONDITIONAL_FOOTNOTE,
        ha="center", va="center", fontsize=8,
    )
    _save_figure(figure, path, stamp)


def _top3_frontier(rows: list[dict]) -> list[dict]:
    candidates = [
        row for row in rows
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


def _frontier_rows(records: list[dict]) -> list[dict]:
    rows = []
    for (scenario, variant), cell_records in sorted(
        _batch_groups(records, ("scenario", "variant")).items()
    ):
        if variant in SCRIPTED_VARIANTS:
            continue
        scored = science_records(cell_records)
        n_scored = len(scored)
        n_clean_success = sum(
            (record.get("metrics") or {}).get("clean_success") is True
            for record in scored
        )
        rate = n_clean_success / n_scored if n_scored else None
        rows.append({
            "scenario": scenario,
            "variant": variant,
            "n_scored": n_scored,
            "clean_success_rate": rate,
            "frontier_regret": (
                (1 if n_clean_success >= 1 else 0) - rate
                if n_scored else None
            ),
        })
    return [
        {
            "scenario": row["scenario"],
            "variant": row["variant"],
            "n_scored": row["n_scored"],
            "clean_success_rate": row["clean_success_rate"],
            "best-of-n minus mean": row["frontier_regret"],
        }
        for row in _top3_frontier(rows)
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


def _asset_entry(
    path: Path, output_root: Path, stamp: dict, source_files: list[Path], *,
    summaries: str | None = None,
) -> dict:
    entry = {
        "path": path.relative_to(output_root).as_posix(),
        "stamp": stamp,
        "source_files": [
            str(source) for source in source_files if Path(source).is_file()
        ],
    }
    if summaries is not None:
        entry["summaries"] = summaries
    return entry


def generate_batch_assets(
    batch_dir: Path, output_dir: Path, output_root: Path, *,
    git_stamp: tuple[str, bool] | None = None, repo_root: Path = REPO_ROOT,
    wave: bool = False,
) -> list[dict]:
    batch_dir = Path(batch_dir)
    output_dir = Path(output_dir)
    output_root = Path(output_root)
    records = _read_jsonl(batch_dir / "results.jsonl")
    summary_path = batch_dir / "summary.json"
    grid_path = batch_dir / "grid_summary.json"
    summaries_derived = not (summary_path.is_file() and grid_path.is_file())
    if summaries_derived:
        summary = aggregate(records)
        grid_rows = grid_summary(records)
    else:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        grid_rows = json.loads(grid_path.read_text(encoding="utf-8"))
    clean_rows = _clean_success_rows(records, grid_rows)
    score_rows = _cell_score_rows(records, clean_rows)
    stamp = build_batch_stamp(
        batch_dir, records, summary, repo_root=repo_root, git_stamp=git_stamp,
        wave=wave, summaries_derived=summaries_derived,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    source_files = [batch_dir / "results.jsonl"]
    if not summaries_derived:
        source_files.extend([summary_path, grid_path])
    if (batch_dir / "reaudit.json").is_file():
        source_files.append(batch_dir / "reaudit.json")
    summaries_source = DERIVED_SUMMARIES if summaries_derived else "read"

    ci_headers = [
        "model", "scenario", "variant", "n_runs", "n_harness_error",
        "n_parse_failure", "n_provider_refusal", "n_refusal_abort",
        "n_spend_cap_stop", "n_scored", "n_clean_success", "clean_success_rate",
        "pass^1", "pass^3", "pass^5", "n_valid_success",
        "clean_success_ci95", "mean_cost", "cost_of_pass",
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
        extra_sections=[
            SCIENCE_DENOMINATOR_CAPTION,
            GRID_DENOMINATOR_NOTE,
            PASS_K_CAPTION,
            COST_OF_PASS_CAPTION,
        ],
    )
    _plot_clean_success(ci_png, clean_rows, stamp)

    raw_png = output_dir / "raw_vs_clean.png"
    _plot_raw_vs_clean(raw_png, score_rows, stamp)

    cost_of_pass_png = output_dir / "cost_of_pass.png"
    _plot_cost_of_pass(cost_of_pass_png, clean_rows, stamp)

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
    experiment_columns = [
        column
        for label in experiment_labels
        for column in (f"bought {label}", f"bought {label} w/ params")
    ]
    selection_headers = [
        "model", "scenario", "variant", "n_runs", "n_counted",
        "mean_cost", "budget",
        *experiment_columns,
        "bought all decisive", "bought all decisive w/ params",
    ]
    selection_csv = output_dir / "experiment_selection.csv"
    selection_md = output_dir / "experiment_selection.md"
    selection_png = output_dir / "experiment_selection.png"
    _write_csv(selection_csv, selection_headers, selection_rows, stamp)
    rule_summary = "; ".join(
        f"scenario {scenario}: " + ", ".join(
            f"{experiment['label']} w/ params = {' + '.join(experiment['rule_ids'])}"
            for experiment in selection_data[scenario]["experiments"]
        )
        for scenario in scenarios
    )
    _write_markdown(
        selection_md,
        "Experiment selection",
        selection_headers,
        selection_rows,
        stamp,
        extra_sections=[
            SCIENCE_DENOMINATOR_CAPTION,
            SELECTION_CAPTION,
            f"Required parameter rules: {rule_summary}",
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

    frontier_rows = _frontier_rows(records)
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
        extra_sections=[SCIENCE_DENOMINATOR_CAPTION],
    )
    _plot_table(
        frontier_png,
        "best-of-n minus mean",
        frontier_headers,
        frontier_rows,
        stamp,
        footnote=f"{SCIENCE_DENOMINATOR_CAPTION} {SCRIPTED_FOOTNOTE}",
    )
    return [
        _asset_entry(
            path, output_root, stamp, source_files, summaries=summaries_source,
        )
        for path in (
            ci_png, ci_csv, ci_md, raw_png, cost_of_pass_png,
            frontier_md, frontier_csv, frontier_png,
        )
    ] + [
        _asset_entry(
            path, output_root, stamp, selection_source_files,
            summaries=summaries_source,
        )
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


def _pooled_replicate_stamp(
    batch_dirs: list[Path], records_by_dir: list[list[dict]], *,
    wave: bool, git_stamp: tuple[str, bool],
) -> dict:
    models = set()
    sampling = set()
    sources = []
    synthetic_flags = []
    for batch_dir, records in zip(batch_dirs, records_by_dir):
        models.update(
            str(record["job"]["model"])
            for record in records
            if record.get("job", {}).get("model") is not None
        )
        sampling.update(_sampling_summary(records))
        synthetic_flags.append(any(
            isinstance(record.get("sampling"), dict)
            and record["sampling"].get("client") == "synthetic"
            for record in records
        ))
        code_shas = sorted(_code_shas(records))
        sha_text = ", ".join(code_shas) if code_shas else "not recorded"
        sources.append(f"{batch_dir} (results SHA: {sha_text})")
    return {
        "git_sha": git_stamp[0],
        "git_dirty": git_stamp[1],
        "models": sorted(models),
        "sampling": sorted(sampling),
        "source": "; ".join(sources),
        "reaudit": None,
        "synthetic": any(synthetic_flags),
        "wave": bool(batch_dirs) and all(wave for _ in batch_dirs),
    }


def generate_replicate_assets(
    batch_dirs: list[Path], output_root: Path, *,
    wave: bool = False, git_stamp: tuple[str, bool] | None = None,
    repo_root: Path = REPO_ROOT,
) -> list[dict]:
    """Generate pooled replicate summaries, requiring only each results.jsonl."""
    batch_dirs = [Path(path) for path in batch_dirs]
    output_root = Path(output_root)
    if git_stamp is None:
        git_stamp = _git_stamp(Path(repo_root))
    records_by_dir = [
        _read_jsonl(batch_dir / "results.jsonl")
        for batch_dir in batch_dirs
    ]
    records = [record for batch_records in records_by_dir for record in batch_records]
    rows, excluded_variants = replicate_rows(records)
    stamp = _pooled_replicate_stamp(
        batch_dirs,
        records_by_dir,
        wave=wave,
        git_stamp=git_stamp,
    )
    output_dir = output_root / "replicates"
    output_dir.mkdir(parents=True, exist_ok=False)
    json_path = output_dir / "replicate_summary.json"
    csv_path = output_dir / "replicate_summary.csv"
    md_path = output_dir / "replicate_summary.md"
    json_path.write_text(
        json.dumps(
            {
                "stamp": stamp,
                "excluded_scripted_variants": excluded_variants,
                "rows": rows,
            },
            indent=2,
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )
    _write_csv(csv_path, list(REPLICATE_HEADERS), rows, stamp)
    scripted_note = (
        "* Scripted variants excluded: " + ", ".join(excluded_variants) + "."
        if excluded_variants
        else "* No scripted variants were present to exclude."
    )
    _write_markdown(
        md_path,
        "Replicate summary",
        list(REPLICATE_HEADERS),
        rows,
        stamp,
        extra_sections=[
            REPLICATE_CAPTION,
            scripted_note,
        ],
    )
    source_files = [batch_dir / "results.jsonl" for batch_dir in batch_dirs]
    return [
        _asset_entry(path, output_root, stamp, source_files)
        for path in (json_path, csv_path, md_path)
    ]


def generate_assets(
    batch_dirs: list[Path], validation_path: Path, output_root: Path, *,
    synthetic_validation: bool = False, repo_root: Path = REPO_ROOT,
    git_stamp: tuple[str, bool] | None = None, wave: bool = False,
    replicate_dirs: list[Path] | None = None,
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
                wave=wave,
            )
        )
    assets.extend(
        generate_replicate_assets(
            batch_dirs if replicate_dirs is None else replicate_dirs,
            output_root,
            wave=wave,
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
    inputs.add_argument("--wave", type=Path, action="append", help="wave batch directory; repeat for more")
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
    if not args.synthetic and not args.batch and not args.wave:
        parser.error("provide --batch or --wave at least once, or use --synthetic")
    input_dirs = args.batch or args.wave or []
    labels = [batch_dir.name for batch_dir in input_dirs]
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
            replicate_dirs = [batch_dir]
            validation_path = args.validation or DEFAULT_VALIDATION
            wave = False
        elif args.wave:
            batch_dirs = args.wave
            replicate_dirs = batch_dirs
            validation_path = args.validation or DEFAULT_VALIDATION
            wave = True
        else:
            batch_dirs = args.batch
            replicate_dirs = batch_dirs
            validation_path = args.validation or DEFAULT_VALIDATION
            wave = False
        assets = generate_assets(
            batch_dirs,
            validation_path,
            args.output,
            git_stamp=git_stamp,
            wave=wave,
            replicate_dirs=replicate_dirs,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Wrote {len(assets)} slide assets to {args.output}")


if __name__ == "__main__":
    main()
