"""Temporary-file regressions for opaque blinded annotation packets."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import random
import socket
import subprocess
import sys

import pytest

from auditor.validation.real import adjudicate as adjudicate_module
from auditor.validation.real import agreement as agreement_module
from auditor.validation.real import common as common_module
from auditor.validation.real import label as label_module
from auditor.validation.real import reliability as reliability_module
from test_real_labelling import _build_results, _read_rows, _scripted
from test_real_reliability import (
    _adjudication_row,
    _read_rows as _read_jsonl,
    _reliability,
    _write_jsonl,
    _write_pair,
    _write_results,
)


ROOT = Path(__file__).resolve().parents[1]
VERDICT_ENUMS = (
    "VALID_SUCCESS",
    "WRONG_CONCLUSION",
    "INSUFFICIENT_EVIDENCE",
    "PARSE_FAILURE",
    "PROTOCOL_VIOLATION",
    "UNSAFE_ACTION",
    "REWARD_HACK",
)


def _packet_module():
    return importlib.import_module("auditor.validation.real.packet")


def _packet_paths(tmp_path: Path, suffix: str = "") -> tuple[Path, Path]:
    packet_path = tmp_path / "packets" / f"packet{suffix}.jsonl"
    mapping_path = tmp_path / "mappings" / f"mapping{suffix}.json"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    return packet_path, mapping_path


def _build_fixture_packet(
    tmp_path: Path,
    *,
    results_path: Path | None = None,
    suffix: str = "",
    salt: bytes | None = None,
) -> tuple[Path, Path, Path, dict]:
    results_path = results_path or tmp_path / f"results{suffix}.jsonl"
    if not results_path.exists():
        _build_results(results_path)
    packet_path, mapping_path = _packet_paths(tmp_path, suffix)
    summary = _packet_module().build_packet(
        results_path, packet_path, mapping_path, salt=salt,
    )
    return results_path, packet_path, mapping_path, summary


def _strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def _keys(value):
    if isinstance(value, dict):
        yield from value
        for item in value.values():
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def _packet_label_pair(
    packet_path: Path,
    labels_a_path: Path,
    labels_b_path: Path,
    *,
    disagree_on: str | None = None,
) -> tuple[list[dict], list[dict]]:
    records = _read_rows(packet_path)
    labels_b = {disagree_on: ["protocol_violation"]} if disagree_on else None
    return _write_pair(
        packet_path,
        records,
        labels_a_path,
        labels_b_path,
        labels_b=labels_b,
    )


def _translate_label_file(
    source_path: Path,
    target_path: Path,
    *,
    original_to_opaque: dict[str, str],
    target_results_sha256: str,
) -> list[dict]:
    translated = []
    for row in _read_jsonl(source_path):
        opaque_id = original_to_opaque.get(row["episode_id"])
        if opaque_id is None:
            continue
        packet_row = deepcopy(row)
        packet_row["episode_id"] = opaque_id
        packet_row["results_sha256"] = target_results_sha256
        translated.append(packet_row)
    _write_jsonl(target_path, translated)
    return translated


def test_packet_records_contain_only_allowed_blinded_fields(tmp_path):
    results_path, packet_path, mapping_path, summary = _build_fixture_packet(
        tmp_path, salt=b"\x01" * 16,
    )
    source = _read_rows(results_path)
    packet = _read_rows(packet_path)
    packet_text = packet_path.read_text(encoding="utf-8")
    original_ids = {record["job"]["episode_id"] for record in source}

    assert packet
    assert all(
        set(record) == {
            "packet_format",
            "job",
            "trajectory",
            "refusals",
            "aborted_on_refusals",
        }
        for record in packet
    )
    assert all(set(record["job"]) == {"episode_id", "scenario"} for record in packet)
    assert not original_ids.intersection(_strings(packet))
    assert "baseline" not in packet_text
    assert "fixture-model" not in packet_text
    assert "seed" not in set(_keys(packet))
    assert not set(VERDICT_ENUMS).intersection(_strings(packet))
    assert not {
        "metrics", "model_call_log", "sampling", "tokens",
    }.intersection(_keys(packet))
    assert summary["packet_sha256"] == hashlib.sha256(
        packet_path.read_bytes(),
    ).hexdigest()
    assert "salt" not in json.dumps(summary).lower()
    assert "episode_id" not in json.dumps(summary)
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert next(iter(mapping)) == "warning"


def test_packet_excludes_and_counts_parse_failures_and_provider_refusals(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _write_results(
        results_path,
        4,
        parse_failure_ids={"00000000"},
        provider_refusal_ids={"00000001"},
    )
    _, packet_path, mapping_path, summary = _build_fixture_packet(
        tmp_path, results_path=results_path, suffix="-excluded",
    )

    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert len(_read_rows(packet_path)) == 2
    assert mapping["excluded"] == {"parse_failure": 1, "provider_refusal": 1}
    assert summary["n_parse_failure"] == 1
    assert summary["n_provider_refusal"] == 1


def test_packet_ids_are_opaque_unique_deterministic_and_sorted(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    _, packet_a, _, _ = _build_fixture_packet(
        tmp_path, results_path=results_path, suffix="-a", salt=b"\x02" * 16,
    )
    _, packet_b, _, _ = _build_fixture_packet(
        tmp_path, results_path=results_path, suffix="-b", salt=b"\x02" * 16,
    )
    _, packet_random_a, _, _ = _build_fixture_packet(
        tmp_path, results_path=results_path, suffix="-random-a",
    )
    _, packet_random_b, _, _ = _build_fixture_packet(
        tmp_path, results_path=results_path, suffix="-random-b",
    )
    source_ids = {record["job"]["episode_id"] for record in _read_rows(results_path)}
    ids_a = [record["job"]["episode_id"] for record in _read_rows(packet_a)]
    ids_b = [record["job"]["episode_id"] for record in _read_rows(packet_b)]
    random_ids_a = {
        record["job"]["episode_id"] for record in _read_rows(packet_random_a)
    }
    random_ids_b = {
        record["job"]["episode_id"] for record in _read_rows(packet_random_b)
    }

    assert packet_a.read_bytes() == packet_b.read_bytes()
    assert ids_a == ids_b == sorted(ids_a)
    assert len(ids_a) == len(set(ids_a))
    assert not source_ids.intersection(ids_a)
    assert random_ids_a != random_ids_b


@pytest.mark.parametrize("existing_output", ["packet", "mapping"])
def test_packet_refuses_to_overwrite_an_existing_output(tmp_path, existing_output):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    packet_path, mapping_path = _packet_paths(tmp_path)
    occupied = packet_path if existing_output == "packet" else mapping_path
    occupied.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        _packet_module().build_packet(results_path, packet_path, mapping_path)
    assert occupied.read_text(encoding="utf-8") == "keep"


def test_packet_refuses_mapping_in_packet_directory(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    packet_path = tmp_path / "same" / "packet.jsonl"
    mapping_path = tmp_path / "same" / "mapping.json"

    with pytest.raises(ValueError, match="separate director"):
        _packet_module().build_packet(results_path, packet_path, mapping_path)


def test_packet_rejects_opaque_id_collisions(tmp_path, monkeypatch):
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    packet_path, mapping_path = _packet_paths(tmp_path)

    class FixedDigest:
        def hexdigest(self):
            return "a" * 64

    packet_module = _packet_module()
    monkeypatch.setattr(packet_module.hmac, "new", lambda *_args: FixedDigest())
    with pytest.raises(ValueError, match="collision"):
        packet_module.build_packet(results_path, packet_path, mapping_path)


def test_annotation_inputs_reject_a_mixed_packet_file(tmp_path):
    results_path = tmp_path / "mixed.jsonl"
    records = _build_results(results_path)
    records[0]["packet_format"] = 1
    _write_jsonl(results_path, records)
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write_pair(results_path, records, labels_a_path, labels_b_path)

    with pytest.raises(ValueError, match="mixes packet and non-packet"):
        common_module.load_annotation_inputs(
            results_path, labels_a_path, labels_b_path,
        )


def test_label_packet_is_verdict_free_resumable_and_shufflable(tmp_path):
    _, packet_path, _, _ = _build_fixture_packet(
        tmp_path, salt=b"\x03" * 16,
    )
    records = _read_rows(packet_path)
    labels_path = tmp_path / "labels.jsonl"
    expected_order = [record["job"]["episode_id"] for record in records]
    seed = 7
    random.Random(f"{seed}:Ada").shuffle(expected_order)
    out = io.StringIO()

    first = label_module.main(
        [
            str(packet_path),
            "--labels", str(labels_path),
            "--labeller", "Ada",
            "--shuffle-seed", str(seed),
        ],
        input_fn=_scripted(["honest", "", "q"]),
        out=out,
    )
    rows = _read_rows(labels_path)
    assert first["labelled"] == 1
    assert rows[0]["episode_id"] == expected_order[0]
    assert rows[0]["saw_verdict"] is False
    assert rows[0]["saw_job_identity"] is False
    assert rows[0]["verdict_revealed"] is False
    assert rows[0]["auditor_verdict"] is None
    assert all(verdict not in out.getvalue() for verdict in VERDICT_ENUMS)
    assert "Warning: without --no-reveal" not in out.getvalue()

    label_module.main(
        [
            str(packet_path),
            "--labels", str(labels_path),
            "--labeller", "Ada",
            "--shuffle-seed", str(seed),
        ],
        input_fn=_scripted(["honest", ""] * (len(records) - 1)),
        out=io.StringIO(),
    )
    assert len(_read_rows(labels_path)) == len(records)
    assert {row["episode_id"] for row in _read_rows(labels_path)} == set(expected_order)

    with pytest.raises(SystemExit):
        label_module.main(
            [
                str(packet_path),
                "--labels", str(tmp_path / "show-verdict.jsonl"),
                "--labeller", "Ada",
                "--show-verdict",
            ],
            out=io.StringIO(),
        )


def test_adjudicate_packet_only_prints_opaque_ids(tmp_path):
    results_path, packet_path, _, _ = _build_fixture_packet(
        tmp_path, salt=b"\x04" * 16,
    )
    original_ids = {
        record["job"]["episode_id"] for record in _read_rows(results_path)
    }
    records = _read_rows(packet_path)
    opaque_id = records[0]["job"]["episode_id"]
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _packet_label_pair(
        packet_path, labels_a_path, labels_b_path, disagree_on=opaque_id,
    )
    adjudications_path = tmp_path / "adjudications.jsonl"
    out = io.StringIO()

    result = adjudicate_module.adjudicate_session(
        packet_path,
        labels_a_path,
        labels_b_path,
        adjudications_path,
        adjudicator="Third Rater",
        input_fn=_scripted(["honest", "Reviewed independently."]),
        out=out,
    )

    assert result["adjudicated"] == 1
    assert all(original_id not in out.getvalue() for original_id in original_ids)
    adjudication = _read_rows(adjudications_path)[0]
    assert adjudication["episode_id"] == opaque_id
    assert all(key != "auditor_verdict" for key in adjudication)


def test_reliability_packet_works_without_mapping_and_requires_mapping_for_reference(
    tmp_path,
):
    _, packet_path, _, _ = _build_fixture_packet(
        tmp_path, salt=b"\x05" * 16,
    )
    records = _read_rows(packet_path)
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _packet_label_pair(packet_path, labels_a_path, labels_b_path)

    report = _reliability(packet_path, labels_a_path, labels_b_path)
    assert report["inter_rater"]["binary"]["n"] == len(records)
    assert report["n_parse_failure"] == 0
    assert report["n_provider_refusal"] == 0
    with pytest.raises(ValueError, match="--mapping and --source-results"):
        _reliability(
            packet_path,
            labels_a_path,
            labels_b_path,
            adjudications_path=tmp_path / "adjudications.jsonl",
        )


def test_packet_mapping_hashes_entries_and_unblinded_equivalence(tmp_path):
    results_path = tmp_path / "source.jsonl"
    source_records = _build_results(results_path)
    _, packet_path, mapping_path, _ = _build_fixture_packet(
        tmp_path,
        results_path=results_path,
        suffix="-equivalence",
        salt=b"\x06" * 16,
    )
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    packet_records = _read_rows(packet_path)
    original_to_opaque = {
        details["episode_id"]: opaque_id
        for opaque_id, details in mapping["entries"].items()
    }
    original_id = next(iter(original_to_opaque))
    labels_a_path, labels_b_path = tmp_path / "source-a.jsonl", tmp_path / "source-b.jsonl"
    _write_pair(
        results_path,
        source_records,
        labels_a_path,
        labels_b_path,
        labels_b={original_id: ["protocol_violation"]},
    )
    source_adjudications_path = tmp_path / "source-adjudications.jsonl"
    _write_jsonl(
        source_adjudications_path,
        [
            _adjudication_row(
                results_path,
                labels_a_path,
                labels_b_path,
                original_id,
                reviewer_labels={"1": ["honest"], "2": ["protocol_violation"]},
                final_labels=["honest"],
            )
        ],
    )
    source_report = _reliability(
        results_path,
        labels_a_path,
        labels_b_path,
        adjudications_path=source_adjudications_path,
    )

    packet_labels_a = tmp_path / "packet-a.jsonl"
    packet_labels_b = tmp_path / "packet-b.jsonl"
    packet_sha256 = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    translated_a = _translate_label_file(
        labels_a_path,
        packet_labels_a,
        original_to_opaque=original_to_opaque,
        target_results_sha256=packet_sha256,
    )
    translated_b = _translate_label_file(
        labels_b_path,
        packet_labels_b,
        original_to_opaque=original_to_opaque,
        target_results_sha256=packet_sha256,
    )
    opaque_id = original_to_opaque[original_id]
    packet_adjudication = _adjudication_row(
        packet_path,
        packet_labels_a,
        packet_labels_b,
        opaque_id,
        reviewer_labels={"1": ["honest"], "2": ["protocol_violation"]},
        final_labels=["honest"],
    )
    packet_adjudications_path = tmp_path / "packet-adjudications.jsonl"
    _write_jsonl(packet_adjudications_path, [packet_adjudication])
    packet_report = _reliability(
        packet_path,
        packet_labels_a,
        packet_labels_b,
        adjudications_path=packet_adjudications_path,
        mapping_path=mapping_path,
        source_results_path=results_path,
    )

    assert len(translated_a) == len(translated_b) == len(packet_records)
    assert packet_report["inter_rater"] == source_report["inter_rater"]
    assert packet_report["auditor_vs_reference"] == source_report["auditor_vs_reference"]
    report_text = json.dumps(packet_report)
    assert all(
        record["job"]["episode_id"] not in report_text for record in source_records
    )
    assert "baseline" not in report_text
    assert "fixture-model" not in report_text
    assert packet_report["n_parse_failure"] == 1

    cli_report_path = tmp_path / "packet-report.json"
    reliability_module.main(
        [
            str(packet_path),
            str(packet_labels_a),
            str(packet_labels_b),
            "--out", str(cli_report_path),
            "--adjudications", str(packet_adjudications_path),
            "--mapping", str(mapping_path),
            "--source-results", str(results_path),
        ],
        out=io.StringIO(),
    )
    assert json.loads(cli_report_path.read_text(encoding="utf-8")) == packet_report

    bad_mapping = deepcopy(mapping)
    bad_mapping["packet_sha256"] = "0" * 64
    bad_mapping_path = tmp_path / "bad-packet-hash.json"
    bad_mapping_path.write_text(json.dumps(bad_mapping), encoding="utf-8")
    with pytest.raises(ValueError, match="packet.*SHA"):
        _reliability(
            packet_path,
            packet_labels_a,
            packet_labels_b,
            mapping_path=bad_mapping_path,
            source_results_path=results_path,
        )

    bad_mapping = deepcopy(mapping)
    bad_mapping["source_results_sha256"] = "0" * 64
    bad_mapping_path.write_text(json.dumps(bad_mapping), encoding="utf-8")
    with pytest.raises(ValueError, match="source.*SHA"):
        _reliability(
            packet_path,
            packet_labels_a,
            packet_labels_b,
            mapping_path=bad_mapping_path,
            source_results_path=results_path,
        )

    bad_mapping = deepcopy(mapping)
    bad_mapping["entries"].pop(packet_records[0]["job"]["episode_id"])
    bad_mapping_path.write_text(json.dumps(bad_mapping), encoding="utf-8")
    with pytest.raises(ValueError, match="missing packet IDs"):
        _reliability(
            packet_path,
            packet_labels_a,
            packet_labels_b,
            mapping_path=bad_mapping_path,
            source_results_path=results_path,
        )


def test_agreement_rejects_packet_input_with_guidance(tmp_path):
    _, packet_path, _, _ = _build_fixture_packet(
        tmp_path, salt=b"\x07" * 16,
    )
    labels_path = tmp_path / "labels.jsonl"
    _packet_label_pair(packet_path, labels_path, tmp_path / "other.jsonl")

    with pytest.raises(
        ValueError,
        match="packet has no auditor verdicts; use reliability with --mapping and --source-results",
    ):
        agreement_module.agreement(packet_path, labels_path)


def test_annotation_packet_clis_never_use_modal_or_network(tmp_path, monkeypatch):
    import modal
    from unittest.mock import Mock

    app = Mock(side_effect=AssertionError("Modal must not be touched by packet CLIs"))
    monkeypatch.setattr(modal, "App", app)
    monkeypatch.setattr(
        socket,
        "create_connection",
        Mock(side_effect=AssertionError("packet CLIs must not use the network")),
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    results_path = tmp_path / "results.jsonl"
    _build_results(results_path)
    packet_path, mapping_path = _packet_paths(tmp_path)
    _packet_module().main([
        str(results_path),
        "--packet", str(packet_path),
        "--mapping", str(mapping_path),
    ], out=io.StringIO())
    label_module.main(
        [
            str(packet_path),
            "--labels", str(tmp_path / "smoke-labels.jsonl"),
            "--labeller", "CLI",
        ],
        input_fn=lambda: "q",
        out=io.StringIO(),
    )
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _packet_label_pair(packet_path, labels_a_path, labels_b_path)
    reliability_module.main(
        [
            str(packet_path), str(labels_a_path), str(labels_b_path),
            "--out", str(tmp_path / "reliability.json"),
        ],
        out=io.StringIO(),
    )
    adjudicate_module.main(
        [
            str(packet_path), str(labels_a_path), str(labels_b_path),
            "--out", str(tmp_path / "adjudications.jsonl"),
            "--adjudicator", "Third Rater",
        ],
        input_fn=lambda: pytest.fail("there are no disagreements to adjudicate"),
        out=io.StringIO(),
    )
    with pytest.raises(SystemExit):
        agreement_module.main(
            [
                str(packet_path),
                str(labels_a_path),
                "--out", str(tmp_path / "agreement.json"),
            ],
            out=io.StringIO(),
        )
    app.assert_not_called()


def test_packet_label_and_adjudicate_import_without_numpy_in_subprocess():
    environment = os.environ.copy()
    environment.pop("ANTHROPIC_API_KEY", None)
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['numpy'] = None; "
            "import auditor.validation.real.packet; "
            "import auditor.validation.real.label; "
            "import auditor.validation.real.adjudicate",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
