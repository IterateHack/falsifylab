"""Score the genetic-support ranking (experiment 1).

The agent ranks candidate genes by how promising they are as drug targets. We
measure precision in the head of the ranking against the set of genes with an
approved medicine, and normalise against the base rate so that a score of 0
means "no better than ranking at random".
"""
from __future__ import annotations

from typing import Any

K = 15


def score(answer: Any, ground_truth: dict[str, Any]) -> dict[str, Any]:
    validated = {g.upper() for g in ground_truth["validated_targets"]}
    n_candidates = int(ground_truth["n_candidates"])
    base_rate = len(validated) / n_candidates if n_candidates else 0.0

    ranked = answer.get("ranked_genes") if isinstance(answer, dict) else None
    if not isinstance(ranked, list) or not ranked:
        return {
            "score": 0.0, "max": 1.0,
            "details": {"error": "answer must contain a non-empty 'ranked_genes' list"},
        }
    seen: set[str] = set()
    clean: list[str] = []
    for g in ranked:
        if not isinstance(g, str):
            continue
        u = g.strip().upper()
        if u and u not in seen:
            seen.add(u)
            clean.append(u)

    head = clean[:K]
    hits = [g for g in head if g in validated]
    precision_at_k = len(hits) / len(head) if head else 0.0

    # Average precision over the first 2K entries: rewards putting the right
    # genes early, not merely including them.
    ap_num, found = 0.0, 0
    for i, g in enumerate(clean[:2 * K], start=1):
        if g in validated:
            found += 1
            ap_num += found / i
    denom = min(len(validated), 2 * K)
    average_precision = ap_num / denom if denom else 0.0

    def lift(x: float) -> float:
        if base_rate >= 1.0:
            return 1.0
        return max(0.0, min(1.0, (x - base_rate) / (1.0 - base_rate)))

    final = 0.6 * lift(precision_at_k) + 0.4 * lift(average_precision)
    return {
        "score": round(final, 4),
        "max": 1.0,
        "details": {
            "k": K,
            "precision_at_k": round(precision_at_k, 4),
            "average_precision": round(average_precision, 4),
            "base_rate": round(base_rate, 4),
            "normalised_precision": round(lift(precision_at_k), 4),
            "normalised_average_precision": round(lift(average_precision), 4),
            "n_ranked": len(clean),
            "hits_in_head": hits,
            "missed_validated": sorted(validated - set(head)),
            "criterion": ground_truth["criterion"],
        },
    }
