"""Blind, resumable adjudication of disagreements between two label files."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Callable, TextIO

from auditor.validation.real.common import (
    eligible_label_pairs,
    load_adjudications,
    load_annotation_inputs,
    validate_adjudicator_name,
)
from auditor.validation.real.label import (
    _load_rubric_labels,
    _parse_labels,
    _trajectory_doc,
    _vocabulary_text,
)
from contract import trajectory_from_dict
from runner.modal_batch import Refusal
from runner.run_one import format_refusals, format_trajectory


def adjudicate_session(
    results_path: Path,
    labels_a_path: Path,
    labels_b_path: Path,
    adjudications_path: Path,
    *,
    adjudicator: str,
    input_fn: Callable[[], str] = input,
    out: TextIO = sys.stdout,
) -> dict:
    inputs = load_annotation_inputs(results_path, labels_a_path, labels_b_path)
    validate_adjudicator_name(adjudicator, inputs["labellers"])
    already_adjudicated, _ = load_adjudications(
        adjudications_path, inputs, allow_missing=True,
    )
    eligible, _ = eligible_label_pairs(inputs)
    queue = [
        item for item in eligible
        if item["labels_a"] != item["labels_b"]
        and item["episode_id"] not in already_adjudicated
    ]
    if not queue:
        print("No disagreements pending adjudication.", file=out, flush=True)
        return {"adjudicated": 0, "skipped": 0, "remaining": 0}

    adjudications_path = Path(adjudications_path)
    adjudications_path.parent.mkdir(parents=True, exist_ok=True)
    adjudicated = 0
    skipped = 0
    remaining = len(queue)
    for index, item in enumerate(queue, start=1):
        record = item["record"]
        episode_id = item["episode_id"]
        scenario = item["scenario"]
        rubric_names = _load_rubric_labels(scenario)
        vocabulary = _vocabulary_text(scenario, rubric_names)
        trajectory = trajectory_from_dict(_trajectory_doc(record, inputs["results_path"]))
        refusals = [Refusal(**value) for value in record.get("refusals", [])]
        print(
            f"\n[{episode_id}] scenario={scenario} ({index} of {len(queue)})",
            file=out,
            flush=True,
        )
        print(format_trajectory(trajectory), file=out, flush=True)
        print(
            format_refusals(
                refusals, record.get("aborted_on_refusals", False),
            ),
            file=out,
            flush=True,
        )
        for reviewer, row in enumerate((item["row_a"], item["row_b"]), start=1):
            note = row.get("note") or "(none)"
            print(
                f"Reviewer {reviewer}: {', '.join(row['labels'])} — note: {note}",
                file=out,
                flush=True,
            )
        print(vocabulary, file=out, flush=True)

        while True:
            print(
                "Final labels (comma-separated; s=skip, q=quit, ?=vocabulary): ",
                end="",
                file=out,
                flush=True,
            )
            raw = input_fn().strip()
            command = raw.lower()
            if command == "s":
                skipped += 1
                remaining = len(queue) - index
                break
            if command == "q":
                remaining = len(queue) - index + 1
                return {
                    "adjudicated": adjudicated,
                    "skipped": skipped,
                    "remaining": remaining,
                }
            if command == "?":
                print(vocabulary, file=out, flush=True)
                continue
            try:
                final_labels = _parse_labels(raw, rubric_names)
            except ValueError as exc:
                print(f"Invalid label: {exc}", file=out, flush=True)
                continue

            while True:
                print("Rationale (required): ", end="", file=out, flush=True)
                rationale = input_fn().strip()
                if rationale:
                    break
                print("Rationale cannot be empty.", file=out, flush=True)

            row = {
                "episode_id": episode_id,
                "scenario": scenario,
                "results_sha256": inputs["results_sha256"],
                "labels_a_sha256": inputs["labels_a_sha256"],
                "labels_b_sha256": inputs["labels_b_sha256"],
                "reviewer_labels": {
                    "1": list(item["row_a"]["labels"]),
                    "2": list(item["row_b"]["labels"]),
                },
                "final_labels": final_labels,
                "rationale": rationale,
                "adjudicator": adjudicator,
                "saw_verdict": False,
                "saw_job_identity": False,
                "adjudicated_at": datetime.now(timezone.utc).isoformat(),
            }
            with adjudications_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
                stream.flush()
            adjudicated += 1
            remaining = len(queue) - index
            break

    return {
        "adjudicated": adjudicated,
        "skipped": skipped,
        "remaining": remaining,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("labels_a", type=Path)
    parser.add_argument("labels_b", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--adjudicator", required=True)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[], str] | None = None,
    out: TextIO | None = None,
) -> dict:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = adjudicate_session(
            args.results,
            args.labels_a,
            args.labels_b,
            args.out,
            adjudicator=args.adjudicator,
            input_fn=input if input_fn is None else input_fn,
            out=sys.stdout if out is None else out,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result), file=sys.stdout if out is None else out)
    return result


if __name__ == "__main__":
    main()
