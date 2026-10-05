"""Replicate-aware data summaries for pooled batch results."""

from __future__ import annotations

import math
import zlib
from collections import defaultdict
from statistics import fmean

import numpy as np

from metrics import is_parse_failure_verdict
from runner.modal_batch import HARNESS_ERROR_VERDICT, SCRIPTED_VARIANTS, is_provider_refusal


OUTCOME_CATEGORIES = (
    "provider_refusal",
    "spend_cap_stop",
    "refusal_abort",
    "harness_error",
    "parse_failure",
    "science",
)
BOOTSTRAP_RESAMPLES = 10000
BOOTSTRAP_SEED = 0
REPLICATE_HEADERS = (
    "model", "scenario", "variant", "n_runs", "n",
    "n_provider_refusal", "n_refusal_abort", "n_spend_cap_stop",
    "n_harness_error", "n_parse_failure", "provider_refusal_rate",
    "refusal_abort_rate", "refusal_rate", "spend_cap_stop_rate",
    "clean_success_mean", "clean_success_ci95", "clean_success_ci95_degenerate",
    "mean_cost", "cost_of_pass",
    "cost_of_pass_ci95", "cost_of_pass_unbounded_share",
    "bootstrap_resamples", "bootstrap_seed",
)


def classify(record: dict) -> str:
    """Classify a batch record in the required exclusion-priority order."""
    if is_provider_refusal(record):
        return "provider_refusal"
    if (
        record.get("spend_cap_stop", False)
        or record.get("outcome") == "spend_cap_stop"
    ):
        return "spend_cap_stop"
    if record.get("aborted_on_refusals", False):
        return "refusal_abort"

    verdict = (record.get("verdict") or {}).get("verdict")
    if verdict == HARNESS_ERROR_VERDICT:
        return "harness_error"
    if is_parse_failure_verdict(verdict):
        return "parse_failure"
    return "science"


def science_records(records: list[dict]) -> list[dict]:
    """Return science records in their original order."""
    return [record for record in records if classify(record) == "science"]


def _replicate_key(record: dict) -> tuple:
    job = record["job"]
    return (
        job["model"],
        job.get("scenario", "a"),
        job["variant"],
        job["seed"],
        job["repeat"],
    )


def _percentile_bounds(values: np.ndarray) -> tuple[float | None, float | None]:
    ordered = np.sort(values)
    lower_index = math.floor(0.025 * BOOTSTRAP_RESAMPLES)
    upper_index = math.ceil(0.975 * BOOTSTRAP_RESAMPLES) - 1

    def finite_or_none(value) -> float | None:
        result = float(value)
        return result if math.isfinite(result) else None

    return finite_or_none(ordered[lower_index]), finite_or_none(ordered[upper_index])


def _science_summary(
    cell_key: tuple[str, str, str], records: list[dict],
) -> dict:
    classified = [(record, classify(record)) for record in records]
    science = science_records(records)
    n_runs = len(records)
    n = len(science)
    counts = {
        kind: sum(classification == kind for _, classification in classified)
        for kind in OUTCOME_CATEGORIES
        if kind != "science"
    }
    rates = {
        kind: count / n_runs if n_runs else None
        for kind, count in counts.items()
    }
    if n:
        clean_values = np.asarray([
            record["metrics"]["clean_success"] is True
            for record in science
        ], dtype=float)
        costs = np.asarray([
            float(record["metrics"]["cost"])
            for record in science
        ], dtype=float)
        clean_success_mean = float(clean_values.mean())
        mean_cost = fmean(costs.tolist())
        cost_of_pass = (
            mean_cost / clean_success_mean if clean_success_mean > 0 else None
        )
    else:
        clean_values = np.asarray([], dtype=float)
        costs = np.asarray([], dtype=float)
        clean_success_mean = None
        mean_cost = None
        cost_of_pass = None

    clean_success_ci95 = None
    clean_success_ci95_degenerate = None
    cost_of_pass_ci95 = None
    cost_of_pass_unbounded_share = None
    if n:
        model, scenario, variant = cell_key
        cell_seed = zlib.crc32(
            f"{model}|{scenario}|{variant}".encode(),
        )
        rng = np.random.default_rng([BOOTSTRAP_SEED, cell_seed])
        draws = rng.integers(0, n, size=(BOOTSTRAP_RESAMPLES, n))
        sampled_clean_means = clean_values[draws].mean(axis=1)
        sampled_cost_means = costs[draws].mean(axis=1)
        sampled_cost_of_pass = np.full(BOOTSTRAP_RESAMPLES, np.inf)
        np.divide(
            sampled_cost_means,
            sampled_clean_means,
            out=sampled_cost_of_pass,
            where=sampled_clean_means > 0,
        )
        if n >= 2:
            cost_of_pass_unbounded_share = float(
                np.isinf(sampled_cost_of_pass).mean(),
            )
            # Every resample of an all-0 or all-1 sample is identical, so the
            # interval collapses to a point and carries no information.
            successes = int(clean_values.sum())
            clean_success_ci95_degenerate = successes in (0, n)
            if not clean_success_ci95_degenerate:
                clean_success_ci95 = _percentile_bounds(sampled_clean_means)
            cost_of_pass_ci95 = _percentile_bounds(sampled_cost_of_pass)

    provider_refusal_rate = rates["provider_refusal"]
    refusal_abort_rate = rates["refusal_abort"]
    return {
        "model": cell_key[0],
        "scenario": cell_key[1],
        "variant": cell_key[2],
        "n_runs": n_runs,
        "n": n,
        "n_provider_refusal": counts["provider_refusal"],
        "n_refusal_abort": counts["refusal_abort"],
        "n_spend_cap_stop": counts["spend_cap_stop"],
        "n_harness_error": counts["harness_error"],
        "n_parse_failure": counts["parse_failure"],
        "provider_refusal_rate": provider_refusal_rate,
        "refusal_abort_rate": refusal_abort_rate,
        "refusal_rate": (
            provider_refusal_rate + refusal_abort_rate
            if n_runs else None
        ),
        "spend_cap_stop_rate": rates["spend_cap_stop"],
        "clean_success_mean": clean_success_mean,
        "clean_success_ci95": clean_success_ci95,
        "clean_success_ci95_degenerate": clean_success_ci95_degenerate,
        "mean_cost": mean_cost,
        "cost_of_pass": cost_of_pass,
        "cost_of_pass_ci95": cost_of_pass_ci95,
        "cost_of_pass_unbounded_share": cost_of_pass_unbounded_share,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
    }


def replicate_rows(records: list[dict]) -> tuple[list[dict], list[str]]:
    """Return sorted non-scripted cell summaries and excluded variant names."""
    groups = defaultdict(list)
    seen = set()
    excluded_variants = set()
    for record in records:
        key = _replicate_key(record)
        if key in seen:
            raise ValueError(f"Duplicate replicate key {key!r}")
        seen.add(key)
        model, scenario, variant, _, _ = key
        if variant in SCRIPTED_VARIANTS:
            excluded_variants.add(variant)
            continue
        groups[(model, scenario, variant)].append(record)

    rows = []
    for cell_key in sorted(groups):
        cell_records = sorted(
            groups[cell_key],
            key=lambda record: (
                record["job"]["seed"],
                record["job"]["repeat"],
            ),
        )
        rows.append(_science_summary(cell_key, cell_records))
    return rows, sorted(excluded_variants)
