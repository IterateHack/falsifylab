"""Golden pass/fail fixtures for every scorer (plan section 9, acceptance criteria).

Each scorer must be deterministic, must give a perfect answer full marks, must
give a deliberately wrong answer a low score, and must not crash on malformed
input. The "naive" cases also check that the pitfall each lesson warns about
actually costs the agent something - a trap nobody falls into teaches nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.scoring import score_answer
from engine.specs import load_curriculum

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def curriculum():
    return load_curriculum(ROOT)


def truth(name: str) -> dict:
    return json.loads((ROOT / "private" / f"{name}.json").read_text())


def run(curriculum, exp_id: str, answer) -> dict:
    return score_answer(curriculum.by_id(exp_id), answer)


# --- exp1: genetic support ------------------------------------------------
def test_exp1_perfect_and_empty(curriculum):
    gt = truth("exp1")
    assert run(curriculum, "exp1_genetic_support",
               {"ranked_genes": gt["validated_targets"]})["score"] == 1.0
    assert run(curriculum, "exp1_genetic_support", {"ranked_genes": []})["score"] == 0.0
    assert run(curriculum, "exp1_genetic_support", {"nope": 1})["score"] == 0.0


def test_exp1_naive_ranking_scores_near_zero(curriculum):
    """Ranking by genetic association score alone is the pitfall in lesson 1."""
    import csv

    with (ROOT / "data" / "exp1_gwas_targets.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    naive = [r["gene"] for r in sorted(
        rows, key=lambda r: -float(r["bmi_genetic_association"] or 0))]
    naive_score = run(curriculum, "exp1_genetic_support",
                      {"ranked_genes": naive})["score"]
    oracle = run(curriculum, "exp1_genetic_support",
                 {"ranked_genes": truth("exp1")["validated_targets"]})["score"]
    assert naive_score < 0.35, "the p-value trap should not score well"
    assert oracle > naive_score + 0.5


def test_exp1_is_case_insensitive_and_ignores_duplicates(curriculum):
    gt = truth("exp1")["validated_targets"]
    messy = [g.lower() for g in gt] + [gt[0]] * 5
    assert run(curriculum, "exp1_genetic_support",
               {"ranked_genes": messy})["score"] == 1.0


# --- exp2: contacts -------------------------------------------------------
def test_exp2_perfect_partial_and_padded(curriculum):
    gt = truth("exp2")["contact_resnums"]
    assert run(curriculum, "exp2_structure_contacts",
               {"contact_residues": gt})["score"] == 1.0

    half = run(curriculum, "exp2_structure_contacts",
               {"contact_residues": gt[: len(gt) // 2]})
    assert 0.6 < half["score"] < 0.75
    assert half["details"]["precision"] == 1.0

    # Listing every receptor residue inflates recall but destroys precision.
    padded = run(curriculum, "exp2_structure_contacts",
                 {"contact_residues": list(range(29, 424))})
    assert padded["details"]["recall"] == 1.0
    assert padded["score"] < 0.25


def test_exp2_accepts_named_residues(curriculum):
    res = run(curriculum, "exp2_structure_contacts",
              {"contact_residues": ["Trp306", "Arg190", "Tyr152"]})
    assert res["details"]["correct"] == [152, 190, 306]


def test_exp2_is_deterministic(curriculum):
    gt = truth("exp2")["contact_resnums"][:20]
    scores = {run(curriculum, "exp2_structure_contacts",
                  {"contact_residues": gt})["score"] for _ in range(3)}
    assert len(scores) == 1


# --- exp3: peptide engineering --------------------------------------------
def test_exp3_perfect_ranking_plus_mechanism(curriculum):
    gt = truth("exp3")
    order = sorted(gt["duration_rank"], key=lambda k: -gt["duration_rank"][k])
    good = {
        "ranking": order,
        "reasoning": (
            "Duration is set by clearance. DPP-4 cleaves between His7 and Ala8, so "
            "Aib8 at position 8 blocks proteolysis. Acylation with a C18 fatty "
            "diacid at Lys26 drives reversible albumin binding, and Fc or albumin "
            "fusion raises molecular size above the renal filtration threshold. "
            "The attachment sits in the mid-region, away from the N-terminus that "
            "engages the receptor core."
        ),
    }
    res = run(curriculum, "exp3_peptide_engineering", good)
    assert res["score"] > 0.95
    assert res["details"]["mechanism_missed"] == []


def test_exp3_reversed_ranking_and_no_mechanism_scores_low(curriculum):
    gt = truth("exp3")
    order = sorted(gt["duration_rank"], key=lambda k: gt["duration_rank"][k])
    res = run(curriculum, "exp3_peptide_engineering",
              {"ranking": order, "reasoning": "Some last longer than others."})
    assert res["score"] < 0.1


def test_exp3_penalises_acylating_the_n_terminus(curriculum):
    gt = truth("exp3")
    order = sorted(gt["duration_rank"], key=lambda k: -gt["duration_rank"][k])
    penalised = run(curriculum, "exp3_peptide_engineering", {
        "ranking": order,
        "reasoning": "N-terminal acylation improves duration, so modify His7. "
                     "Albumin binding via a fatty diacid helps. DPP-4 cleaves Ala8.",
    })
    clean = run(curriculum, "exp3_peptide_engineering", {
        "ranking": order,
        "reasoning": "Albumin binding via a fatty diacid at Lys26 helps. "
                     "DPP-4 cleaves Ala8 so Aib8 blocks it.",
    })
    assert penalised["score"] < clean["score"]


# --- exp4: potency --------------------------------------------------------
def test_exp4_perfect_fit_and_ranking(curriculum):
    gt = truth("exp4")
    res = run(curriculum, "exp4_potency", {
        "fitted_pec50": {m: c["true_pec50"] for m, c in gt["curves"].items()},
        "ranking": gt["ranking_most_to_least_potent"],
    })
    assert res["score"] == 1.0
    assert res["details"]["mean_absolute_error_log_units"] == 0.0


def test_exp4_partial_coverage_is_penalised(curriculum):
    gt = truth("exp4")
    items = list(gt["curves"].items())[:4]
    res = run(curriculum, "exp4_potency", {
        "fitted_pec50": {m: c["true_pec50"] for m, c in items},
        "ranking": gt["ranking_most_to_least_potent"],
    })
    assert res["details"]["coverage"] < 0.35
    assert res["details"]["fit_score"] < 0.35


def test_exp4_biased_fits_lose_points(curriculum):
    """A half-log-unit bias is roughly what the naive midpoint estimate costs."""
    gt = truth("exp4")
    res = run(curriculum, "exp4_potency", {
        "fitted_pec50": {m: c["true_pec50"] + 0.55 for m, c in gt["curves"].items()},
        "ranking": gt["ranking_most_to_least_potent"],
    })
    assert 0.5 < res["score"] < 0.75
    assert res["details"]["mean_absolute_error_log_units"] == pytest.approx(0.55, abs=1e-6)


def test_exp4_handles_string_numbers_and_junk(curriculum):
    gt = truth("exp4")
    res = run(curriculum, "exp4_potency", {
        "fitted_pec50": {m: str(c["true_pec50"]) for m, c in gt["curves"].items()},
        "ranking": gt["ranking_most_to_least_potent"],
    })
    assert res["score"] == 1.0
    assert run(curriculum, "exp4_potency", {"fitted_pec50": "nonsense"})["score"] == 0.0


# --- exp5: species selectivity --------------------------------------------
def test_exp5_good_answer_scores_high(curriculum):
    res = run(curriculum, "exp5_small_molecule_feasibility", {
        "assay_model": "Recombinant human GLP-1R in a cAMP accumulation assay, with "
                       "a parallel beta-arrestin recruitment readout.",
        "prediction": "A non-peptide agonist can work, but not at the orthosteric "
                      "peptide site - it must act at a distinct site involving the "
                      "extracellular domain. Expect partial agonism biased to "
                      "G protein signalling.",
        "default_choice_outcome": "A wild-type mouse model would show no effect, "
                                  "because residue 33 is Trp33 in human and Ser in "
                                  "rodents; that is a false negative, not an inactive "
                                  "compound.",
        "reasoning": "Experiment 2 showed the peptide interface spans 40 residues.",
    })
    assert res["score"] > 0.9


def test_exp5_rodent_default_is_penalised(curriculum):
    res = run(curriculum, "exp5_small_molecule_feasibility", {
        "assay_model": "Use a diet-induced obese mouse model and measure weight loss.",
        "prediction": "The compound should work as a full agonist.",
        "reasoning": "Mice are the standard obesity model.",
    })
    assert res["score"] < 0.15
    assert res["details"]["penalised"], "the rodent trap must apply a penalty"


def test_exp5_rodent_mention_is_excused_when_rejected(curriculum):
    """Naming the rodent model in order to reject it must not be penalised."""
    res = run(curriculum, "exp5_small_molecule_feasibility", {
        "assay_model": "Recombinant human GLP-1R, cAMP readout.",
        "prediction": "Works at an allosteric site; partial agonist.",
        "default_choice_outcome": "A diet-induced obese mouse would be unsuitable "
                                  "and would fail because of Trp33.",
        "reasoning": "humanized knock-in would be needed for in vivo work.",
    })
    assert not res["details"]["penalised"]
    assert res["score"] > 0.9


# --- exp6: capstone -------------------------------------------------------
def test_exp6_weighted_verdict_scores_high(curriculum):
    res = run(curriculum, "exp6_capstone", {
        "verdict": "H1 is supported, with uneven confidence across its three claims.",
        "per_claim": {
            "genetically_supported": "Strong: GWAS evidence at GLP1R and GIPR.",
            "druggable": "Strong: the 7KI0 structure and approved peptide agonists.",
            "oral_non_peptide_feasible": "Strong: orforglipron, an oral small molecule, "
                                         "reached a phase 3 endpoint.",
        },
        "not_established": "No cardiovascular outcome benefit is established, and "
                           "durability after discontinuation remains open.",
        "would_change_my_mind": "A failed replication of the oral agent.",
        "reasoning": "Structural contact residues, half-life engineering via albumin "
                     "binding, EC50 potency ranking, and the rodent Trp33 species "
                     "caveat all feed in. Confidence is a limitation worth stating.",
    })
    assert res["score"] > 0.9


def test_exp6_overclaiming_is_penalised(curriculum):
    strong = ("The hypothesis is supported. Genetic GWAS evidence, the 7KI0 structure, "
              "albumin half-life engineering, EC50 potency and the oral non-peptide "
              "orforglipron result all agree, with a species caveat about rodents. "
              "My confidence is limited by...")
    clean = run(curriculum, "exp6_capstone", {"reasoning": strong})
    over = run(curriculum, "exp6_capstone", {
        "reasoning": strong + " It also cures obesity and has proven cardiovascular "
                              "benefit."})
    assert over["score"] < clean["score"]


def test_exp6_empty_answer_scores_zero(curriculum):
    assert run(curriculum, "exp6_capstone", {})["score"] == 0.0


# --- cross-cutting --------------------------------------------------------
@pytest.mark.parametrize("exp_id", [
    "exp1_genetic_support", "exp2_structure_contacts", "exp3_peptide_engineering",
    "exp4_potency", "exp5_small_molecule_feasibility", "exp6_capstone",
])
def test_every_scorer_survives_junk(curriculum, exp_id):
    for junk in ({}, {"answer": None}, {"ranking": "not a list"}, []):
        res = run(curriculum, exp_id, junk)
        assert 0.0 <= res["score"] <= 1.0
