"""Compare two runs - typically with and without lesson cards.

This is the learning evidence (plan section 10.4). The claim the project makes is
that lessons carry forward and help later experiments, and the only honest way to
show that is to run the same curriculum twice and look at the difference on the
experiments that declare a dependency.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load(run_dir: str | Path) -> dict[str, Any]:
    return json.loads((Path(run_dir) / "notebook.json").read_text())


def compare(with_lessons_dir: str | Path, without_lessons_dir: str | Path,
            curriculum_root: str | Path = "curricula/glp1r") -> dict[str, Any]:
    from .specs import load_curriculum

    curriculum = load_curriculum(curriculum_root)
    depends = {e.id: bool(e.requires_lessons) for e in curriculum.experiments}

    a, b = load(with_lessons_dir), load(without_lessons_dir)
    by_id_a = {e["experiment_id"]: e for e in a["entries"]}
    by_id_b = {e["experiment_id"]: e for e in b["entries"]}

    rows = []
    for exp_id, ea in by_id_a.items():
        eb = by_id_b.get(exp_id)
        if ea.get("score") is None or not eb or eb.get("score") is None:
            continue
        rows.append({
            "experiment_id": exp_id,
            "order": ea["order"],
            "title": ea["title"],
            "depends_on_lessons": depends.get(exp_id, False),
            "score_with": round(ea["score"], 4),
            "score_without": round(eb["score"], 4),
            "delta": round(ea["score"] - eb["score"], 4),
            "confidence_with": ea.get("confidence"),
            "confidence_without": eb.get("confidence"),
        })
    rows.sort(key=lambda r: r["order"])

    dependent = [r for r in rows if r["depends_on_lessons"]]
    independent = [r for r in rows if not r["depends_on_lessons"]]

    def mean(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 4) if xs else None

    return {
        "rows": rows,
        "n_compared": len(rows),
        "mean_delta_all": mean([r["delta"] for r in rows]),
        "mean_delta_lesson_dependent": mean([r["delta"] for r in dependent]),
        "mean_delta_lesson_independent": mean([r["delta"] for r in independent]),
        "n_dependent": len(dependent),
        "n_independent": len(independent),
        "with_run": a["run_id"],
        "without_run": b["run_id"],
    }


def render(result: dict[str, Any]) -> str:
    lines = [
        f"Lesson-card control: {result['with_run']} (with) vs "
        f"{result['without_run']} (without)",
        "",
        f"{'#':>2}  {'experiment':38s} {'needs':>6} {'with':>6} {'without':>8} {'delta':>7}",
        "-" * 74,
    ]
    for r in result["rows"]:
        lines.append(
            f"{r['order']:>2}  {r['title'][:38]:38s} "
            f"{'yes' if r['depends_on_lessons'] else 'no':>6} "
            f"{r['score_with']:>6.2f} {r['score_without']:>8.2f} "
            f"{r['delta']:>+7.2f}"
        )
    lines += [
        "-" * 74,
        f"mean delta, all experiments            {_fmt(result['mean_delta_all'])}",
        f"mean delta, experiments needing lessons ({result['n_dependent']})  "
        f"{_fmt(result['mean_delta_lesson_dependent'])}",
        f"mean delta, experiments not needing them ({result['n_independent']}) "
        f"{_fmt(result['mean_delta_lesson_independent'])}",
        "",
    ]
    dep = result["mean_delta_lesson_dependent"]
    ind = result["mean_delta_lesson_independent"]
    if dep is not None and ind is not None:
        if dep > ind + 0.05:
            lines.append(
                "Lesson-dependent experiments gained more than independent ones, "
                "which is what the curriculum design predicts.")
        elif dep < ind - 0.05:
            lines.append(
                "Lesson-dependent experiments gained LESS than independent ones. "
                "That is evidence against the lessons mattering - the difference is "
                "more likely run-to-run variance.")
        else:
            lines.append(
                "No clear separation between lesson-dependent and independent "
                "experiments. With one run per arm this is well within noise; "
                "repeat the control before claiming the lessons helped.")
    lines.append(
        "Caveat: n=1 per arm. Treat any delta under about 0.1 as noise. "
        "For several runs per arm, with an interval, use `aggregate`.")
    return "\n".join(lines)


def _fmt(v: float | None) -> str:
    return "   n/a" if v is None else f"{v:+.3f}"
