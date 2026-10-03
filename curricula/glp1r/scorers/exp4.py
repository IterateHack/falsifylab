"""Score dose-response fitting and the consensus potency ranking (experiment 4).

Two halves, because they test different things. The fitted pEC50 values test
whether the agent actually fitted a curve - truncated curves and varying Emax
make the eyeball estimate biased by roughly half a log unit. The ranking tests
whether it aggregated the messy ChEMBL table sensibly: on the log scale, with
censored records and binding assays excluded.
"""
from __future__ import annotations

from typing import Any

from rubric import spearman

TOLERANCE_LOG = 0.7      # a fit this far out scores zero on the error term


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def score(answer: Any, ground_truth: dict[str, Any]) -> dict[str, Any]:
    curves = ground_truth["curves"]
    truth_order = ground_truth["ranking_most_to_least_potent"]

    if not isinstance(answer, dict):
        return {"score": 0.0, "max": 1.0,
                "details": {"error": "answer must be an object"}}

    # --- half 1: fitted pEC50 accuracy -----------------------------------
    fitted = answer.get("fitted_pec50") or {}
    errors: dict[str, float] = {}
    if isinstance(fitted, dict):
        for mol, truth in curves.items():
            got = _num(fitted.get(mol))
            if got is None:
                continue
            errors[mol] = abs(got - float(truth["true_pec50"]))
    if errors:
        mae = sum(errors.values()) / len(errors)
        coverage = len(errors) / len(curves)
        fit_score = max(0.0, 1.0 - mae / TOLERANCE_LOG) * coverage
    else:
        mae, coverage, fit_score = float("nan"), 0.0, 0.0

    # --- half 2: consensus ranking ----------------------------------------
    ranking = answer.get("ranking")
    rank_score, rank_detail = 0.0, {}
    if isinstance(ranking, list) and len(ranking) >= 3:
        idx_truth = {m: i for i, m in enumerate(truth_order)}
        pred, act, unknown = [], [], []
        for pos, mol in enumerate(ranking):
            if not isinstance(mol, str):
                continue
            key = mol.strip()
            if key not in idx_truth:
                match = next((m for m in idx_truth if m.lower() == key.lower()), None)
                if match is None:
                    unknown.append(mol)
                    continue
                key = match
            pred.append(float(pos))
            act.append(float(idx_truth[key]))
        if len(pred) >= 3:
            rho = spearman(pred, act)
            rank_score = max(0.0, rho)
            rank_detail = {"spearman": round(rho, 4), "n_matched": len(pred),
                           "unrecognised": unknown}
        else:
            rank_detail = {"error": "fewer than 3 recognisable molecule ids",
                           "unrecognised": unknown}
    else:
        rank_detail = {"error": "answer must contain a 'ranking' list of "
                                "molecule_chembl_id, most potent first"}

    final = 0.5 * fit_score + 0.5 * rank_score
    return {
        "score": round(final, 4),
        "max": 1.0,
        "details": {
            "fit_score": round(fit_score, 4),
            "mean_absolute_error_log_units": round(mae, 4) if errors else None,
            "n_molecules_fitted": len(errors),
            "n_molecules_expected": len(curves),
            "coverage": round(coverage, 4),
            "per_molecule_abs_error": {k: round(v, 3) for k, v in sorted(errors.items())},
            "worst_fit": (max(errors, key=errors.get) if errors else None),
            "ranking_score": round(rank_score, 4),
            "ranking": rank_detail,
            "tolerance_log_units": TOLERANCE_LOG,
            "protocol": ground_truth["protocol"],
            "truncated_curves": [m for m, c in curves.items() if c["curve_truncated"]],
            "consensus_pec50": ground_truth["consensus_pec50"],
        },
    }
