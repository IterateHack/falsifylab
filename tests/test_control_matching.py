import pytest

from control_matching import blocked_control_wordings, matches_control_aliases
from contract import Action
from env import Env
from runner.factories import scenario_dir


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


@pytest.mark.parametrize(
    "wording",
    [
        "no-cell medium stability",
        "no-cell medium control",
        "cell-free medium",
        "medium-only control",
    ],
    ids=[
        "no_cell_medium_stability",
        "no_cell_medium_control",
        "cell_free_medium",
        "medium_only_control",
    ],
)
def test_no_bacteria_accepted_aliases(wording):
    alias = "bacteria_free_control"
    assert matches_control_aliases([wording], alias) is True
    assert blocked_control_wordings([wording], alias) == []

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
