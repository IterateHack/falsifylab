"""Score the dependency classification (WRN curriculum, experiment 1).

Three classes, so accuracy alone would reward always guessing the majority.
Scoring is macro-averaged F1 across the three classes, which makes getting the
rare class right matter as much as the common one.
"""
from __future__ import annotations

from typing import Any

CLASSES = ("common_essential", "selective", "non_essential")
ALIASES = {
    "common": "common_essential", "pan-essential": "common_essential",
    "pan_essential": "common_essential", "core_essential": "common_essential",
    "essential": "common_essential",
    "selective_dependency": "selective", "context_specific": "selective",
    "context-specific": "selective", "selective_essential": "selective",
    "non-essential": "non_essential", "none": "non_essential",
    "not_essential": "non_essential", "neutral": "non_essential",
}


def _norm(label: Any) -> str | None:
    if not isinstance(label, str):
        return None
    key = label.strip().lower().replace(" ", "_").replace("-", "_")
    if key in CLASSES:
        return key
    return ALIASES.get(key) or ALIASES.get(label.strip().lower())


def score(answer: Any, ground_truth: dict[str, Any]) -> dict[str, Any]:
    truth = {g.upper(): c for g, c in ground_truth["labels"].items()}
    got = answer.get("classifications") if isinstance(answer, dict) else None
    if not isinstance(got, dict) or not got:
        return {"score": 0.0, "max": 1.0,
                "details": {"error": "answer must contain a 'classifications' object "
                                     "mapping gene symbol to one of "
                                     f"{list(CLASSES)}",
                            "rule": ground_truth["rule"]}}

    predicted: dict[str, str | None] = {}
    for gene, label in got.items():
        if isinstance(gene, str):
            predicted[gene.strip().upper()] = _norm(label)

    per_class: dict[str, dict[str, int]] = {c: {"tp": 0, "fp": 0, "fn": 0} for c in CLASSES}
    correct, wrong, missing = [], [], []
    for gene, want in truth.items():
        have = predicted.get(gene)
        if have is None:
            missing.append(gene)
            per_class[want]["fn"] += 1
            continue
        if have == want:
            correct.append(gene)
            per_class[want]["tp"] += 1
        else:
            wrong.append({"gene": gene, "predicted": have, "actual": want})
            per_class[want]["fn"] += 1
            if have in per_class:
                per_class[have]["fp"] += 1

    f1s = {}
    for c, m in per_class.items():
        denom = 2 * m["tp"] + m["fp"] + m["fn"]
        f1s[c] = (2 * m["tp"] / denom) if denom else 0.0
    macro_f1 = sum(f1s.values()) / len(CLASSES)

    return {
        "score": round(macro_f1, 4),
        "max": 1.0,
        "details": {
            "macro_f1": round(macro_f1, 4),
            "per_class_f1": {c: round(v, 4) for c, v in f1s.items()},
            "accuracy": round(len(correct) / len(truth), 4) if truth else 0.0,
            "n_genes": len(truth),
            "n_correct": len(correct),
            "misclassified": wrong,
            "not_classified": missing,
            "rule": ground_truth["rule"],
        },
    }
