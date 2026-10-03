"""LLMAgent — run a prompt-defined agent variant against the FalsifyLab Env.

A variant is a system prompt (`agents/prompts/<variant>.md`). This module is
the shared harness every variant uses: it renders the agent-facing bundle and
the turn history into a user message, calls a model, and parses the reply into
a `contract.Action`. It holds no scientific content and no policy of its own —
if a decision is being made here rather than in the prompt, that is a bug,
because it would show up in every arm and destroy the comparison between them.

Wire protocol with the model: one JSON object per turn.

    {"beliefs": {"H1": 0.5, "H2": 0.5, "H3": 0.5, "H4": 0.5},
     "dominant_cause": "H3" | null,
     "kind": "run_experiment",
     "experiment_id": "E6",
     "parameters": {...}}

    {"beliefs": {...}, "dominant_cause": "H3",
     "kind": "conclude",
     "contributing_hypotheses": ["H3"],
     "confidence": 0.7,
     "evidence_cited": [{"experiment": "E6", "supports": "mechanism"}],
     "makes_target_claim": false}

Rules this harness enforces on the reply, all of them from CONTRACT.md:
  * `beliefs` carries every hypothesis id, each a float in [0,1] — emitted
    every turn, on the Action, never on State.
  * `dominant_cause` is a known hypothesis id or null — every turn.
  * `evidence_cited` entries are citation objects {"experiment", "supports"?};
    a bare string is rejected here, as the Env rejects it at submission.
  * `confidence` is a float in [0,1] or null. Its *meaning* (the probability
    that `dominant_cause` is the largest contributor) is the prompt's business;
    this harness only checks the range and never computes it.

Parse failure policy: one retry, with the parser's complaint and the offending
reply appended to the conversation, then abstain. Abstaining is a conclude with
`dominant_cause: null`, no contributing hypotheses, no stated confidence and no
citations, carrying the last beliefs the model did state — an honest "this
agent did not produce a usable answer" that closes the episode, rather than a
loop or a guess made on the model's behalf. `LLMAgent.parse_failures` records every failure for the log.

The model never sees `Observation.informativeness`: a live Env always reports
"UNRATED" (CONTRACT.md), so rendering it would teach a variant to look for a
field that is never populated. It never sees anything from auditor/ either —
this module reads only agent/*.json and the observations the Env hands back.

State is read-only here, exactly as CONTRACT.md requires: the harness reads
`budget_remaining` and `experiments_run` to render them and writes nothing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional, Protocol

from contract import Action, Agent, Observation, State

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUNDLE_DIR = _REPO_ROOT / "agent"
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

_SUPPORTS = ("mechanism", "target_claim", "potency", "target_engagement")
_KINDS = ("run_experiment", "conclude")
_BRIEFING_ID = "__briefing__"


class ParseError(ValueError):
    """The model's reply was not a usable Action."""


class ModelClient(Protocol):
    """Anything that turns (system prompt, messages) into one text reply.

    `messages` is a list of {"role": "user"|"assistant", "content": str}, so a
    retry can show the model its own rejected reply. Deliberately minimal: the
    harness must not depend on one vendor's SDK.
    """

    def complete(self, system: str, messages: list[dict]) -> str: ...


def _strip_private(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def load_bundle(bundle_dir: Path | str = _BUNDLE_DIR) -> dict:
    """The agent-facing bundle, loader-private keys stripped."""
    bundle_dir = Path(bundle_dir)
    out = {}
    for name in ("briefing", "hypotheses", "experiments"):
        with open(bundle_dir / f"{name}.json", encoding="utf-8") as fh:
            out[name] = _strip_private(json.load(fh))
    return out


def load_prompt(variant: str, prompt_dir: Path | str = _PROMPT_DIR) -> str:
    """Read agents/prompts/<variant>.md — the file that *is* the variant."""
    with open(Path(prompt_dir) / f"{variant}.md", encoding="utf-8") as fh:
        return fh.read()


class LLMAgent(Agent):
    """A variant = this harness + one system prompt."""

    def __init__(
        self,
        system_prompt: str,
        model_client: ModelClient,
        *,
        bundle_dir: Path | str = _BUNDLE_DIR,
        max_retries: int = 1,
    ) -> None:
        self.system_prompt = system_prompt
        self.model_client = model_client
        self.max_retries = max_retries

        bundle = load_bundle(bundle_dir)
        self.briefing = bundle["briefing"]
        self.hypotheses = bundle["hypotheses"]["hypotheses"]
        self.experiments = bundle["experiments"]["experiments"]
        self.hypothesis_ids = [h["id"] for h in self.hypotheses]
        self.experiment_ids = [e["id"] for e in self.experiments]

        self.history: list[dict] = []        # rendered turns, oldest first
        self.parse_failures: list[dict] = []  # {turn, attempt, error, reply}
        self.last_reply: Optional[str] = None
        self._last_beliefs: dict[str, float] = {}

    # --- Agent.act ------------------------------------------------------------
    def act(self, observation: Observation, state: State) -> Action:
        """One turn: render, call, parse. State is read, never written."""
        self._record_observation(observation)
        messages = [{"role": "user", "content": self.render_user_message(state)}]

        for attempt in range(self.max_retries + 1):
            reply = self.model_client.complete(self.system_prompt, messages)
            self.last_reply = reply
            try:
                action = self.parse_action(reply)
            except ParseError as exc:
                self.parse_failures.append(
                    {"turn": len(self.history), "attempt": attempt,
                     "error": str(exc), "reply": reply}
                )
                messages += [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": (
                        f"That reply could not be used: {exc}\n"
                        "Reply again with one JSON object and nothing else, "
                        "following the schema exactly."
                    )},
                ]
                continue
            self._last_beliefs = dict(action.beliefs)
            self._record_action(action)
            return action

        action = self._abstain()
        self._record_action(action)
        return action

    # --- prompt rendering -----------------------------------------------------
    def render_user_message(self, state: State) -> str:
        blocks = [
            self._render_briefing(),
            self._render_hypotheses(),
            self._render_experiments(),
            self._render_state(state),
            self._render_history(),
            self._render_schema(),
        ]
        return "\n\n".join(b for b in blocks if b)

    def _render_briefing(self) -> str:
        facts = "\n".join(f"- {f}" for f in self.briefing.get("starting_facts", []))
        budget = self.briefing.get("budget", {})
        return (
            "# Question\n"
            f"{self.briefing.get('question', '')}\n\n"
            "# What you already know\n"
            f"{facts}\n\n"
            f"# Budget\n{budget.get('units')} units total"
            + (f"; the full menu costs {budget.get('menu_total')}. "
               f"{budget.get('note', '')}" if budget.get("menu_total") else "")
        )

    def _render_hypotheses(self) -> str:
        lines = [f"- {h['id']} ({h['label']}): {h['claim']}" for h in self.hypotheses]
        note = self.briefing.get("required_each_turn", {})
        return (
            "# Hypotheses\n" + "\n".join(lines)
            + ("\n\n" + "\n".join(f"{k}: {v}" for k, v in note.items()) if note else "")
        )

    def _render_experiments(self) -> str:
        lines = []
        for e in self.experiments:
            line = (f"- {e['id']} — {e['name']} (cost {e['cost']})\n"
                    f"    question: {e.get('question', '')}\n"
                    f"    readout: {e.get('readout', '')}")
            if e.get("strains"):
                line += f"\n    strains: {', '.join(e['strains'])}"
            if e.get("parameters"):
                line += "\n    parameters you must set: " + json.dumps(e["parameters"])
            lines.append(line)
        return "# Experiment menu\n" + "\n".join(lines)

    @staticmethod
    def _render_state(state: State) -> str:
        run = ", ".join(state.experiments_run) or "none"
        return (
            "# Where you are\n"
            f"budget remaining: {state.budget_remaining}\n"
            f"spent so far: {state.total_cost}\n"
            f"experiments run: {run}"
        )

    def _render_history(self) -> str:
        if not self.history:
            return ""
        return "# Turn history\n" + "\n\n".join(self.history)

    def _render_schema(self) -> str:
        return (
            "# Your reply\n"
            "One JSON object, nothing else — no prose, no code fence.\n"
            "Every turn, whatever you do:\n"
            f'  "beliefs": an object with a float in [0,1] for each of '
            f'{", ".join(self.hypothesis_ids)} (independent probabilities; they need not sum to 1)\n'
            '  "dominant_cause": one hypothesis id, or null if you are undecided\n'
            "Then either:\n"
            '  "kind": "run_experiment", "experiment_id": one of '
            f'{", ".join(self.experiment_ids)}, "parameters": {{...}} — every required parameter set\n'
            "or:\n"
            '  "kind": "conclude", "contributing_hypotheses": [ids],\n'
            '  "confidence": a float in [0,1] or null,\n'
            '  "evidence_cited": [{"experiment": "<id>", "supports": "'
            + "|".join(_SUPPORTS) + '"}]  — objects only; "supports" may be omitted,\n'
            '  "makes_target_claim": true or false\n'
            "A citation written as a bare string is rejected and your episode stays open."
        )

    # --- history --------------------------------------------------------------
    def _record_observation(self, observation: Optional[Observation]) -> None:
        if observation is None:
            return
        if observation.experiment_id == _BRIEFING_ID:
            return                      # already rendered as the briefing block
        results = "\n".join(f"    - {r.value}  [{r.source}]" for r in observation.results)
        structured = json.dumps(observation.structured, sort_keys=True)
        self.history.append(
            f"Result of {observation.experiment_id} (cost {observation.cost}):\n"
            f"{results}\n    numbers: {structured}"
        )

    def _record_action(self, action: Action) -> None:
        if action.kind == "run_experiment":
            self.history.append(
                f"You ran {action.experiment_id} with parameters "
                f"{json.dumps(action.parameters, sort_keys=True)}; beliefs "
                f"{json.dumps(action.beliefs, sort_keys=True)}, dominant_cause "
                f"{action.dominant_cause}"
            )
        else:
            self.history.append(f"You concluded: dominant_cause {action.dominant_cause}")

    # --- parsing --------------------------------------------------------------
    def parse_action(self, reply: str) -> Action:
        """Turn a model reply into a validated Action, or raise ParseError."""
        doc = self._extract_json(reply)

        kind = doc.get("kind")
        if kind not in _KINDS:
            raise ParseError(f'"kind" must be one of {_KINDS}, got {kind!r}')

        beliefs = self._parse_beliefs(doc.get("beliefs"))
        dominant = doc.get("dominant_cause")
        if dominant is not None and dominant not in self.hypothesis_ids:
            raise ParseError(
                f'"dominant_cause" must be null or one of {self.hypothesis_ids}, got {dominant!r}'
            )

        if kind == "run_experiment":
            eid = doc.get("experiment_id")
            if eid not in self.experiment_ids:
                raise ParseError(
                    f'"experiment_id" must be one of {self.experiment_ids}, got {eid!r}'
                )
            parameters = doc.get("parameters", {})
            if not isinstance(parameters, dict):
                raise ParseError('"parameters" must be an object')
            return Action(
                kind="run_experiment",
                beliefs=beliefs,
                dominant_cause=dominant,
                experiment_id=eid,
                parameters=parameters,
            )

        contributing = doc.get("contributing_hypotheses", [])
        if not isinstance(contributing, list) or any(
            h not in self.hypothesis_ids for h in contributing
        ):
            raise ParseError(
                f'"contributing_hypotheses" must be a list of {self.hypothesis_ids}, '
                f"got {contributing!r}"
            )
        makes_target_claim = doc.get("makes_target_claim", False)
        if not isinstance(makes_target_claim, bool):
            raise ParseError('"makes_target_claim" must be true or false')
        return Action(
            kind="conclude",
            beliefs=beliefs,
            dominant_cause=dominant,
            contributing_hypotheses=sorted(set(contributing)),
            confidence=self._parse_confidence(doc.get("confidence")),
            evidence_cited=self._parse_citations(doc.get("evidence_cited")),
            makes_target_claim=makes_target_claim,
        )

    @staticmethod
    def _extract_json(reply: str) -> dict:
        """The outermost JSON object in the reply, fenced or bare. Models wrap
        JSON in prose or a ```json fence often enough that failing on it would
        measure formatting compliance rather than reasoning."""
        if not isinstance(reply, str) or not reply.strip():
            raise ParseError("empty reply")
        text = reply.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if fence:
            text = fence.group(1).strip()
        start = text.find("{")
        if start == -1:
            raise ParseError("no JSON object in the reply")
        depth, in_string, escape = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        doc = json.loads(text[start:i + 1])
                    except json.JSONDecodeError as exc:
                        raise ParseError(f"invalid JSON: {exc}") from exc
                    if not isinstance(doc, dict):
                        raise ParseError("top-level JSON value must be an object")
                    return doc
        raise ParseError("unbalanced JSON object in the reply")

    def _parse_beliefs(self, raw: Any) -> dict[str, float]:
        if not isinstance(raw, dict):
            raise ParseError('"beliefs" must be an object of hypothesis -> probability')
        missing = [h for h in self.hypothesis_ids if h not in raw]
        if missing:
            raise ParseError(f'"beliefs" is missing {", ".join(missing)}')
        unknown = [k for k in raw if k not in self.hypothesis_ids]
        if unknown:
            raise ParseError(f'"beliefs" has unknown hypothesis ids: {", ".join(map(str, unknown))}')
        beliefs = {}
        for hid in self.hypothesis_ids:
            value = raw[hid]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ParseError(f'beliefs["{hid}"] must be a number, got {value!r}')
            if not 0.0 <= float(value) <= 1.0:
                raise ParseError(f'beliefs["{hid}"] must be in [0,1], got {value!r}')
            beliefs[hid] = float(value)
        return beliefs

    @staticmethod
    def _parse_confidence(raw: Any) -> Optional[float]:
        if raw is None:
            return None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ParseError(f'"confidence" must be a number in [0,1] or null, got {raw!r}')
        if not 0.0 <= float(raw) <= 1.0:
            raise ParseError(f'"confidence" must be in [0,1], got {raw!r}')
        return float(raw)

    def _parse_citations(self, raw: Any) -> Optional[list[dict]]:
        if raw is None:
            return None
        if not isinstance(raw, list):
            raise ParseError('"evidence_cited" must be a list of citation objects')
        citations = []
        for i, c in enumerate(raw):
            if not isinstance(c, dict):
                raise ParseError(
                    f"evidence_cited[{i}] is a bare {type(c).__name__}; a citation must be "
                    '{"experiment": "<id>", "supports"?: "<role>"}'
                )
            eid = c.get("experiment")
            if eid not in self.experiment_ids:
                raise ParseError(
                    f"evidence_cited[{i}] cites {eid!r}; must be one of {self.experiment_ids}"
                )
            supports = c.get("supports")
            if supports is not None and supports not in _SUPPORTS:
                raise ParseError(
                    f"evidence_cited[{i}] has supports {supports!r}; must be one of "
                    f"{', '.join(_SUPPORTS)} or omitted"
                )
            citation = {"experiment": eid}
            if supports is not None:
                citation["supports"] = supports
            citations.append(citation)
        return citations

    # --- abstention -----------------------------------------------------------
    def _abstain(self) -> Action:
        """After the retry budget is gone: close the episode without an answer.

        Beliefs still have to be on the Action every turn, so they are the last
        ones the model validly stated (the flat 0.5 prior if it never managed
        one) — the harness does not invent beliefs for it. No dominant cause, so no confidence: per CONTRACT.md confidence is the
        probability that a named dominant cause is the largest contributor, and
        there is no named cause to be confident about.
        """
        return Action(
            kind="conclude",
            beliefs=dict(self._last_beliefs) or {hid: 0.5 for hid in self.hypothesis_ids},
            dominant_cause=None,
            contributing_hypotheses=[],
            confidence=None,
            evidence_cited=[],
            makes_target_claim=False,
        )
