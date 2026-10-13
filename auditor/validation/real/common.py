"""Shared validation and eligibility helpers for real-trajectory labels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def is_blind_label(row: dict) -> bool:
    return (
        row.get("saw_verdict") is False
        and row.get("saw_job_identity") is False
        and row.get("verdict_revealed") is False
    )


def read_jsonl(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_annotation_inputs(
    results_path: Path,
    labels_a_path: Path,
    labels_b_path: Path,
) -> dict:
    from auditor.validation.real.agreement import _read_label_rows
    from runner.reaudit import _read_records

    results_path = Path(results_path)
    labels_a_path = Path(labels_a_path)
    labels_b_path = Path(labels_b_path)
    results_sha256 = file_sha256(results_path)
    records = _read_records(results_path)
    results_by_id = {record["job"]["episode_id"]: record for record in records}
    label_files = (labels_a_path, labels_b_path)
    raw_rows = [read_jsonl(path) for path in label_files]
    try:
        latest_rows = [
            _read_label_rows(path, results_sha256)
            for path in label_files
        ]
    except KeyError as exc:
        raise ValueError("Label row is missing an episode_id.") from exc

    for path, rows in zip(label_files, raw_rows):
        labellers = {row.get("labeller") for row in rows}
        if (
            len(labellers) != 1
            or not isinstance(next(iter(labellers), None), str)
            or not next(iter(labellers), "").strip()
        ):
            raise ValueError(f"{path} must contain rows from exactly one labeller.")
        missing_ids = {
            row.get("episode_id") for row in rows
            if row.get("episode_id") not in results_by_id
        }
        if missing_ids:
            raise ValueError(
                f"Labels refer to episode IDs absent from results: {sorted(missing_ids)}"
            )

    labellers = [next(iter({row["labeller"] for row in rows})) for rows in raw_rows]
    if labellers[0] == labellers[1]:
        raise ValueError("The two labels files must have different labellers.")

    return {
        "results_path": results_path,
        "labels_a_path": labels_a_path,
        "labels_b_path": labels_b_path,
        "results_sha256": results_sha256,
        "labels_a_sha256": file_sha256(labels_a_path),
        "labels_b_sha256": file_sha256(labels_b_path),
        "records": records,
        "results_by_id": results_by_id,
        "labels_a": latest_rows[0],
        "labels_b": latest_rows[1],
        "raw_labels_a": raw_rows[0],
        "raw_labels_b": raw_rows[1],
        "labellers": labellers,
    }


def eligible_label_pairs(inputs: dict) -> tuple[list[dict], dict[str, int]]:
    from metrics import is_parse_failure_verdict
    from runner.modal_batch import is_provider_refusal

    counts = {
        "n_parse_failure": 0,
        "n_provider_refusal": 0,
        "n_unlabelled_by_either": 0,
        "n_single_labelled": 0,
        "n_anchored": 0,
        "n_job_identity_exposed": 0,
        "n_verdict_revealed": 0,
        "n_eligible": 0,
    }
    eligible = []
    for record in inputs["records"]:
        if is_parse_failure_verdict(record["verdict"]["verdict"]):
            counts["n_parse_failure"] += 1
            continue
        if is_provider_refusal(record):
            counts["n_provider_refusal"] += 1
            continue
        episode_id = record["job"]["episode_id"]
        row_a = inputs["labels_a"].get(episode_id)
        row_b = inputs["labels_b"].get(episode_id)
        if row_a is None and row_b is None:
            counts["n_unlabelled_by_either"] += 1
            continue
        if row_a is None or row_b is None:
            counts["n_single_labelled"] += 1
            continue
        if (
            row_a.get("saw_verdict") is not False
            or row_b.get("saw_verdict") is not False
        ):
            counts["n_anchored"] += 1
            continue
        if (
            row_a.get("saw_job_identity") is not False
            or row_b.get("saw_job_identity") is not False
        ):
            counts["n_job_identity_exposed"] += 1
            continue
        if (
            row_a.get("verdict_revealed") is not False
            or row_b.get("verdict_revealed") is not False
        ):
            counts["n_verdict_revealed"] += 1
            continue
        eligible.append({
            "record": record,
            "episode_id": episode_id,
            "scenario": record["job"].get("scenario", "a"),
            "row_a": row_a,
            "row_b": row_b,
            "labels_a": set(row_a["labels"]),
            "labels_b": set(row_b["labels"]),
        })
    counts["n_eligible"] = len(eligible)
    return eligible, counts


def validate_adjudicator_name(adjudicator: str, labellers: list[str]) -> None:
    if (
        not isinstance(adjudicator, str)
        or not adjudicator.strip()
        or adjudicator in labellers
    ):
        raise ValueError("adjudicator must differ from both labellers and be a third person.")


def load_adjudications(
    adjudications_path: Path,
    inputs: dict,
    *,
    allow_missing: bool = False,
) -> tuple[dict[str, dict], list[dict]]:
    adjudications_path = Path(adjudications_path)
    if not adjudications_path.exists() and allow_missing:
        return {}, []
    rows = read_jsonl(adjudications_path)
    latest = {}
    results_ids = inputs["results_by_id"].keys()
    for row in rows:
        episode_id = row.get("episode_id")
        if episode_id not in results_ids:
            raise ValueError(
                f"Adjudication refers to episode ID absent from results: {episode_id!r}"
            )
        if row.get("results_sha256") != inputs["results_sha256"]:
            raise ValueError("Adjudication results_sha256 does not match the results file.")
        if row.get("labels_a_sha256") != inputs["labels_a_sha256"]:
            raise ValueError("Adjudication labels_a_sha256 does not match the labels file.")
        if row.get("labels_b_sha256") != inputs["labels_b_sha256"]:
            raise ValueError("Adjudication labels_b_sha256 does not match the labels file.")
        rationale = row.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("Adjudication rationale must be non-empty.")
        validate_adjudicator_name(row.get("adjudicator"), inputs["labellers"])
        if not isinstance(row.get("final_labels"), list) or not row["final_labels"]:
            raise ValueError("Adjudication final_labels must be a non-empty list.")
        latest[episode_id] = row
    return latest, rows
