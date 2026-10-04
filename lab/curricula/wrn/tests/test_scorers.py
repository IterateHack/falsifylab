"""Golden fixtures for the WRN curriculum's scorers."""
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


def test_h2exp1_perfect(curriculum):
    gt = truth("h2exp1")
    res = run(curriculum, "h2exp1_dependency_classes",
              {"classifications": gt["labels"]})
    assert res["score"] == 1.0


def test_h2exp1_accepts_aliases_and_case(curriculum):
    gt = truth("h2exp1")
    alias = {"common_essential": "Pan-essential", "selective": "context-specific",
             "non_essential": "Non-Essential"}
    res = run(curriculum, "h2exp1_dependency_classes",
              {"classifications": {g.lower(): alias[c] for g, c in gt["labels"].items()}})
    assert res["score"] == 1.0


def test_h2exp1_majority_guess_scores_poorly(curriculum):
    """Macro-F1 is used precisely so this does not work."""
    gt = truth("h2exp1")
    res = run(curriculum, "h2exp1_dependency_classes",
              {"classifications": {g: "non_essential" for g in gt["labels"]}})
    assert res["score"] < 0.25


def test_h2exp1_median_ranking_trap(curriculum):
    """Classifying by median gene effect alone misses selective dependencies."""
    gt = truth("h2exp1")
    med = gt["median_gene_effect"]
    naive = {
        g: ("common_essential" if med[g] <= -1.0
            else "selective" if med[g] <= -0.4
            else "non_essential")
        for g in gt["labels"]
    }
    res = run(curriculum, "h2exp1_dependency_classes", {"classifications": naive})
    perfect = run(curriculum, "h2exp1_dependency_classes",
                  {"classifications": gt["labels"]})["score"]
    assert res["score"] <= 0.8, "the median trap should cost real points"
    assert perfect >= res["score"] + 0.2
    # The damage is concentrated where it matters: the selective class, which is
    # the only one worth drugging.
    assert res["details"]["per_class_f1"]["selective"] <= 0.6
    # And it mislabels WRN itself - the gene the whole hypothesis is about.
    assert any(m["gene"] == "WRN" and m["predicted"] == "non_essential"
               for m in res["details"]["misclassified"])


def test_h2exp1_rejects_malformed(curriculum):
    for junk in ({}, {"classifications": "nope"}, {"classifications": {}}, []):
        assert run(curriculum, "h2exp1_dependency_classes", junk)["score"] == 0.0


def test_h2exp2_good_answer(curriculum):
    gt = truth("h2exp2")
    res = run(curriculum, "h2exp2_lineage_confounder", {
        "top_tissues": gt["ranking_most_to_least_dependent"][:5],
        "explanation": "WRN dependency concentrates in uterus and intestine, which "
                       "are the lineages enriched in microsatellite instability. "
                       "Lineage is a proxy for MMR-deficient MSI status, not the "
                       "cause. This is a synthetic lethal relationship: expanded "
                       "TA-repeat secondary structures require WRN helicase to "
                       "resolve them.",
        "next_test": "Annotate MSI status per cell line and test within lineage.",
    })
    assert res["score"] > 0.9


def test_h2exp2_tissue_as_cause_is_penalised(curriculum):
    gt = truth("h2exp2")
    res = run(curriculum, "h2exp2_lineage_confounder", {
        "top_tissues": gt["ranking_most_to_least_dependent"][:5],
        "explanation": "The tissue of origin is the cause of the dependency - "
                       "colorectal cancer causes WRN dependence.",
    })
    assert res["details"]["explanation_penalised"]
    # The ranking half can still be earned - the observation was right. The
    # interpretation half goes to zero, which is the whole point of the lesson.
    assert res["details"]["explanation_score"] == 0.0
    assert res["score"] <= 0.5


def test_h2exp2_right_tissues_wrong_reason_loses_half(curriculum):
    """Finding the lineages is the easy half; the explanation is the lesson."""
    gt = truth("h2exp2")
    res = run(curriculum, "h2exp2_lineage_confounder", {
        "top_tissues": gt["ranking_most_to_least_dependent"][:5],
        "explanation": "These tissues depend on WRN more than others.",
    })
    assert res["details"]["ranking_score"] > 0.9
    assert res["details"]["explanation_score"] < 0.2
    assert 0.4 < res["score"] < 0.6


def test_h2exp2_rejects_malformed(curriculum):
    for junk in ({}, {"top_tissues": "nope"}, []):
        assert 0.0 <= run(curriculum, "h2exp2_lineage_confounder", junk)["score"] <= 1.0
