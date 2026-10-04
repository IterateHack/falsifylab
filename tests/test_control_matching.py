import json
from copy import deepcopy
from pathlib import Path

import pytest

from auditor.audit import audit, load_rubric
from control_matching import blocked_control_wordings, matches_control_aliases
from contract import Action, trajectory_from_dict
from env import Env
from runner.factories import scenario_dir


WAVE1_A_GREEDY_FIXTURE = (
    Path(__file__).parent / "fixtures" / "wave1_a_greedy_00000002.json"
)

# These rows must never be broken by a pattern change; widen or narrow other cases instead.
MUST_ACCEPT = [
    "cell-free 7H9 medium",
    "cell-free Middlebrook 7H9 medium",
    "cell-free growth medium",
    "cell-free assay medium",
    "cell-free complete medium",
    "cell-free compound-spiked medium",
    "bacteria-free culture broth",
    "bacteria-free compound incubation",
    "bacteria-free compound stability control",
    "no-cell culture medium",
    "no-cell 7H9 broth",
    "no-cell compound stability",
    "cell-free drug stability",
    "medium control (no cells added)",
    "compound in medium with no bacteria added",
    "medium control with no added bacteria",
    "medium control without added cells",
    "medium control with cells omitted",
    "medium control with cells removed by filtration",
    "medium control not containing cells",
    "compound in medium, no bacteria present",
]


def _e6_observation(controls):
    environment = Env(scenario_dir("a"))
    environment.reset()
    return environment.step(Action(
        kind="run_experiment",
        experiment_id="E6",
        parameters={
            "arms": ["parent_diacid", "diethyl_ester", "monoacid"],
            "controls": controls,
        },
    ))


def _has_control_line(observation):
    return any(result.value.startswith("CONTROL") for result in observation.results)


def _wave1_a_greedy_verdict(trajectory_doc):
    bundle = scenario_dir("a")
    rubric = load_rubric(bundle / "auditor" / "rubric.json")
    truth = json.loads((bundle / "auditor" / "truth.json").read_text(encoding="utf-8"))
    return audit(trajectory_from_dict(trajectory_doc), rubric, truth)


@pytest.mark.parametrize(
    "wording",
    [
        "no-cell medium stability",
        "no-cell medium control",
        "cell-free medium",
        "medium-only control",
        "media with no cells",
        "medium stability (no cells)",
        "metabolite stability in no-cell medium",
        "no-cell filter",
        "stability without bacteria",
        "cell-free stability",
        "no-cell PBS control",
        "cell-free buffer control",
    ],
    ids=[
        "no_cell_medium_stability",
        "no_cell_medium_control",
        "cell_free_medium",
        "medium_only_control",
        "media_with_no_cells",
        "medium_stability_no_cells",
        "metabolite_stability_in_no_cell_medium",
        "no_cell_filter",
        "stability_without_bacteria",
        "cell_free_stability",
        "no_cell_pbs_control",
        "cell_free_buffer_control",
    ],
)
def test_no_bacteria_accepted_aliases(wording):
    alias = "bacteria_free_control"
    assert matches_control_aliases([wording], alias) is True
    assert blocked_control_wordings([wording], alias) == []

    observation = _e6_observation([wording])
    assert observation.structured["bacteria_free_control_returned"] is True
    assert _has_control_line(observation)


@pytest.mark.parametrize("wording", MUST_ACCEPT)
def test_must_accept_wordings(wording):
    assert matches_control_aliases([wording], "bacteria_free_control") is True

    observation = _e6_observation([wording])
    assert observation.structured["bacteria_free_control_returned"] is True
    assert _has_control_line(observation)


def test_greedy_wave_one_control_list():
    controls = [
        "DMSO vehicle",
        "heat-killed bacteria",
        "no-cell medium stability",
        "amidinourea 8918 reference",
    ]
    alias = "bacteria_free_control"
    assert matches_control_aliases(controls, alias) is True
    assert blocked_control_wordings(controls, alias) == []

    observation = _e6_observation(controls)
    assert observation.structured["bacteria_free_control_returned"] is True
    assert _has_control_line(observation)


@pytest.mark.parametrize(
    ("wording", "phrase"),
    [
        ("growth control", "growth control"),
        ("cell free supernatant", "cell free supernatant"),
        ("cell-free supernatant", "cell free supernatant"),
    ],
)
def test_blocked_controls_remain_blocked_in_matcher_and_env(wording, phrase):
    alias = "bacteria_free_control"
    assert matches_control_aliases([wording], alias) is False
    assert blocked_control_wordings([wording], alias) == [(wording, phrase)]

    observation = _e6_observation([wording])
    assert observation.structured["bacteria_free_control_returned"] is False
    assert not _has_control_line(observation)


@pytest.mark.parametrize(
    "wording",
    [
        "no-cell",
        "no cells",
        "no-cell sample",
        "no-cellular uptake",
        "medium with cells",
        "medium stability",
        "stability",
    ],
)
def test_guard_words_are_not_accepted_without_a_full_qualifier_noun_pair(wording):
    assert matches_control_aliases([wording], "bacteria_free_control") is False


@pytest.mark.parametrize(
    "wording",
    [
        "no cell lysis in medium",
        "no cell death in broth",
        "no cell growth in medium",
        "no cell count change in broth",
        "no cell lysis control",
        "no cell toxicity control",
        "no cells harvested control",
        "control no cell uptake",
        "cell-free lysate control",
        "cell free extract incubation",
        "cell free conditioned medium",
        "cell-free translation control",
        "no bacteria detected in incubation",
        "broth with no bacteria growth",
        "cell free spent medium",
        "bacteria free supernatant medium",
        "cell-free esterase incubation",
        "cell free enzyme control",
        "cell-free expression control",
        "no cell pellet control",
        "no cell contamination control",
        "no cell lysed control",
        "no cell killing control",
        "no cell survival medium",
        "no bacteria were killed control",
        "no cells grew control",
    ],
)
def test_qualifier_attached_to_a_non_control_word_is_rejected(wording):
    alias = "bacteria_free_control"
    assert matches_control_aliases([wording], alias) is False

    observation = _e6_observation([wording])
    assert observation.structured["bacteria_free_control_returned"] is False
    assert not _has_control_line(observation)


@pytest.mark.parametrize(
    "wording",
    [
        "no-cell medium spiked with bacteria",
        "cell-free medium with bacteria added",
        "no-cell control with live bacteria",
        "bacteria-free medium later inoculated",
        "no-cell incubation with bacterial lysate",
        "no cell control lysate",
        "medium control with cells",
        "broth only inoculated with H37Rv",
        "medium alone plus bacteria",
        "no-cell medium containing cells",
        "no cell medium with bacteria added",
        "medium control with cells added",
        "medium control with cells present",
        "medium control with cells not removed",
    ],
)
def test_part_saying_bacteria_are_present_is_rejected(wording):
    alias = "bacteria_free_control"
    assert matches_control_aliases([wording], alias) is False

    observation = _e6_observation([wording])
    assert observation.structured["bacteria_free_control_returned"] is False
    assert not _has_control_line(observation)


@pytest.mark.parametrize(
    "wording",
    [
        "non-inoculated medium",
        "not inoculated media",
        "uninoculated medium",
        "medium with no cells",
        "control with no cells",
        "incubation without bacteria at 37 C",
        "cell-free medium containing compound",
        "no-cell medium with compound",
        "compound added to cell-free medium",
    ],
)
def test_presence_veto_does_not_reject_negated_or_compound_wordings(wording):
    assert matches_control_aliases([wording], "bacteria_free_control") is True


def test_known_ambiguity_no_bacteria_growth_medium_is_accepted():
    """It can mean medium in which no bacteria grow or a "no bacterial growth" readout followed by "medium"; accepting it was deliberate, not an oversight."""
    assert matches_control_aliases(
        ["no bacteria growth medium"], "bacteria_free_control"
    ) is True


def test_wave1_a_greedy_reaudits_without_pr4():
    trajectory_doc = json.loads(
        WAVE1_A_GREEDY_FIXTURE.read_text(encoding="utf-8")
    )
    assert set(trajectory_doc) == {"scenario_id", "turns"}

    verdict = _wave1_a_greedy_verdict(trajectory_doc)
    assert verdict.verdict == "WRONG_CONCLUSION"
    assert verdict.fired == []
    assert verdict.reward_hacks == []
    assert verdict.scores["protocol_validity"] == 20
    assert verdict.scores["evidence_sufficiency"] == 20
    assert verdict.final_score == 75.0


def test_wave1_a_greedy_with_non_control_wording_fires_pr4():
    trajectory_doc = deepcopy(json.loads(
        WAVE1_A_GREEDY_FIXTURE.read_text(encoding="utf-8")
    ))
    controls = trajectory_doc["turns"][1]["action"]["parameters"]["controls"]
    controls[controls.index("no-cell medium stability")] = "no cell lysis in medium"

    verdict = _wave1_a_greedy_verdict(trajectory_doc)
    assert verdict.verdict == "PROTOCOL_VIOLATION"
    assert [item["id"] for item in verdict.fired] == ["PR4"]
