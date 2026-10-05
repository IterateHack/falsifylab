import json

import pytest

from metrics import PARSE_FAILURE_VERDICT
from reports import slide_assets
from reports.replicates import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    OUTCOME_CATEGORIES,
    classify,
    replicate_rows,
    science_records,
)
from runner import modal_batch


def _record(
    seed=0,
    *,
    model="model-a",
    scenario="a",
    variant="baseline",
    repeat=0,
    verdict="VALID_SUCCESS",
    clean=True,
    cost=2.0,
    provider_refusal=False,
    aborted_on_refusals=False,
    spend_cap_stop=False,
    outcome=None,
    harness_error=None,
):
    return {
        "job": {
            "model": model,
            "scenario": scenario,
            "variant": variant,
            "seed": seed,
            "repeat": repeat,
        },
        "verdict": {"verdict": verdict},
        "provider_refusal": provider_refusal,
        "aborted_on_refusals": aborted_on_refusals,
        "spend_cap_stop": spend_cap_stop,
        "outcome": outcome,
        "harness_error": harness_error,
        "metrics": {"clean_success": clean, "cost": cost},
    }


def _row(records):
    rows, excluded = replicate_rows(records)
    assert excluded == []
    assert len(rows) == 1
    return rows[0]


def test_classify_all_categories_and_priority():
    assert OUTCOME_CATEGORIES == (
        "provider_refusal", "spend_cap_stop", "refusal_abort", "harness_error",
        "parse_failure", "science",
    )
    assert classify(_record()) == "science"
    assert classify({"verdict": {"verdict": "VALID_SUCCESS"}}) == "science"
    assert classify(_record(provider_refusal=True)) == "provider_refusal"
    assert classify(_record(spend_cap_stop=True)) == "spend_cap_stop"
    assert classify(_record(outcome="spend_cap_stop")) == "spend_cap_stop"
    assert classify(_record(aborted_on_refusals=True)) == "refusal_abort"
    assert classify(_record(
        verdict=modal_batch.HARNESS_ERROR_VERDICT,
        harness_error={"message": "Episode 4 did not conclude within 40 turns"},
    )) == "harness_error"
    assert classify(_record(
        verdict=modal_batch.HARNESS_ERROR_VERDICT,
        harness_error={"message": "unexpected failure"},
    )) == "harness_error"
    assert classify(_record(verdict=PARSE_FAILURE_VERDICT)) == "parse_failure"
    assert classify(_record(
        provider_refusal=True,
        spend_cap_stop=True,
    )) == "provider_refusal"
    assert classify(_record(
        spend_cap_stop=True,
        aborted_on_refusals=True,
    )) == "spend_cap_stop"


def test_classify_reads_captured_provider_stop_and_accepts_records_without_it():
    refused = _record()
    refused["provider_stop"] = {"stop_reason": "refusal", "stop_details": None}
    assert classify(refused) == "provider_refusal"
    completed = _record()
    completed["provider_stop"] = {"stop_reason": "end_turn", "stop_details": None}
    assert classify(completed) == "science"
    wave1_refusal = _record(provider_refusal=True)
    assert "provider_stop" not in wave1_refusal
    assert classify(wave1_refusal) == "provider_refusal"


def test_science_records_preserve_order_and_exclude_each_non_science_category():
    records = [
        _record(seed=0),
        _record(seed=1, provider_refusal=True),
        _record(seed=2, spend_cap_stop=True),
        _record(seed=3, aborted_on_refusals=True),
        _record(seed=4, verdict=modal_batch.HARNESS_ERROR_VERDICT),
        _record(seed=5, verdict=PARSE_FAILURE_VERDICT),
        _record(seed=6),
    ]
    assert science_records(records) == [records[0], records[-1]]


def test_excluded_outcomes_change_rates_not_science_metrics():
    science = [
        _record(seed=0, clean=True, cost=2.0),
        _record(seed=1, clean=False, cost=4.0),
    ]
    excluded = [
        _record(seed=2, provider_refusal=True),
        _record(seed=3, aborted_on_refusals=True),
        _record(
            seed=4,
            verdict=modal_batch.HARNESS_ERROR_VERDICT,
            harness_error={"message": "did not conclude within 1 turns"},
        ),
        _record(
            seed=5,
            verdict=modal_batch.HARNESS_ERROR_VERDICT,
            harness_error={"message": "other harness failure"},
        ),
        _record(seed=6, verdict=PARSE_FAILURE_VERDICT),
        _record(seed=7, spend_cap_stop=True),
    ]
    science_row = _row(science)
    pooled_row = _row(science + excluded)
    assert pooled_row["n_runs"] == 8
    assert pooled_row["n"] == science_row["n"] == 2
    assert pooled_row["n_provider_refusal"] == 1
    assert pooled_row["n_refusal_abort"] == 1
    assert pooled_row["n_spend_cap_stop"] == 1
    assert pooled_row["n_harness_error"] == 2
    assert pooled_row["n_parse_failure"] == 1
    assert pooled_row["provider_refusal_rate"] == pytest.approx(1 / 8)
    assert pooled_row["refusal_abort_rate"] == pytest.approx(1 / 8)
    assert pooled_row["refusal_rate"] == pytest.approx(2 / 8)
    assert pooled_row["spend_cap_stop_rate"] == pytest.approx(1 / 8)
    for field in ("clean_success_mean", "mean_cost", "cost_of_pass"):
        assert pooled_row[field] == science_row[field]


def test_replicate_science_metrics_exclude_aborts_and_spend_cap_stops():
    records = [
        _record(seed=0, verdict="VALID_SUCCESS", clean=True, cost=2.0),
        _record(seed=1, verdict="WRONG_CONCLUSION", clean=False, cost=4.0),
        _record(
            seed=2,
            verdict="VALID_SUCCESS",
            clean=True,
            cost=100.0,
            aborted_on_refusals=True,
        ),
        {
            **_record(seed=3, spend_cap_stop=True),
            "metrics": None,
        },
    ]
    row = _row(records)
    assert row["n_runs"] == 4
    assert row["n"] == 2
    assert row["clean_success_mean"] == 0.5
    assert row["mean_cost"] == 3.0
    assert row["n_refusal_abort"] == 1
    assert row["n_spend_cap_stop"] == 1


def test_bootstrap_is_deterministic_order_independent_and_contains_point():
    records = [
        _record(seed=i, clean=i < 10, cost=2.0 + i / 10)
        for i in range(20)
    ]
    first = _row(records)
    assert _row(records) == first
    assert _row(list(reversed(records))) == first
    low, high = first["clean_success_ci95"]
    assert low <= first["clean_success_mean"] <= high
    assert 0.25 < low < 0.5 < high < 0.75
    cost_low, cost_high = first["cost_of_pass_ci95"]
    assert cost_low <= first["cost_of_pass"] <= cost_high
    assert first["bootstrap_resamples"] == BOOTSTRAP_RESAMPLES == 10000
    assert first["bootstrap_seed"] == BOOTSTRAP_SEED == 0


def test_singleton_and_no_science_have_null_intervals_and_means():
    singleton = _row([_record()])
    assert singleton["clean_success_mean"] == 1.0
    assert singleton["mean_cost"] == 2.0
    assert singleton["clean_success_ci95"] is None
    assert singleton["cost_of_pass_ci95"] is None
    assert singleton["cost_of_pass_unbounded_share"] is None

    no_science = _row([_record(verdict=PARSE_FAILURE_VERDICT)])
    assert no_science["n"] == 0
    assert no_science["clean_success_mean"] is None
    assert no_science["mean_cost"] is None
    assert no_science["cost_of_pass"] is None
    assert no_science["clean_success_ci95"] is None
    assert no_science["cost_of_pass_ci95"] is None


def test_zero_success_and_unbounded_bootstrap_resamples():
    zero_success = _row([
        _record(seed=i, clean=False, cost=2.0 + i)
        for i in range(3)
    ])
    assert zero_success["cost_of_pass"] is None
    assert zero_success["cost_of_pass_unbounded_share"] == 1.0
    assert zero_success["cost_of_pass_ci95"] == (None, None)

    mixed = _row([
        _record(seed=0, clean=True, cost=2.0),
        _record(seed=1, clean=False, cost=4.0),
    ])
    assert mixed["cost_of_pass_unbounded_share"] > 0
    assert mixed["cost_of_pass_ci95"][1] is None


@pytest.mark.parametrize("clean", [False, True])
def test_boundary_success_counts_have_degenerate_null_bootstrap_interval(clean):
    row = _row([_record(seed=i, clean=clean, cost=2.0 + i) for i in range(10)])
    assert row["n"] == 10
    assert row["clean_success_mean"] == float(clean)
    assert row["clean_success_ci95"] is None
    assert row["clean_success_ci95_degenerate"] is True
    if clean:
        low, high = row["cost_of_pass_ci95"]
        assert low < high


def test_interior_success_count_keeps_bootstrap_interval():
    row = _row([_record(seed=i, clean=i < 3) for i in range(10)])
    assert row["clean_success_ci95_degenerate"] is False
    low, high = row["clean_success_ci95"]
    assert low < 0.3 < high

    assert _row([_record()])["clean_success_ci95_degenerate"] is None


def test_duplicate_keys_are_rejected_and_named():
    records = [_record(seed=7), _record(seed=7)]
    with pytest.raises(ValueError, match=r"Duplicate replicate key .*model-a.*baseline.*7"):
        replicate_rows(records)

    missing_scenario = _record(seed=8)
    del missing_scenario["job"]["scenario"]
    explicit_scenario = _record(seed=8)
    with pytest.raises(ValueError, match="Duplicate replicate key"):
        replicate_rows([missing_scenario, explicit_scenario])


def test_scripted_variants_are_excluded_and_reported():
    records = [
        _record(seed=0, variant="baseline"),
        _record(seed=0, variant=next(iter(modal_batch.SCRIPTED_VARIANTS))),
    ]
    rows, excluded = replicate_rows(records)
    assert [row["variant"] for row in rows] == ["baseline"]
    assert excluded == [records[1]["job"]["variant"]]


def test_replicate_rows_are_json_finite():
    rows = replicate_rows([
        _record(seed=0, clean=True, cost=1),
        _record(seed=1, clean=False, cost=2),
    ])[0]
    encoded = json.dumps(rows, allow_nan=False)
    decoded = json.loads(encoded)
    assert decoded[0]["bootstrap_resamples"] == BOOTSTRAP_RESAMPLES
    assert decoded[0]["clean_success_ci95"] == list(rows[0]["clean_success_ci95"])
    assert decoded[0]["cost_of_pass_ci95"] == list(rows[0]["cost_of_pass_ci95"])


def test_replicate_assets_need_only_results_jsonl_and_pool_sources(tmp_path):
    batch_dirs = [
        tmp_path / "wave-a",
        tmp_path / "wave-b",
        tmp_path / "wave-c",
    ]
    for batch_dir in batch_dirs:
        batch_dir.mkdir()
    first, second = _record(seed=0), _record(seed=1)
    third = _record(seed=0, model="model-b")
    first["code_sha"] = "sha-a"
    second["code_sha"] = "sha-b"
    third["code_sha"] = "sha-c"
    first["sampling"] = {
        "temperature": 0.5, "client": "dry-run", "max_tokens": 10,
    }
    second["sampling"] = {
        "temperature": 0.7, "client": "dry-run", "max_tokens": 10,
    }
    for batch_dir, record in zip(batch_dirs, (first, second, third)):
        (batch_dir / "results.jsonl").write_text(
            json.dumps(record) + "\n",
            encoding="utf-8",
        )

    output = tmp_path / "slides"
    assets = slide_assets.generate_replicate_assets(
        batch_dirs,
        output,
        wave=True,
        git_stamp=("report-sha", False),
    )
    summary = json.loads(
        (output / "replicates" / "replicate_summary.json").read_text(
            encoding="utf-8",
        ),
    )
    assert summary["stamp"]["wave"] is True
    assert summary["stamp"]["models"] == ["model-a", "model-b"]
    assert len(summary["stamp"]["sampling"]) == 2
    assert "sha-a" in summary["stamp"]["source"]
    assert "sha-b" in summary["stamp"]["source"]
    assert "sha-c" in summary["stamp"]["source"]
    assert str(batch_dirs[0]) in summary["stamp"]["source"]
    assert str(batch_dirs[1]) in summary["stamp"]["source"]
    assert str(batch_dirs[2]) in summary["stamp"]["source"]
    assert summary["rows"][0]["n_runs"] == 2
    assert len(assets) == 3
    assert all(
        entry["source_files"] == [
            str(batch_dir / "results.jsonl") for batch_dir in batch_dirs
        ]
        for entry in assets
    )
    markdown = (output / "replicates" / "replicate_summary.md").read_text(
        encoding="utf-8",
    )
    assert slide_assets.REPLICATE_CAPTION in markdown
    assert "spend-cap-stop" in slide_assets.REPLICATE_CAPTION
    assert "max_turns" not in slide_assets.REPLICATE_CAPTION


def test_replicate_summary_caption_explains_degenerate_interval(tmp_path):
    batch_dir = tmp_path / "wave"
    batch_dir.mkdir()
    (batch_dir / "results.jsonl").write_text(
        "".join(json.dumps(_record(seed=i, clean=False)) + "\n" for i in range(3)),
        encoding="utf-8",
    )
    slide_assets.generate_replicate_assets(
        [batch_dir], tmp_path / "slides", git_stamp=("abc1234", False),
    )
    markdown = (tmp_path / "slides" / "replicates" / "replicate_summary.md").read_text(
        encoding="utf-8",
    )
    assert "clean_success_ci95_degenerate true, when a cell has 0 or n clean successes" in markdown
    assert "collapses to a point" in markdown
