"""Build opaque-ID blinded annotation packets for real trajectories."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sys
from typing import TextIO

from auditor.validation.real.label import _trajectory_doc
from metrics import is_parse_failure_verdict
from runner.modal_batch import is_provider_refusal
from runner.reaudit import _read_records


_MAPPING_WARNING = "COORDINATOR ONLY - never send to annotators or adjudicators"


def build_packet(
    results_path: Path,
    packet_path: Path,
    mapping_path: Path,
    *,
    salt: bytes | None = None,
) -> dict:
    results_path = Path(results_path)
    packet_path = Path(packet_path)
    mapping_path = Path(mapping_path)
    if packet_path.exists() or packet_path.is_symlink():
        raise FileExistsError(f"Packet output already exists: {packet_path}")
    if mapping_path.exists() or mapping_path.is_symlink():
        raise FileExistsError(f"Mapping output already exists: {mapping_path}")
    if packet_path.parent.resolve() == mapping_path.parent.resolve():
        raise ValueError("Mapping and packet must be written to separate directories.")

    if salt is None:
        salt = secrets.token_bytes(16)
    if not isinstance(salt, bytes) or len(salt) != 16:
        raise ValueError("salt must be exactly 16 bytes.")

    results_sha256 = hashlib.sha256(results_path.read_bytes()).hexdigest()
    packet_records = []
    entries = {}
    excluded = {"parse_failure": 0, "provider_refusal": 0}
    for record in _read_records(results_path):
        verdict = record.get("verdict", {}).get("verdict")
        if is_parse_failure_verdict(verdict):
            excluded["parse_failure"] += 1
            continue
        if is_provider_refusal(record):
            excluded["provider_refusal"] += 1
            continue

        episode_id = record["job"]["episode_id"]
        opaque_id = "T" + hmac.new(
            salt,
            f"{results_sha256}:{episode_id}".encode(),
            "sha256",
        ).hexdigest()[:12]
        if opaque_id in entries:
            raise ValueError("Opaque packet ID collision.")
        entries[opaque_id] = {"episode_id": episode_id}
        packet_records.append({
            "packet_format": 1,
            "job": {
                "episode_id": opaque_id,
                "scenario": record["job"].get("scenario", "a"),
            },
            "trajectory": _trajectory_doc(record, results_path),
            "refusals": record.get("refusals", []),
            "aborted_on_refusals": record.get("aborted_on_refusals", False),
        })

    packet_records.sort(key=lambda record: record["job"]["episode_id"])
    entries = {
        record["job"]["episode_id"]: entries[record["job"]["episode_id"]]
        for record in packet_records
    }
    packet_text = "".join(
        json.dumps(record, allow_nan=False) + "\n"
        for record in packet_records
    )
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(packet_text, encoding="utf-8")
    packet_sha256 = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    mapping = {
        "warning": _MAPPING_WARNING,
        "mapping_format": 1,
        "salt_hex": salt.hex(),
        "source_results_sha256": results_sha256,
        "packet_sha256": packet_sha256,
        "excluded": excluded,
        "entries": entries,
    }
    mapping_path.write_text(
        json.dumps(mapping, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return {
        "n_packet_records": len(packet_records),
        "n_parse_failure": excluded["parse_failure"],
        "n_provider_refusal": excluded["provider_refusal"],
        "packet_sha256": packet_sha256,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> dict:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = build_packet(args.results, args.packet, args.mapping)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary), file=sys.stdout if out is None else out)
    return summary


if __name__ == "__main__":
    main()
