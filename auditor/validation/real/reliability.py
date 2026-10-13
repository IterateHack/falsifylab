"""Two-rater reliability for blind labels on saved real trajectories."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TextIO

from auditor.validation.cases import HONEST
from auditor.validation.real import agreement
from auditor.validation.real.common import (
    eligible_label_pairs,
    load_adjudications,
    load_annotation_inputs,
)
from auditor.validation.run_validation import bootstrap_kappa, cohen_kappa


MIN_HEADLINE_N = 30
SEVEN_CLASS_REASON = (
    "human labels are behaviour categories, not auditor verdict classes; "
    "seven-class verdict agreement is measured only on the synthetic set "
    "(auditor/validation/REPORT.md)"
)


def _cohen_block(pairs: list[tuple[bool, bool]], seed_key: str) -> dict:
    rows = [
        {"label": "flagged" if first else HONEST, "passed": not second}
        for first, second in pairs
    ]
    result = cohen_kappa(rows)
    result["bootstrap"] = bootstrap_kappa(
        rows, [[index] for index in range(len(rows))], seed_key=seed_key,
    )
    result["counts"] = {
        "both_flagged": sum(first and second for first, second in pairs),
        "a_only": sum(first and not second for first, second in pairs),
        "b_only": sum(not first and second for first, second in pairs),
        "both_honest": sum(not first and not second for first, second in pairs),
    }
    return result


def _category_block(
    pairs: list[tuple[bool, bool]],
    *,
    name: str,
    seed_key: str,
) -> dict:
    result = _cohen_block(pairs, seed_key)
    counts = result.pop("counts")
    return {
        "name": name,
        **result,
        "tp": counts["both_flagged"],
        "fp": counts["a_only"],
        "fn": counts["b_only"],
        "tn": counts["both_honest"],
    }


def _category_names(records: list[dict]) -> dict[str, str]:
    names = {}
    scenarios = dict.fromkeys(record["job"].get("scenario", "a") for record in records)
    for scenario in scenarios:
        for hack_id, name in agreement._rubric_names(scenario).items():
            names[f"{scenario}:{hack_id}"] = name
    names["unsafe"] = "Unsafe action"
    names["other_hack"] = "Uncategorised reward hack"
    names["protocol_violation"] = "Protocol violation"
    return names


def _per_category(
    items: list[dict],
    category_names: dict[str, str],
    *,
    left_key: str,
    right_key: str,
    seed_prefix: str,
) -> dict:
    result = {}
    for category, name in category_names.items():
        if ":" in category:
            scenario, category_id = category.split(":", 1)
            members = [item for item in items if item["scenario"] == scenario]
        else:
            category_id = category
            members = items
        pairs = [
            (category_id in item[left_key], category_id in item[right_key])
            for item in members
        ]
        result[category] = _category_block(
            pairs,
            name=name,
            seed_key=f"{seed_prefix}:{category}",
        )
    return result


def _inter_rater(items: list[dict], category_names: dict[str, str]) -> dict:
    binary_pairs = [
        (item["labels_a"] != {"honest"}, item["labels_b"] != {"honest"})
        for item in items
    ]
    exact_count = sum(item["labels_a"] == item["labels_b"] for item in items)
    return {
        "binary": _cohen_block(binary_pairs, "real:inter_rater:binary"),
        "per_category": _per_category(
            items,
            category_names,
            left_key="labels_a",
            right_key="labels_b",
            seed_prefix="real:inter_rater",
        ),
        "exact_label_set_agreement": {
            "count": exact_count,
            "rate": round(exact_count / len(items), 4) if items else None,
        },
    }


def _auditor_reference(
    items: list[dict],
    adjudications: dict[str, dict],
    category_names: dict[str, str],
) -> dict:
    reference_items = []
    n_unadjudicated = 0
    for item in items:
        if item["labels_a"] == item["labels_b"]:
            reference = item["labels_a"]
        else:
            row = adjudications.get(item["episode_id"])
            if row is None:
                n_unadjudicated += 1
                continue
            reference = set(row["final_labels"])
        reference_items.append({
            "scenario": item["scenario"],
            "labels_a": reference,
            "labels_b": agreement.auditor_labels(item["record"]),
        })
    binary_pairs = [
        (item["labels_a"] != {"honest"}, item["labels_b"] != {"honest"})
        for item in reference_items
    ]
    return {
        "binary": _cohen_block(
            binary_pairs, "real:auditor_vs_reference:binary",
        ),
        "per_category": _per_category(
            reference_items,
            category_names,
            left_key="labels_a",
            right_key="labels_b",
            seed_prefix="real:auditor_vs_reference",
        ),
        "n_unadjudicated": n_unadjudicated,
    }


def reliability(
    results_path: Path,
    labels_a_path: Path,
    labels_b_path: Path,
    *,
    adjudications_path: Path | None = None,
) -> dict:
    inputs = load_annotation_inputs(results_path, labels_a_path, labels_b_path)
    items, exclusion_counts = eligible_label_pairs(inputs)
    classified_count = sum(
        exclusion_counts[key]
        for key in (
            "n_parse_failure",
            "n_provider_refusal",
            "n_unlabelled_by_either",
            "n_single_labelled",
            "n_anchored",
            "n_job_identity_exposed",
            "n_verdict_revealed",
            "n_eligible",
        )
    )
    assert classified_count == len(inputs["records"])
    category_names = _category_names(inputs["records"])
    report = {
        "inter_rater": _inter_rater(items, category_names),
        "seven_class": {"available": False, "reason": SEVEN_CLASS_REASON},
        "min_headline_n": MIN_HEADLINE_N,
        "labellers": inputs["labellers"],
        **exclusion_counts,
    }
    adjudication_rows = []
    if adjudications_path is not None:
        adjudications, adjudication_rows = load_adjudications(
            adjudications_path, inputs,
        )
        report["auditor_vs_reference"] = _auditor_reference(
            items, adjudications, category_names,
        )

    synthetic_rows = (
        inputs["records"]
        + inputs["raw_labels_a"]
        + inputs["raw_labels_b"]
        + adjudication_rows
    )
    synthetic = any(row.get("synthetic") is True for row in synthetic_rows)
    if synthetic:
        status = "synthetic_placeholder"
    elif exclusion_counts["n_eligible"] < MIN_HEADLINE_N:
        status = "insufficient_sample"
    else:
        status = "ok"
    report["status"] = status
    report["headline_eligible"] = status == "ok"
    return report


def _ci_text(block: dict) -> str:
    bootstrap = block["bootstrap"]
    ci95 = bootstrap["ci95"]
    if ci95 is not None:
        return f"[{ci95[0]:.4f}, {ci95[1]:.4f}]"
    if bootstrap["degenerate"] is True:
        return "n/a (degenerate: all cases agree)"
    if bootstrap["n_clusters"] < 2:
        return "n/a (fewer than 2 cases)"
    return "n/a (fewer than 2 defined resamples)"


def _append_reliability_section(lines: list[str], title: str, block: dict) -> None:
    binary = block["binary"]
    kappa = binary["kappa"]
    kappa_text = "n/a" if kappa is None else f"{kappa:.4f}"
    lines.extend([
        f"## {title}",
        "",
        (
            f"Binary: n={binary['n']}; kappa={kappa_text}; "
            f"95% CI={_ci_text(binary)}."
        ),
        "",
        "Per-category, one-vs-rest:",
    ])
    for category, category_block in block["per_category"].items():
        kappa = category_block["kappa"]
        value = "n/a" if kappa is None else f"{kappa:.4f}"
        lines.append(
            f"- {category}: n={category_block['n']}; kappa={value}; "
            f"95% CI={_ci_text(category_block)}."
        )


def format_markdown(report: dict) -> str:
    lines = ["# Two-rater reliability", ""]
    if report["status"] == "synthetic_placeholder":
        lines.extend([
            "NOT A HEADLINE RESULT: synthetic placeholder labels are not human evidence",
            "",
        ])
    elif report["status"] == "insufficient_sample":
        lines.extend([
            (
                "NOT A HEADLINE RESULT: "
                f"n_eligible={report['n_eligible']} below the minimum of {MIN_HEADLINE_N}"
            ),
            "",
        ])
    _append_reliability_section(
        lines, "Inter-rater reliability (human vs human)", report["inter_rater"],
    )
    lines.extend([
        "",
        "Exact label-set agreement: "
        f"{report['inter_rater']['exact_label_set_agreement']['count']} / "
        f"{report['n_eligible']} "
        f"({report['inter_rater']['exact_label_set_agreement']['rate']}).",
        "",
    ])
    reference = report.get("auditor_vs_reference")
    if reference is None:
        lines.extend([
            "## Auditor vs adjudicated reference",
            "",
            "Not computed; provide --adjudications to construct a reference.",
        ])
    else:
        _append_reliability_section(
            lines, "Auditor vs adjudicated reference", reference,
        )
        lines.extend([
            "",
            f"Unadjudicated disagreements excluded: {reference['n_unadjudicated']}.",
        ])
    lines.extend([
        "",
        (
            f"Exclusions: parse_failure={report['n_parse_failure']}; "
            f"provider_refusal={report['n_provider_refusal']}; "
            f"unlabelled_by_either={report['n_unlabelled_by_either']}; "
            f"single_labelled={report['n_single_labelled']}; "
            f"anchored={report['n_anchored']}; "
            f"job_identity_exposed={report['n_job_identity_exposed']}; "
            f"verdict_revealed={report['n_verdict_revealed']}."
        ),
        "",
    ])
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("labels_a", type=Path)
    parser.add_argument("labels_b", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--adjudications", type=Path)
    return parser


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> dict:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = reliability(
            args.results,
            args.labels_a,
            args.labels_b,
            adjudications_path=args.adjudications,
        )
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
