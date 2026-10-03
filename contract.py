"""FalsifyLab shared interfaces — the single source every workstream codes against.

This module is STUBS ONLY. It fixes the types and signatures described in
CONTRACT.md so the environment, the agent and the auditor can be built
independently and the golden tests in auditor/tests/golden/ have something to
import.

Do NOT implement env/agent/audit logic here — those land in their own
workstreams. The dataclasses and the `trajectory_from_dict` loader are concrete
because they define the wire format and nothing scientific lives in them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# --- Identifiers (closed sets, defined by agent/ and auditor/) ----------------
HypothesisId = str   # one of "H1", "H2", "H3", "H4"   (agent/hypotheses.json)
ExperimentId = str   # one of "E1".."E6"                (agent/experiments.json)

VERDICTS = (
    "VALID_SUCCESS",
    "WRONG_CONCLUSION",
    "INSUFFICIENT_EVIDENCE",
    "PROTOCOL_VIOLATION",
    "UNSAFE_ACTION",
    "REWARD_HACK",
)
FLAGS = ("OVERCONFIDENT",)
REWARD_HACKS = ("RH1", "RH2", "RH3")
# Keys the auditor must set on Verdict.scores. applicable_max_evidence is the
# denominator the evidence gate divides by (20 or 30, per the target claim).
# "brier" is the computed Brier value feeding scientific_correctness; it is
# reported here because the golden acceptance tests pin it.
SCORE_KEYS = (
    "scientific_correctness",
    "evidence_sufficiency",
    "protocol_validity",
    "safety",
    "applicable_max_evidence",
    "brier",
)


# --- Core typed records -------------------------------------------------------
@dataclass(frozen=True)
class Result:
    """One readout line from auditor/expected_observations.json, shown to the
    agent and the UI. The auditor never parses these strings."""
    value: str
    source: str


@dataclass
class Observation:
    """What Env.step returns for a run_experiment action. reset() returns the
    briefing as experiment_id='__briefing__' with starting_facts as results.

    `structured` carries the machine-readable numbers the auditor scores on
    (e.g. E4 -> {"best_IC50_nM": 18}). Per auditor/expected_observations.json's
    _structured_contract, the auditor reads `structured` only, never `results`.
    """
    experiment_id: ExperimentId
    results: list[Result]
    informativeness: str          # "UNRATED" from a live Env — the ratings in
                                  # expected_observations.json are auditor-view and
                                  # never reach the agent. Logged episodes may carry
                                  # the real rating; the auditor ignores the field.
    cost: int
    structured: dict = field(default_factory=dict)


@dataclass
class Action:
    """The agent's output for one turn.

    beliefs + dominant_cause are emitted EVERY turn (briefing.required_each_turn)
    and live here, on the action — never on State. State is env-owned and
    read-only to the agent; an agent must not record its beliefs by mutating it.

    kind='run_experiment' -> experiment_id + parameters.
    kind='conclude'       -> contributing_hypotheses, confidence, evidence_cited,
                             makes_target_claim (cost 0).
    """
    kind: str                     # "run_experiment" | "conclude"
    beliefs: dict[HypothesisId, float] = field(default_factory=dict)   # independent P per H, [0,1]
    dominant_cause: Optional[HypothesisId] = None                      # single id or None
    experiment_id: Optional[ExperimentId] = None
    parameters: dict = field(default_factory=dict)
    contributing_hypotheses: Optional[list[HypothesisId]] = None
    confidence: Optional[float] = None
    evidence_cited: Optional[list] = None   # REQUIRED shape per entry: a citation dict
                                            # {"experiment": "E4", "supports": "mechanism"};
                                            # supports in {mechanism, target_claim, potency,
                                            # target_engagement}, absent = "for the conclusion".
                                            # The ENVIRONMENT rejects bare-string entries at
                                            # submission (env workstream) — a prose citation is
                                            # an auditor-invisible reward-hack loophole. The
                                            # auditor itself ignores non-dict entries defensively
                                            # and never text-matches.
    makes_target_claim: bool = False   # True iff asserting on/off-target for analogue killing


@dataclass
class Turn:
    index: int
    action: Action                                # carries this turn's beliefs/dominant_cause
    observation: Optional[Observation]            # None on a conclude turn


@dataclass
class Trajectory:
    scenario_id: str
    turns: list[Turn]


@dataclass
class Verdict:
    verdict: str                                  # one of VERDICTS
    flags: list[str]                              # subset of FLAGS
    scores: dict                                # every SCORE_KEYS entry (floats), plus
                                                # "epistemic_flags": list[str] — kept separate
                                                # from `flags` so flag assertions stay valid
    raw_total: float
    R_visible: float
    final_score: float
    reward_hacks: list[str] = field(default_factory=list)   # subset of REWARD_HACKS


@dataclass
class State:
    """Env.state — env-owned and READ-ONLY to the agent. The agent must never
    mutate it; its beliefs go on the Action it returns, not here. Env.step is
    the only writer."""
    scenario_id: str
    budget_remaining: int                         # starts at briefing.budget.units (8)
    total_cost: int
    experiments_run: list[ExperimentId]
    concluded: bool


# --- Protocols (STUBS — implemented in their own workstreams) -----------------
class Env:
    """Stateful simulator. Replays auditor/expected_observations.json blocks."""
    state: State

    def reset(self) -> Observation:               # -> briefing Observation
        raise NotImplementedError("env workstream")

    def step(self, action: Action) -> Observation:
        raise NotImplementedError("env workstream")


class Agent:
    def act(self, observation: Observation, state: State) -> Action:
        raise NotImplementedError("agent workstream")


def audit(trajectory: Trajectory, rubric: dict, truth: dict) -> Verdict:
    """PURE scoring of a completed trajectory.

    No Env, no Agent, no I/O, no hidden state: everything needed is in the three
    arguments.
      - trajectory: the episode (actions carry beliefs; observations carry
        `structured` numbers).
      - rubric: json.load(auditor/rubric.json).
      - truth:  json.load(auditor/truth.json) -> {contribution_labels, dominant_cause}.
        Kept out of the rubric so one rubric can score any scenario.
    Implemented in auditor/audit.py (imported lazily so this module stays free
    of the auditor workstream's dependencies and there is no import cycle).
    auditor/ must never gain an __init__.py: it is a PEP 420 namespace package,
    and making it a regular package would shadow any sibling auditor module.
    """
    from auditor.audit import audit as _audit
    return _audit(trajectory, rubric, truth)


# --- Logged-episode <-> dataclass loader (concrete; see CONTRACT.md) ----------
def trajectory_from_dict(doc: dict) -> Trajectory:
    """Parse a logged-episode JSON object into a Trajectory."""
    turns = []
    for t in doc["turns"]:
        obs = t.get("observation")
        observation = (
            Observation(
                experiment_id=obs["experiment_id"],
                results=[Result(**r) for r in obs["results"]],
                informativeness=obs["informativeness"],
                cost=obs["cost"],
                structured=obs.get("structured", {}),
            )
            if obs is not None
            else None
        )
        a = t["action"]
        turns.append(
            Turn(
                index=t["index"],
                action=Action(
                    kind=a["kind"],
                    beliefs=a.get("beliefs", {}),
                    dominant_cause=a.get("dominant_cause"),
                    experiment_id=a.get("experiment_id"),
                    parameters=a.get("parameters", {}),
                    contributing_hypotheses=a.get("contributing_hypotheses"),
                    confidence=a.get("confidence"),
                    evidence_cited=a.get("evidence_cited"),
                    makes_target_claim=a.get("makes_target_claim", False),
                ),
                observation=observation,
            )
        )
    return Trajectory(scenario_id=doc["scenario_id"], turns=turns)
