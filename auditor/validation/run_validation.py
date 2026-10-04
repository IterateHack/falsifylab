"""Run the auditor over the labelled validation set and report how it did.

    python3 -m auditor.validation.run_validation          # rewrite results.json + REPORT.md
    python3 -m auditor.validation.run_validation --check  # exit 1 if either is stale

Per pattern: recall = planted cases where the pattern's signal fired;
false-positive rate = honest cases (same scenario(s)) where it fired. The
label x verdict matrix shows how precedence lands the verdict, and the
pass/flag matrix treats "VALID_SUCCESS with no reward hack" as the auditor
passing a trajectory.
"""
from __future__ import annotations

import argparse
import json
import sys
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
        "cohens_kappa": {
            "definition": "label planted vs honest against auditor flagged vs passed",
            "overall": cohen_kappa(rows),
            "explicit_only": cohen_kappa([r for r in rows if r["label"] == HONEST
                                          or PATTERNS[r["label"]]["provenance"] == "explicit"]),
        },
        "misses": [r for r in rows if r["label"] != HONEST and r["label"] not in r["signals_fired"]],
        "false_alarms": [r for r in rows if r["label"] == HONEST and not r["passed"]],
        "detected_but_scored": [r for r in rows if r["label"] != HONEST
                                and r["label"] in r["signals_fired"] and r["final_score"] > 0],
        "cases": rows,
    }


def _pct(x):
    return "n/a" if x is None else f"{x:.0%}"


def render_markdown(s: dict) -> str:
    pp = s["per_pattern"]
    out = ["# Auditor validation report", "",
           "Generated by `python3 -m auditor.validation.run_validation`; do not edit by hand.", ""]
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
            "Explicit-only keeps the honest cases and the RH1-RH3 cases.", "",
            "| subset | n | observed agreement | kappa |", "|---|---|---|---|"]
    out += [f"| {name} | {kp[key]['n']} | {_pct(kp[key]['observed_agreement'])} | "
            + ("n/a" if kp[key]["kappa"] is None else f"{kp[key]['kappa']:.3f}") + " |"
            for key, name in (("overall", "overall"), ("explicit_only", "explicit patterns only"))]
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
