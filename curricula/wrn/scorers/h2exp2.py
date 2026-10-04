"""Score the lineage analysis of WRN dependency (WRN curriculum, experiment 2).

Half the score is whether the agent found the right lineages; half is whether it
explains them correctly. Finding that WRN dependency concentrates in uterus and
intestine is the easy part - saying that lineage is a proxy for microsatellite
instability, rather than the cause, is the lesson.
"""
from __future__ import annotations

from typing import Any

from rubric import gather_text, score_rubric, spearman

TOP_N = 5


def score(answer: Any, ground_truth: dict[str, Any]) -> dict[str, Any]:
    truth_order = ground_truth["ranking_most_to_least_dependent"]
    index = {t.lower(): i for i, t in enumerate(truth_order)}

    ranking = answer.get("top_tissues") if isinstance(answer, dict) else None
    rank_score, rank_detail = 0.0, {}
    if isinstance(ranking, list) and len(ranking) >= 3:
        pred, act, unknown = [], [], []
        for pos, name in enumerate(ranking[:TOP_N * 2]):
            if not isinstance(name, str):
                continue
            key = name.strip().lower()
            hit = key if key in index else next(
                (t for t in index if t in key or key in t), None)
            if hit is None:
                unknown.append(name)
                continue
            pred.append(float(pos))
            act.append(float(index[hit]))
        if len(pred) >= 3:
            rho = spearman(pred, act)
            # Also reward simply identifying the right set, not just the order.
            named = {t for t in index if any(
                t in str(x).lower() or str(x).lower() in t for x in ranking[:TOP_N])}
            overlap = len(named & set(truth_order[:TOP_N])) / TOP_N
            rank_score = max(0.0, 0.5 * max(0.0, rho) + 0.5 * overlap)
            rank_detail = {"spearman": round(rho, 4),
                           "top_set_overlap": round(overlap, 4),
                           "unrecognised": unknown}
        else:
            rank_detail = {"error": "fewer than 3 recognisable tissue names",
                           "unrecognised": unknown}
    else:
        rank_detail = {"error": "answer must contain a 'top_tissues' list, "
                                "most dependent first"}

    rub = score_rubric(gather_text(answer), ground_truth["rubric"],
                       ground_truth.get("penalties"))
    final = 0.5 * rank_score + 0.5 * rub["score"]
    return {
        "score": round(final, 4),
        "max": 1.0,
        "details": {
            "ranking_score": round(rank_score, 4),
            "ranking": rank_detail,
            "explanation_score": rub["score"],
            "explanation_missed": rub["missed"],
            "explanation_penalised": rub["penalised"],
            "breakdown": rub["breakdown"],
            "rubric_density": rub["rubric_density"],
            "true_top_tissues": ground_truth["top_tissues"],
        },
    }
