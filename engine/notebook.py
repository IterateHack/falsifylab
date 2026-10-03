"""The lab notebook: the artefact the whole project exists to produce.

Section order follows the plan's template (section 8.3). Sections 1, 2, 5, 6, 7
and 8 are written by the agent; section 4 is filled in by the engine from the
scorer, so the agent cannot edit its own grade.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SECTION_ORDER = [
    "hypothesis_and_prediction",
    "plan",
    "what_i_did",
    "score_and_outcome",
    "what_i_got_wrong",
    "lesson_learned",
    "lessons_applied",
    "prior_knowledge_claimed",
]

SECTION_TITLES = {
    "hypothesis_and_prediction": "Hypothesis and prediction",
    "plan": "Plan",
    "what_i_did": "What I did",
    "score_and_outcome": "Score and outcome",
    "what_i_got_wrong": "What I got wrong, and why I was confident anyway",
    "lesson_learned": "Lesson learned",
    "lessons_applied": "Lessons applied from earlier experiments",
    "prior_knowledge_claimed": "Prior knowledge claimed",
}


@dataclass
class NotebookEntry:
    experiment_id: str
    title: str
    order: int
    sections: dict[str, str] = field(default_factory=dict)
    confidence: float | None = None
    score: float | None = None
    score_max: float = 1.0
    score_details: dict[str, Any] = field(default_factory=dict)
    answer: Any = None
    applied_lesson_ids: list[str] = field(default_factory=list)
    papers: list[str] = field(default_factory=list)
    status: str = "locked"        # locked | running | scored | done
    tool_calls_used: int = 0
    model: str = ""

    def set(self, section: str, text: str) -> None:
        if section not in SECTION_TITLES:
            raise KeyError(section)
        self.sections[section] = text.strip()

    def has(self, section: str) -> bool:
        return bool(self.sections.get(section, "").strip())

    # ---- derived -------------------------------------------------------
    @property
    def calibration_gap(self) -> float | None:
        """Stated confidence minus the score actually achieved.

        Positive means overconfident. This single number is what the project is
        really about, so it lives on the entry rather than being recomputed.
        """
        if self.confidence is None or self.score is None:
            return None
        return round(self.confidence - (self.score / (self.score_max or 1.0)), 4)

    def record_score(self, result: dict[str, Any]) -> None:
        self.score = float(result.get("score", 0.0))
        self.score_max = float(result.get("max", 1.0))
        self.score_details = result.get("details", {}) or {}
        self.status = "scored"
        self.set("score_and_outcome", self._render_outcome())

    def _render_outcome(self) -> str:
        pct = 100.0 * (self.score or 0.0) / (self.score_max or 1.0)
        lines = [f"**Score: {self.score:.2f} / {self.score_max:.2f}** ({pct:.0f}%)"]
        if self.confidence is not None:
            gap = self.calibration_gap
            verdict = ("overconfident" if gap and gap > 0.15 else
                       "underconfident" if gap and gap < -0.15 else "well calibrated")
            lines.append(f"Stated confidence before running: **{self.confidence:.2f}** "
                         f"- calibration gap {gap:+.2f} ({verdict}).")
        det = self.score_details
        interesting = [k for k in ("precision_at_k", "f1", "precision", "recall",
                                   "ranking_score", "fit_score", "mechanism_score",
                                   "mean_absolute_error_log_units", "average_precision")
                       if k in det]
        if interesting:
            lines.append("")
            lines.append("| metric | value |")
            lines.append("| --- | --- |")
            for k in interesting:
                lines.append(f"| {k.replace('_', ' ')} | {det[k]} |")
        for key, label in (("missed", "Rubric points missed"),
                           ("penalised", "Penalties applied")):
            vals = det.get(key)
            if vals:
                lines.append("")
                lines.append(f"**{label}:**")
                lines.extend(f"- {v}" for v in vals)
        if det.get("scorer_error"):
            lines.append("")
            lines.append(f"**Scorer error:** `{det['scorer_error']}`")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        out = [f"# Experiment {self.order}: {self.title}", ""]
        if self.model:
            out.append(f"*Model: {self.model}. Tool calls used: {self.tool_calls_used}.*")
            out.append("")
        for i, key in enumerate(SECTION_ORDER, start=1):
            body = self.sections.get(key, "").strip()
            if not body:
                if key == "lessons_applied" and not self.applied_lesson_ids:
                    continue
                if key in ("what_i_got_wrong", "lesson_learned") and self.status != "done":
                    continue
                body = "_not written_"
            out.append(f"## {i}. {SECTION_TITLES[key]}")
            out.append("")
            out.append(body)
            out.append("")
        if self.papers:
            out.append("## Teaching source")
            out.append("")
            out.extend(f"- {p}" for p in self.papers)
            out.append("")
        return "\n".join(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "title": self.title,
            "order": self.order,
            "status": self.status,
            "sections": dict(self.sections),
            "section_order": SECTION_ORDER,
            "section_titles": SECTION_TITLES,
            "confidence": self.confidence,
            "score": self.score,
            "score_max": self.score_max,
            "score_details": self.score_details,
            "calibration_gap": self.calibration_gap,
            "applied_lesson_ids": self.applied_lesson_ids,
            "papers": self.papers,
            "tool_calls_used": self.tool_calls_used,
            "model": self.model,
            "answer": _jsonable(self.answer),
            "markdown": self.to_markdown(),
        }


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


@dataclass
class Notebook:
    run_id: str
    hypothesis: str
    entries: list[NotebookEntry] = field(default_factory=list)

    def get(self, experiment_id: str) -> NotebookEntry:
        for e in self.entries:
            if e.experiment_id == experiment_id:
                return e
        raise KeyError(experiment_id)

    def to_markdown(self) -> str:
        parts = [f"# Lab notebook - run `{self.run_id}`", "",
                 "## Hypothesis", "", self.hypothesis.strip(), ""]
        parts.append(self.calibration_summary_markdown())
        # Locked entries are blank pages in the UI; in the markdown they are just
        # noise, so only experiments that actually ran are rendered.
        for e in sorted(self.entries, key=lambda x: x.order):
            if e.status == "locked":
                continue
            parts.append("---")
            parts.append("")
            parts.append(e.to_markdown())
        return "\n".join(parts)

    def calibration_summary(self) -> dict[str, Any]:
        scored = [e for e in self.entries if e.score is not None]
        rows = []
        for e in sorted(scored, key=lambda x: x.order):
            rows.append({
                "experiment_id": e.experiment_id,
                "order": e.order,
                "title": e.title,
                "confidence": e.confidence,
                "score": round(e.score / (e.score_max or 1.0), 4),
                "gap": e.calibration_gap,
            })
        gaps = [r["gap"] for r in rows if r["gap"] is not None]
        confs = [r["confidence"] for r in rows if r["confidence"] is not None]
        scores = [r["score"] for r in rows]
        n_over = sum(1 for g in gaps if g > 0.15)
        return {
            "rows": rows,
            "n_scored": len(rows),
            "mean_confidence": round(sum(confs) / len(confs), 4) if confs else None,
            "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
            "mean_gap": round(sum(gaps) / len(gaps), 4) if gaps else None,
            "mean_absolute_gap": round(sum(abs(g) for g in gaps) / len(gaps), 4)
            if gaps else None,
            "n_overconfident": n_over,
            "verdict": _calibration_verdict(gaps),
        }

    def calibration_summary_markdown(self) -> str:
        s = self.calibration_summary()
        if not s["rows"]:
            return ""
        lines = ["## Calibration summary", "",
                 "| # | experiment | stated confidence | score | gap |",
                 "| --- | --- | --- | --- | --- |"]
        for r in s["rows"]:
            conf = f"{r['confidence']:.2f}" if r["confidence"] is not None else "-"
            gap = f"{r['gap']:+.2f}" if r["gap"] is not None else "-"
            lines.append(f"| {r['order']} | {r['title']} | {conf} | {r['score']:.2f} | {gap} |")
        lines += ["",
                  f"Mean stated confidence **{s['mean_confidence']}** against mean score "
                  f"**{s['mean_score']}**; mean gap **{s['mean_gap']:+}** "
                  f"(absolute {s['mean_absolute_gap']}). "
                  f"{s['n_overconfident']} of {s['n_scored']} experiments were "
                  f"overconfident by more than 0.15.", "",
                  f"_{s['verdict']}_", ""]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "hypothesis": self.hypothesis,
            "entries": [e.to_dict() for e in sorted(self.entries, key=lambda x: x.order)],
            "calibration": self.calibration_summary(),
        }


def _calibration_verdict(gaps: list[float]) -> str:
    if not gaps:
        return "No scored experiments yet."
    mean = sum(gaps) / len(gaps)
    if mean > 0.2:
        return ("Systematically overconfident: the scientist claimed more certainty "
                "than its results earned.")
    if mean > 0.05:
        return "Mildly overconfident on average."
    if mean < -0.2:
        return ("Systematically underconfident: it did better than it expected to.")
    if mean < -0.05:
        return "Mildly underconfident on average."
    return "Broadly well calibrated across the curriculum."
