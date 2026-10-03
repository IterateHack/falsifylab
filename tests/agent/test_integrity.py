"""Integrity variant: the prompt arm through the shared LLMAgent harness, and
the scripted control arm against the live Env.

The harness itself (agents/llm_agent.py) is consumed from agent/greedy and is
tested there; these tests pin only what this variant adds. No model is called:
`model_client` is a scripted stub.
"""
import json
from pathlib import Path

import pytest

from agents.llm_agent import LLMAgent
from agents.scripted.integrity import IntegrityAgent
from contract import Action
from env import Env, EnvRejection

HYPOTHESIS_IDS = ("H1", "H2", "H3", "H4")
PROMPT = Path(__file__).resolve().parents[2] / "agents" / "prompts" / "integrity.md"
B = {"H1": 0.3, "H2": 0.5, "H3": 0.5, "H4": 0.5}


class StubClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages):
        user = "\n\n".join(m["content"] for m in messages if m["role"] == "user")
        self.calls.append({"system": system, "user": user})
        return self.replies.pop(0)


def _run(**doc):
    return json.dumps({"beliefs": B, "dominant_cause": None, **doc})


# --- the prompt arm ----------------------------------------------------------

def test_prompt_states_the_contract_definitions():
    text = PROMPT.read_text().lower()
    assert "unrated" in text
    assert "do not compute it from your belief vector" in text
    assert '{"experiment": "e4", "supports": "mechanism"}' in text
    assert "must be `null`" in text


def test_prompt_names_no_experiment_as_the_one_that_matters():
    """The variant is a discipline, not a route: it must not steer toward any
    particular purchase or hypothesis."""
    text = PROMPT.read_text()
    for eid in ("E1", "E2", "E3", "E5", "E6"):
        assert eid not in text
    for hid in ("H1", "H2", "H3", "H4"):
        assert hid not in text.replace("H_n", "")


def test_prompt_arm_completes_a_live_episode_through_the_harness():
    client = StubClient(
        _run(kind="run_experiment", experiment_id="E1",
             parameters={"buffer": "gel_filtration", "coa_mM": 1.0, "compound_uM": 50}),
        _run(kind="run_experiment", experiment_id="E6",
             parameters={"arms": ["parent_diacid", "diethyl_ester", "monoacid"],
                         "controls": ["bacteria-free medium incubation"]}),
        _run(kind="conclude", contributing_hypotheses=[], confidence=None,
             evidence_cited=[{"experiment": "E6", "supports": "mechanism"}],
             makes_target_claim=False),
    )
    env = Env()
    obs = env.reset()
    agent = LLMAgent(system_prompt=PROMPT.read_text(), model_client=client)
    while not env.state.concluded:
        obs = env.step(agent.act(obs, env.state))
    assert env.state.experiments_run == ["E1", "E6"]
    assert client.calls[0]["system"] == PROMPT.read_text()
    assert all("UNRATED" not in c["user"] for c in client.calls)


# --- the scripted control arm ------------------------------------------------

def test_scripted_integrity_completes_a_live_episode():
    env = Env()
    obs = env.reset()
    agent = IntegrityAgent()
    for _ in range(8):
        action = agent.act(obs, env.state)
        assert set(action.beliefs) == set(HYPOTHESIS_IDS)
        obs = env.step(action)
        if env.state.concluded:
            break
    assert env.state.concluded is True
    assert env.state.budget_remaining >= 0


def test_scripted_integrity_plan_fits_the_budget():
    from agents.scripted.integrity import PLAN
    agent = IntegrityAgent()
    assert sum(agent._costs[eid] for eid, _, _ in PLAN) <= 8


def test_scripted_integrity_citations_are_only_experiments_it_ran():
    env = Env()
    obs = env.reset()
    agent = IntegrityAgent()
    while not env.state.concluded:
        action = agent.act(obs, env.state)
        if action.kind == "conclude":
            cited = {c["experiment"] for c in action.evidence_cited}
            assert cited <= set(env.state.experiments_run)
            assert all(isinstance(c, dict) for c in action.evidence_cited)
        obs = env.step(action)


def test_scripted_integrity_declares_no_target_claim_without_the_panel():
    """E3 is the only licence for a target claim: an agent stopped before it
    must not declare one."""
    env = Env()
    obs = env.reset()
    agent = IntegrityAgent()
    obs = env.step(agent.act(obs, env.state))     # E1
    action = agent.act(obs, env.state)
    assert action.kind == "run_experiment"
    conclusion = agent._conclude(env.state)
    assert conclusion.makes_target_claim is False


def test_scripted_integrity_abstains_from_a_dominant_cause_without_discrimination():
    agent = IntegrityAgent()
    assert agent._dominant_cause() is None
    assert agent._conclude(Env().state).confidence is None


def test_scripted_integrity_conclude_is_accepted_by_the_env():
    env = Env()
    obs = env.reset()
    agent = IntegrityAgent()
    action = agent._conclude(env.state)
    try:
        env.step(action)
    except EnvRejection as exc:
        pytest.fail(f"env rejected the conclude: {exc}")
    assert isinstance(action, Action)
    assert obs is not None
