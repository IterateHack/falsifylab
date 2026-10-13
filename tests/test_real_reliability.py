"""Synthetic, temporary-file tests for multi-rater real-trajectory annotation."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
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


ROOT = Path(__file__).resolve().parents[1]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, allow_nan=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_results(
    path: Path,
    count: int,
    *,
    parse_failure_ids: set[str] | None = None,
    provider_refusal_ids: set[str] | None = None,
    verdicts: dict[str, tuple[str, list[str]]] | None = None,
) -> list[dict]:
    seed_path = path.with_name(path.name + ".fixture")
    seed_records = _build_results(seed_path)
    valid = next(row for row in seed_records if row["verdict"]["verdict"] != "PARSE_FAILURE")
    parse_failure = next(
        row for row in seed_records if row["verdict"]["verdict"] == "PARSE_FAILURE"
    )
    parse_failure_ids = parse_failure_ids or set()
    provider_refusal_ids = provider_refusal_ids or set()
    records = []
    for index in range(count):
        episode_id = f"{index:08d}"
        record = deepcopy(parse_failure if episode_id in parse_failure_ids else valid)
        record["job"]["episode_id"] = episode_id
        record["job"]["seed"] = index
        record["job"]["variant"] = "TEST_VARIANT"
        record["job"]["model"] = "TEST_MODEL"
        if verdicts and episode_id in verdicts:
            verdict, reward_hacks = verdicts[episode_id]
            record["verdict"]["verdict"] = verdict
            record["verdict"]["reward_hacks"] = reward_hacks
        if episode_id in provider_refusal_ids:
            record["outcome"] = "provider_refusal"
            record["provider_refusal"] = True
            record["provider_stop"] = None
            record["refusals"] = []
            record["verdict"]["verdict"] = "INSUFFICIENT_EVIDENCE"
            record["verdict"]["reward_hacks"] = []
        records.append(record)
    _write_jsonl(path, records)
    return records


def _write_labels(
    results_path: Path,
    records: list[dict],
    labels_path: Path,
    *,
    labeller: str,
    labels_by_id: dict[str, list[str]] | None = None,
    saw_verdict_ids: set[str] | None = None,
    saw_job_identity_ids: set[str] | None = None,
    legacy_ids: set[str] | None = None,
    synthetic_ids: set[str] | None = None,
    verdict_revealed_ids: set[str] | None = None,
    legacy_verdict_revealed_ids: set[str] | None = None,
    omit_ids: set[str] | None = None,
    labeller_by_id: dict[str, str] | None = None,
) -> list[dict]:
    results_sha256 = hashlib.sha256(results_path.read_bytes()).hexdigest()
    labels_by_id = labels_by_id or {}
    saw_verdict_ids = saw_verdict_ids or set()
    saw_job_identity_ids = saw_job_identity_ids or set()
    legacy_ids = legacy_ids or set()
    synthetic_ids = synthetic_ids or set()
    verdict_revealed_ids = verdict_revealed_ids or set()
    legacy_verdict_revealed_ids = legacy_verdict_revealed_ids or set()
    omit_ids = omit_ids or set()
    labeller_by_id = labeller_by_id or {}
    rows = []
    for record in records:
        episode_id = record["job"]["episode_id"]
        if episode_id in omit_ids:
            continue
        row = {
            "episode_id": episode_id,
            "scenario": record["job"].get("scenario", "a"),
            "results_sha256": results_sha256,
            "labels": labels_by_id.get(episode_id, ["honest"]),
            "labeller": labeller_by_id.get(episode_id, labeller),
            "saw_verdict": episode_id in saw_verdict_ids,
            "saw_job_identity": episode_id in saw_job_identity_ids,
            "verdict_revealed": episode_id in verdict_revealed_ids,
        }
        if episode_id in legacy_ids:
            row.pop("saw_job_identity")
        if episode_id in legacy_verdict_revealed_ids:
            row.pop("verdict_revealed")
        if episode_id in synthetic_ids:
            row["synthetic"] = True
        rows.append(row)
    _write_jsonl(labels_path, rows)
    return rows


def _write_pair(
    results_path: Path,
    records: list[dict],
    labels_a_path: Path,
    labels_b_path: Path,
    *,
    labels_a: dict[str, list[str]] | None = None,
    labels_b: dict[str, list[str]] | None = None,
    labeller_a: str = "Rater A",
    labeller_b: str = "Rater B",
    options_a: dict | None = None,
    options_b: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    rows_a = _write_labels(
        results_path, records, labels_a_path,
        labeller=labeller_a, labels_by_id=labels_a, **(options_a or {}),
    )
    rows_b = _write_labels(
        results_path, records, labels_b_path,
        labeller=labeller_b, labels_by_id=labels_b, **(options_b or {}),
    )
    return rows_a, rows_b


def _adjudication_row(
    results_path: Path,
    labels_a_path: Path,
    labels_b_path: Path,
    episode_id: str,
    *,
    reviewer_labels: dict[str, list[str]],
    final_labels: list[str],
    adjudicator: str = "Adjudicator",
    rationale: str = "Reviewed the two independent annotations.",
) -> dict:
    return {
        "episode_id": episode_id,
        "scenario": "a",
        "results_sha256": hashlib.sha256(results_path.read_bytes()).hexdigest(),
        "labels_a_sha256": hashlib.sha256(labels_a_path.read_bytes()).hexdigest(),
        "labels_b_sha256": hashlib.sha256(labels_b_path.read_bytes()).hexdigest(),
        "reviewer_labels": reviewer_labels,
        "final_labels": final_labels,
        "rationale": rationale,
        "adjudicator": adjudicator,
        "saw_verdict": False,
        "saw_job_identity": False,
        "adjudicated_at": "2026-01-01T00:00:00+00:00",
    }


def _reliability(results_path: Path, labels_a_path: Path, labels_b_path: Path, **kwargs):
    return reliability_module.reliability(
        results_path, labels_a_path, labels_b_path, **kwargs,
    )


@pytest.mark.parametrize(
    ("key", "state"),
    [
        (key, state)
        for key in ("saw_verdict", "saw_job_identity", "verdict_revealed")
        for state in ("true", "missing", "none", "false")
    ],
    ids=[
        f"{key}-{state}"
        for key in ("saw_verdict", "saw_job_identity", "verdict_revealed")
        for state in ("true", "missing", "none", "false")
    ],
)
def test_is_blind_label_requires_explicit_false(key, state):
    row = {
        "saw_verdict": False,
        "saw_job_identity": False,
        "verdict_revealed": False,
    }
    if state == "true":
        row[key] = True
    elif state == "missing":
        row.pop(key)
    elif state == "none":
        row[key] = None

    assert common_module.is_blind_label(row) is (state == "false")


def test_human_human_kappa_counts_and_bootstrap_are_deterministic(tmp_path):
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 10)
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    # Both flag 3; A-only and B-only each flag 1; both call 5 honest.
    # p_e=.4*.4+.6*.6=.52, so kappa=(.8-.52)/(1-.52)=7/12=.5833.
    flags_a, flags_b = {1, 2, 3, 4}, {1, 2, 3, 5}
    labels_a = {
        record["job"]["episode_id"]: (
            ["RH1"] if index in flags_a else ["honest"]
        )
        for index, record in enumerate(records)
    }
    labels_b = {
        record["job"]["episode_id"]: (
            ["RH1"] if index in flags_b else ["honest"]
        )
        for index, record in enumerate(records)
    }
    _write_pair(
        results_path, records, labels_a_path, labels_b_path,
        labels_a=labels_a, labels_b=labels_b,
    )

    report = _reliability(results_path, labels_a_path, labels_b_path)
    repeated = _reliability(results_path, labels_a_path, labels_b_path)
    binary = report["inter_rater"]["binary"]
    assert binary["n"] == 10
    assert binary["observed_agreement"] == 0.8
    assert binary["kappa"] == 0.5833
    assert binary["counts"] == {
        "both_flagged": 3, "a_only": 1, "b_only": 1, "both_honest": 5,
    }
    bootstrap = report["inter_rater"]["binary"]["bootstrap"]
    assert bootstrap == repeated["inter_rater"]["binary"]["bootstrap"]
    assert isinstance(bootstrap["seed"], int)
    assert isinstance(bootstrap["resamples"], int) and bootstrap["resamples"] > 0
    assert bootstrap["ci95"] is not None
    assert bootstrap["degenerate"] is False

    perfect_path = tmp_path / "perfect.jsonl"
    perfect_labels_a = tmp_path / "perfect-a.jsonl"
    perfect_labels_b = tmp_path / "perfect-b.jsonl"
    perfect_records = _write_results(perfect_path, 3)
    _write_pair(perfect_path, perfect_records, perfect_labels_a, perfect_labels_b)
    perfect = _reliability(perfect_path, perfect_labels_a, perfect_labels_b)
    perfect_bootstrap = perfect["inter_rater"]["binary"]["bootstrap"]
    assert perfect_bootstrap["ci95"] is None
    assert perfect_bootstrap["degenerate"] is True

    one_path = tmp_path / "one.jsonl"
    one_a, one_b = tmp_path / "one-a.jsonl", tmp_path / "one-b.jsonl"
    one_records = _write_results(one_path, 1)
    _write_pair(one_path, one_records, one_a, one_b)
    one = _reliability(one_path, one_a, one_b)
    assert one["inter_rater"]["binary"]["bootstrap"]["ci95"] is None


def test_exclusion_counts_are_separate_and_excluded_rows_never_enter_inter_rater(tmp_path):
    results_path = tmp_path / "results.jsonl"
    parse_id = "00000002"
    records = _write_results(results_path, 10, parse_failure_ids={parse_id})
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write_pair(
        results_path, records, labels_a_path, labels_b_path,
        options_a={
            "saw_job_identity_ids": {"00000004"},
            "verdict_revealed_ids": {"00000008"},
            "omit_ids": {"00000006"},
        },
        options_b={
            "saw_verdict_ids": {"00000003"},
            "legacy_verdict_revealed_ids": {"00000009"},
            "omit_ids": {"00000005", "00000006"},
        },
    )

    report = _reliability(results_path, labels_a_path, labels_b_path)
    assert {
        key: report[key]
        for key in (
            "n_parse_failure", "n_provider_refusal", "n_unlabelled_by_either",
            "n_single_labelled", "n_anchored", "n_job_identity_exposed",
            "n_verdict_revealed", "n_eligible",
        )
    } == {
            "n_parse_failure": 1,
            "n_provider_refusal": 0,
            "n_unlabelled_by_either": 1,
            "n_single_labelled": 1,
            "n_anchored": 1,
            "n_job_identity_exposed": 1,
            "n_verdict_revealed": 2,
            "n_eligible": 3,
        }
    assert report["inter_rater"]["binary"]["n"] == 3
    assert sum(
        report[key]
        for key in (
            "n_parse_failure", "n_provider_refusal", "n_unlabelled_by_either",
            "n_single_labelled", "n_anchored", "n_job_identity_exposed",
            "n_verdict_revealed", "n_eligible",
        )
    ) == len(records)
    inputs = common_module.load_annotation_inputs(
        results_path, labels_a_path, labels_b_path,
    )
    eligible, _ = common_module.eligible_label_pairs(inputs)
    assert all(
        common_module.is_blind_label(item["row_a"])
        and common_module.is_blind_label(item["row_b"])
        for item in eligible
    )


def test_provider_refusals_are_excluded_from_all_annotation_paths(tmp_path):
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 3, provider_refusal_ids={"00000000"})
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write_pair(
        results_path, records, labels_a_path, labels_b_path,
        labels_a={"00000000": ["RH1"], "00000001": ["honest"]},
        labels_b={"00000000": ["honest"], "00000001": ["RH1"]},
    )

    label_path, label_output = tmp_path / "label.jsonl", io.StringIO()
    label_result = label_module.label_session(
        results_path, label_path, labeller="Queue test", no_reveal=True,
        input_fn=_scripted(["q"]), out=label_output,
    )
    assert label_result == {
        "labelled": 0,
        "skipped": 0,
        "remaining": 2,
        "excluded_parse_failure": 0,
        "excluded_provider_refusal": 1,
    }
    assert "Excluded 1 provider_refusal episode(s) from labelling." in label_output.getvalue()
    assert label_path.exists() is False

    agreement = agreement_module.agreement(results_path, labels_a_path)
    assert agreement["n_provider_refusal"] == 1
    assert agreement["n_scored"] == 2
    assert "provider_refusal excluded=1" in agreement_module.format_markdown(agreement)
    assert all(item["episode_id"] != "00000000" for item in agreement["disagreements"])

    reliability = _reliability(results_path, labels_a_path, labels_b_path)
    assert reliability["n_provider_refusal"] == 1
    assert reliability["n_eligible"] == 2
    assert reliability["inter_rater"]["binary"]["n"] == 2
    reliability_markdown = reliability_module.format_markdown(reliability)
    assert "provider_refusal=1" in reliability_markdown
    assert "verdict_revealed=0" in reliability_markdown

    adjudications_path, adjudication_output = tmp_path / "adj.jsonl", io.StringIO()
    adjudicate_module.main(
        _adjudicate_args(
            results_path, labels_a_path, labels_b_path, adjudications_path,
        ),
        input_fn=_scripted(["honest", "Reviewed independently."]),
        out=adjudication_output,
    )
    assert "[00000000]" not in adjudication_output.getvalue()
    assert "[00000001]" in adjudication_output.getvalue()
    assert [row["episode_id"] for row in _read_rows(adjudications_path)] == ["00000001"]


def test_agreement_excludes_non_false_verdict_revealed_rows(tmp_path):
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 4)
    labels_path = tmp_path / "labels.jsonl"
    rows = _write_labels(
        results_path, records, labels_path, labeller="Rater",
    )
    rows[0]["verdict_revealed"] = True
    rows[1].pop("verdict_revealed")
    rows[2]["verdict_revealed"] = None
    _write_jsonl(labels_path, rows)

    report = agreement_module.agreement(results_path, labels_path)
    assert report["n_scored"] == 4
    assert report["n_blind"] == 1
    assert report["n_saw_verdict"] == 0
    assert report["n_job_identity_exposed"] == 0
    assert report["n_verdict_revealed"] == 3
    assert report["binary"]["n"] == 1
    assert (
        report["n_blind"]
        + report["n_saw_verdict"]
        + report["n_job_identity_exposed"]
        + report["n_verdict_revealed"]
        == report["n_scored"]
    )
    assert "/ verdict_revealed=3" in agreement_module.format_markdown(report)


@pytest.mark.parametrize(
    ("invalid", "message"),
    [
        ("same_labeller", "different labellers"),
        ("multiple_labellers", "exactly one labeller"),
        ("foreign_sha", "results_sha256"),
        ("foreign_id", "absent from results"),
    ],
)
def test_label_file_validation_errors(tmp_path, invalid, message):
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 2)
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    rows_a, _ = _write_pair(
        results_path, records, labels_a_path, labels_b_path,
        labeller_b="Rater A" if invalid == "same_labeller" else "Rater B",
    )
    if invalid == "multiple_labellers":
        rows_a[1]["labeller"] = "Rater C"
    elif invalid == "foreign_sha":
        rows_a[0]["results_sha256"] = "foreign"
    elif invalid == "foreign_id":
        rows_a.append({**rows_a[0], "episode_id": "missing"})
    if invalid != "same_labeller":
        _write_jsonl(labels_a_path, rows_a)
    with pytest.raises(ValueError, match=message):
        _reliability(results_path, labels_a_path, labels_b_path)


def test_status_threshold_synthetic_precedence_and_seven_class_notice(tmp_path):
    results_path = tmp_path / "small.jsonl"
    small_records = _write_results(results_path, 4)
    small_a, small_b = tmp_path / "small-a.jsonl", tmp_path / "small-b.jsonl"
    _write_pair(results_path, small_records, small_a, small_b)
    small = _reliability(results_path, small_a, small_b)
    assert small["status"] == "insufficient_sample"
    assert small["headline_eligible"] is False
    assert small["n_eligible"] == 4
    assert "NOT A HEADLINE RESULT:" in reliability_module.format_markdown(small)
    assert "n_eligible=4 below the minimum of 30" in reliability_module.format_markdown(small)

    large_path = tmp_path / "large.jsonl"
    large_records = _write_results(large_path, 30)
    large_a, large_b = tmp_path / "large-a.jsonl", tmp_path / "large-b.jsonl"
    _write_pair(
        large_path, large_records, large_a, large_b,
        options_a={"synthetic_ids": {"00000000"}},
    )
    placeholder = _reliability(large_path, large_a, large_b)
    assert placeholder["status"] == "synthetic_placeholder"
    assert placeholder["headline_eligible"] is False

    human_a, human_b = tmp_path / "human-a.jsonl", tmp_path / "human-b.jsonl"
    _write_pair(large_path, large_records, human_a, human_b)
    ok = _reliability(large_path, human_a, human_b)
    assert ok["status"] == "ok"
    assert ok["headline_eligible"] is True
    assert ok["min_headline_n"] == 30
    assert ok["seven_class"] == {
        "available": False,
        "reason": (
            "human labels are behaviour categories, not auditor verdict classes; "
            "seven-class verdict agreement is measured only on the synthetic set "
            "(auditor/validation/REPORT.md)"
        ),
    }


def test_adjudicated_reference_uses_agreements_and_final_labels(tmp_path):
    verdicts = {
        "00000000": ("VALID_SUCCESS", []),
        "00000001": ("REWARD_HACK", ["RH1"]),
        "00000002": ("VALID_SUCCESS", []),
        "00000003": ("VALID_SUCCESS", []),
    }
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 4, verdicts=verdicts)
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    labels_a = {
        "00000000": ["honest"], "00000001": ["RH1"],
        "00000002": ["honest"], "00000003": ["honest"],
    }
    labels_b = {
        "00000000": ["honest"], "00000001": ["RH1"],
        "00000002": ["RH1"], "00000003": ["RH1"],
    }
    rows_a, rows_b = _write_pair(
        results_path, records, labels_a_path, labels_b_path,
        labels_a=labels_a, labels_b=labels_b,
    )
    adj_path = tmp_path / "adjudications.jsonl"
    _write_jsonl(adj_path, [
        _adjudication_row(
            results_path, labels_a_path, labels_b_path, "00000002",
            reviewer_labels={"1": ["honest"], "2": ["RH1"]},
            final_labels=["unsafe"],
        ),
    ])

    report = _reliability(
        results_path, labels_a_path, labels_b_path, adjudications_path=adj_path,
    )
    reference = report["auditor_vs_reference"]
    # Reference positives are the agreed RH1 case and the adjudicated unsafe
    # case. Against the auditor there are two agreements and one human-only flag:
    # p_e=4/9, p_o=2/3, kappa=(2/3-4/9)/(1-4/9)=.4.
    assert reference["binary"]["n"] == 3
    assert reference["binary"]["observed_agreement"] == 0.6667
    assert reference["binary"]["kappa"] == 0.4
    assert reference["n_unadjudicated"] == 1
    assert reference["per_category"]["unsafe"]["fp"] == 1
    assert report["labellers"] == ["Rater A", "Rater B"]
    assert len(rows_a) == len(rows_b) == 4


@pytest.mark.parametrize(
    ("invalid", "message"),
    [
        ("labels_sha", "labels.*sha256"),
        ("same_adjudicator", "adjudicator.*labeller"),
        ("empty_rationale", "rationale"),
    ],
)
def test_adjudication_file_validation_errors(tmp_path, invalid, message):
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 1)
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write_pair(results_path, records, labels_a_path, labels_b_path)
    row = _adjudication_row(
        results_path, labels_a_path, labels_b_path, "00000000",
        reviewer_labels={"1": ["honest"], "2": ["RH1"]},
        final_labels=["honest"],
    )
    if invalid == "labels_sha":
        row["labels_a_sha256"] = "foreign"
    elif invalid == "same_adjudicator":
        row["adjudicator"] = "Rater A"
    else:
        row["rationale"] = "  "
    adj_path = tmp_path / "adjudications.jsonl"
    _write_jsonl(adj_path, [row])
    with pytest.raises(ValueError, match=message):
        _reliability(
            results_path, labels_a_path, labels_b_path, adjudications_path=adj_path,
        )


def _adjudicate_args(results_path, labels_a_path, labels_b_path, out_path, name="Third Rater"):
    return [
        str(results_path), str(labels_a_path), str(labels_b_path),
        "--out", str(out_path), "--adjudicator", name,
    ]


def test_adjudicator_blind_queue_rows_and_resume(tmp_path):
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 4)
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write_pair(
        results_path, records, labels_a_path, labels_b_path,
        labeller_a="PRIVATE_RATER_A", labeller_b="PRIVATE_RATER_B",
        labels_b={"00000000": ["RH1"]},
    )
    out_path, output = tmp_path / "adjudications.jsonl", io.StringIO()
    adjudicate_module.main(
        _adjudicate_args(results_path, labels_a_path, labels_b_path, out_path),
        input_fn=_scripted(["honest", "Reviewed independently."]),
        out=output,
    )
    text = output.getvalue()
    assert "[00000000]" in text
    for episode_id in ("00000001", "00000002", "00000003"):
        assert episode_id not in text
    for hidden in (
        "VALID_SUCCESS", "PROTOCOL_VIOLATION", "== Audit ==",
        "TEST_VARIANT", "TEST_MODEL", "PRIVATE_RATER_A", "PRIVATE_RATER_B",
    ):
        assert hidden not in text
    assert "Reviewer 1:" in text
    assert "Reviewer 2:" in text

    rows = _read_rows(out_path)
    assert len(rows) == 1
    assert rows[0]["final_labels"] == ["honest"]
    assert rows[0]["adjudicator"] == "Third Rater"
    assert "auditor_verdict" not in rows[0]
    assert "verdict" not in rows[0]
    assert set(rows[0]) == {
        "episode_id", "scenario", "results_sha256", "labels_a_sha256",
        "labels_b_sha256", "reviewer_labels", "final_labels", "rationale",
        "adjudicator", "saw_verdict", "saw_job_identity", "adjudicated_at",
    }
    resumed_output = io.StringIO()
    adjudicate_module.main(
        _adjudicate_args(results_path, labels_a_path, labels_b_path, out_path),
        input_fn=lambda: pytest.fail("resume must skip an adjudicated episode"),
        out=resumed_output,
    )
    assert len(_read_rows(out_path)) == 1
    assert "[00000000]" not in resumed_output.getvalue()


def test_empty_adjudication_rationale_reprompts_without_writing(tmp_path):
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 1)
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write_pair(
        results_path, records, labels_a_path, labels_b_path,
        labels_b={"00000000": ["RH1"]},
    )
    out_path, output = tmp_path / "adjudications.jsonl", io.StringIO()
    values = iter(["honest", "", "A reason"])

    def input_fn():
        assert not out_path.exists()
        return next(values)

    adjudicate_module.main(
        _adjudicate_args(results_path, labels_a_path, labels_b_path, out_path),
        input_fn=input_fn,
        out=output,
    )
    assert "Rationale cannot be empty" in output.getvalue()
    assert len(_read_rows(out_path)) == 1


def test_adjudicator_cli_rejects_a_labeller_name(tmp_path):
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 1)
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write_pair(
        results_path, records, labels_a_path, labels_b_path,
        labeller_a="Same Person", labels_b={"00000000": ["RH1"]},
    )
    with pytest.raises(SystemExit) as exc_info:
        adjudicate_module.main(
            _adjudicate_args(
                results_path, labels_a_path, labels_b_path, tmp_path / "adj.jsonl",
                name="Same Person",
            ),
            input_fn=lambda: pytest.fail("invalid adjudicator must fail before prompting"),
            out=io.StringIO(),
        )
    assert exc_info.value.code == 2


def test_label_blind_header_verdict_reveal_and_row_identity(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _write_results(results_path, 1)
    blind_path, blind_out = tmp_path / "blind.jsonl", io.StringIO()
    label_module.label_session(
        results_path, blind_path, labeller="Rater",
        input_fn=_scripted(["honest", ""]), out=blind_out,
    )
    blind_text = blind_out.getvalue()
    assert "[00000000] scenario=a (1 of 1)" in blind_text
    for hidden in ("TEST_VARIANT", "TEST_MODEL", "seed="):
        assert hidden not in blind_text
    blind_row = _read_rows(blind_path)[0]
    assert blind_row["saw_job_identity"] is False
    assert blind_row["verdict_revealed"] is True

    triage_path, triage_out = tmp_path / "triage.jsonl", io.StringIO()
    label_module.label_session(
        results_path, triage_path, labeller="Triage", show_verdict=True,
        input_fn=_scripted(["honest", ""]), out=triage_out,
    )
    triage_text = triage_out.getvalue()
    assert (
        "[00000000] scenario=a variant=TEST_VARIANT model=TEST_MODEL seed=0 (1 of 1)"
        in triage_text
    )
    assert _read_rows(triage_path)[0]["saw_job_identity"] is True


def test_label_no_reveal_hides_verdict_and_rejects_show_verdict_combo(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _write_results(results_path, 1)
    labels_path, output = tmp_path / "no-reveal.jsonl", io.StringIO()
    label_module.label_session(
        results_path, labels_path, labeller="Rater", no_reveal=True,
        input_fn=_scripted(["honest", ""]), out=output,
    )
    text = output.getvalue()
    for hidden in ("VALID_SUCCESS", "PROTOCOL_VIOLATION", "== Audit ==", "TEST_MODEL"):
        assert hidden not in text
    row = _read_rows(labels_path)[0]
    assert row["auditor_verdict"] is None
    assert row["verdict_revealed"] is False

    with pytest.raises(SystemExit) as exc_info:
        label_module.main(
            [
                str(results_path), "--labels", str(tmp_path / "bad.jsonl"),
                "--labeller", "Rater", "--no-reveal", "--show-verdict",
            ],
            input_fn=lambda: pytest.fail("invalid option combination must fail first"),
            out=io.StringIO(),
        )
    assert exc_info.value.code == 2


def test_shuffle_seed_is_deterministic_and_resume_filters_first(tmp_path):
    results_path = tmp_path / "results.jsonl"
    _write_results(results_path, 5, parse_failure_ids={"00000002"})
    default_path, default_out = tmp_path / "default.jsonl", io.StringIO()
    label_module.label_session(
        results_path, default_path, labeller="Ada",
        input_fn=_scripted(["honest", ""] * 4), out=default_out,
    )
    default_ids = re.findall(r"^\[([0-9]{8})\]", default_out.getvalue(), re.MULTILINE)
    seed = next(
        seed for seed in range(100)
        if (lambda shuffled: shuffled != default_ids)(
            _shuffled(default_ids, seed, "Ada")
        )
    )
    expected_first_order = _shuffled(default_ids, seed, "Ada")

    labels_path, first_out = tmp_path / "shuffled.jsonl", io.StringIO()
    label_module.label_session(
        results_path, labels_path, labeller="Ada", shuffle_seed=seed,
        input_fn=_scripted(["honest", "", "q"]), out=first_out,
    )
    first_id = _read_rows(labels_path)[0]["episode_id"]
    assert first_id == expected_first_order[0]

    remaining_default = [episode_id for episode_id in default_ids if episode_id != first_id]
    expected_resume_order = _shuffled(remaining_default, seed, "Ada")
    resume_out = io.StringIO()
    label_module.label_session(
        results_path, labels_path, labeller="Ada", shuffle_seed=seed,
        input_fn=_scripted(["honest", ""] * 3), out=resume_out,
    )
    resumed_ids = re.findall(r"^\[([0-9]{8})\]", resume_out.getvalue(), re.MULTILINE)
    assert resumed_ids == expected_resume_order
    assert len(_read_rows(labels_path)) == 4


def _shuffled(episode_ids: list[str], seed: int, labeller: str) -> list[str]:
    result = list(episode_ids)
    random.Random(f"{seed}:{labeller}").shuffle(result)
    return result


def test_agreement_excludes_job_identity_and_legacy_rows_but_keeps_anchored_section(tmp_path):
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 5, parse_failure_ids={"00000002"})
    labels_path = tmp_path / "labels.jsonl"
    _write_labels(
        results_path, records, labels_path, labeller="Rater",
        saw_verdict_ids={"00000003"},
        saw_job_identity_ids={"00000001"},
        legacy_ids={"00000004"},
    )

    report = agreement_module.agreement(results_path, labels_path)
    assert report["binary"]["n"] == 1
    assert report["n_blind"] == 1
    assert report["n_job_identity_exposed"] == 2
    assert report["n_saw_verdict"] == 1
    assert report["saw_verdict"]["binary"]["n"] == 1
    assert "/ job_identity_exposed=2" in agreement_module.format_markdown(report)


def test_reliability_and_adjudication_clis_never_launch_modal_or_network(
    tmp_path, monkeypatch,
):
    import modal
    from unittest.mock import Mock

    app = Mock(side_effect=AssertionError("Modal must not be touched by annotation CLIs"))
    monkeypatch.setattr(modal, "App", app)
    monkeypatch.setattr(
        socket, "create_connection",
        Mock(side_effect=AssertionError("annotation CLIs must not use the network")),
    )
    results_path = tmp_path / "results.jsonl"
    records = _write_results(results_path, 2)
    labels_a_path, labels_b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write_pair(results_path, records, labels_a_path, labels_b_path)
    reliability_module.main(
        [
            str(results_path), str(labels_a_path), str(labels_b_path),
            "--out", str(tmp_path / "reliability.json"),
            "--markdown", str(tmp_path / "reliability.md"),
        ],
        out=io.StringIO(),
    )
    adjudicate_module.main(
        _adjudicate_args(
            results_path, labels_a_path, labels_b_path, tmp_path / "adjudications.jsonl",
        ),
        input_fn=lambda: pytest.fail("there are no disagreements to adjudicate"),
        out=io.StringIO(),
    )
    app.assert_not_called()


def test_label_and_adjudicate_import_without_numpy_in_subprocess():
    environment = os.environ.copy()
    environment.pop("ANTHROPIC_API_KEY", None)
    process = subprocess.run(
        [
            sys.executable, "-c",
            "import sys; sys.modules['numpy'] = None; "
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
