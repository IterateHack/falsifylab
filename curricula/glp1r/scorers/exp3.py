"""Score duration-of-action prediction and its mechanistic reasoning (experiment 3).

Half the score is the ordering of the analogues by duration class - an ordering
that is not in scientific dispute - and half is a mechanism checklist, so an
agent cannot score well by pattern-matching known drug names without saying why.
"""
from __future__ import annotations

from typing import Any

from rubric import gather_text, score_rubric, spearman


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def score(answer: Any, ground_truth: dict[str, Any]) -> dict[str, Any]:
    truth_rank = {_norm(k): v for k, v in ground_truth["duration_rank"].items()}
    ranking = answer.get("ranking") if isinstance(answer, dict) else None

    rank_score, rank_detail = 0.0, {}
    if isinstance(ranking, list) and len(ranking) >= 3:
        # The agent submits longest-acting first; position 0 is the longest.
        predicted, actual = [], []
        matched, unmatched = [], []
        for pos, name in enumerate(ranking):
            if not isinstance(name, str):
                continue
            key = _norm(name)
            hit = key if key in truth_rank else next(
                (k for k in truth_rank if k and (k in key or key in k)), None)
            if hit is None:
                unmatched.append(name)
                continue
            matched.append(name)
            predicted.append(-float(pos))          # earlier = longer acting
            actual.append(float(truth_rank[hit]))
        if len(predicted) >= 3:
            rho = spearman(predicted, actual)
            rank_score = max(0.0, rho)
            rank_detail = {"spearman": round(rho, 4), "n_matched": len(matched),
                           "unrecognised_names": unmatched}
        else:
            rank_detail = {"error": "fewer than 3 recognisable analogue names",
                           "unrecognised_names": unmatched}
    else:
        rank_detail = {"error": "answer must contain a 'ranking' list, "
                                "longest-acting first"}

    rub = score_rubric(gather_text(answer), ground_truth["rubric"],
                       ground_truth.get("penalties"))
    final = 0.5 * rank_score + 0.5 * rub["score"]
    return {
        "score": round(final, 4),
        "max": 1.0,
        "details": {
            "ranking_score": round(rank_score, 4),
            "ranking": rank_detail,
            "mechanism_score": rub["score"],
            "mechanism_missed": rub["missed"],
            "mechanism_penalised": rub["penalised"],
            "breakdown": rub["breakdown"],
            "truth_duration_classes": ground_truth["duration_classes"],
        },
    }
