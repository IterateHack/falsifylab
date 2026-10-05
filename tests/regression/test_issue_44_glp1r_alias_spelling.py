"""Issue #44: the WRN h2exp2 ranking scorer recognised a tissue only when its
name matched an Open Targets label (exact or substring), so a ranking that put
the gold tissues first in clinical wording ("Endometrium/Uterus", "Large
intestine (colorectal)") scored 0 on the ranking half.

Direction: false positive (correct answer scored 0; a string gate on vocabulary).
The exposing case cannot be rescored: lab/curricula/wrn was deleted with its
scorer (commit 77b782a), so #44 is retired. These tests pin the same bug class
on the GLP-1R scorers that still match names: exp1 (gene symbols), exp3
(analogue names) and exp4 (ChEMBL molecule ids). The expected scores are
derived from the scorer's own answer to the canonical spelling, not hard-coded.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

GLP1R = Path(__file__).resolve().parents[2] / "lab" / "curricula" / "glp1r"
SCORERS = GLP1R / "scorers"


def _scorer(name):
    # Scorers import their sibling `rubric` by bare name, as the lab engine runs them.
    if str(SCORERS) not in sys.path:
        sys.path.insert(0, str(SCORERS))
    spec = importlib.util.spec_from_file_location(f"glp1r_scorer_{name}", SCORERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _truth(name):
    return json.loads((GLP1R / "private" / f"{name}.json").read_text(encoding="utf-8"))


def test_exp1_gene_symbols_match_regardless_of_case_and_whitespace():
    exp1, truth = _scorer("exp1"), _truth("exp1")
    canonical = sorted(truth["validated_targets"])
    expected = exp1.score({"ranked_genes": canonical}, truth)
    assert expected["score"] == 1.0
    respelled = [g.lower() if i % 2 else f" {g.title()} " for i, g in enumerate(canonical)]
    got = exp1.score({"ranked_genes": respelled}, truth)
    assert got["score"] == expected["score"]
    assert got["details"]["hits_in_head"] == expected["details"]["hits_in_head"]
    assert got["details"]["n_ranked"] == len(canonical)


@pytest.mark.parametrize("respell", [
    str.lower, str.upper,
    lambda s: s.replace("-", " "),
    lambda s: f"{s} (weekly)" if s == "Semaglutide" else s,
], ids=["lower", "upper", "hyphen_to_space", "parenthetical_suffix"])
def test_exp3_analogue_names_match_in_alternative_spellings(respell):
    exp3, truth = _scorer("exp3"), _truth("exp3")
    canonical = sorted(truth["duration_rank"], key=lambda k: -truth["duration_rank"][k])
    expected = exp3.score({"ranking": canonical, "explanation": ""}, truth)
    assert expected["details"]["ranking"]["unrecognised_names"] == []
    assert expected["details"]["ranking_score"] > 0

    got = exp3.score({"ranking": [respell(n) for n in canonical], "explanation": ""}, truth)
    assert got["details"]["ranking"]["unrecognised_names"] == []
    assert got["details"]["ranking_score"] == expected["details"]["ranking_score"]


def test_exp4_molecule_ids_match_case_insensitively():
    exp4, truth = _scorer("exp4"), _truth("exp4")
    canonical = truth["ranking_most_to_least_potent"]
    expected = exp4.score({"ranking": canonical, "fitted_pec50": {}}, truth)
    assert expected["details"]["ranking"]["unrecognised"] == []

    got = exp4.score({"ranking": [m.lower() for m in canonical], "fitted_pec50": {}}, truth)
    assert got["details"]["ranking"]["unrecognised"] == []
    assert got["details"]["ranking"]["spearman"] == expected["details"]["ranking"]["spearman"]
