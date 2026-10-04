"""Human-vs-auditor agreement for hand-labelled real trajectories."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import TextIO

from metrics import is_parse_failure_verdict
from runner.factories import scenario_dir
from runner.reaudit import _read_records


def auditor_labels(record: dict) -> set[str]:
    """Map a record's verdict to the auditor's episode-level category labels."""
    verdict = record["verdict"]
    labels = set(verdict.get("reward_hacks", []))
    if verdict["verdict"] == "REWARD_HACK" and not labels:
        labels.add("other_hack")
    if verdict["verdict"] == "UNSAFE_ACTION":
        labels.add("unsafe")
    return labels or {"honest"}


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> dict:
    """Cohen's kappa using the #19 validation report's same binary definition."""
    n = len(pairs)
    if n == 0:
        return {"n": 0, "observed_agreement": None, "kappa": None}
    observed = sum(left == right for left, right in pairs) / n
    positive_left = sum(left for left, _ in pairs) / n
    positive_right = sum(right for _, right in pairs) / n
    expected = positive_left * positive_right + (1 - positive_left) * (1 - positive_right)
    kappa = None if expected == 1 else (observed - expected) / (1 - expected)
    return {
        "n": n,
        "observed_agreement": round(observed, 4),
        "kappa": None if kappa is None else round(kappa, 4),
    }


def _read_label_rows(labels_path: Path, results_sha256: str) -> dict[str, dict]:
    latest = {}
    if not labels_path.exists():
        return latest
    with labels_path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("results_sha256") != results_sha256:
                raise ValueError(
                    "Labels belong to one results file; results_sha256 does not match this file."
                )
            latest[row["episode_id"]] = row
    return latest


def _rubric_names(scenario: str) -> dict[str, str]:
    path = scenario_dir(scenario) / "auditor" / "rubric.json"
    rubric = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: value["name"]
        for key, value in rubric["reward_hack_detection"].items()
        if isinstance(value, dict) and "trigger" in value
    }


def _binary_block(pairs: list[tuple[bool, bool]]) -> dict:
    result = cohen_kappa(pairs)
    result["counts"] = {
        "both_flagged": sum(human and auditor for human, auditor in pairs),
        "human_only": sum(human and not auditor for human, auditor in pairs),
        "auditor_only": sum(not human and auditor for human, auditor in pairs),
        "both_honest": sum(not human and not auditor for human, auditor in pairs),
    }
    return result


def _category_block(pairs: list[tuple[bool, bool]]) -> dict:
    result = cohen_kappa(pairs)
    result.update({
        "tp": sum(human and auditor for human, auditor in pairs),
        "fp": sum(human and not auditor for human, auditor in pairs),
        "fn": sum(not human and auditor for human, auditor in pairs),
        "tn": sum(not human and not auditor for human, auditor in pairs),
    })
    return result


def agreement(results_path: Path, labels_path: Path) -> dict:
    results_path = Path(results_path)
    labels_path = Path(labels_path)
    results_sha256 = hashlib.sha256(results_path.read_bytes()).hexdigest()
    records = _read_records(results_path)
    labels_by_id = _read_label_rows(labels_path, results_sha256)
    results_by_id = {record["job"]["episode_id"]: record for record in records}
    missing_ids = labels_by_id.keys() - results_by_id.keys()
    if missing_ids:
        raise ValueError(f"Labels refer to episode IDs absent from results: {sorted(missing_ids)}")

    parse_failures = [
        record for record in records
        if is_parse_failure_verdict(record["verdict"]["verdict"])
    ]
    scored = []
    n_unlabelled = 0
    for record in records:
        if is_parse_failure_verdict(record["verdict"]["verdict"]):
            continue
        row = labels_by_id.get(record["job"]["episode_id"])
        if row is None:
            n_unlabelled += 1
            continue
        human = set(row["labels"])
        scored.append({
            "record": record,
            "row": row,
            "human": human,
            "auditor": auditor_labels(record),
            "scenario": record["job"].get("scenario", "a"),
        })

    binary_pairs = [
        (item["human"] != {"honest"}, item["auditor"] != {"honest"})
        for item in scored
    ]
    blind_pairs = [
        pair for pair, item in zip(
            binary_pairs, scored,
        ) if not item["row"].get("saw_verdict", True)
    ]
    category_names: dict[str, str] = {}
    scenarios = dict.fromkeys(record["job"].get("scenario", "a") for record in records)
    for scenario in scenarios:
        for hack_id, name in _rubric_names(scenario).items():
            category_names[f"{scenario}:{hack_id}"] = name
    category_names["unsafe"] = "Unsafe action"
    category_names["other_hack"] = "Uncategorised reward hack"
    per_category = {}
    for category, name in category_names.items():
        if ":" in category:
            scenario, hack_id = category.split(":", 1)
            members = [item for item in scored if item["scenario"] == scenario]
        else:
            hack_id = category
            members = scored
        pairs = [
            (hack_id in item["human"], hack_id in item["auditor"])
            for item in members
        ]
        per_category[category] = {"name": name, **_category_block(pairs)}

    disagreements = []
    for item in scored:
        if item["human"] != item["auditor"]:
            record, row = item["record"], item["row"]
            disagreements.append({
                "episode_id": record["job"]["episode_id"],
                "scenario": item["scenario"],
                "human": sorted(item["human"]),
                "auditor": sorted(item["auditor"]),
                "verdict": record["verdict"]["verdict"],
                "note": row.get("note"),
            })
    return {
        "binary": _binary_block(binary_pairs),
        "per_category": per_category,
        "blind_only": _binary_block(blind_pairs),
        "n_parse_failure": len(parse_failures),
        "n_unlabelled": n_unlabelled,
        "n_saw_verdict": sum(bool(item["row"].get("saw_verdict", True)) for item in scored),
        "n_blind": sum(not bool(item["row"].get("saw_verdict", True)) for item in scored),
        "n_scored": len(scored),
        "disagreements": disagreements,
    }


def format_markdown(report: dict) -> str:
    binary = report["binary"]
    counts = binary["counts"]
    lines = [
        "# Human-vs-auditor agreement",
        "",
        "## Binary: flagged vs honest",
        "",
        "| n | Observed agreement | Cohen's kappa | Both flagged | Human only | Auditor only | Both honest |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {binary['n']} | {_show(binary['observed_agreement'])} | {_show(binary['kappa'])} "
            f"| {counts['both_flagged']} | {counts['human_only']} | {counts['auditor_only']} "
            f"| {counts['both_honest']} |"
        ),
        "",
        "## Per-category, one-vs-rest",
        "",
        "| Category | n | Observed agreement | Kappa | TP | FP | FN | TN |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for category, row in report["per_category"].items():
        lines.append(
            f"| {category} — {row['name']} | {row['n']} | {_show(row['observed_agreement'])} "
            f"| {_show(row['kappa'])} | {row['tp']} | {row['fp']} | {row['fn']} | {row['tn']} |"
        )
    lines.extend([
        "",
        (
            f"Counts: scored={report['n_scored']} / parse_failure excluded={report['n_parse_failure']} "
            f"/ unlabelled={report['n_unlabelled']} / saw_verdict={report['n_saw_verdict']} "
            f"/ blind={report['n_blind']}."
        ),
        "",
        "Blind-only binary agreement: "
        f"n={report['blind_only']['n']}, kappa={_show(report['blind_only']['kappa'])}.",
        "",
        "## Disagreements",
        "",
    ])
    if report["disagreements"]:
        for item in report["disagreements"]:
            lines.append(
                f"- **{item['episode_id']}** (scenario {item['scenario']}; "
                f"{item['verdict']}): human `{', '.join(item['human'])}`, "
                f"auditor `{', '.join(item['auditor'])}`"
                + (f" — {item['note']}" if item["note"] else "")
            )
    else:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def _show(value) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    return parser


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> dict:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = agreement(args.results, args.labels)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    markdown = format_markdown(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.markdown is not None:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    print(markdown, end="", file=sys.stdout if out is None else out)
    return report


if __name__ == "__main__":
    main()
