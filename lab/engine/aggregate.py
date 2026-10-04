"""Many runs per arm -> the difference between arms, with its uncertainty.

`compare.py` diffs two runs and says so when the gap is noise. This takes any
number of runs, groups them by the arm recorded in `run_meta.json`, and reports
the difference in mean score with a bootstrap confidence interval, a permutation
p-value and an effect size. The unit of replication is the whole run: a run's
score is the mean normalised score over the experiments they share, and runs are
independent, so resampling is over runs.
"""
from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIN_RUNS = 5


@dataclass
class Run:
    run_id: str
    arm: str
    scores: dict[str, float]          # experiment id -> score / max


def load_runs(paths: list[str | Path]) -> list[Run]:
    """Each path is a run directory or a directory of run directories."""
    runs: list[Run] = []
    for raw in paths:
        p = Path(raw)
        dirs = [p] if (p / "notebook.json").exists() else sorted(
            d for d in p.iterdir() if (d / "notebook.json").exists())
        for d in dirs:
            meta_path = d / "run_meta.json"
            if not meta_path.exists():
                raise ValueError(f"{d}: no run_meta.json, so its arm is unknown")
            arm = json.loads(meta_path.read_text())["arm"]
            nb = json.loads((d / "notebook.json").read_text())
            scores = {e["experiment_id"]: e["score"] / (e.get("score_max") or 1.0)
                      for e in nb["entries"] if e.get("score") is not None}
            runs.append(Run(run_id=nb.get("run_id", d.name), arm=arm, scores=scores))
    return runs


def _shared(runs: list[Run]) -> list[str]:
    ids = set.intersection(*(set(r.scores) for r in runs)) if runs else set()
    return sorted(ids)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _ci(xs: list[float], ys: list[float], rng: random.Random, n_boot: int
        ) -> tuple[float, float]:
    diffs = sorted(
        _mean(rng.choices(ys, k=len(ys))) - _mean(rng.choices(xs, k=len(xs)))
        for _ in range(n_boot))
    return diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot) - 1]


def _perm_p(xs: list[float], ys: list[float], rng: random.Random, n_perm: int) -> float:
    observed = abs(_mean(ys) - _mean(xs))
    pool, k = xs + ys, len(xs)
    hits = 0
    for _ in range(n_perm):
        rng.shuffle(pool)
        if abs(_mean(pool[k:]) - _mean(pool[:k])) >= observed - 1e-12:
            hits += 1
    return (hits + 1) / (n_perm + 1)


def _cohens_d(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(ys) < 2:
        return None
    pooled = (((len(xs) - 1) * statistics.variance(xs)
               + (len(ys) - 1) * statistics.variance(ys))
              / (len(xs) + len(ys) - 2)) ** 0.5
    return None if pooled == 0 else (_mean(ys) - _mean(xs)) / pooled


def compare_arms(runs: list[Run], baseline: str, treatment: str, *,
                 n_boot: int = 10000, seed: int = 0) -> dict[str, Any]:
    a = [r for r in runs if r.arm == baseline]
    b = [r for r in runs if r.arm == treatment]
    if not a or not b:
        raise ValueError(f"need runs in both arms; have {baseline}={len(a)}, "
                         f"{treatment}={len(b)}")
    exps = _shared(a + b)
    if not exps:
        raise ValueError("the runs share no scored experiment")
    rng = random.Random(seed)
    per_run = lambda rs: [_mean([r.scores[e] for e in exps]) for r in rs]
    xs, ys = per_run(a), per_run(b)
    lo, hi = _ci(xs, ys, rng, n_boot)
    rows = []
    for e in exps:
        ea, eb = [r.scores[e] for r in a], [r.scores[e] for r in b]
        elo, ehi = _ci(ea, eb, rng, n_boot)
        rows.append({"experiment_id": e, "baseline": round(_mean(ea), 4),
                     "treatment": round(_mean(eb), 4),
                     "diff": round(_mean(eb) - _mean(ea), 4),
                     "ci95": [round(elo, 4), round(ehi, 4)]})
    n_min = min(len(a), len(b))
    return {
        "baseline_arm": baseline, "treatment_arm": treatment,
        "n_baseline": len(a), "n_treatment": len(b),
        "experiments": exps,
        "mean_baseline": round(_mean(xs), 4), "mean_treatment": round(_mean(ys), 4),
        "diff": round(_mean(ys) - _mean(xs), 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "p_permutation": round(_perm_p(xs, ys, rng, n_boot), 4),
        "cohens_d": None if _cohens_d(xs, ys) is None else round(_cohens_d(xs, ys), 3),
        "per_experiment": rows,
        "warning": (f"only {n_min} run(s) in the smaller arm; an interval from fewer "
                    f"than {MIN_RUNS} is not a measurement of the noise")
        if n_min < MIN_RUNS else None,
    }


def summarise(runs: list[Run]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in sorted({r.arm for r in runs}):
        rs = [r for r in runs if r.arm == arm]
        exps = _shared(rs)
        means = [_mean([r.scores[e] for e in exps]) for r in rs] if exps else []
        out[arm] = {"n": len(rs), "mean": round(_mean(means), 4) if means else None,
                    "sd": round(statistics.stdev(means), 4) if len(means) > 1 else None}
    return out


def render(res: dict[str, Any]) -> str:
    lo, hi = res["ci95"]
    lines = [
        f"{res['treatment_arm']} (n={res['n_treatment']}) minus "
        f"{res['baseline_arm']} (n={res['n_baseline']})",
        f"  {res['mean_treatment']:.3f} - {res['mean_baseline']:.3f} = "
        f"{res['diff']:+.3f}   95% CI [{lo:+.3f}, {hi:+.3f}]   "
        f"permutation p = {res['p_permutation']}   Cohen's d = {res['cohens_d']}",
        "", f"  {'experiment':36s} {'base':>6} {'treat':>6} {'diff':>7}   95% CI",
    ]
    for r in res["per_experiment"]:
        lines.append(f"  {r['experiment_id'][:36]:36s} {r['baseline']:>6.2f} "
                     f"{r['treatment']:>6.2f} {r['diff']:>+7.2f}   "
                     f"[{r['ci95'][0]:+.2f}, {r['ci95'][1]:+.2f}]")
    if res["warning"]:
        lines += ["", "  WARNING: " + res["warning"]]
    return "\n".join(lines)
