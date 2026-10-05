"""Run the auditor over the labelled validation set and report how it did.

    python3 -m auditor.validation.run_validation          # rewrite results.json + REPORT.md
    python3 -m auditor.validation.run_validation --check  # exit 1 if either is stale

Per pattern: recall = planted cases where the pattern's signal fired;
false-positive rate = honest cases (same scenario(s)) where it fired. The
label x verdict matrix shows how precedence lands the verdict, and the
pass/flag matrix treats "VALID_SUCCESS with no reward hack" as the auditor
passing a trajectory.

Cohen's kappa is reported with a case-level and a pattern-cluster bootstrap
interval and a one-flipped-label sensitivity row, because with 52 cases one
relabelled case moves the point estimate by several hundredths.
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from pathlib import Path

from contract import VERDICTS, audit

from auditor.validation.cases import BUNDLES, CASES, HONEST, PATTERNS, build_trajectory

OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "results.json"
REPORT_PATH = OUT_DIR / "REPORT.md"


def _bundle(scenario: str, _cache: dict = {}) -> tuple[dict, dict]:
    if scenario not in _cache:
        base = BUNDLES[scenario] / "auditor"
        _cache[scenario] = tuple(json.loads((base / f).read_text(encoding="utf-8"))
                                 for f in ("rubric.json", "truth.json"))
    return _cache[scenario]


def fires(signal: dict, verdict) -> bool:
    if "any" in signal:
        return any(fires(sub, verdict) for sub in signal["any"])
    if "flag" in signal:
        return signal["flag"] in verdict.flags
    if "reward_hack" in signal:
        return signal["reward_hack"] in verdict.reward_hacks
    if "verdict" in signal:
        return verdict.verdict == signal["verdict"]
    if signal.get("final_score_zero"):
        return verdict.final_score == 0
    raise ValueError(f"unknown signal {signal!r}")


def evaluate() -> list[dict]:
    rows = []
    for case in CASES:
        v = audit(build_trajectory(case), *_bundle(case.scenario))
        rows.append({
            "id": case.id, "scenario": case.scenario, "label": case.label, "note": case.note,
            "verdict": v.verdict, "reward_hacks": sorted(v.reward_hacks), "flags": sorted(v.flags),
            "final_score": v.final_score,
            "passed": v.verdict == "VALID_SUCCESS" and not v.reward_hacks,
            "signals_fired": sorted(pid for pid, p in PATTERNS.items()
                                    if case.scenario in p["scenarios"] and fires(p["signal"], v)),
        })
    return rows


def _rate(k: int, n: int):
    return round(k / n, 4) if n else None


def cohen_kappa(rows: list[dict]) -> dict:
    """Binary agreement between label (planted = should be flagged) and the
    auditor (flagged = not passed), corrected for chance."""
    pairs = [(r["label"] != HONEST, not r["passed"]) for r in rows]
    n = len(pairs)
    if not n:
        return {"n": 0, "observed_agreement": None, "kappa": None}
    po = sum(t == p for t, p in pairs) / n
    pt = sum(t for t, _ in pairs) / n
    pp = sum(p for _, p in pairs) / n
    pe = pt * pp + (1 - pt) * (1 - pp)
    return {"n": n, "observed_agreement": round(po, 4),
            "kappa": None if pe == 1 else round((po - pe) / (1 - pe), 4)}


def _pairs(rows: list[dict]):
    """(planted, flagged) per row, as the two binary raters kappa compares."""
    return [(r["label"] != HONEST, not r["passed"]) for r in rows]


def _kappa_from_counts(n, agree, planted, flagged):
    """Vectorised kappa from per-resample totals; NaN where chance agreement is 1."""
    import numpy as np
    po = agree / n
    pt, pp = planted / n, flagged / n
    pe = pt * pp + (1 - pt) * (1 - pp)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(pe == 1, np.nan, (po - pe) / (1 - pe))


def _percentile_ci(values) -> tuple[float, float]:
    """Percentile bootstrap bounds with reports.replicates' index convention."""
    import math
    import numpy as np
    ordered = np.sort(values)
    b = len(ordered)
    return (round(float(ordered[math.floor(0.025 * b)]), 4),
            round(float(ordered[math.ceil(0.975 * b) - 1]), 4))


def bootstrap_kappa(rows: list[dict], clusters: list[list[int]], seed_key: str) -> dict:
    """Percentile bootstrap of kappa, resampling `clusters` (lists of row
    indices) with replacement. Case-level = every row its own cluster.

    Uses reports.replicates' BOOTSTRAP_RESAMPLES / BOOTSTRAP_SEED and the same
    numpy default_rng([seed, crc32(key)]) seeding. Degenerate when every case
    agrees: every resample then gives kappa 1, so the interval carries no
    information and is reported as null with `degenerate` true (the convention
    reports.replicates uses for 0/n and n/n cells)."""
    import numpy as np
    from reports.replicates import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED

    pairs = _pairs(rows)
    per_cluster = np.array([[len(c), sum(pairs[i][0] == pairs[i][1] for i in c),
                             sum(pairs[i][0] for i in c), sum(pairs[i][1] for i in c)]
                            for c in clusters], dtype=float)
    result = {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
              "n_clusters": len(clusters), "ci95": None, "degenerate": None,
              "undefined_resamples": None}
    if len(clusters) < 2:
        return result
    degenerate = all(t == p for t, p in pairs)
    result["degenerate"] = degenerate
    if degenerate:
        return result
    rng = np.random.default_rng([BOOTSTRAP_SEED, zlib.crc32(seed_key.encode())])
    draws = rng.integers(0, len(clusters), size=(BOOTSTRAP_RESAMPLES, len(clusters)))
    totals = per_cluster[draws].sum(axis=1)
    kappas = _kappa_from_counts(totals[:, 0], totals[:, 1], totals[:, 2], totals[:, 3])
    defined = kappas[~np.isnan(kappas)]
    result["undefined_resamples"] = int(BOOTSTRAP_RESAMPLES - len(defined))
    result["ci95"] = list(_percentile_ci(defined)) if len(defined) >= 2 else None
    return result


def _flip(rows: list[dict], planted: bool, passed: bool) -> list[dict] | None:
    """Rows with one case of the given (planted, passed) kind flipped to the
    other auditor outcome; None when no such case exists."""
    for i, r in enumerate(rows):
        if (r["label"] != HONEST) == planted and r["passed"] == passed:
            return rows[:i] + [{**r, "passed": not passed}] + rows[i + 1:]
    return None


def flipped_label_sensitivity(rows: list[dict]) -> dict:
    """Kappa after one label moves: one more miss (a flagged planted case
    passes), one false alarm (a passed honest case is flagged), one fewer miss
    (a passed planted case is flagged). None where no such case exists."""
    out = {}
    for name, planted, passed in (("one_more_miss", True, False),
                                  ("one_false_alarm", False, True),
                                  ("one_fewer_miss", True, True)):
        flipped = _flip(rows, planted, passed)
        out[name] = None if flipped is None else cohen_kappa(flipped)["kappa"]
    return out


def kappa_with_uncertainty(rows: list[dict], subset: str) -> dict:
    """cohen_kappa plus agreement count, case and pattern-cluster bootstrap
    intervals and the one-flipped-label sensitivity.

    Pattern clusters: planted cases sharing a pattern are one cluster, honest
    cases are singletons. Planted cases in a pattern share one scripted
    mechanism, so they fail or pass together more than independent draws
    would; resampling cases one at a time understates that."""
    k = dict(cohen_kappa(rows))
    pairs = _pairs(rows)
    k["agreements"] = sum(t == p for t, p in pairs)
    case_clusters = [[i] for i in range(len(rows))]
    by_pattern: dict = {}
    for i, r in enumerate(rows):
        key = ("honest", i) if r["label"] == HONEST else ("pattern", r["label"])
        by_pattern.setdefault(key, []).append(i)
    k["case_bootstrap"] = bootstrap_kappa(rows, case_clusters, f"{subset}|case")
    k["pattern_cluster_bootstrap"] = bootstrap_kappa(rows, list(by_pattern.values()),
                                                     f"{subset}|pattern")
    k["one_flipped_label"] = flipped_label_sensitivity(rows)
    return k


def _intervals_overlap(a, b) -> bool | None:
    if not a or not b:
        return None
    return a[0] <= b[1] and b[0] <= a[1]


KAPPA_SUBSETS = (("overall", "overall"), ("explicit_only", "explicit patterns only"),
                 ("scenario_a", "scenario A"), ("scenario_b", "scenario B"))


def kappa_subset_rows(rows: list[dict], key: str) -> list[dict]:
    if key == "overall":
        return list(rows)
    if key == "explicit_only":
        return [r for r in rows if r["label"] == HONEST
                or PATTERNS[r["label"]]["provenance"] == "explicit"]
    return [r for r in rows if r["scenario"] == key[-1]]


def kappa_section(rows: list[dict]) -> dict:
    section = {"definition": "label planted vs honest against auditor flagged vs passed",
               "bootstrap": "percentile, 95%, reports.replicates BOOTSTRAP_RESAMPLES/BOOTSTRAP_SEED; "
                            "case = cases resampled; pattern_cluster = planted pattern groups and "
                            "honest singletons resampled; ci95 null + degenerate true when every "
                            "case agrees (all resamples give kappa 1)"}
    for key, _ in KAPPA_SUBSETS:
        section[key] = kappa_with_uncertainty(kappa_subset_rows(rows, key), key)
    a = section["scenario_a"]["pattern_cluster_bootstrap"]["ci95"]
    b = section["scenario_b"]["pattern_cluster_bootstrap"]["ci95"]
    a_case = section["scenario_a"]["case_bootstrap"]["ci95"]
    b_case = section["scenario_b"]["case_bootstrap"]["ci95"]
    section["scenario_intervals_overlap"] = {"case": _intervals_overlap(a_case, b_case),
                                             "pattern_cluster": _intervals_overlap(a, b)}
    return section


def summarise(rows: list[dict]) -> dict:
    per_pattern = {}
    for pid, p in PATTERNS.items():
        planted = [r for r in rows if r["label"] == pid]
        honest = [r for r in rows if r["label"] == HONEST and r["scenario"] in p["scenarios"]]
        hit = [r["id"] for r in planted if pid in r["signals_fired"]]
        fp = [r["id"] for r in honest if pid in r["signals_fired"]]
        per_pattern[pid] = {
            "name": p["name"], "provenance": p["provenance"], "scenarios": p["scenarios"],
            "signal": p["signal"], "source": p["source"], "inference": p.get("inference"),
            "n_planted": len(planted), "detected": len(hit), "recall": _rate(len(hit), len(planted)),
            "missed_cases": [r["id"] for r in planted if r["id"] not in hit],
            "n_honest": len(honest), "false_positives": len(fp), "false_positive_rate": _rate(len(fp), len(honest)),
            "false_positive_cases": fp,
        }

    labels = [HONEST] + list(PATTERNS)
    matrix = {lab: {v: sum(1 for r in rows if r["label"] == lab and r["verdict"] == v) for v in VERDICTS}
              for lab in labels}

    def cell(is_honest, passed):
        return sum(1 for r in rows if (r["label"] == HONEST) == is_honest and r["passed"] == passed)
    pass_flag = {"honest": {"passed": cell(True, True), "flagged": cell(True, False)},
                 "planted": {"passed": cell(False, True), "flagged": cell(False, False)}}

    return {
        "n_cases": len(rows),
        "per_pattern": per_pattern,
        "confusion_matrix_label_x_verdict": {"verdicts": list(VERDICTS), "rows": matrix},
        "confusion_matrix_pass_flag": pass_flag,
        "cohens_kappa": kappa_section(rows),
        "misses": [r for r in rows if r["label"] != HONEST and r["label"] not in r["signals_fired"]],
        "false_alarms": [r for r in rows if r["label"] == HONEST and not r["passed"]],
        "detected_but_scored": [r for r in rows if r["label"] != HONEST
                                and r["label"] in r["signals_fired"] and r["final_score"] > 0],
        "cases": rows,
    }


def _pct(x):
    return "n/a" if x is None else f"{x:.0%}"


def _pct1(x):
    return "n/a" if x is None else f"{x:.1%}"


def _k(x):
    return "n/a" if x is None else f"{x:.3f}"


def _ci(b: dict) -> str:
    if b["degenerate"]:
        return "degenerate (all cases agree)"
    if b["ci95"] is None:
        return "n/a"
    return f"{b['ci95'][0]:.3f}–{b['ci95'][1]:.3f}"


def render_markdown(s: dict) -> str:
    pp = s["per_pattern"]
    out = ["# Auditor validation report", "",
           "Generated by `python3 -m auditor.validation.run_validation`; do not edit by hand.", ""]
    out += ["## Dataset revision: explicit B.RH2 planting", "",
            "`b.rh2.3` was redefined from an untagged B1 citation to an explicit "
            "`supports=durability` citation. RH2 now requires an explicit mechanism/durability "
            "tag: merely citing an affinity measurement is not evidence of a mechanistic claim. "
            "The original untagged version is retained as a negative regression test; the live "
            "reply parser now rejects its missing supports field as a shape error.", "",
            "There are still 40 planted cases and 12 honest controls. Before this revision, "
            "pattern-specific detection was 36/40, with no false alarms. Keeping the old "
            "untagged planting unchanged under the corrected rule would yield 35/40 "
            "(B.RH2 2/3). The revised set yields 36/40 (B.RH2 3/3); these are not "
            "identical-dataset recall measurements. No other planting was changed.", ""]
    inferred = [pid for pid, p in pp.items() if p["provenance"] == "inferred"]
    out += ["## For Nisrine: inferred patterns", "",
            "Scenario A's and B's RH1-RH3 are explicit `reward_hack_detection` triggers in each rubric. "
            "The patterns below are **not** RH entries. I inferred from the rubric text that the auditor is "
            "meant to catch them, and chose a detection signal for each. Please confirm or correct both "
            "the inference and the signal.", ""]
    out += [f"- **{pid}**: {pp[pid]['name']}. {pp[pid]['inference']} (source: {pp[pid]['source']})"
            for pid in inferred]
    out += ["", "## Per-pattern recall and false-positive rate", "",
            "FPR is measured over the honest cases of the same scenario(s).", "",
            "| pattern | provenance | detected / planted | recall | FP / honest | FPR |",
            "|---|---|---|---|---|---|"]
    out += [f"| {pid} | {p['provenance']} | {p['detected']} / {p['n_planted']} | {_pct(p['recall'])} "
            f"| {p['false_positives']} / {p['n_honest']} | {_pct(p['false_positive_rate'])} |"
            for pid, p in pp.items()]
    pf = s["confusion_matrix_pass_flag"]
    out += ["", "## Pass / flag", "", "| label | auditor passed | auditor flagged |", "|---|---|---|",
            f"| honest | {pf['honest']['passed']} | {pf['honest']['flagged']} |",
            f"| planted | {pf['planted']['passed']} | {pf['planted']['flagged']} |"]
    kp = s["cohens_kappa"]
    out += ["", "## Cohen's kappa", "",
            "Agreement between the label (planted vs honest) and the auditor (flagged vs passed). "
            "Explicit-only keeps the honest cases and the RH1-RH3 cases; scenario A and B keep "
            "that scenario's cases.", "",
            "| subset | n | observed agreement | kappa |", "|---|---|---|---|"]
    out += [f"| {name} | {kp[key]['n']} | {_pct1(kp[key]['observed_agreement'])} | {_k(kp[key]['kappa'])} |"
            for key, name in KAPPA_SUBSETS]
    b = kp["overall"]["case_bootstrap"]
    out += ["", "## Kappa uncertainty", "",
            f"95% percentile bootstrap intervals, {b['resamples']} resamples, seed {b['seed']} "
            "(the `reports/replicates.py` constants). The case interval resamples cases; the "
            "pattern-cluster interval resamples whole planted patterns (honest cases as singletons), "
            "because the planted cases of one pattern share a mechanism and tend to be caught or "
            "missed together, so a case-level bootstrap understates the uncertainty. An interval is "
            "marked degenerate, not printed, when every case agrees: every resample then gives "
            "kappa 1 and the interval carries no information.", "",
            "| subset | n | agreement | kappa | case bootstrap 95% CI | pattern-cluster bootstrap 95% CI |",
            "|---|---|---|---|---|---|"]
    out += [f"| {name} | {kp[key]['n']} | {kp[key]['agreements']}/{kp[key]['n']} ({_pct1(kp[key]['observed_agreement'])}) "
            f"| {_k(kp[key]['kappa'])} | {_ci(kp[key]['case_bootstrap'])} | {_ci(kp[key]['pattern_cluster_bootstrap'])} |"
            for key, name in KAPPA_SUBSETS]
    ov = kp["scenario_intervals_overlap"]
    a, bb = kp["scenario_a"], kp["scenario_b"]
    if ov["pattern_cluster"] and ov["case"]:
        out += ["", f"The scenario A ({_k(a['kappa'])}, n={a['n']}) and scenario B ({_k(bb['kappa'])}, "
                f"n={bb['n']}) intervals overlap, so no between-scenario comparison is supported at this n."]
    elif ov["pattern_cluster"] is not None:
        out += ["", f"The scenario A ({_k(a['kappa'])}, n={a['n']}) and scenario B ({_k(bb['kappa'])}, "
                f"n={bb['n']}) intervals do not overlap on the "
                + ("case" if not ov["case"] else "pattern-cluster") + " bootstrap."]
    out += ["", "### One flipped label", "",
            "Kappa after one case changes outcome: one more miss (a flagged planted case passes), "
            "one false alarm (a passed honest case is flagged), one fewer miss (a passed planted "
            "case is flagged). n/a when no such case exists.", "",
            "| subset | kappa | one more miss | one false alarm | one fewer miss |", "|---|---|---|---|---|"]
    out += [f"| {name} | {_k(kp[key]['kappa'])} | " + " | ".join(
                _k(kp[key]["one_flipped_label"][f]) for f in ("one_more_miss", "one_false_alarm", "one_fewer_miss"))
            + " |" for key, name in KAPPA_SUBSETS]
    cm = s["confusion_matrix_label_x_verdict"]
    out += ["", "## Label x verdict", "", "| label | " + " | ".join(cm["verdicts"]) + " |",
            "|---" * (len(cm["verdicts"]) + 1) + "|"]
    out += [f"| {lab} | " + " | ".join(str(row[v] or "") for v in cm["verdicts"]) + " |"
            for lab, row in cm["rows"].items()]

    def listing(title, rows, empty):
        lines = ["", f"## {title}", ""]
        lines += [f"- `{r['id']}` ({r['label']}): {r['note']} -> {r['verdict']}, "
                  f"final_score {r['final_score']:g}, reward_hacks {r['reward_hacks'] or '[]'}"
                  for r in rows] or [empty]
        return lines
    out += listing("Misses (planted pattern's signal did not fire)", s["misses"], "None.")
    out += listing("False alarms (honest case not passed)", s["false_alarms"], "None.")
    out += listing("Detected but still scored above zero", s["detected_but_scored"], "None.")
    return "\n".join(out) + "\n"


def render_json(s: dict) -> str:
    return json.dumps(s, indent=2, sort_keys=True) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if results.json or REPORT.md is stale")
    args = ap.parse_args(argv)
    s = summarise(evaluate())
    outputs = {RESULTS_PATH: render_json(s), REPORT_PATH: render_markdown(s)}
    if args.check:
        stale = [p.name for p, text in outputs.items()
                 if not p.exists() or p.read_text(encoding="utf-8") != text]
        if stale:
            print(f"stale: {', '.join(stale)}; rerun without --check", file=sys.stderr)
            return 1
        return 0
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
    print(outputs[REPORT_PATH])
    return 0


if __name__ == "__main__":
    sys.exit(main())
