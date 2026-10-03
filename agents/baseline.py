"""Baseline FalsifyLab agent.

Implements `contract.Agent.act` exactly as specified in CONTRACT.md:

    def act(self, observation: Observation, state: State) -> Action

Design, in one paragraph. The agent holds an independent probability per
hypothesis that it contributes materially to the failure. It starts every
hypothesis at 0.5 and buys experiments greedily by expected discrimination per
unit of budget: each experiment carries a weight per hypothesis (`DISCRIMINATES`),
derived from the question and readout it advertises in `agent/experiments.json`,
and the experiment with the highest (weighted uncertainty addressed) / cost is
bought next. Weights, not a flat coverage list, are what stop a cheap experiment
whose readout cannot see the relevant quantity from crowding out a dearer one
that can. Beliefs are
then updated by odds-ratio multipliers keyed to what the readout actually says,
not to what the readout is expected to say -- every rule below fires in both
directions, so a readout contradicting the current favourite drives its
probability down. The agent concludes only once it has observed something; with
no observation it has no licence to name a cause.

Two deliberate restraints:

* Confidence is capped below certainty (`MAX_CONFIDENCE`), because the audited
  quantity is calibration, not conviction.
* `makes_target_claim` is set True only when the agent has actually run the
  strain panel that could license an on/off-target statement about analogues.

`Action` carries no beliefs field, and the per-turn `beliefs` / `dominant_cause`
recorded in a `Turn` come from `Env.state` (CONTRACT.md: `State` owns both, and
`step` advances the state). So `act` writes its updated beliefs back onto the
`state` it was handed, and touches nothing else on it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

from contract import Action, Agent, ExperimentId, HypothesisId, Observation, Result, State

BUNDLE_DIR = Path(__file__).resolve().parents[1] / "agent"

BRIEFING_ID = "__briefing__"
PRIOR = 0.5
CONTRIBUTES_AT = 0.6          # probability at or above which a hypothesis is asserted
MAX_CONFIDENCE = 0.8          # never claim more than this in a conclusion
MIN_MEANINGFUL_SHIFT_C = 2.0  # thermal shift below this is noise, not binding
SATURATING_COA_mM = 1.0       # at or above this, substrate is taken as saturating
STRONG_LR = 8.0               # likelihood ratio for a clear, direct measurement
DECISIVE_LR = 20.0            # reserved for the arm-resolved dominant contributor
_EPS = 1e-6

# How strongly each experiment can discriminate each hypothesis, read off the
# `question` and `readout` fields the experiment advertises in
# agent/experiments.json. Weights, not a flat list: E4 reports IC50 against the
# purified enzyme, which by construction cannot observe what becomes of the
# compound inside a cell, so it is near-worthless for H3/H4 however cheap it
# is. E3 and E5 ask whether killing runs through the nominated target: they
# bear on a target claim about the analogues, not on why the parent fails.
DISCRIMINATES: dict[ExperimentId, dict[HypothesisId, float]] = {
    "E1": {"H1": 0.9, "H2": 0.9},    # does it still bind when substrate saturates the enzyme?
    "E2": {"H1": 0.7, "H2": 0.8},    # where and how does it bind?
    "E3": {},                        # target dependence of killing
    "E4": {"H3": 0.2, "H4": 0.2},    # at best weak, indirect evidence about the cell
    "E5": {},                        # target dependence of killing
    "E6": {"H3": 1.0, "H4": 1.0},    # how much gets in, and does it survive in there?
}

# Experiments that license an on/off-target claim about the analogue series.
TARGET_CLAIM_EXPERIMENTS: frozenset[ExperimentId] = frozenset({"E3", "E5"})


def _load(bundle_dir: Path, name: str) -> dict:
    """Load one agent-facing bundle file, dropping loader-private keys."""
    doc = json.loads((bundle_dir / name).read_text(encoding="utf-8"))
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def _temperature_shift(text: str) -> Optional[float]:
    """Largest melting-temperature change stated in a thermal-shift readout,
    including the `40 to 55 degrees` form, which is a 15 degree shift."""
    ranged = re.search(r"(\d+(?:\.\d+)?)\s*(?:to|->|-)\s*(\d+(?:\.\d+)?)\s*(?:degrees|deg|c\b)", text)
    if ranged:
        return abs(float(ranged.group(2)) - float(ranged.group(1)))
    deltas = [
        float(m)
        for m in re.findall(r"(?:delta\s*t_?m|shift(?:ed)?(?: of| by)?|t_?m shift)[^\d\-]{0,20}(\d+(?:\.\d+)?)", text)
    ]
    if deltas:
        return max(deltas)
    plain = re.findall(r"(\d+(?:\.\d+)?)\s*(?:degrees|deg c|deg\b)", text)
    return max(float(p) for p in plain) if plain else None


def _numbers(text: str) -> list[float]:
    return [float(m) for m in re.findall(r"(\d+(?:\.\d+)?)\s*(?:\+/-\s*\d+(?:\.\d+)?\s*)?percent", text)]


class BaselineAgent(Agent):
    """Greedy value-of-information agent with explicit, symmetric evidence rules."""

    def __init__(self, bundle_dir: Path | None = None) -> None:
        self.bundle_dir = Path(bundle_dir) if bundle_dir is not None else BUNDLE_DIR
        self.briefing = _load(self.bundle_dir, "briefing.json")
        self.hypotheses = _load(self.bundle_dir, "hypotheses.json")["hypotheses"]
        self.experiments = {e["id"]: e for e in _load(self.bundle_dir, "experiments.json")["experiments"]}
        self.ids: list[HypothesisId] = [h["id"] for h in self.hypotheses]
        self.beliefs: dict[HypothesisId, float] = {h: PRIOR for h in self.ids}
        self.evidence: list[str] = []          # what this agent may cite: things it ran
        self._seen: list[ExperimentId] = []
        self._requested: dict[ExperimentId, dict] = {}

    # ---------------------------------------------------------------- act ----
    def act(self, observation: Observation, state: State) -> Action:
        self._absorb(observation)
        self._publish(state)

        experiment_id = self._next_experiment(state)
        if experiment_id is None:
            return self._conclude()
        parameters = self._parameters(experiment_id)
        self._requested[experiment_id] = parameters
        return Action(kind="run_experiment", experiment_id=experiment_id, parameters=parameters)

    # ------------------------------------------------------------- beliefs ---
    def _absorb(self, observation: Optional[Observation]) -> None:
        """Fold one observation into the beliefs. The briefing carries the
        premise only, which is already priced into the priors."""
        if observation is None or observation.experiment_id == BRIEFING_ID:
            return
        eid = observation.experiment_id
        if eid in self._seen:
            return
        self._seen.append(eid)

        text = " ".join(r.value for r in observation.results).lower()
        for hypothesis, likelihood_ratio in self._interpret(eid, text).items():
            self._update(hypothesis, likelihood_ratio)
        self.evidence.extend(self._cite(eid, observation.results))

    def _update(self, hypothesis: HypothesisId, likelihood_ratio: float) -> None:
        """Bayes on the odds of a single independent hypothesis."""
        p = min(max(self.beliefs.get(hypothesis, PRIOR), _EPS), 1 - _EPS)
        odds = (p / (1 - p)) * likelihood_ratio
        self.beliefs[hypothesis] = odds / (1 + odds)

    def _interpret(self, eid: ExperimentId, text: str) -> dict[HypothesisId, float]:
        """Likelihood ratios implied by what this readout says.

        Each rule is written as a test on the readout with an explicit opposite
        branch, so the evidence can push a hypothesis either way.
        """
        lrs: dict[HypothesisId, float] = {}

        if eid in ("E1", "E2"):
            binds = self._says_binding(eid, text)
            if binds is True:
                lrs["H1"] = 0.1          # a real, localisable interaction: not an assay artefact
            elif binds is False:
                lrs["H1"] = 6.0          # nothing binds: the tube result is the suspect

            outcompeted = self._says_substrate_outcompetes(eid, text, binds)
            if outcompeted is True:
                lrs["H2"] = 6.0
            elif outcompeted is False:
                lrs["H2"] = 0.15         # holds on with substrate present / displaces it

        if eid == "E6":
            lrs.update(self._interpret_pk(text))

        if eid == "E4":
            # Potency gains that still do not kill are weak evidence that the
            # barrier sits between the tube and the target, not in affinity.
            gained = "more potent" in text or "fold" in text
            still_dead = "inactive" in text or "no killing" in text or re.search(r"mic\d*\s*>", text)
            if gained and still_dead:
                lrs["H3"] = lrs["H4"] = 1.3
            elif gained and not still_dead:
                lrs["H3"] = lrs["H4"] = 0.7

        return lrs

    def _says_binding(self, eid: ExperimentId, text: str) -> Optional[bool]:
        """Did the compound demonstrably engage the enzyme?

        For the thermal shift this is the sign of the readout the experiment
        advertises -- a melting-temperature change in degrees -- rather than
        any particular phrasing of it. For the structure it is whether a model
        with contacts came out at all.
        """
        if re.search(r"\b(no|zero|absent|without)\b[^.]*\b(shift|density|binding|change in (the )?melting)", text):
            return False
        if eid == "E1":
            shift = _temperature_shift(text)
            if shift is None:
                return None
            return shift >= MIN_MEANINGFUL_SHIFT_C
        if re.search(r"\b(contact|h-bond|hydrogen bond|resolution|space group|angstrom|\bpocket)", text):
            return True
        if re.search(r"\b(no|not) (interpretable |usable )?(density|model|structure)", text):
            return False
        return None

    def _says_substrate_outcompetes(
        self, eid: ExperimentId, text: str, binds: Optional[bool]
    ) -> Optional[bool]:
        """Does millimolar substrate displace the compound from the site?

        The strongest reading is not in the prose: the agent itself chose the
        substrate concentration for this run, so a thermal shift measured under
        a saturating coenzyme A concentration answers the question directly.
        """
        if re.search(r"(coenzyme a|coa)[^.]*displaced", text):
            return False
        if re.search(r"(shift (is )?(abolished|lost|absent)|no shift)[^.]*(coenzyme a|coa)", text):
            return True
        if re.search(r"(coenzyme a|coa)[^.]*(abolish|block|prevent|outcompet)", text):
            return True
        if eid == "E1" and binds is not None:
            coa = self._requested.get("E1", {}).get("coa_mM")
            if coa is not None and coa >= SATURATING_COA_mM:
                return not binds      # shift survives saturating substrate -> it is not outcompeted
        return None

    def _interpret_pk(self, text: str) -> dict[HypothesisId, float]:
        """Intrabacterial pharmacokinetics: separate 'cannot get in' from
        'gets in and is destroyed'. Both, either or neither may be supported."""
        lrs: dict[HypothesisId, float] = {}
        percentages = _numbers(text)

        poor_entry = bool(re.search(r"(only\s+\d|efflux|not taken up|poor(ly)? (uptake|permeat))", text))
        low_recovery = any(p < 10 for p in percentages) and bool(
            re.search(r"(recovered|intracellular|uptake)", text)
        )
        good_entry = bool(
            re.search(r"\b([5-9]\d|100)(\.\d+)?\s*(\+/-\s*[\d.]+\s*)?percent[^.]*(uptake|taken up)", text)
        )
        modified = bool(re.search(r"(metabolis|biotransform|demethylat|ester loss|mass loss)", text))
        mostly_intact = bool(re.search(r"(remains|found) (unmodified|intact)", text)) and any(
            p > 70 for p in percentages
        )

        if poor_entry or low_recovery:
            lrs["H3"] = STRONG_LR
        elif good_entry:
            lrs["H3"] = 1 / STRONG_LR

        if modified and not mostly_intact:
            lrs["H4"] = STRONG_LR
        elif mostly_intact:
            lrs["H4"] = 1 / STRONG_LR

        # Which of the two is the larger contributor is decided by the arm that
        # did get in. If some arm clears the envelope and is still destroyed,
        # entry is not what caps the series -- survival inside is. If nothing
        # gets in anywhere and what little does is untouched, the reverse.
        if good_entry and modified and not mostly_intact:
            lrs["H4"] = DECISIVE_LR
        elif (poor_entry or low_recovery) and not modified:
            lrs["H3"] = DECISIVE_LR

        return lrs

    def _publish(self, state: State) -> None:
        """Write beliefs back to the state, the only channel the contract gives
        an agent for the per-turn `beliefs` and `dominant_cause` of a Turn."""
        state.beliefs = dict(self.beliefs)
        state.dominant_cause = self._dominant()

    # -------------------------------------------------------------- policy ---
    def _next_experiment(self, state: State) -> Optional[ExperimentId]:
        """Greedy pick: most remaining uncertainty addressed per unit of budget.

        Returns None when nothing affordable is worth buying, which is the
        signal to conclude.
        """
        already = set(state.experiments_run) | set(self._seen)
        best: Optional[ExperimentId] = None
        best_value = 0.0
        for eid, experiment in self.experiments.items():
            if eid in already:
                continue
            cost = int(experiment["cost"])
            if cost > state.budget_remaining:
                continue
            value = self._value(eid, already) / cost
            if value > best_value + 1e-9:
                best, best_value = eid, value
        return best

    def _value(self, eid: ExperimentId, already: Iterable[ExperimentId]) -> float:
        """Uncertainty this experiment could resolve, in probability units."""
        value = sum(
            weight * min(self.beliefs[h], 1 - self.beliefs[h])
            for h, weight in DISCRIMINATES.get(eid, {}).items()
            if h in self.beliefs
        )
        # A target-dependence panel is worth buying once the agent is close to
        # asserting a cause: without it the agent must stay silent on whether
        # the analogues that do kill act through the nominated target.
        if eid in TARGET_CLAIM_EXPERIMENTS and not (set(already) & TARGET_CLAIM_EXPERIMENTS):
            if self._contributing():
                value += 0.5
        return value

    def _parameters(self, eid: ExperimentId) -> dict:
        """Fill the settable fields declared for this experiment.

        Choices are made from the experiment's own parameter spec: saturating
        substrate is what makes E1 discriminate H2, all three arms are
        mandatory for E6, and the free-list control is named rather than
        ticked -- a measurement of compound lost from the medium means nothing
        unless a cell-free arm shows the loss is not adsorption.
        """
        spec = (self.experiments.get(eid) or {}).get("parameters") or {}
        params: dict = {}
        for name, field_spec in spec.items():
            kind = field_spec.get("type")
            if kind == "multi_enum":
                params[name] = list(field_spec.get("values", []))
            elif kind == "enum":
                values = field_spec.get("values", [])
                params[name] = "gel_filtration" if "gel_filtration" in values else (values[0] if values else None)
            elif kind == "free_list":
                params[name] = ["bacteria-free filter control (adsorption, not uptake)",
                                "no-compound vehicle control"]
            elif kind == "float":
                low, high = field_spec.get("range", [0, 1])
                if name == "coa_mM":
                    params[name] = high            # saturate the substrate: that is the question E1 asks
                elif name == "compound_uM":
                    params[name] = high / 2
                else:
                    params[name] = high / 2
            elif kind == "int":
                low, high = field_spec.get("range", [0, 1])
                if name == "atc_free_days":
                    params[name] = 6               # deplete the target before dosing
                elif name == "read_day":
                    params[name] = min(max(9, low), high)
                else:
                    params[name] = (low + high) // 2
            elif kind == "string":
                params[name] = "positive control at top dose; vehicle-only negative control"
        return params

    # ------------------------------------------------------------ conclude ---
    def _contributing(self) -> list[HypothesisId]:
        return [h for h in self.ids if self.beliefs[h] >= CONTRIBUTES_AT]

    def _dominant(self) -> Optional[HypothesisId]:
        contributing = self._contributing()
        if not contributing:
            return None
        top = max(self.beliefs[h] for h in contributing)
        leaders = [h for h in contributing if self.beliefs[h] >= top - 1e-9]
        if len(leaders) > 1:
            return None            # genuinely undecided between them; say so
        return leaders[0]

    def _confidence(self) -> float:
        contributing = self._contributing()
        if not contributing:
            return 0.0
        joint = 1.0
        for h in self.ids:
            p = self.beliefs[h]
            joint *= p if h in contributing else (1 - p)
        return round(min(MAX_CONFIDENCE, joint), 3)

    def _conclude(self) -> Action:
        return Action(
            kind="conclude",
            contributing_hypotheses=self._contributing(),
            dominant_cause=self._dominant(),
            confidence=self._confidence(),
            evidence_cited=list(self.evidence),
            makes_target_claim=bool(set(self._seen) & TARGET_CLAIM_EXPERIMENTS),
        )

    @staticmethod
    def _cite(eid: ExperimentId, results: list[Result]) -> list[str]:
        """Cite what was actually run, result by result, with its source."""
        return [f"{eid}: {r.value} [{r.source}]" for r in results]
