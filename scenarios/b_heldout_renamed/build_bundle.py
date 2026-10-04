"""Build a renamed, held-out copy of the scenario B bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "scenarios" / "b_cd5_affinity"
TARGET = Path(__file__).resolve().parent
GENERATED_FILES = (
    "agent/briefing.json",
    "agent/experiments.json",
    "agent/hypotheses.json",
    "auditor/rubric.json",
    "auditor/constraints.json",
    "auditor/truth.json",
    "auditor/expected_observations.json",
    "auditor/provenance.json",
)
DEFAULT_RENAME_MAP = (
    ("falsifylab.v0_1.binder_affinity_durability", "falsifylab.v0_1.heldout_b_renamed"),
    ("targeting a T-cell antigen", "targeting the T-cell antigen TRV9"),
    ("CD5", "TRV9"),
    ("clone_H", "clone_P"),
    ("clone_A", "clone_Q"),
    ("clone_C", "clone_R"),
    ("clone_F", "clone_S"),
    ("clone_D", "clone_T"),
    ("H65", "clone_P"),
    ("A2", "clone_Q"),
    ("C7", "clone_R"),
    ("F8", "clone_S"),
    ("D9", "clone_T"),
    ("Myc tag", "VT1 tag"),
    ("CD8a", "HX2"),
    ("4-1BB", "KS3"),
    ("CD3zeta", "ZR1"),
    ("Octet", "BLI"),
)
PROVENANCE_NOTE = (
    "AUDITOR-ONLY: Env and audit never load this file. Truth's verbatim quotes "
    "in this bundle have been passed through the rename map and are no longer "
    "verbatim."
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _provenance(rename_map: list[dict[str, str]]) -> dict:
    observations = _read_json(SOURCE / "auditor" / "expected_observations.json")
    return {
        "source_doi": observations["source_doi"],
        "source_citation": observations["source_citation"],
        "clone_key": observations["clone_key"],
        "rename_map": rename_map,
        "derived_from": "scenarios/b_cd5_affinity",
        "_": PROVENANCE_NOTE,
    }


def _mapping_pairs(provenance: dict) -> tuple[tuple[str, str], ...]:
    pairs = tuple(
        (entry["from"], entry["to"])
        for entry in provenance["rename_map"]
    )
    if not pairs or any(not before or not after for before, after in pairs):
        raise ValueError("provenance rename_map must contain non-empty from/to pairs")
    return pairs


def transform(value, rename_map):
    """Apply ordered whole-word replacements to JSON string values and keys."""
    patterns = [
        (
            re.compile(r"(?<![A-Za-z0-9_])" + re.escape(before) + r"(?![A-Za-z0-9_])"),
            after,
        )
        for before, after in rename_map
    ]

    def replace_strings(item):
        if isinstance(item, str):
            for pattern, replacement in patterns:
                item = pattern.sub(lambda _: replacement, item)
            return item
        if isinstance(item, list):
            return [replace_strings(child) for child in item]
        if isinstance(item, dict):
            result = {}
            for key, child in item.items():
                renamed_key = replace_strings(key)
                if renamed_key in result:
                    raise ValueError(f"rename map creates duplicate JSON key {renamed_key!r}")
                result[renamed_key] = replace_strings(child)
            return result
        return item

    return replace_strings(value)


def _load_provenance(check: bool) -> tuple[dict, tuple[tuple[str, str], ...]]:
    path = TARGET / "auditor" / "provenance.json"
    if not path.exists():
        if check:
            raise FileNotFoundError(path)
        initial = [
            {"from": before, "to": after}
            for before, after in DEFAULT_RENAME_MAP
        ]
        path.write_text(_json_text(_provenance(initial)), encoding="utf-8")
    provenance = _read_json(path)
    pairs = _mapping_pairs(provenance)
    expected = _provenance(provenance["rename_map"])
    if provenance != expected:
        raise ValueError("provenance.json metadata differs from its source")
    return provenance, pairs


def _expected_files(rename_map, provenance: dict) -> dict[str, str]:
    files = {}
    for relative in GENERATED_FILES:
        if relative == "auditor/provenance.json":
            document = provenance
        else:
            document = _read_json(SOURCE / relative)
            if relative == "auditor/expected_observations.json":
                for key in ("source_doi", "source_citation", "clone_key"):
                    document.pop(key)
            document = transform(document, rename_map)
        files[relative] = _json_text(document)
    return files


def _check_files(expected: dict[str, str]) -> bool:
    stale = []
    for relative, content in expected.items():
        path = TARGET / relative
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            stale.append(relative)
    expected_paths = {TARGET / relative for relative in expected}
    actual_json = {
        *((TARGET / "agent").glob("*.json")),
        *((TARGET / "auditor").glob("*.json")),
    }
    stale.extend(
        str(path.relative_to(TARGET))
        for path in sorted(actual_json - expected_paths)
    )
    if stale:
        print(f"stale bundle files: {', '.join(stale)}", file=sys.stderr)
        return False
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if generated bundle files differ from a fresh build",
    )
    args = parser.parse_args(argv)

    try:
        provenance, rename_map = _load_provenance(args.check)
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        print(f"invalid bundle provenance: {exc}", file=sys.stderr)
        return 1

    expected = _expected_files(rename_map, provenance)
    if args.check:
        return 0 if _check_files(expected) else 1

    for relative, content in expected.items():
        (TARGET / relative).write_text(content, encoding="utf-8")
    print("Wrote renamed scenario B bundle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
