"""Uncertainty variant: the prompt, the shared harness driving it, and the
scripted control.

Nothing here asserts on readout prose. The live-Env tests check action-side
facts (what was bought, what was declared, what the budget did) so the suite
stays free of scenario answers.
"""
import json
import re
from pathlib import Path

import pytest

from agents.llm_agent import LLMAgent
from agents.scripted.uncertainty import UncertaintyAgent
from contract import Action
from env import Env, EnvRejection


PROMPT = Path(__file__).resolve().parents[2] / "agents" / "prompts" / "uncertainty.md"

# The prompt audit's patterns: no hypothesis, experiment or outcome is named.
AUDIT_PATTERNS = [
    r"metabolis|biotransform|uptake|efflux|permeab|degrad|\bH[1-4]\b|\bE[1-6]\b"
    r"|dominant cause is|the answer",
    r"thermal|crystal|\bMIC|strain|pharmacokin|\bPK\b|counter-screen|CoA|potency|IC50"
    r"|artefact|substrate|competition|access|PptT|engagement|intrabacterial",
]


def load_prompt() -> str:
    return PROMPT.read_text(encoding="utf-8")


class StubClient:
    """Returns canned replies in order and records each call's system prompt
    and a copy of the conversation it was given."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system: str, messages: list[dict]) -> str:
        self.calls.append((system, [dict(m) for m in messages]))
        return self.replies.pop(0) if self.replies else "not json"


BELIEFS = {"H1": 0.3, "H2": 0.3, "H3": 0.3, "H4": 0.3}


def _reply(**overrides) -> str:
    doc = {"kind": "run_experiment", "experiment_id": "E4", "parameters": {},
           "beliefs": dict(BELIEFS), "dominant_cause": None,
           "reasoning": "opening: every hypothesis at 0.30, nothing beyond the briefing"}
    doc.update(overrides)
    return json.dumps(doc)


def _run(agent) -> list[Action]:
    env = Env()
    obs = env.reset()
    actions: list[Action] = []
    for _ in range(10):
        action = agent.act(obs, env.state)
        actions.append(action)
        try:
            obs = env.step(action)
        except EnvRejection as exc:
            pytest.fail(f"env refused an action the agent should not have taken: {exc}")
        if action.kind == "conclude":
            break
    return actions, env


# --- the prompt ---------------------------------------------------------------
def test_prompt_states_the_ledger_discipline():
    prompt = load_prompt().lower()
    assert "ledger" in prompt
    assert "moved nothing" in prompt
    assert "unmoved" in prompt and "conflict" in prompt
    assert "no entry, no change" in prompt


def test_prompt_states_the_contract_rules():
    prompt = load_prompt()
    for field in ("beliefs", "dominant_cause", "confidence", "evidence_cited",
                  "makes_target_claim", "contributing_hypotheses"):
        assert f"`{field}`" in prompt
    assert "do not\n  calculate it from your belief numbers" in prompt


@pytest.mark.parametrize("pattern", AUDIT_PATTERNS)
def test_prompt_names_no_hypothesis_experiment_or_outcome(pattern):
    hits = [line for line in load_prompt().splitlines()
            if re.search(pattern, line, re.IGNORECASE)]
    assert hits == []


def test_citation_examples_use_placeholder_ids_only():
    cited = re.findall(r'"experiment":\s*"([^"]+)"', load_prompt())
    assert cited and set(cited) <= {"EN", "EX"}


# --- the prompt through the shared harness ------------------------------------
def test_llm_arm_drives_a_full_episode_with_the_ledger_kept_in_the_conversation():
    first = _reply()
    client = StubClient(
        first,
        _reply(kind="conclude", experiment_id=None, dominant_cause="H2",
               beliefs={"H1": 0.3, "H2": 0.6, "H3": 0.3, "H4": 0.3},
               contributing_hypotheses=["H2"], confidence=0.5,
               evidence_cited=[{"experiment": "E4", "supports": "mechanism"}], makes_target_claim=False,
               reasoning="E4: H2 0.30 -> 0.60 | ... | ...; H1, H3, H4 unchanged"),
    )
    agent = LLMAgent(system_prompt=load_prompt(), model_client=client)
    actions, env = _run(agent)

    assert [a.kind for a in actions] == ["run_experiment", "conclude"]
    assert env.state.concluded is True
    assert env.state.experiments_run == ["E4"]
    assert all(system == load_prompt() for system, _ in client.calls)
    _, second_turn = client.calls[1]
    assert {"role": "assistant", "content": first} in second_turn
    assert actions[-1].evidence_cited == [{"experiment": "E4", "supports": "mechanism"}]
    assert actions[-1].abstain_reason is None


# --- the scripted control -----------------------------------------------------
def test_scripted_control_arm_completes_within_budget():
    actions, env = _run(UncertaintyAgent())
    assert actions[-1].kind == "conclude"
    assert env.state.concluded is True
    assert env.state.total_cost <= 8
    assert all(set(a.beliefs) == {"H1", "H2", "H3", "H4"} for a in actions)
    assert all(isinstance(c, dict) and c["experiment"] in env.state.experiments_run
               for c in actions[-1].evidence_cited or [])


def test_scripted_control_arm_records_every_belief_change():
    """The whole point of the arm: no emitted belief moves without a ledger
    entry naming the experiment that moved it."""
    agent = UncertaintyAgent()
    actions, env = _run(agent)
    for before, after in zip(actions, actions[1:]):
        for hid, p in after.beliefs.items():
            if abs(p - before.beliefs[hid]) > 1e-9:
                entries = [u for u in agent.ledger if u.hypothesis == hid
                           and abs(u.posterior - p) < 1e-9]
                assert entries, f"{hid} moved without a ledger entry"
                assert all(u.experiment_id in env.state.experiments_run for u in entries)


def test_scripted_control_arm_never_mutates_state():
    env = Env()
    agent = UncertaintyAgent()
    obs = env.reset()
    before = env.state
    agent.act(obs, env.state)
    assert env.state == before
