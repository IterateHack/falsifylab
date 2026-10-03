"""Falsification variant: the LLM harness, the prompt, and the scripted control.

Nothing here asserts on readout prose. The live-Env tests check action-side
facts (what was bought, what was declared, what the budget did) so the suite
stays free of scenario answers.
"""
import json

import pytest

from pathlib import Path

from agents.llm_agent import LLMAgent, ParseFailure
from agents.scripted.falsification import FalsificationAgent
from contract import Action
from env import Env, EnvRejection


PROMPT = Path(__file__).resolve().parents[2] / "agents" / "prompts" / "falsification.md"


def load_prompt() -> str:
    return PROMPT.read_text(encoding="utf-8")


class StubClient:
    """Returns canned replies in order and records the prompts it was given."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def __call__(self, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append((system_prompt, user_prompt))
        return self.replies.pop(0) if self.replies else "not json"


BELIEFS = {"H1": 0.1, "H2": 0.1, "H3": 0.6, "H4": 0.8}


def _reply(**overrides) -> str:
    doc = {"beliefs": dict(BELIEFS), "dominant_cause": "H4", "kind": "run_experiment",
           "experiment_id": "E1",
           "parameters": {"buffer": "hepes_without_stabilisers", "coa_mM": 1.0,
                          "compound_uM": 50.0}}
    doc.update(overrides)
    return json.dumps(doc)


def _agent(*replies: str, retries: int = 1) -> LLMAgent:
    return LLMAgent(system_prompt="SYSTEM", model_client=StubClient(*replies), max_retries=retries)


def _parse(reply: str):
    return _agent().parse(reply, Env().state)


# --- parsing ------------------------------------------------------------------
def test_run_experiment_reply_becomes_an_action():
    env = Env()
    agent = _agent(_reply())
    action = agent.act(env.reset(), env.state)
    assert action.kind == "run_experiment"
    assert action.experiment_id == "E1"
    assert action.beliefs == BELIEFS
    assert action.dominant_cause == "H4"
    assert action.parameters["coa_mM"] == 1.0


def test_conclude_reply_keeps_structured_citations():
    env = Env()
    action = _agent(_reply(kind="conclude", experiment_id=None,
                           contributing_hypotheses=["H3", "H4"], confidence=0.6,
                           evidence_cited=[{"experiment": "E6", "supports": "mechanism"}],
                           makes_target_claim=True)).act(env.reset(), env.state)
    assert action.kind == "conclude"
    assert action.contributing_hypotheses == ["H3", "H4"]
    assert action.confidence == 0.6
    assert action.evidence_cited == [{"experiment": "E6", "supports": "mechanism"}]
    assert action.makes_target_claim is True


def test_bare_string_citation_is_a_parse_failure():
    """The Env refuses bare strings, so the harness turns one into a retry
    instead of a conclude that would leave the episode open."""
    with pytest.raises(ParseFailure):
        _parse(_reply(kind="conclude", contributing_hypotheses=["H4"], confidence=0.5,
                      evidence_cited=["E6"]))


def test_bare_string_citation_then_valid_retry_completes_the_episode():
    env = Env()
    agent = _agent(
        _reply(kind="conclude", contributing_hypotheses=["H4"], confidence=0.5,
               evidence_cited=["the intrabacterial PK run"]),
        _reply(kind="conclude", contributing_hypotheses=["H4"], confidence=0.5,
               evidence_cited=[{"experiment": "E6", "supports": "mechanism"}]),
    )
    action = agent.act(env.reset(), env.state)
    env.step(action)
    assert env.state.concluded is True
    assert action.evidence_cited == [{"experiment": "E6", "supports": "mechanism"}]


@pytest.mark.parametrize("bad", [
    {"beliefs": {"H1": 0.1, "H2": 0.1, "H3": 0.6}},                 # missing H4
    {"beliefs": {"H1": 0.1, "H2": 0.1, "H3": 0.6, "H4": 1.4}},      # out of range
    {"dominant_cause": "H9"},
    {"kind": "think_harder"},
    {"experiment_id": "E9"},
])
def test_invalid_fields_raise_parse_error(bad):
    with pytest.raises(ParseFailure):
        _parse(_reply(**bad))


def test_confidence_without_a_dominant_cause_is_rejected():
    with pytest.raises(ParseFailure):
        _parse(_reply(kind="conclude", dominant_cause=None,
                      contributing_hypotheses=["H4"], confidence=0.9))


def test_json_is_found_inside_prose_and_fences():
    action = _parse("Here is my move:\n```json\n" + _reply() + "\n```\nDone.")
    assert action.experiment_id == "E1"


# --- retry and abstention -----------------------------------------------------
def test_retries_once_then_takes_the_valid_reply():
    env = Env()
    agent = _agent("no json here", _reply())
    action = agent.act(env.reset(), env.state)
    assert action.kind == "run_experiment"
    assert len(agent.transcript) == 2
    assert agent.transcript[0]["error"] and agent.transcript[1]["error"] is None


def test_abstains_after_two_bad_replies():
    env = Env()
    agent = _agent("rubbish", "still rubbish")
    action = agent.act(env.reset(), env.state)
    assert action.kind == "conclude"
    assert action.dominant_cause is None
    assert action.confidence is None
    assert not action.contributing_hypotheses
    assert agent.abstained is True
    env.step(action)                      # an abstention is still a valid conclude
    assert env.state.concluded is True


# --- prompt rendering ---------------------------------------------------------
def test_prompt_carries_the_menu_and_the_env_owned_budget():
    env = Env()
    agent = _agent(_reply())
    agent.act(env.reset(), env.state)
    _, user_prompt = agent.model_client.prompts[0]
    for eid in ("E1", "E2", "E3", "E4", "E5", "E6"):
        assert eid in user_prompt
    assert "8 of 8 units remain" in user_prompt
    assert "arms" in user_prompt and "at least 3" in user_prompt


def test_prompt_never_shows_the_informativeness_field():
    env = Env()
    agent = _agent(_reply(), _reply(experiment_id="E4", parameters={}))
    obs = env.reset()
    obs = env.step(agent.act(obs, env.state))
    agent.act(obs, env.state)
    assert all("informativeness" not in p and "UNRATED" not in p
               for _, p in agent.model_client.prompts)


def test_prompt_does_not_leak_loader_private_keys():
    env = Env()
    agent = _agent(_reply())
    agent.act(env.reset(), env.state)
    _, user_prompt = agent.model_client.prompts[0]
    assert "Loader must strip" not in user_prompt


def test_variant_prompt_states_the_contract_rules():
    prompt = load_prompt()
    assert "falsification" in prompt.lower()
    assert "dominant_cause" in prompt and "evidence_cited" in prompt
    assert "makes_target_claim" in prompt


# --- live episodes ------------------------------------------------------------
def test_llm_agent_drives_a_full_episode():
    env = Env()
    agent = LLMAgent(
        system_prompt=load_prompt(),
        model_client=StubClient(
            _reply(experiment_id="E6", parameters={
                "arms": ["parent_diacid", "diethyl_ester", "monoacid"],
                "controls": ["cell-free medium control"]}),
            _reply(kind="conclude", contributing_hypotheses=["H3", "H4"], confidence=0.7,
                   evidence_cited=[{"experiment": "E6", "supports": "mechanism"}]),
        ),
    )
    obs = env.reset()
    for _ in range(2):
        action = agent.act(obs, env.state)
        obs = env.step(action)
    assert env.state.concluded is True
    assert env.state.experiments_run == ["E6"]
    assert env.state.budget_remaining == 4


def test_scripted_control_arm_completes_within_budget():
    env = Env()
    agent = FalsificationAgent()
    obs = env.reset()
    actions: list[Action] = []
    for _ in range(10):
        action = agent.act(obs, env.state)
        actions.append(action)
        obs = env.step(action)
        if action.kind == "conclude":
            break
    assert actions[-1].kind == "conclude"
    assert env.state.concluded is True
    assert env.state.total_cost <= 8
    assert all(a.beliefs and set(a.beliefs) == {"H1", "H2", "H3", "H4"} for a in actions)
    assert all(isinstance(c, dict) and c["experiment"] in env.state.experiments_run
               for c in actions[-1].evidence_cited)


def test_scripted_control_arm_attacks_its_leader_before_concluding():
    """The whole point of the arm: nothing is asserted as dominant until an
    experiment that could have refuted it has been run."""
    env = Env()
    agent = FalsificationAgent()
    obs = env.reset()
    for _ in range(10):
        action = agent.act(obs, env.state)
        obs = env.step(action)
        if action.kind == "conclude":
            break
    dominant = action.dominant_cause
    if dominant is not None:
        tested = (agent.ledger.severe_tests_passed.get(dominant, [])
                  + agent.ledger.severe_tests_failed.get(dominant, []))
        assert tested, f"concluded {dominant} without running a test that could refute it"
        assert action.confidence is not None
    else:
        assert action.confidence is None


def test_scripted_control_arm_never_mutates_state():
    env = Env()
    agent = FalsificationAgent()
    obs = env.reset()
    before = env.state
    agent.act(obs, env.state)
    assert env.state == before


def test_e6_purchase_declares_a_cell_free_control():
    """PR4 is the agent's job: the control must be named, not assumed."""
    params = FalsificationAgent()._parameters("E6")
    assert len(set(params["arms"])) == 3
    assert any("cell-free" in c.lower() or "cell free" in c.lower() for c in params["controls"])


def test_unaffordable_purchase_is_never_attempted():
    env = Env()
    agent = FalsificationAgent()
    obs = env.reset()
    for _ in range(10):
        action = agent.act(obs, env.state)
        if action.kind == "run_experiment":
            assert agent.costs[action.experiment_id] <= env.state.budget_remaining
        try:
            obs = env.step(action)
        except EnvRejection as exc:
            pytest.fail(f"env refused an action the agent should not have taken: {exc}")
        if action.kind == "conclude":
            break
