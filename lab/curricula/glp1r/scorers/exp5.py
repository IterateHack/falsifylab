"""Score the small-molecule feasibility judgement (experiment 5).

A checklist rubric, because the deliverable is a design decision and a
prediction rather than a number. The heaviest penalty is for choosing an
unmodified rodent model: orforglipron depends on human Trp33, which mouse and
rat replace with Ser, so a rodent experiment would read as "the compound does
not work" when in fact the model was wrong.
"""
from __future__ import annotations

from typing import Any

from rubric import gather_text, score_rubric


def score(answer: Any, ground_truth: dict[str, Any]) -> dict[str, Any]:
    text = gather_text(answer)
    if not text.strip():
        return {"score": 0.0, "max": 1.0,
                "details": {"error": "empty answer"}}
    rub = score_rubric(text, ground_truth["rubric"], ground_truth.get("penalties"))
    return {
        "score": rub["score"],
        "max": 1.0,
        "details": {
            "earned_weight": rub["earned_weight"],
            "deducted_weight": rub["deducted_weight"],
            "total_weight": rub["total_weight"],
            "missed": rub["missed"],
            "penalised": rub["penalised"],
            "breakdown": rub["breakdown"],
            "rubric_density": rub["rubric_density"],
            "residue_33_by_species": ground_truth["residue_33_by_species"],
        },
    }
