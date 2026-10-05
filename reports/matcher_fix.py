"""Compare recorded verdicts with an offline matcher-fix re-audit."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
from statistics import fmean
from typing import Callable

from matplotlib.patches import FancyBboxPatch, Rectangle

from reports import slide_assets
from reports.replicates import classify
from runner.modal_batch import SCRIPTED_VARIANTS

REPO_ROOT = Path(__file__).resolve().parents[1]

CONFOUND_CAPTION = (
    "The re-audit re-scores each recorded trajectory with the fixed auditor. It corrects the "
    "score, not the observation the agent received during the episode. Where the environment "
    "withheld a control readout that the fixed matcher would now return (marked confounded), "
    "the agent acted on a different observation than the fixed system would give, so that "
    "cell stays confounded: its after-verdict is not what the agent would have earned with "
    "the fix in place."
)
EXCLUSION_CAPTION = (
    "Provider refusals, refusal-aborted, spend-cap-stopped, harness-error and PARSE_FAILURE "
    "runs carry no verdict here; they are shown only as n=0 counts."
)

CELL_HEADERS = (
    "model", "scenario", "variant", "n_runs", "n_science",
    "n_provider_refusal", "n_refusal_abort", "n_spend_cap_stop",
    "n_harness_error", "n_parse_failure", "verdicts_before", "verdicts_after",
    "final_score_mean_before", "final_score_mean_after",
    "fired_removed", "fired_added", "n_verdict_changed", "n_score_changed",
    "n_confounded", "status",
)
EPISODE_HEADERS = (
    "label", "model", "scenario", "variant", "episode_id", "outcome",
    "verdict_before", "verdict_after", "final_score_before", "final_score_after",
    "fired_before", "fired_after", "verdict_changed", "score_changed",
    "observation_withheld", "confounded",
)

_VERDICT_COLORS = {
    "VALID_SUCCESS": "#16845b",
    "WRONG_CONCLUSION": "#e69500",
    "INSUFFICIENT_EVIDENCE": "#64748b",
    "PROTOCOL_VIOLATION": "#dc2626",
    "REWARD_HACK": "#7e22ce",
    "UNSAFE_ACTION": "#7f1d1d",
}
_EXCLUDED_CATEGORIES = (
    "provider_refusal", "refusal_abort", "spend_cap_stop",
    "harness_error", "parse_failure",
)


def _read_jsonl(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def _query_key(alias_set: str, controls: object) -> tuple[str, str]:
    return alias_set, json.dumps(controls, sort_keys=True, separators=(",", ":"))


def _withheld_queries(record: dict) -> list[tuple[str, object]]:
    trajectory = record.get("trajectory") or {}
    turns = trajectory.get("turns", []) if isinstance(trajectory, dict) else []
    queries = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        observation = turn.get("observation") or {}
        structured = observation.get("structured") or {}
        if not isinstance(structured, dict):
            continue
        action = turn.get("action") or {}
        parameters = action.get("parameters") or {}
        for key, value in structured.items():
            if key.endswith("_control_returned") and value is False:
                queries.append((key[:-len("_returned")], parameters.get("controls")))
    return queries


def _fired_ids(record: dict) -> list[str]:
    verdict = record.get("verdict") or {}
    fired = verdict.get("fired") or []
    return sorted(
        str(item["id"])
        for item in fired
        if isinstance(item, dict) and item.get("id") is not None
    )


def _verdict(record: dict) -> str | None:
    return (record.get("verdict") or {}).get("verdict")


def _final_score(record: dict) -> float | None:
    value = (record.get("verdict") or {}).get("final_score")
    return None if value is None else float(value)


def _record_index(label: str, records: list[dict]) -> dict[tuple[str, object], dict]:
    indexed = {}
    for record in records:
        job = record.get("job")
        if not isinstance(job, dict) or "episode_id" not in job:
            raise ValueError(f"Record in {label!r} has no job.episode_id")
        key = (label, job["episode_id"])
        if key in indexed:
            raise ValueError(f"Duplicate episode {key!r}")
        indexed[key] = record
    return indexed


def _episode_row(
    label: str,
    before: dict,
    after: dict,
    outcome: str,
    returns_now: Callable[[str, object], bool],
) -> dict:
    job = before["job"]
    withheld_queries = _withheld_queries(before)
    science = outcome == "science"
    if science:
        verdict_before = _verdict(before)
        verdict_after = _verdict(after)
        score_before = _final_score(before)
        score_after = _final_score(after)
        if score_before is None or score_after is None:
            raise ValueError(
                f"Science episode {job['episode_id']!r} has no final_score"
            )
        verdict_changed = verdict_before != verdict_after
        score_changed = not math.isclose(
            score_before, score_after, abs_tol=1e-9,
        )
        fired_before = _fired_ids(before)
        fired_after = _fired_ids(after)
    else:
        verdict_before = None
        verdict_after = None
        score_before = None
        score_after = None
        verdict_changed = False
        score_changed = False
        fired_before = []
        fired_after = []
    return {
        "label": label,
        "model": job.get("model"),
        "scenario": job.get("scenario", "a"),
        "variant": job.get("variant"),
        "episode_id": job["episode_id"],
        "outcome": outcome,
        "verdict_before": verdict_before,
        "verdict_after": verdict_after,
        "final_score_before": score_before,
        "final_score_after": score_after,
        "fired_before": fired_before,
        "fired_after": fired_after,
        "verdict_changed": verdict_changed,
        "score_changed": score_changed,
        "observation_withheld": bool(withheld_queries),
        "confounded": any(
            returns_now(alias_set, controls)
            for alias_set, controls in withheld_queries
        ),
    }


def _verdict_summary(values: list[str]) -> str | None:
    counts = Counter(values)
    if not counts:
        return None
    if sum(counts.values()) == 1:
        return next(iter(counts))
    return ", ".join(
        f"{verdict}×{count}"
        for verdict, count in sorted(counts.items())
    )


def compare_records(
    before: dict[str, list[dict]],
    after: dict[str, list[dict]],
    returns_now: Callable[[str, object], bool],
) -> tuple[list[dict], list[dict]]:
    """Pair records and summarize recorded versus re-audited science outcomes."""
    if set(before) != set(after):
        missing_after = sorted(set(before) - set(after))
        missing_before = sorted(set(after) - set(before))
        raise ValueError(
            f"Record labels differ; missing after={missing_after}, "
            f"missing before={missing_before}"
        )

    before_index = {}
    after_index = {}
    for label in sorted(before):
        before_index.update(_record_index(label, before[label]))
        after_index.update(_record_index(label, after[label]))
    if set(before_index) != set(after_index):
        missing_after = sorted(set(before_index) - set(after_index), key=repr)
        missing_before = sorted(set(after_index) - set(before_index), key=repr)
        raise ValueError(
            f"Episode pairing mismatch; missing after={missing_after}, "
            f"missing before={missing_before}"
        )

    episode_rows = []
    for key in sorted(before_index, key=repr):
        before_record = before_index[key]
        after_record = after_index[key]
        if before_record.get("job") != after_record.get("job"):
            raise ValueError(f"Job differs for episode {key!r}")
        before_outcome = classify(before_record)
        after_outcome = classify(after_record)
        if before_outcome != after_outcome:
            raise ValueError(
                f"Classification changed for episode {key!r}: "
                f"{before_outcome} -> {after_outcome}"
            )
        if before_record["job"].get("variant") in SCRIPTED_VARIANTS:
            continue
        episode_rows.append(
            _episode_row(
                key[0],
                before_record,
                after_record,
                before_outcome,
                returns_now,
            )
        )

    groups = defaultdict(list)
    for row in episode_rows:
        groups[(row["model"], row["scenario"], row["variant"])].append(row)

    cell_rows = []
    for model, scenario, variant in sorted(groups):
        episodes = groups[(model, scenario, variant)]
        science_episodes = [
            row for row in episodes if row["outcome"] == "science"
        ]
        counts = {
            category: sum(row["outcome"] == category for row in episodes)
            for category in _EXCLUDED_CATEGORIES
        }
        before_verdicts = [
            row["verdict_before"] for row in science_episodes
        ]
        after_verdicts = [
            row["verdict_after"] for row in science_episodes
        ]
        fired_removed = set()
        fired_added = set()
        for row in science_episodes:
            fired_removed.update(set(row["fired_before"]) - set(row["fired_after"]))
            fired_added.update(set(row["fired_after"]) - set(row["fired_before"]))

        n_science = len(science_episodes)
        n_verdict_changed = sum(row["verdict_changed"] for row in science_episodes)
        n_score_changed = sum(row["score_changed"] for row in science_episodes)
        n_confounded = sum(row["confounded"] for row in science_episodes)
        if n_science == 0:
            status = slide_assets._no_science_label({
                "n_scored": 0,
                "_excluded_counts": counts,
            })
        else:
            changes = []
            if n_verdict_changed:
                changes.append("verdict changed")
            if n_score_changed:
                changes.append("score changed")
            if n_confounded:
                changes.append("confounded")
            status = "; ".join(changes) if changes else "unchanged"

        before_modes = Counter(before_verdicts)
        after_modes = Counter(after_verdicts)
        cell_rows.append({
            "model": model,
            "scenario": scenario,
            "variant": variant,
            "n_runs": len(episodes),
            "n_science": n_science,
            "n_provider_refusal": counts["provider_refusal"],
            "n_refusal_abort": counts["refusal_abort"],
            "n_spend_cap_stop": counts["spend_cap_stop"],
            "n_harness_error": counts["harness_error"],
            "n_parse_failure": counts["parse_failure"],
            "verdicts_before": _verdict_summary(before_verdicts),
            "verdicts_after": _verdict_summary(after_verdicts),
            "final_score_mean_before": (
                fmean(row["final_score_before"] for row in science_episodes)
                if n_science else None
            ),
            "final_score_mean_after": (
                fmean(row["final_score_after"] for row in science_episodes)
                if n_science else None
            ),
            "fired_removed": sorted(fired_removed) or None,
            "fired_added": sorted(fired_added) or None,
            "n_verdict_changed": n_verdict_changed,
            "n_score_changed": n_score_changed,
            "n_confounded": n_confounded,
            "status": status,
            "_verdict_before_mode": (
                min(before_modes, key=lambda name: (-before_modes[name], name))
                if before_modes else None
            ),
            "_verdict_after_mode": (
                min(after_modes, key=lambda name: (-after_modes[name], name))
                if after_modes else None
            ),
        })
    return cell_rows, episode_rows


def _resolve_auditor_sha(auditor_ref: str, repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{auditor_ref}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ValueError(
            f"Unknown auditor SHA or commit {auditor_ref!r}: "
            f"{result.stderr.strip()}"
        )
    full_sha = result.stdout.strip()
    for path in ("runner/reaudit.py", "control_matching.py"):
        check = subprocess.run(
            ["git", "cat-file", "-e", f"{full_sha}:{path}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if check.returncode:
            raise ValueError(
                f"Auditor commit {full_sha} does not contain {path}: "
                f"{check.stderr.strip()}"
            )
    return full_sha


def _run_worktree(
    full_sha: str,
    records_by_label: dict[str, list[dict]],
    results_paths: dict[str, Path],
    output_root: Path,
    repo_root: Path,
) -> tuple[dict[str, list[dict]], Callable[[str, object], bool]]:
    temp_root = Path(tempfile.mkdtemp(prefix="matcher-fix-"))
    worktree = temp_root / "tree"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    worktree_added = False
    active_exception = False
    cleanup_error = None
    after_records = {}
    try:
        added = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), full_sha],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if added.returncode:
            raise ValueError(
                f"Could not create auditor worktree at {full_sha}: "
                f"{added.stderr.strip()}"
            )
        worktree_added = True

        for label in sorted(records_by_label):
            reaudited_dir = output_root / "reaudit" / label
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "runner.reaudit",
                    str(results_paths[label]),
                    "--output",
                    str(reaudited_dir),
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
            )
            if result.returncode:
                raise ValueError(
                    f"Re-audit failed for {label!r}: {result.stderr.strip()}"
                )
            reaudit_path = reaudited_dir / "reaudit.json"
            reaudit_doc = json.loads(reaudit_path.read_text(encoding="utf-8"))
            if reaudit_doc.get("code_sha") != full_sha:
                raise ValueError(
                    f"Re-audit code SHA mismatch for {label!r}: "
                    f"expected {full_sha}, got {reaudit_doc.get('code_sha')!r}"
                )
            after_records[label] = _read_jsonl(reaudited_dir / "results.jsonl")

        queries = []
        query_keys = []
        for label in sorted(records_by_label):
            for record in records_by_label[label]:
                for alias_set, controls in _withheld_queries(record):
                    queries.append([alias_set, controls])
                    query_keys.append(_query_key(alias_set, controls))
        script = (
            "import json, sys\n"
            "from control_matching import matches_control_aliases\n"
            "queries = json.load(sys.stdin)\n"
            "print(json.dumps([\n"
            "    matches_control_aliases(controls, alias_set)\n"
            "    for alias_set, controls in queries\n"
            "]))\n"
        )
        check = subprocess.run(
            [sys.executable, "-c", script],
            cwd=worktree,
            env=env,
            input=json.dumps(queries),
            capture_output=True,
            text=True,
        )
        if check.returncode:
            raise ValueError(
                f"Control-matcher confound check failed: {check.stderr.strip()}"
            )
        try:
            matches = json.loads(check.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Control-matcher confound check returned invalid JSON: "
                f"{check.stdout!r}"
            ) from exc
        if (
            not isinstance(matches, list)
            or len(matches) != len(query_keys)
            or any(type(value) is not bool for value in matches)
        ):
            raise ValueError("Control-matcher confound check returned invalid results")
        lookup = dict(zip(query_keys, matches))

        def returns_now(alias_set: str, controls: object) -> bool:
            key = _query_key(alias_set, controls)
            if key not in lookup:
                raise ValueError(f"Missing control-matcher result for {key!r}")
            return lookup[key]

    except BaseException:
        active_exception = True
        raise
    finally:
        removed = subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if worktree_added and removed.returncode:
            cleanup_error = ValueError(
                f"Could not remove auditor worktree {worktree}: "
                f"{removed.stderr.strip()}"
            )
        shutil.rmtree(temp_root, ignore_errors=True)
        if cleanup_error is not None and not active_exception:
            raise cleanup_error
    return after_records, returns_now


def _excluded_scripted_variants(records_by_label: dict[str, list[dict]]) -> list[str]:
    return sorted({
        record.get("job", {}).get("variant")
        for records in records_by_label.values()
        for record in records
        if record.get("job", {}).get("variant") in SCRIPTED_VARIANTS
    })


def _scripted_footnote(variants: list[str]) -> str:
    if variants:
        return "Scripted variants excluded entirely: " + ", ".join(variants) + "."
    return "No scripted variants were present to exclude."


def _episode_csv_rows(episode_rows: list[dict]) -> list[dict]:
    return [
        {
            **row,
            "fired_before": row["fired_before"] or None,
            "fired_after": row["fired_after"] or None,
        }
        for row in episode_rows
    ]


def _results_sha(records: list[dict]) -> str:
    values = sorted(slide_assets._code_shas(records))
    return ", ".join(values) if values else "not recorded"


def _build_stamp(
    records_by_label: dict[str, list[dict]],
    records_dirs: dict[str, str],
    results_sha: dict[str, str],
    cell_rows: list[dict],
    full_sha: str,
    wave: bool,
    git_stamp: tuple[str, bool],
) -> dict:
    records = [
        record
        for label in sorted(records_by_label)
        for record in records_by_label[label]
    ]
    n_science = sum(row["n_science"] for row in cell_rows)
    n_verdict_changed = sum(row["n_verdict_changed"] for row in cell_rows)
    n_confounded = sum(row["n_confounded"] for row in cell_rows)
    git_sha, dirty = git_stamp
    return {
        "git_sha": git_sha,
        "git_dirty": dirty,
        "models": sorted({
            str(record["job"]["model"])
            for record in records
            if record.get("job", {}).get("model") is not None
        }),
        "sampling": slide_assets._sampling_summary(records),
        "synthetic": any(
            isinstance(record.get("sampling"), dict)
            and record["sampling"].get("client") == "synthetic"
            for record in records
        ),
        "wave": wave,
        "reaudit": (
            f"auditor {full_sha[:7]} vs recorded verdicts "
            f"({n_science} science episodes, {n_verdict_changed} verdicts changed, "
            f"{n_confounded} confounded)"
        ),
        "source": "; ".join(
            f"{records_dirs[label]} (results SHA: {results_sha[label]})"
            for label in sorted(records_dirs)
        ) or f"(results SHA: {', '.join(results_sha.values()) or 'not recorded'})",
    }


def _score_text(value: float | None) -> str:
    return "—" if value is None else f"final_score {value:.2f}"


def _plot_comparison(
    path: Path,
    cell_rows: list[dict],
    stamp: dict,
    auditor_sha: str,
    captions: list[str],
) -> None:
    figure = slide_assets._figure(stamp)
    row_count = len(cell_rows)
    if row_count > 10:
        figure.set_size_inches(10, max(5.625, row_count * 0.56 + 2.0))
    axes = figure.subplots()
    axes.axis("off")
    axes.set_xlim(0, 1)
    axes.set_ylim(row_count - 0.45, -1.0)
    figure.subplots_adjust(left=0.02, right=0.99, bottom=0.25, top=0.87)
    axes.set_title("Matcher-fix re-audit: verdict before vs after", fontsize=13, pad=10)

    axes.text(
        0.38, -0.72, "before (recorded)",
        ha="center", va="center", fontsize=8, fontweight="bold",
    )
    axes.text(
        0.67, -0.72, f"after (auditor {auditor_sha[:7]})",
        ha="center", va="center", fontsize=8, fontweight="bold",
    )
    models = {row["model"] for row in cell_rows}
    for index, row in enumerate(cell_rows):
        y = index
        label = f"{row['scenario']} · {row['variant']}"
        if len(models) > 1:
            label = f"{row['model']} · {label}"
        axes.text(
            0.235, y, label,
            ha="right", va="center", fontsize=7, color="#374151",
        )
        if row["n_science"] == 0:
            axes.add_patch(Rectangle(
                (0.26, y - 0.28), 0.53, 0.56,
                facecolor="#f3f4f6", edgecolor="#9ca3af",
                hatch="////", linewidth=0.8,
            ))
            axes.text(
                0.525, y, row["status"],
                ha="center", va="center", fontsize=7, color="#374151",
            )
            continue

        changed = bool(row["n_verdict_changed"] or row["n_score_changed"])
        for x, verdicts, score, dominant, is_after in (
            (
                0.265, row["verdicts_before"], row["final_score_mean_before"],
                row["_verdict_before_mode"], False,
            ),
            (
                0.555, row["verdicts_after"], row["final_score_mean_after"],
                row["_verdict_after_mode"], True,
            ),
        ):
            color = _VERDICT_COLORS.get(dominant, "#6b7280")
            axes.add_patch(FancyBboxPatch(
                (x, y - 0.31), 0.235, 0.62,
                boxstyle="round,pad=0.012",
                facecolor=color,
                edgecolor="black" if is_after and changed else color,
                linewidth=2.2 if is_after and changed else 0.9,
            ))
            verdict_text = textwrap.fill(str(verdicts), width=27)
            axes.text(
                x + 0.1175, y,
                f"{verdict_text}\n{_score_text(score)}",
                ha="center", va="center", fontsize=6.2, color="white",
                linespacing=1.0,
            )
        axes.annotate(
            "",
            xy=(0.545, y),
            xytext=(0.505, y),
            arrowprops={"arrowstyle": "->", "color": "#4b5563", "lw": 1.1},
        )
        if changed:
            axes.text(
                0.81, y + (0.08 if row["n_confounded"] else 0),
                "changed", ha="left", va="center",
                fontsize=6.8, color="#111827", fontweight="bold",
            )
        if row["n_confounded"]:
            axes.text(
                0.81, y - (0.08 if changed else 0),
                "confounded", ha="left", va="center",
                fontsize=6.8, color="#b91c1c", fontweight="bold",
            )

    if row_count == 0:
        axes.text(
            0.5, 0.5, "No non-scripted cells to compare",
            ha="center", va="center", fontsize=10, color="#6b7280",
            transform=axes.transAxes,
        )
    caption_text = " ".join(captions)
    width = int((figure.get_figwidth() - 0.2) * 72 / (5.5 * 0.58))
    figure.text(
        0.5, 0.14, textwrap.fill(caption_text, width=width),
        ha="center", va="center", fontsize=5.5, linespacing=1.1,
    )
    slide_assets._save_figure(figure, path, stamp)


def _validate_records_dirs(records_dirs: list[Path]) -> tuple[list[str], dict[str, Path]]:
    labels = [Path(directory).name for directory in records_dirs]
    if len(labels) != len(set(labels)):
        raise ValueError("Records directory names must be unique for output labels")
    paths = {}
    for label, directory in zip(labels, records_dirs):
        resolved = Path(directory).resolve()
        results_path = resolved / "results.jsonl"
        if not results_path.is_file():
            raise ValueError(f"Missing results.jsonl in records directory: {directory}")
        paths[label] = results_path
    if not paths:
        raise ValueError("Provide --records at least once")
    return labels, paths


def generate_comparison(
    records_dirs: list[Path],
    auditor_sha: str,
    output_dir: Path,
    *,
    wave: bool = False,
    repo_root: Path = REPO_ROOT,
) -> list[dict]:
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise ValueError("Output directory already exists; choose a new directory")
    records_dirs = [Path(directory) for directory in records_dirs]
    repo_root = Path(repo_root).resolve()
    labels, results_paths = _validate_records_dirs(records_dirs)
    full_sha = _resolve_auditor_sha(auditor_sha, Path(repo_root))
    records_by_label = {
        label: _read_jsonl(results_paths[label])
        for label in labels
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    after_records, returns_now = _run_worktree(
        full_sha,
        records_by_label,
        results_paths,
        output_dir,
        Path(repo_root),
    )
    cell_rows, episode_rows = compare_records(
        records_by_label, after_records, returns_now,
    )
    excluded_scripted = _excluded_scripted_variants(records_by_label)
    records_dir_names = {
        label: str(directory)
        for label, directory in zip(labels, records_dirs)
    }
    results_sha = {
        label: _results_sha(records_by_label[label])
        for label in labels
    }
    stamp = _build_stamp(
        records_by_label,
        records_dir_names,
        results_sha,
        cell_rows,
        full_sha,
        wave,
        slide_assets._git_stamp(Path(repo_root)),
    )
    sha_caption = "; ".join(
        f"{label}: {results_sha[label]}" for label in labels
    )
    audit_caption = (
        f"Before: verdicts as recorded (results SHA {sha_caption}). After: offline "
        f"re-audit by runner.reaudit from a clean worktree of auditor SHA "
        f"{full_sha[:7]}."
    )
    captions = [CONFOUND_CAPTION, EXCLUSION_CAPTION, audit_caption]

    markdown_path = output_dir / "matcher_fix_comparison.md"
    csv_path = output_dir / "matcher_fix_comparison.csv"
    png_path = output_dir / "matcher_fix_comparison.png"
    episodes_path = output_dir / "matcher_fix_episodes.csv"
    slide_assets._write_markdown(
        markdown_path,
        "Matcher-fix re-audit comparison",
        list(CELL_HEADERS),
        cell_rows,
        stamp,
        footnote=_scripted_footnote(excluded_scripted),
        extra_sections=["\n\n".join(captions)],
    )
    slide_assets._write_csv(csv_path, list(CELL_HEADERS), cell_rows, stamp)
    slide_assets._write_csv(
        episodes_path, list(EPISODE_HEADERS), _episode_csv_rows(episode_rows), stamp,
    )
    _plot_comparison(png_path, cell_rows, stamp, full_sha, captions)

    source_files = [
        results_paths[label]
        for label in labels
    ] + [
        output_dir / "reaudit" / label / "results.jsonl"
        for label in labels
    ]
    assets = [
        slide_assets._asset_entry(
            path, output_dir, stamp, source_files,
        )
        for path in (markdown_path, csv_path, png_path, episodes_path)
    ]
    for label in labels:
        reaudited_dir = output_dir / "reaudit" / label
        for path in sorted(reaudited_dir.rglob("*")):
            if path.is_file():
                assets.append(slide_assets._asset_entry(
                    path,
                    output_dir,
                    stamp,
                    [results_paths[label], path],
                ))
    manifest = {
        "auditor_sha": full_sha,
        "results_sha": results_sha,
        "records_dirs": records_dir_names,
        "excluded_scripted_variants": excluded_scripted,
        "assets": assets,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return assets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--records", type=Path, action="append", required=True,
        help="records directory; repeat to compare multiple sources",
    )
    parser.add_argument("--auditor-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wave", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Output directory already exists; choose a new directory")
    try:
        assets = generate_comparison(
            args.records,
            args.auditor_sha,
            args.output,
            wave=args.wave,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Wrote {len(assets)} matcher-fix assets to {args.output}")


if __name__ == "__main__":
    main()
