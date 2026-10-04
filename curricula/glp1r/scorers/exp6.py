"""Score the capstone verdict on H1 (experiment 6).

The rubric rewards weighting each evidence strand and grading its own
confidence, and penalises claims that run past the evidence in the curriculum.
"""
from __future__ import annotations

from typing import Any

from rubric import gather_text, score_rubric


def score(answer: Any, ground_truth: dict[str, Any]) -> dict[str, Any]:
    text = gather_text(answer)
    if not text.strip():
        return {"score": 0.0, "max": 1.0, "details": {"error": "empty answer"}}
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
            "reference": ground_truth["reference"],
        },
    }
