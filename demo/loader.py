"""Load sample episode records and expose the viewer's replay-step model."""
from __future__ import annotations

import json
from pathlib import Path

REQUIRED_RECORD_KEYS = {
    "job",
    "verdict",
    "metrics",
    "trajectory",
    "refusals",
    "refusal_count",
    "aborted_on_refusals",
}


def load_results(path) -> list[dict]:
    """Read JSONL records, validating the core modal_batch record shape."""
    records = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"line {line_number}: record must be a JSON object")
            missing = sorted(REQUIRED_RECORD_KEYS - record.keys())
            if missing:
                raise ValueError(
                    f"line {line_number}: missing required keys: {', '.join(missing)}"
                )
            records.append(record)
    return records


def episode_steps(record: dict) -> list[dict]:
    """Convert a serialized trajectory to the viewer's turn-by-turn replay model."""
    steps = []
    cumulative_cost = 0
    for turn in record["trajectory"]["turns"]:
        action = turn["action"]
        if action["kind"] == "run_experiment":
            observation = turn.get("observation") or {}
            cost = observation.get("cost", 0)
            cumulative_cost += cost
            steps.append({
                "index": turn["index"],
                "kind": "experiment",
                "experiment_id": action.get("experiment_id"),
                "parameters": action.get("parameters", {}),
                "cost": cost,
                "cumulative_cost": cumulative_cost,
                "beliefs": action.get("beliefs", {}),
                "dominant_cause": action.get("dominant_cause"),
                "results": [
                    result["value"] for result in observation.get("results", [])
                ],
            })
        else:
            steps.append({
                "index": turn["index"],
                "kind": "conclude",
                "contributing_hypotheses": action.get("contributing_hypotheses"),
                "dominant_cause": action.get("dominant_cause"),
                "confidence": action.get("confidence"),
                "beliefs": action.get("beliefs", {}),
                "evidence_cited": action.get("evidence_cited"),
                "makes_target_claim": action.get("makes_target_claim", False),
            })
    return steps
