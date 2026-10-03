"""Greedy agent variant — deterministic control arm.

The scripted twin of agents/prompts/greedy.md: same policy, no model in the
loop, so a run can tell a bad policy apart from a model that did not follow it.

Character of this arm: *cost discipline*. It spends the briefing budget like a
programme manager under pressure — always the next experiment with the highest
discrimination per unit of cost, and it stops the moment the question it was
asked ("why did this optimisation programme fail?") has a direct answer, even
with budget left on the table. It never buys an experiment whose live
hypotheses are already resolved, and it never buys evidence for a claim it is
not going to make.

Greed here is about *purchasing*, not about reporting. The agent cites only
experiments it actually ran and whose result actually moved its beliefs, and
its confidence is a self-report about one claim, not a number squeezed out of
the belief vector. Buying less is the lever; overstating what was bought is not.

Coded against CONTRACT.md + agent/briefing.json + agent/hypotheses.json +
agent/experiments.json only. `Observation.informativeness` is "UNRATED" from a
live Env and is never read: evidence is graded from the experiment's own
name/question/readout, whether the readout is a number or prose, and how far
the result moved this agent's own beliefs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from contract import Action, ExperimentId, HypothesisId, Observation, State

AGENT_DIR = Path(__file__).resolve().parent.parent.parent / "agent"

BRIEFING_EXPERIMENT_ID = "__briefing__"

# Priors, read off briefing.starting_facts (independent probabilities, not a
# simplex). Inhibition is reversible, enzyme-concentration independent and
# reproduced in an orthogonal assay, so a pure tube artefact already looks
# unlikely; nothing in the briefing speaks to access or metabolism either way.
PRIORS: dict[HypothesisId, float] = {"H1": 0.30, "H2": 0.40, "H3": 0.50, "H4": 0.50}

# Which hypotheses each experiment can actually move, read from its `question`
# and `readout` in agent/experiments.json. Weight = how directly the readout
# bears on that hypothesis (1.0 = the readout is about it).
COVERAGE: dict[ExperimentId, dict[HypothesisId, float]] = {
    # "Does the compound still bind when the enzyme is saturated with its
    # natural substrate?" — binding reality (H1) and CoA competition (H2).
    "E1": {"H1": 0.9, "H2": 1.0},
    # "Where and how does the compound bind?" — binding reality, and the site
    # tells us something about competition.
    "E2": {"H1": 1.0, "H2": 0.5},
    # "Does killing depend on the nominated target?" — a target-dependence
    # question, not a why-did-it-fail question.
    "E3": {"H1": 0.3},
    # "Can the compound be made more potent against the purified enzyme?" —
    # potency is not one of the four hypotheses; a potency gain that still does
    # not kill is weak, indirect support for a cell-side barrier.
    "E4": {"H3": 0.2, "H4": 0.2},
    # "Do any analogues that kill act through the nominated target?" —
    # target attribution again.
    "E5": {"H1": 0.3},
    # "How much compound gets inside, and does it survive once there?" — the
    # only readout that separates access failure from biotransformation.
    "E6": {"H3": 1.0, "H4": 1.0},
}

# Experiments whose question is about target attribution for analogue killing.
# This agent does not assert an on/off-target claim, so it does not buy them:
# CONTRACT.md makes a target claim raise the evidence requirement, and buying
# evidence for a claim you will not make is exactly the spend this arm refuses.
TARGET_CLAIM_ONLY = ("E3", "E5")

# Stop buying once no affordable experiment clears this discrimination-per-unit
# ratio. Deliberately blunt: this arm would rather under-buy than over-buy.
MIN_RATIO = 0.08

# A belief move of at least this much is what "this result mattered" means here.
CITATION_MOVE = 0.10

# Default parameters for the experiments this agent is willing to buy. Values
# are the ones its own question implies: a stabiliser-free, gel-filtration
# buffer so the shift is the compound's; CoA at the top of the offered range so
# "saturated" means saturated; all three E6 arms (the assay is not offered for
# fewer) and a named bacteria-free control so medium chemistry is not mistaken
# for bacterial metabolism.
PARAMETERS: dict[ExperimentId, dict] = {
    "E1": {"buffer": "gel_filtration", "coa_mM": 2.0, "compound_uM": 100.0},
    "E6": {
        "arms": ["parent_diacid", "diethyl_ester", "monoacid"],
        "controls": ["bacteria-free medium incubated with each arm"],
    },
}

# `supports` tag per experiment, derived from its own `question` text.
SUPPORTS: dict[ExperimentId, str] = {
    "E1": "mechanism",
    "E2": "mechanism",
    "E3": "target_claim",
    "E4": "potency",
    "E5": "target_engagement",
    "E6": "mechanism",
}


def _load(name: str) -> dict:
    with open(AGENT_DIR / name, encoding="utf-8") as fh:
        return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}


def _clamp(p: float) -> float:
    return min(0.97, max(0.03, p))


def _update(p: float, likelihood_ratio: float) -> float:
    """Odds-form update of one independent probability."""
    p = _clamp(p)
    odds = (p / (1.0 - p)) * likelihood_ratio
    return _clamp(odds / (1.0 + odds))


def _numbers(structured: dict) -> dict[str, float]:
    """Flatten the structured block to {lowercased key path: float}. Keys are
    matched by substring below, so the agent does not depend on the exact
    naming the environment happens to use."""
    out: dict[str, float] = {}

    def walk(prefix: str, node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}".strip("."), v)
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                walk(f"{prefix}.{i}", v)
        elif isinstance(node, bool):
            out[prefix.lower()] = 1.0 if node else 0.0
        elif isinstance(node, (int, float)):
            out[prefix.lower()] = float(node)

    walk("", structured)
    return out


def _find(numbers: dict[str, float], *all_of: str, exclude: tuple[str, ...] = ()) -> Optional[float]:
    """First numeric value whose key contains every token in `all_of` and none
    in `exclude`."""
    for key, value in numbers.items():
        if all(tok in key for tok in all_of) and not any(tok in key for tok in exclude):
            return value
    return None


def _best(numbers: dict[str, float], *any_of: str, require: str = "") -> Optional[float]:
    """Largest value across every key carrying one of these metric tokens
    (optionally restricted to keys naming one compound arm)."""
    hits = [
        v
        for k, v in numbers.items()
        if (require in k) and any(tok in k for tok in any_of)
    ]
    return max(hits) if hits else None


def _prose(observation: Observation) -> list[str]:
    return [r.value.lower() for r in observation.results]


def _says(lines: list[str], *, about: tuple[str, ...], positive: tuple[str, ...],
          negative: tuple[str, ...]) -> Optional[bool]:
    """Crude reading of a prose-only readout: True if a line about `about`
    reads positive, False if it reads negative, None if it says neither. Prose
    is treated as weaker evidence than a number — see the likelihood ratios at
    the call sites."""
    for line in lines:
        if not any(tok in line for tok in about):
            continue
        if any(tok in line for tok in negative):
            return False
        if any(tok in line for tok in positive):
            return True
    return None


class Agent:
    """One episode. `act` is called once per turn with the live observation."""

    def __init__(self) -> None:
        briefing = _load("briefing.json")
        self.budget_units: int = int(briefing["budget"]["units"])
        self.costs: dict[ExperimentId, int] = {
            e["id"]: int(e["cost"]) for e in _load("experiments.json")["experiments"]
        }
        self.hypotheses: list[HypothesisId] = [h["id"] for h in _load("hypotheses.json")["hypotheses"]]
        self.beliefs: dict[HypothesisId, float] = dict(PRIORS)
        self.moves: dict[ExperimentId, float] = {}      # total |Δbelief| caused by each experiment
        self.direct: set[ExperimentId] = set()          # experiments whose readout was numeric
        self.notes: list[str] = []                      # agent-side reasoning, not part of the Action

    # --- the contract entry point -------------------------------------------
    def act(self, observation: Observation, state: State) -> Action:
        if observation is not None and observation.experiment_id != BRIEFING_EXPERIMENT_ID:
            self._digest(observation)

        choice = self._next_purchase(state)
        if choice is None:
            return self._conclude(state)
        return Action(
            kind="run_experiment",
            experiment_id=choice,
            parameters=dict(PARAMETERS.get(choice, {})),
            beliefs=self._beliefs(),
            dominant_cause=self._dominant(),
        )

    # --- purchasing ----------------------------------------------------------
    def _next_purchase(self, state: State) -> Optional[ExperimentId]:
        """Highest discrimination per unit of cost, or None to stop."""
        already = set(state.experiments_run)
        best, best_ratio = None, 0.0
        for eid, coverage in COVERAGE.items():
            if eid in already or eid in TARGET_CLAIM_ONLY:
                continue
            cost = self.costs[eid]
            if cost > state.budget_remaining:
                continue
            ratio = self._value(coverage) / cost
            if ratio > best_ratio:
                best, best_ratio = eid, ratio
        if best is None or best_ratio < MIN_RATIO:
            return None
        self.notes.append(f"buying {best} at {best_ratio:.2f} discrimination/unit")
        return best

    def _value(self, coverage: dict[HypothesisId, float]) -> float:
        """How much live uncertainty this experiment's readout sits on. 4p(1-p)
        is 1 at p=0.5 and 0 once a hypothesis is settled, so an experiment about
        questions already answered is worth nothing however cheap it is."""
        return sum(
            weight * 4.0 * self.beliefs[h] * (1.0 - self.beliefs[h])
            for h, weight in coverage.items()
            if h in self.beliefs
        )

    # --- reading a result ----------------------------------------------------
    def _digest(self, observation: Observation) -> None:
        eid = observation.experiment_id
        before = dict(self.beliefs)
        numbers = _numbers(observation.structured)
        if numbers:
            # A measured readout. Prose-only results are still read, but the
            # likelihood ratios below are deliberately milder for them.
            self.direct.add(eid)
        handler = getattr(self, f"_read_{eid.lower()}", None)
        if handler is not None:
            handler(numbers, _prose(observation))
        self.moves[eid] = sum(abs(self.beliefs[h] - before[h]) for h in self.beliefs)

    def _read_e1(self, numbers: dict[str, float], lines: list[str]) -> None:
        """Thermal shift +/- CoA. A real shift is binding (against H1); a shift
        that survives CoA saturation is binding the substrate cannot displace
        (against H2). This readout comes back as prose, so both updates are
        made at prose strength."""
        shift = _find(numbers, "shift") or _find(numbers, "tm", exclude=("coa",))
        if shift is not None:
            self._set("H1", 0.2 if shift >= 2.0 else 3.0, "E1 measured shift")
        else:
            binds = _says(
                lines,
                about=("tm", "melting", "thermal"),
                positive=("shift", "stabilis", "stabiliz", "increase"),
                negative=("no shift", "no change", "not observed", "unchanged"),
            )
            if binds is not None:
                self._set("H1", 0.45 if binds else 2.2, "E1 prose: binding")
        survives = _says(
            lines,
            about=("coa", "coenzyme a"),
            positive=("retain", "persist", "unchanged", "still", "comparable",
                      "similar", "unaffect", "saturat"),
            negative=("abolish", "lost", "loss", "no shift", "outcompet", "reduced", "blocked"),
        )
        if survives is not None:
            self._set("H2", 0.4 if survives else 2.5, "E1 prose: shift under CoA")

    def _read_e2(self, numbers: dict[str, float], lines: list[str]) -> None:
        """A solved co-crystal is direct evidence the compound binds the enzyme."""
        solved = _find(numbers, "resolution") is not None or _says(
            lines,
            about=("structure", "resolution", "angstrom", "\u00e5", "density"),
            positive=("resolution", "solved", "refined", "angstrom", "\u00e5"),
            negative=("no density", "unresolved", "not solved", "failed"),
        )
        if solved:
            self._set("H1", 0.2, "E2 structure solved")

    def _read_e4(self, numbers: dict[str, float], lines: list[str]) -> None:
        """Potency optimisation. Better enzyme potency with no whole-cell gain
        says the barrier is on the cell side, but only weakly - it does not say
        which cell-side barrier, so it can never be the answer on its own."""
        best = _find(numbers, "ic50", exclude=("parent",))
        mic = _find(numbers, "mic")
        if best is not None and (mic is None or mic > 50.0):
            self._set("H3", 1.3, "E4 potency gain without killing")
            self._set("H4", 1.3, "E4 potency gain without killing")

    def _read_e6(self, numbers: dict[str, float], lines: list[str]) -> None:
        """Intrabacterial PK, all three arms at once: percent of input in the
        medium, intact inside the cell, or chemically transformed. The arms are
        the point - if the parent barely gets in but another arm does, access
        is a property of the molecule and not the barrier for the series; if
        what gets in comes back out transformed, metabolism is."""
        entered = ("cell_associated", "intracellular", "uptake", "intact", "inside")
        transformed_tokens = ("metabol", "biotransform", "hydrolys", "converted")

        parent_entry = _best(numbers, *entered, require="parent")
        any_entry = _best(numbers, *entered)
        transformed = _best(numbers, *transformed_tokens)

        if parent_entry is not None and parent_entry < 5.0:
            self._set("H3", 3.0, "E6 parent barely cell-associated")
        elif parent_entry is not None:
            self._set("H3", 0.4, "E6 parent enters the cell")
        if any_entry is not None and any_entry >= 20.0:
            # Something in the series does get in, so access is not what the
            # programme as a whole ran into.
            self._set("H3", 0.35, "E6 another arm enters freely")
        if transformed is not None:
            self._set("H4", 6.0 if transformed >= 10.0 else 0.3, "E6 transformed fraction")
        elif any_entry is not None and any_entry >= 20.0:
            self._set("H4", 1.5, "E6 material enters but does not act")

        if _find(numbers, "control") == 0.0:
            self.notes.append("E6 ran without a bacteria-free control; treating it as weaker")

    def _set(self, hid: HypothesisId, likelihood_ratio: float, why: str) -> None:
        self.beliefs[hid] = _update(self.beliefs[hid], likelihood_ratio)
        self.notes.append(f"{hid} -> {self.beliefs[hid]:.2f} ({why})")

    # --- concluding ----------------------------------------------------------
    def _conclude(self, state: State) -> Action:
        contributing = [h for h in self.hypotheses if self.beliefs[h] >= 0.6]
        dominant = self._dominant()
        if dominant is not None and dominant not in contributing:
            contributing.append(dominant)
        return Action(
            kind="conclude",
            beliefs=self._beliefs(),
            dominant_cause=dominant,
            contributing_hypotheses=[h for h in self.hypotheses if h in contributing] or None,
            confidence=self._confidence(dominant, state),
            evidence_cited=self._citations(state),
            # This arm never buys E3/E5, so it never asserts whether analogue
            # killing depends on the nominated target.
            makes_target_claim=False,
        )

    def _dominant(self) -> Optional[HypothesisId]:
        ranked = sorted(self.hypotheses, key=lambda h: self.beliefs[h], reverse=True)
        top = ranked[0]
        if self.beliefs[top] < 0.6:
            return None
        runner_up = self.beliefs[ranked[1]]
        if self.beliefs[top] - runner_up < 0.05:
            return None   # a tie is not a dominant cause
        return top

    def _confidence(self, dominant: Optional[HypothesisId], state: State) -> Optional[float]:
        """Self-reported probability that `dominant` really is the *largest*
        contributor — one number about one claim, stated, not computed from the
        belief vector. It is set by what this agent actually bought for that
        claim, which is the thing a cost-greedy arm is most at risk of skimping.
        """
        if dominant is None:
            return None
        bought_direct = [
            eid
            for eid in state.experiments_run
            if eid in self.direct and COVERAGE.get(eid, {}).get(dominant, 0.0) >= 1.0
        ]
        if not bought_direct:
            # Nothing was run whose readout is about this hypothesis: the ranking
            # rests on priors and indirect inference.
            return 0.35
        separates_rivals = any(
            sum(1 for h, w in COVERAGE[eid].items() if w >= 1.0) > 1 for eid in bought_direct
        )
        # A measurement that covers the dominant cause and its nearest rival in
        # the same run is the only thing that licenses a high number here; one
        # that touches the dominant cause alone leaves the ordering open.
        return 0.75 if separates_rivals else 0.55

    def _citations(self, state: State) -> list[dict]:
        """Only experiments that were run and whose result actually moved a
        belief. An experiment bought and ignored is not evidence."""
        cited: list[dict] = []
        for eid in state.experiments_run:
            if eid in [c["experiment"] for c in cited]:
                continue
            if self.moves.get(eid, 0.0) < CITATION_MOVE:
                continue
            cited.append({"experiment": eid, "supports": SUPPORTS[eid]})
        return cited

    def _beliefs(self) -> dict[HypothesisId, float]:
        return {h: round(self.beliefs[h], 3) for h in self.hypotheses}
