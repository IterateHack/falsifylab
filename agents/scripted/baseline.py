"""Baseline control arm — a plain, legible, hand-coded policy.

This is the deterministic control for the `baseline` variant. The variant
itself is the system prompt in agents/prompts/baseline.md, run through
agents/llm_agent.py; this module is the same policy written out by hand so a
prompt-driven episode can be compared against a fixed one.

Coded against CONTRACT.md and the agent-facing bundle (`agent/briefing.json`,
`agent/hypotheses.json`, `agent/experiments.json`) only. Nothing here is
specific to the answer: hypothesis ids, experiment ids, costs and the budget
are read from the bundle at construction time, and every belief update is
justified by text the agent is given (an experiment's own name, question and
readout description, or a starting fact).

The policy, in one paragraph. Start from a uniform prior of 0.5 on each
hypothesis — the briefing says the hypotheses are independent and more than one
may be true, so a prior that sums to 1 would already be an assumption. Nudge
those priors with the starting facts that bear on a hypothesis. Then, each
turn, re-plan: score every unrun, affordable experiment by how much live
uncertainty it addresses per unit of budget, buy the best one, read its
`structured` payload, and move the affected hypotheses in log-odds. Stop when
nothing affordable is worth buying, and conclude with the hypotheses above 0.5,
the largest as `dominant_cause`, structured citations for the experiments
actually run, and a confidence the agent states itself.

Grading evidence without `informativeness`. A live Env always reports
"UNRATED" (CONTRACT.md), so this agent never reads the field. It judges an
observation by what it legitimately has: whether the payload carried a
measurement at all, whether the measurement bears on the hypothesis the
experiment was bought to address, and whether two readouts inside one
observation point in opposite directions.

Confidence. Per CONTRACT.md, `confidence` is the agent's probability that
`dominant_cause` really is the largest contributor — one number about one
claim, stated directly. It is NOT computed from the belief vector here; it is
read off a declared ladder (`_CONFIDENCE_LADDER`) according to what kind of
evidence the agent bought for that one claim.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Optional

from contract import Action, Agent, Observation, State

_BUNDLE_DIR = Path(__file__).resolve().parents[2] / "agent"

# Log-odds increments. Named so the update sites read as judgements, not magic.
_WEAK = 0.4
_MODERATE = 1.1
_STRONG = 2.2

_PRIOR = 0.5          # briefing: independent probabilities, "more than one may be true"
_BELIEF_CLAMP = 0.02  # never go fully to 0 or 1 on a single scenario's evidence
_CONTRIBUTES_AT = 0.5 # a hypothesis is asserted as contributing above this
_UNCERTAIN_AT = 0.15  # below this much uncertainty a hypothesis is not worth paying to resolve

# What the agent is willing to pay for, expressed as value. Hypothesis value is
# the live uncertainty an experiment could resolve; a target-discriminating
# experiment also has standing value because `makes_target_claim` is part of the
# conclude signature and must be bought, not asserted.
_TARGET_QUESTION_VALUE = 0.5

# Vocabulary expansion per hypothesis, derived from that hypothesis's own claim
# in agent/hypotheses.json: each entry is the ordinary pharmacology wording for
# a phrase in the claim, so an experiment's question can be matched to the
# hypothesis it bears on. Keyed by the claim words, not by hypothesis id, and
# attached below by matching those words — a hypothesis whose claim uses none of
# this vocabulary simply gets no expansion.
_CLAIM_VOCABULARY = {
    # "does not reflect genuine binding ... the tube assay is misleading"
    "binding": ("bind", "binds", "binding", "affinity", "complex", "co-crystal",
                "crystal", "structure", "thermal", "melting", "shift", "occupancy",
                "contact", "residues", "reversible", "orthogonal", "artefact", "assay"),
    # "millimolar intracellular coenzyme A outcompetes it at the active site"
    "competition": ("coenzyme", "coa", "substrate", "competition", "competitive",
                    "outcompete", "saturated", "saturation", "pre-saturation",
                    "active", "site"),
    # "cannot reach the cytoplasm ... poor permeation or active efflux"
    "access": ("reach", "cytoplasm", "permeation", "permeability", "uptake",
               "efflux", "inside", "enters", "entry", "accumulation",
               "intracellular", "partitioned", "medium", "exposure"),
    # "chemically modified faster than it can act"
    "biotransformation": ("modified", "modification", "biotransformed",
                          "biotransformation", "metabolism", "metabolised",
                          "metabolite", "hydrolysis", "hydrolysed", "ester",
                          "stability", "survive", "intact", "degraded"),
}

# The confidence ladder: the probability the agent is willing to state that its
# nominated dominant cause really is the largest contributor, by the kind of
# evidence it holds for that specific claim. Stated, not computed.
_CONFIDENCE_LADDER = {
    "direct_measurement_uncontested": 0.80,
    "direct_measurement_contested": 0.65,
    "indirect_only": 0.50,
    "no_measurement": 0.35,
}

# Words that carry no discriminating content when matching an experiment's
# question to a hypothesis's claim.
_STOPWORDS = set("""
a an and are as at be but by can cannot does do enough faster for from has have
in into is it its may more much not of on or over per quantity sufficient than
that the their them there they this to was what when where whether which while
with without compound compounds enzyme bacterium bacterial cell cells act acts
acting result results reported achieved any across both
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _strip_private(doc: dict) -> dict:
    """Loader convention: keys beginning with underscore are not agent-facing."""
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def _load(name: str) -> dict:
    with open(_BUNDLE_DIR / name, encoding="utf-8") as fh:
        return _strip_private(json.load(fh))


def _logit(p: float) -> float:
    p = min(max(p, _BELIEF_CLAMP), 1.0 - _BELIEF_CLAMP)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _uncertainty(p: float) -> float:
    """1.0 at p=0.5, 0.0 at p=0 or 1 — how much a hypothesis is still open."""
    return 1.0 - abs(2.0 * p - 1.0)


class BaselineAgent(Agent):
    """Control-arm agent. Deterministic: same observations, same actions."""

    def __init__(self) -> None:
        self.briefing = _load("briefing.json")
        self.hypotheses = _load("hypotheses.json")["hypotheses"]
        self.experiments = _load("experiments.json")["experiments"]

        self.hypothesis_ids = [h["id"] for h in self.hypotheses]
        self.costs = {e["id"]: int(e["cost"]) for e in self.experiments}
        self._experiment_by_id = {e["id"]: e for e in self.experiments}

        self.beliefs = {hid: _PRIOR for hid in self.hypothesis_ids}
        self._concept_of = self._primary_concepts()
        self._vocab = self._hypothesis_vocabulary()
        self._bears_on = self._relevance_map()

        # Evidence ledger: what the agent bought and what it took from it. Used
        # for citations and for grading its own evidence; never for `confidence`
        # by arithmetic — see `_state_confidence`.
        self._ledger: dict[str, dict] = {}
        self._briefing_read = False
        self._target_evidence: Optional[str] = None   # None | "on_target" | "off_target"
        self._sent_parameters: dict[str, dict] = {}

    # --- bundle-derived structure --------------------------------------------
    def _primary_concepts(self) -> dict[str, str]:
        """The concept each hypothesis's claim is chiefly about, by overlap
        with that concept's ordinary wording. Exclusive: a claim that merely
        mentions binding in passing (as the competition claim does) is not
        thereby an experiment about binding."""
        primary = {}
        for h in self.hypotheses:
            claim = _tokens(h["label"] + " " + h["claim"])
            scored = [
                (len(claim & set(words) | (claim & _tokens(concept))), concept)
                for concept, words in _CLAIM_VOCABULARY.items()
            ]
            best, concept = max(scored, key=lambda sc: (sc[0], -list(_CLAIM_VOCABULARY).index(sc[1])))
            primary[h["id"]] = concept if best else ""
        return primary

    def _hypothesis_vocabulary(self) -> dict[str, set[str]]:
        """Tokens that mark an experiment as bearing on a hypothesis: the
        ordinary wording for the concept that hypothesis's claim is chiefly
        about. Incidental claim words ("intracellular" in the competition
        claim, "target" in the biotransformation claim) are deliberately not
        used — they would tie an experiment to a hypothesis it does not test."""
        return {
            hid: set(_CLAIM_VOCABULARY[c]) - _STOPWORDS if c else set()
            for hid, c in self._concept_of.items()
        }

    @staticmethod
    def _experiment_text(exp: dict) -> str:
        parts = [exp.get("name", ""), exp.get("question", ""), exp.get("readout", "")]
        parts += [str(s) for s in exp.get("strains", [])]
        parts += list(exp.get("parameters", {}).keys())
        return " ".join(parts)

    def _relevance_map(self) -> dict[str, set[str]]:
        """Which hypotheses each experiment speaks to, by matching the
        experiment's own name/question/readout against each hypothesis's
        vocabulary. No experiment is privileged by hand."""
        mapping = {}
        for exp in self.experiments:
            text_tokens = _tokens(self._experiment_text(exp))
            mapping[exp["id"]] = {
                hid for hid, words in self._vocab.items() if text_tokens & words
            }
        return mapping

    def _asks_about_target(self, eid: str) -> bool:
        """The conclude signature carries `makes_target_claim`; an experiment
        whose own question is about the nominated target is what licenses it."""
        return "target" in _tokens(self._experiment_by_id[eid].get("question", ""))

    # --- Agent.act ------------------------------------------------------------
    def act(self, observation: Observation, state: State) -> Action:
        """One turn. State is env-owned and read-only here: it is read for
        budget and experiments already run, and never written to."""
        self._absorb(observation)

        choice = self._choose_experiment(state)
        if choice is not None:
            eid = choice
            params = self._parameters_for(eid)
            self._sent_parameters[eid] = params
            return Action(
                kind="run_experiment",
                experiment_id=eid,
                parameters=params,
                beliefs=dict(self.beliefs),
                dominant_cause=self._dominant_cause(),
            )
        return self._conclude()

    # --- reading observations -------------------------------------------------
    def _absorb(self, observation: Observation) -> None:
        if observation is None:
            return
        eid = observation.experiment_id
        if eid == "__briefing__":
            if not self._briefing_read:
                self._read_starting_facts(observation)
                self._briefing_read = True
            return
        if eid in self._ledger:        # the conclude step replays the briefing
            return
        reader = getattr(self, f"_read_{eid.lower()}", None)
        entry = {"quality": "no_measurement", "moved": set(), "conflict": False}
        self._ledger[eid] = entry
        if reader is not None:
            reader(observation, entry)

    def _read_starting_facts(self, observation: Observation) -> None:
        """The briefing's starting facts are free evidence; a few of them bear
        on a hypothesis directly."""
        facts = " ".join(r.value.lower() for r in observation.results)
        # "fully reversible ... IC50 is independent of enzyme concentration" —
        # the two standard controls against an inhibition artefact (H1's claim).
        if "reversible" in facts and "independent of enzyme concentration" in facts:
            for hid in self._hypotheses_matching("binding"):
                self._nudge(hid, -_MODERATE)
        # Potency quoted from several assays with a Hill slope near 1 is the
        # same control, weakly.
        if "orthogonal assay" in facts:
            for hid in self._hypotheses_matching("binding"):
                self._nudge(hid, -_WEAK)

    def _hypotheses_matching(self, concept: str) -> list[str]:
        """Hypotheses whose claim is chiefly about a concept — so an update can
        be written in terms of what was measured, not a hypothesis id."""
        return sorted(hid for hid, c in self._concept_of.items() if c == concept)

    @staticmethod
    def _numbers(structured: dict, *required: str) -> list[float]:
        """Numeric values whose key mentions all the given words. The agent does
        not know the payload's key names in advance, so it matches on wording."""
        out = []
        for key, value in structured.items():
            key_tokens = _tokens(str(key))
            if all(any(req in t for t in key_tokens) for req in required):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    out.append(float(value))
                elif isinstance(value, dict):
                    out += [float(v) for v in value.values()
                            if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return out

    @staticmethod
    def _prose(obs: Observation) -> str:
        return " ".join(r.value for r in obs.results)

    @staticmethod
    def _temperatures_in_prose(obs: Observation) -> list[float]:
        """Degrees-Celsius figures in the readout lines, for experiments whose
        `structured` payload is empty and whose readout is a temperature.
        Reads single values ("52 C") and ranges written with an arrow, a dash
        or "to" ("40 to 55 C"), which share one unit. The degree sign is
        optional: readout lines are plain text and may omit it."""
        text = " ".join(r.value for r in obs.results)
        unit = r"\s*(?:\u00b0\s*)?(?:C\b|deg(?:rees)?\s*C)"
        num = r"(-?\d+(?:\.\d+)?)"
        sep = r"\s*(?:\u2192|->|\u2013|\u2014|-|to)\s*"
        temps: list[float] = []
        for a, b in re.findall(num + sep + num + unit, text):
            temps += [float(a), float(b)]
        temps += [float(m) for m in re.findall(num + unit, text)]
        return temps

    # Per-experiment readers. Each one is justified by that experiment's own
    # question in agent/experiments.json, quoted above the rule.

    def _read_e1(self, obs: Observation, entry: dict) -> None:
        """E1: "Does the compound still bind when the enzyme is saturated with
        its natural substrate?" A shift that survives saturating coenzyme A is
        evidence of binding (against the artefact claim) and against the
        substrate-competition claim at once."""
        shifts = self._numbers(obs.structured, "tm") or self._numbers(obs.structured, "shift")
        if not shifts:
            temps = self._temperatures_in_prose(obs)
            if len(temps) >= 2:
                shifts = [max(temps) - min(temps)]
        if not shifts:
            if obs.results:
                entry["quality"] = "indirect"
            return
        entry["quality"] = "direct"
        if max(shifts) > 1.0:
            for hid in self._hypotheses_matching("binding"):
                self._nudge(hid, -_STRONG)
                entry["moved"].add(hid)
            # The purchase was made at saturating substrate: a shift that
            # persists there is what disfavours competition.
            if self._bought_at_saturating_substrate(obs.experiment_id):
                for hid in self._hypotheses_matching("competition"):
                    self._nudge(hid, -_MODERATE)
                    entry["moved"].add(hid)
        else:
            for hid in self._hypotheses_matching("competition"):
                self._nudge(hid, +_MODERATE)
                entry["moved"].add(hid)

    def _read_e2(self, obs: Observation, entry: dict) -> None:
        """E2: "Where and how does the compound bind?" A solved complex is
        direct evidence against the inhibition being an assay artefact."""
        prose = self._prose(obs).lower()
        solved = bool(self._numbers(obs.structured, "resolution")) or "resolution" in prose \
            or "\u00c5" in self._prose(obs) or "angstrom" in prose
        if solved:
            entry["quality"] = "direct"
            for hid in self._hypotheses_matching("binding"):
                self._nudge(hid, -_STRONG)
                entry["moved"].add(hid)

    def _read_e3(self, obs: Observation, entry: dict) -> None:
        """E3: "Does killing depend on the nominated target?" Sensitisation when
        the target is depleted is on-target killing; a flat panel is not."""
        mics = self._numbers(obs.structured, "mic")
        if not mics:
            return
        entry["quality"] = "direct"
        if max(mics) > 0 and min(mics) <= max(mics) / 4.0:
            self._target_evidence = "on_target"
        else:
            self._target_evidence = "off_target"

    def _read_e4(self, obs: Observation, entry: dict) -> None:
        """E4: "Can the compound be made more potent against the purified
        enzyme?" Potency that improves at the enzyme while the whole-cell
        readout does not move says the barrier is not potency, which is weak
        support for every cell-side hypothesis and weak evidence that the
        enzyme-level result is real."""
        ic50s = self._numbers(obs.structured, "ic50")
        mics = self._numbers(obs.structured, "mic")
        if not ic50s:
            return
        entry["quality"] = "indirect"
        for hid in self._hypotheses_matching("binding"):
            self._nudge(hid, -_WEAK)
            entry["moved"].add(hid)
        if mics and min(mics) >= 100.0:
            for concept in ("access", "biotransformation"):
                for hid in self._hypotheses_matching(concept):
                    self._nudge(hid, +_WEAK)
                    entry["moved"].add(hid)

    def _read_e5(self, obs: Observation, entry: dict) -> None:
        """E5: "Do any analogues that kill the bacterium act through the
        nominated target?" A counter-screen answers the target question only,
        so it moves no hypothesis; it settles `makes_target_claim` only if the
        readout says so in as many words."""
        prose = self._prose(obs).lower()
        if not prose and not obs.structured:
            return
        entry["quality"] = "indirect"
        if "off-target" in prose or "unrelated enzyme" in prose and "not" in prose:
            self._target_evidence = self._target_evidence or "off_target"
        elif "on-target" in prose:
            self._target_evidence = self._target_evidence or "on_target"

    def _read_e6(self, obs: Observation, entry: dict) -> None:
        """E6: "How much compound gets inside, and does it survive once there?"
        The readout splits input into medium / intracellular intact /
        biotransformed, which is exactly the access-versus-biotransformation
        question. Read the arms as a whole: the best intact fraction any arm
        achieves bounds access, and the largest biotransformed fraction bounds
        how fast the compound is modified once in."""
        intact = (self._numbers(obs.structured, "intact")
                  + self._numbers(obs.structured, "intracellular")
                  + self._numbers(obs.structured, "cell", "associated")
                  + self._numbers(obs.structured, "uptake"))
        transformed = (self._numbers(obs.structured, "biotransform")
                       + self._numbers(obs.structured, "metabol"))
        if not intact and not transformed:
            return
        entry["quality"] = "direct"
        access = self._hypotheses_matching("access")
        biotransformation = [hid for hid in self._hypotheses_matching("biotransformation")
                             if hid not in access]
        if intact and max(intact) < 5.0:
            for hid in access:
                self._nudge(hid, +_STRONG)
                entry["moved"].add(hid)
        elif intact and max(intact) > 20.0:
            for hid in access:
                self._nudge(hid, -_MODERATE)
                entry["moved"].add(hid)
        if transformed and max(transformed) > 20.0:
            for hid in biotransformation:
                self._nudge(hid, +_STRONG)
                entry["moved"].add(hid)
        elif transformed and max(transformed) < 5.0:
            for hid in biotransformation:
                self._nudge(hid, -_MODERATE)
                entry["moved"].add(hid)
        # Two readouts in one payload that both come back high is the agent's
        # own conflict test, standing in for the informativeness it is not told.
        if intact and transformed and max(intact) > 20.0 and max(transformed) > 20.0:
            entry["conflict"] = True

    def _nudge(self, hid: str, delta: float) -> None:
        self.beliefs[hid] = round(_sigmoid(_logit(self.beliefs[hid]) + delta), 4)

    # --- planning -------------------------------------------------------------
    def _bought_at_saturating_substrate(self, eid: str) -> bool:
        spec = self._experiment_by_id[eid].get("parameters", {}).get("coa_mM")
        sent = self._sent_parameters.get(eid, {}).get("coa_mM")
        return bool(spec and sent is not None and sent >= spec["range"][1])

    def _value(self, eid: str) -> float:
        value = sum(_uncertainty(self.beliefs[hid])
                    for hid in self._bears_on[eid]
                    if _uncertainty(self.beliefs[hid]) >= _UNCERTAIN_AT)
        if self._asks_about_target(eid) and self._target_evidence is None:
            value += _TARGET_QUESTION_VALUE
        return value

    def _choose_experiment(self, state: State) -> Optional[str]:
        """Re-planned every turn: the affordable, unrun experiment with the most
        live uncertainty per unit of budget. Ties go to the larger absolute
        value, then to the cheaper experiment, then to the lower id — so the
        policy is deterministic."""
        candidates = []
        for eid, cost in self.costs.items():
            if eid in self._ledger or cost > state.budget_remaining:
                continue
            value = self._value(eid)
            if value <= 0.0:
                continue
            candidates.append((value / cost, value, -cost, eid))
        if not candidates:
            return None
        return max(candidates, key=lambda c: (c[0], c[1], c[2], [-ord(x) for x in c[3]]))[3]

    def _parameters_for(self, eid: str) -> dict:
        """Settable fields come from agent/experiments.json; the values are the
        agent's protocol choices, each one aimed at the experiment's question."""
        spec = self._experiment_by_id[eid].get("parameters", {})
        params: dict = {}
        if "buffer" in spec:
            # Stabilisers in the buffer are a confound for a melting-point
            # readout; take the cleanest preparation offered.
            values = spec["buffer"].get("values", [])
            params["buffer"] = "gel_filtration" if "gel_filtration" in values else values[0]
        if "coa_mM" in spec:
            # The question is whether binding survives substrate saturation, so
            # run at the top of the offered range.
            params["coa_mM"] = float(spec["coa_mM"]["range"][1])
        if "compound_uM" in spec:
            # Well above the biochemical IC50 quoted in the briefing, well below
            # the top of the range, so a null is informative.
            params["compound_uM"] = 50.0
        if "atc_free_days" in spec:
            # Knockdown strains need the target actually depleted before dosing.
            params["atc_free_days"] = 6
        if "read_day" in spec:
            params["read_day"] = 14 if 14 <= spec["read_day"]["range"][1] else spec["read_day"]["range"][1]
        if "normalisation_control" in spec:
            params["normalisation_control"] = "H37Rv wild-type, no ATc, same plate"
        if "arms" in spec:
            params["arms"] = list(spec["arms"]["values"])      # all arms, as required
        if "controls" in spec:
            # Free list on purpose: a compound that disappears from the medium
            # without bacteria is chemistry, not biology, so the bacteria-free
            # incubation has to be run alongside.
            params["controls"] = ["bacteria-free medium incubation",
                                  "time-zero input quantification"]
        return params

    # --- concluding -----------------------------------------------------------
    def _dominant_cause(self) -> Optional[str]:
        """The single hypothesis currently believed to be the largest
        contributor; None while nothing stands clear of the prior or while two
        hypotheses are indistinguishable."""
        ranked = sorted(self.beliefs.items(), key=lambda kv: (-kv[1], kv[0]))
        top, top_p = ranked[0]
        if top_p <= _CONTRIBUTES_AT:
            return None
        if len(ranked) > 1 and abs(top_p - ranked[1][1]) < 1e-9:
            return None
        return top

    def _state_confidence(self, dominant: Optional[str]) -> Optional[float]:
        """The agent's stated probability that `dominant` really is the largest
        contributor (CONTRACT.md). Read off `_CONFIDENCE_LADDER` by the kind of
        evidence held for that one claim — deliberately not a function of the
        belief vector, which answers a different question (whether each
        hypothesis contributes at all)."""
        if dominant is None:
            return None
        direct = [e for e in self._ledger.values()
                  if e["quality"] == "direct" and dominant in e["moved"]]
        if not direct:
            indirect = [e for e in self._ledger.values()
                        if e["quality"] == "indirect" and dominant in e["moved"]]
            rung = "indirect_only" if indirect else "no_measurement"
            return _CONFIDENCE_LADDER[rung]
        contested = any(e["conflict"] for e in direct) or any(
            len(e["moved"]) > 1 for e in direct
        )
        rung = "direct_measurement_contested" if contested else "direct_measurement_uncontested"
        return _CONFIDENCE_LADDER[rung]

    def _citations(self) -> list[dict]:
        """Structured citations only: {"experiment", "supports"}. `supports` is
        read off the experiment's own question — CONTRACT.md rejects a conclude
        carrying bare strings, so the written reasoning stays agent-side."""
        citations = []
        for eid in self._ledger:
            citations.append({"experiment": eid, "supports": self._supports(eid)})
        return sorted(citations, key=lambda c: c["experiment"])

    def _supports(self, eid: str) -> str:
        question = _tokens(self._experiment_by_id[eid].get("question", "") + " " +
                           self._experiment_by_id[eid].get("readout", ""))
        if "target" in question and {"killing", "kill", "kills"} & question:
            return "target_claim"
        if {"potent", "potency"} & question:
            return "potency"
        if {"bind", "binds", "binding"} & question:
            return "target_engagement"
        return "mechanism"

    def _conclude(self) -> Action:
        dominant = self._dominant_cause()
        contributing = sorted(hid for hid, p in self.beliefs.items() if p > _CONTRIBUTES_AT)
        return Action(
            kind="conclude",
            beliefs=dict(self.beliefs),
            dominant_cause=dominant,
            contributing_hypotheses=contributing,
            confidence=self._state_confidence(dominant),
            evidence_cited=self._citations(),
            # Asserted only when an experiment that asks the target question was
            # actually run; asserting it on inference would be a misdeclaration.
            makes_target_claim=self._target_evidence is not None,
        )

    # --- agent-side narrative (never sent to the Env) -------------------------
    def rationale(self) -> list[str]:
        """Why the agent holds its current beliefs, for logs and review. Kept
        off the Action: `evidence_cited` takes structured citations only."""
        lines = [f"prior {_PRIOR} on each of {', '.join(self.hypothesis_ids)} "
                 f"(independent; more than one may be true)"]
        for eid, entry in self._ledger.items():
            moved = ", ".join(sorted(entry["moved"])) or "nothing"
            lines.append(
                f"{eid} ({self._experiment_by_id[eid]['name']}, cost "
                f"{self.costs[eid]}): {entry['quality']} evidence, moved {moved}"
                + (" [readouts in tension]" if entry["conflict"] else "")
            )
        dominant = self._dominant_cause()
        lines.append(
            f"beliefs {self.beliefs}; dominant_cause {dominant}; "
            f"stated confidence {self._state_confidence(dominant)}"
        )
        return lines


def build() -> BaselineAgent:
    """Factory, so a runner does not need to know the class name."""
    return BaselineAgent()

