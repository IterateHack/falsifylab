"""Score the peptide-receptor contact set (experiment 2).

Fully deterministic: ground truth is recomputed from PDB 7KI0 by the fetcher at
a fixed 4.0 A heavy-atom cutoff, and the agent's residue set is compared to it
by F1. Precision and recall are both reported because the two failure modes
differ - listing the whole binding region inflates recall, listing three famous
residues inflates precision.
"""
from __future__ import annotations

import re
from typing import Any


def _as_resnums(value: Any) -> list[int]:
    out: list[int] = []
    if isinstance(value, list):
        for v in value:
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                out.append(v)
            elif isinstance(v, float) and v.is_integer():
                out.append(int(v))
            elif isinstance(v, str):
                # accepts "Trp306", "W306", "306", "Arg 190"
                m = re.search(r"(\d+)", v)
                if m:
                    out.append(int(m.group(1)))
            elif isinstance(v, dict):
                for key in ("resnum", "residue_number", "position", "number"):
                    if key in v:
                        out.extend(_as_resnums([v[key]]))
                        break
    return out


def score(answer: Any, ground_truth: dict[str, Any]) -> dict[str, Any]:
    truth = set(int(x) for x in ground_truth["contact_resnums"])
    raw = answer.get("contact_residues") if isinstance(answer, dict) else None
    predicted = set(_as_resnums(raw))
    if not predicted:
        return {
            "score": 0.0, "max": 1.0,
            "details": {"error": "answer must contain 'contact_residues' as a list of "
                                 "GLP-1R residue numbers",
                        "definition": ground_truth["definition"]},
        }
    tp = predicted & truth
    precision = len(tp) / len(predicted)
    recall = len(tp) / len(truth)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "score": round(f1, 4),
        "max": 1.0,
        "details": {
            "f1": round(f1, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "n_predicted": len(predicted),
            "n_truth": len(truth),
            "correct": sorted(tp),
            "false_positives": sorted(predicted - truth),
            "missed": sorted(truth - predicted),
            "definition": ground_truth["definition"],
        },
    }
