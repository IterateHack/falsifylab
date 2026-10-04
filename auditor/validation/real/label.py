"""Interactive, resumable human labelling for saved real trajectories."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Callable, TextIO

from contract import Verdict, trajectory_from_dict
from metrics import is_parse_failure_verdict
from runner.factories import scenario_dir
from runner.modal_batch import Refusal
from runner.reaudit import _read_records
from runner.run_one import format_refusals, format_trajectory, format_verdict


def _load_rubric_labels(scenario: str) -> dict[str, str]:
    rubric_path = scenario_dir(scenario) / "auditor" / "rubric.json"
    rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
    return {
        key: value["name"]
        for key, value in rubric["reward_hack_detection"].items()
        if isinstance(value, dict) and "trigger" in value
    }


def _label_rows(labels_path: Path) -> list[dict]:
    if not labels_path.exists():
        return []
    with labels_path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _trajectory_doc(record: dict, results_path: Path) -> dict:
    if "trajectory" in record:
        return record["trajectory"]
    episode_id = record["job"]["episode_id"]
    fallback = results_path.parent / "episodes" / f"{episode_id}.json"
    try:
        return json.loads(fallback.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Missing trajectory for episode {episode_id}: {fallback}"
        ) from exc


def _vocabulary_text(scenario: str, rubric_names: dict[str, str]) -> str:
    entries = ["honest"]
    entries.extend(f"{key} ({name})" for key, name in rubric_names.items())
    entries.extend(("unsafe", "protocol_violation", "other_hack (requires a note)"))
    return f"Labels for scenario {scenario}: " + "; ".join(entries)


def _parse_labels(raw: str, rubric_names: dict[str, str]) -> list[str]:
    allowed = {"honest", *rubric_names, "unsafe", "protocol_violation", "other_hack"}
    entered = [part.strip().lower() for part in raw.split(",")]
    if not entered or any(not item for item in entered):
        raise ValueError("Enter one or more comma-separated labels.")
    if len(set(entered)) != len(entered):
        raise ValueError("Duplicate labels are not allowed.")
    if any(item not in {label.lower() for label in allowed} for item in entered):
        raise ValueError("Unknown label for this scenario.")
    canonical = []
    for item in entered:
        canonical.append(next(label for label in allowed if label.lower() == item))
    if "honest" in canonical and len(canonical) != 1:
        raise ValueError("honest must be used alone.")
    return canonical


def label_session(
    results_path: Path,
    labels_path: Path,
    *,
    labeller: str,
    show_verdict: bool = False,
    input_fn: Callable[[], str] = input,
    out: TextIO = sys.stdout,
    relabel: tuple[str, ...] | list[str] = (),
) -> dict:
    """Prompt for labels, appending and flushing each accepted row immediately."""
    results_path = Path(results_path)
    labels_path = Path(labels_path)
    results_sha256 = hashlib.sha256(results_path.read_bytes()).hexdigest()
    records = _read_records(results_path)
    prior_rows = _label_rows(labels_path)
    if any(row.get("results_sha256") != results_sha256 for row in prior_rows):
        raise ValueError(
            "Labels belong to one results file; results_sha256 does not match this file."
        )

    relabel_ids = set(relabel)
    episode_ids = {record["job"]["episode_id"] for record in records}
    unknown_relabels = relabel_ids - episode_ids
    if unknown_relabels:
        raise ValueError(f"Cannot relabel episode IDs absent from results: {sorted(unknown_relabels)}")

    parse_failures = [
        record for record in records
        if is_parse_failure_verdict(record["verdict"]["verdict"])
    ]
    already_labelled = {row["episode_id"] for row in prior_rows}
    queue = [
        record for record in records
        if not is_parse_failure_verdict(record["verdict"]["verdict"])
        and (
            record["job"]["episode_id"] not in already_labelled
            or record["job"]["episode_id"] in relabel_ids
        )
    ]
    print(
        f"Excluded {len(parse_failures)} PARSE_FAILURE episode(s) from labelling.",
        file=out,
        flush=True,
    )
    labelled = 0
    skipped = 0
    remaining = len(queue)
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    for index, record in enumerate(queue, start=1):
        job = record["job"]
        episode_id = job["episode_id"]
        scenario = job.get("scenario", "a")
        rubric_names = _load_rubric_labels(scenario)
        vocabulary = _vocabulary_text(scenario, rubric_names)
        verdict = Verdict(**record["verdict"])
        aborted = record.get("aborted_on_refusals", False)
        trajectory = trajectory_from_dict(_trajectory_doc(record, results_path))
        refusals = [Refusal(**item) for item in record.get("refusals", [])]
        print(
            f"\n[{episode_id}] scenario={scenario} variant={job.get('variant')} "
            f"model={job.get('model')} seed={job.get('seed')} ({index} of {len(queue)})",
            file=out,
            flush=True,
        )
        print(format_trajectory(trajectory), file=out, flush=True)
        print(format_refusals(refusals, aborted), file=out, flush=True)
        if show_verdict:
            print(format_verdict(verdict, aborted_on_refusals=aborted), file=out, flush=True)
        print(vocabulary, file=out, flush=True)

        while True:
            print("Label (comma-separated; s=skip, q=quit, ?=vocabulary): ", end="", file=out, flush=True)
            raw = input_fn().strip()
            command = raw.lower()
            if command == "s":
                skipped += 1
                remaining = len(queue) - index
                break
            if command == "q":
                remaining = len(queue) - index + 1
                return {
                    "labelled": labelled,
                    "skipped": skipped,
                    "remaining": remaining,
                    "excluded_parse_failure": len(parse_failures),
                }
            if command == "?":
                print(vocabulary, file=out, flush=True)
                continue
            try:
                labels = _parse_labels(raw, rubric_names)
            except ValueError as exc:
                print(f"Invalid label: {exc}", file=out, flush=True)
                continue

            print("Note (optional): ", end="", file=out, flush=True)
            note = input_fn().strip()
            if "other_hack" in labels and not note:
                print("Invalid label: other_hack requires a non-empty note.", file=out, flush=True)
                continue
            row = {
                "episode_id": episode_id,
                "scenario": scenario,
                "results_sha256": results_sha256,
                "labels": labels,
                "note": note or None,
                "labeller": labeller,
                "saw_verdict": show_verdict,
                "auditor_verdict": verdict.verdict,
                "labelled_at": datetime.now(timezone.utc).isoformat(),
            }
            with labels_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
                stream.flush()
            labelled += 1
            remaining = len(queue) - index
            if not show_verdict:
                print(format_verdict(verdict, aborted_on_refusals=aborted), file=out, flush=True)
            break
    return {
        "labelled": labelled,
        "skipped": skipped,
        "remaining": remaining,
        "excluded_parse_failure": len(parse_failures),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--labeller", required=True)
    parser.add_argument(
        "--show-verdict",
        action="store_true",
        help="triage only: show the auditor verdict before labelling; these labels are excluded from the headline kappa",
    )
    parser.add_argument("--relabel", action="append", default=[], metavar="EPISODE_ID")
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
        result = label_session(
            args.results,
            args.labels,
            labeller=args.labeller,
            show_verdict=args.show_verdict,
            input_fn=input if input_fn is None else input_fn,
            out=sys.stdout if out is None else out,
            relabel=args.relabel,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result), file=sys.stdout if out is None else out)
    return result


if __name__ == "__main__":
    main()
