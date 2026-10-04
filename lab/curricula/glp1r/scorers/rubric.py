"""Checklist rubric scoring for the reasoning experiments (plan section 4.4.2).

Deterministic by construction: the same answer text always yields the same
score, because scoring is phrase matching over a fixed checklist rather than a
model judging a model. Rubric items carry required points; penalties subtract
for claims the papers contradict.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalise(text: str) -> str:
    """Lowercase, fold accents and collapse whitespace and dash variants.

    Agents write "β-arrestin", "b-arrestin" and "beta-arrestin" for the same
    thing, and an en dash where a hyphen was expected; none of that should
    change a score.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("β", "beta").replace("ß", "beta")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[‐-―−]", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _hit(text: str, phrases: list[str]) -> str | None:
    for p in phrases:
        if normalise(p) in text:
            return p
    return None


def score_rubric(answer_text: str, rubric: list[dict[str, Any]],
                 penalties: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    text = normalise(answer_text)
    penalties = penalties or []
    total_weight = sum(float(item.get("weight", 1.0)) for item in rubric) or 1.0

    earned = 0.0
    breakdown: list[dict[str, Any]] = []
    for item in rubric:
        weight = float(item.get("weight", 1.0))
        hit = _hit(text, item.get("any_of", []))
        ok = hit is not None
        extra = None
        if ok and item.get("must_also"):
            extra = _hit(text, item["must_also"])
            ok = extra is not None
        if ok:
            earned += weight
        breakdown.append({
            "id": item.get("id", ""),
            "kind": "rubric",
            "weight": weight,
            "awarded": weight if ok else 0.0,
            "matched_on": hit if ok else None,
            "also_matched": extra,
            "points": item.get("points", ""),
        })

    deducted = 0.0
    for pen in penalties:
        weight = float(pen.get("weight", 1.0))
        hit = _hit(text, pen.get("any_of", []))
        excused = _hit(text, pen.get("unless_any_of", [])) if hit else None
        applies = hit is not None and excused is None
        if applies:
            deducted += weight
        breakdown.append({
            "id": pen.get("id", ""),
            "kind": "penalty",
            "weight": weight,
            "awarded": -weight if applies else 0.0,
            "matched_on": hit if applies else None,
            "excused_by": excused,
            "points": pen.get("why", ""),
        })

    fraction = max(0.0, min(1.0, (earned - deducted) / total_weight))
    # Phrase matching can be gamed by listing rubric terms. Record how dense the
    # matches are so the audit can look; no threshold is applied here until one
    # has been calibrated on labelled runs (docs/eval-hygiene.md).
    n_words = len(text.split())
    n_hits = sum(1 for b in breakdown if b["kind"] == "rubric" and b["awarded"] > 0)
    return {
        "score": round(fraction, 4),
        "rubric_density": {"words": n_words, "items_matched": n_hits,
                           "per_100_words": round(100.0 * n_hits / max(n_words, 1), 2)},
        "max": 1.0,
        "earned_weight": round(earned, 3),
        "deducted_weight": round(deducted, 3),
        "total_weight": round(total_weight, 3),
        "breakdown": breakdown,
        "missed": [b["points"] for b in breakdown
                   if b["kind"] == "rubric" and b["awarded"] == 0.0],
        "penalised": [b["points"] for b in breakdown
                      if b["kind"] == "penalty" and b["awarded"] < 0.0],
    }


def gather_text(answer: Any, keys: list[str] | None = None) -> str:
    """Flatten an answer into one searchable string.

    Agents put their reasoning wherever they like - a `reasoning` key, a prose
    `answer`, a list of bullets - so the rubric reads the whole submission
    rather than one blessed field.
    """
    if isinstance(answer, str):
        return answer
    parts: list[str] = []
    if isinstance(answer, dict):
        items = ((k, v) for k, v in answer.items()
                 if keys is None or k in keys)
        for _, v in items:
            parts.append(gather_text(v))
    elif isinstance(answer, (list, tuple)):
        for v in answer:
            parts.append(gather_text(v))
    else:
        parts.append(str(answer))
    return "\n".join(p for p in parts if p)


def spearman(a: list[float], b: list[float]) -> float:
    """Rank correlation without a scipy dependency inside the scorer sandbox."""
    n = len(a)
    if n < 2:
        return 0.0

    def ranks(xs: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: xs[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return num / (da * db) if da and db else 0.0
