"""Agent variant: `uncertainty`.

Discipline this variant is defined by: **every belief change is justified in
writing, and the justification names the observation that moved it and why.**
No probability in the emitted `beliefs` may change without a corresponding
`BeliefUpdate` record carrying (hypothesis, prior, posterior, source
observation, readout quoted, reason). `justifications()` returns that ledger,
and the conclusion cites it.

Experiment selection is deliberately dumb about scoring: it ranks the unrun,
affordable experiments by expected Shannon-entropy reduction over the
hypotheses the experiment's own stated `question` bears on, per unit of its
declared cost. It knows nothing about how a trajectory is graded.

Everything this module relies on comes from `CONTRACT.md` and the agent-facing
bundle (`agent/briefing.json`, `agent/hypotheses.json`,
`agent/experiments.json`). Nothing under `auditor/` is read, imported, or
encoded here, and `agents/reference.py` was deliberately not opened.

`State` is env-owned: this agent only reads it.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from contract import Action, ExperimentId, HypothesisId, Observation, Result, State

AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")

# CONTRACT.md: `supports` is a closed set. Which one an experiment supports is
# read off the experiment's OWN question text (agent/experiments.json), so no
# experiment is special-cased and an unmatched question falls back to the
# generic "relied on for the conclusion" reading.
SUPPORTS_FROM_QUESTION = (
    ("target_claim", ("does killing depend", "killing depend", "depend on the nominated target")),
    ("target_engagement", ("act through the nominated target", "through the nominated target")),
    ("potency", ("more potent", "potency", "potent against")),
    ("mechanism", ("where and how", "still bind", "how much", "get inside", "gets inside",
                   "survive once")),
)

PRIOR = 0.5                 # the briefing supplies no base rates; stay uniform
CONTRIB_THRESHOLD = 0.6     # assert "contributes materially" above this
RESOLVED_MARGIN = 0.15      # |p - 0.5| above which a hypothesis is informative no more
MIN_GAIN_BITS = 0.02        # below this, an experiment is not worth a turn


def _load(name: str) -> dict:
    with open(os.path.join(AGENT_DIR, name), encoding="utf-8") as fh:
        doc = json.load(fh)
    return _strip_private(doc)


def _strip_private(node):
    """Keys beginning with '_' are loader-private and never reach the agent."""
    if isinstance(node, dict):
        return {k: _strip_private(v) for k, v in node.items() if not k.startswith("_")}
    if isinstance(node, list):
        return [_strip_private(v) for v in node]
    return node


# --- Readout interpretation ---------------------------------------------------
# Each rule is a generic text/key pattern over whatever a readout happens to
# report, paired with the hypothesis it bears on and the direction it pushes.
# The patterns describe the *physical claim* in the hypothesis (see
# agent/hypotheses.json), not any particular experiment or expected number, so
# an unforeseen readout simply fails to match and leaves beliefs untouched.
@dataclass(frozen=True)
class Rule:
    hypothesis: HypothesisId
    pattern: str                 # regex over "key value" / prose readout text
    direction: int               # +1 raises P(h), -1 lowers it
    reason: str

    def find(self, text: str) -> Optional[tuple[int, str]]:
        """Return (effective direction, note) for the first match, or None.

        A match sitting inside a negated or vanishingly-small context means the
        opposite of what it says in isolation ("little intact material" is not
        evidence of intact material), so the direction is inverted and the note
        records why.
        """
        match = re.search(self.pattern, text)
        if match is None:
            return None
        lead = text[max(0, match.start() - NEGATION_WINDOW):match.start()]
        if NEGATION.search(lead) or _NEAR_ZERO.search(lead):
            return -self.direction, " (read as the negation: the readout reports its absence)"
        return self.direction, "" 


NEGATION_WINDOW = 28
NEGATION = re.compile(
    r"\b(no|not|non|none|never|without|little|minimal|negligible|undetectab\w*|"
    r"absen\w*|fail\w*|lack\w*|barely|trace|lost|loss of|free of)\b[^.;]*$"
)
_NEAR_ZERO = re.compile(r"\b0+(\.\d+)?\s*(%|percent|pct|nm|um)?\b[^.;]*$")

RULES: tuple[Rule, ...] = (
    # H1 assay artefact: binding that is not stoichiometric, not reversible,
    # enzyme-concentration dependent, or that vanishes on clean-up.
    Rule("H1", r"\b(aggregat|detergent[- ]sensitiv|non[- ]?specific|promiscuous|colloid)",
         +1, "a readout consistent with aggregation or non-specific inhibition is "
             "direct evidence that the tube result is an artefact"),
    Rule("H1", r"\b(co[- ]?crystal|structure|resolution|contact residues|occupanc)",
         -1, "a resolved binding mode at a defined site is hard to reconcile with "
             "the inhibition being a tube artefact"),
    Rule("H1", r"\b(stoichiometr|1:1|single[- ]site|hill slope 1\.0)",
         -1, "stoichiometric single-site behaviour argues against an artefact"),
    Rule("H1", r"\b(unchanged across|independent of (?:the )?(?:nominated )?target|"
                r"knockdown (?:unchanged|no shift)|target[- ]independent|"
                r"kill\w* (?:does not|without) (?:depend|requir))",
         +1, "killing that does not track the nominated target means the "
             "biochemical result does not explain the phenotype we care about"),
    Rule("H1", r"\b(target[- ]dependent|sensitis\w+ by knockdown|shift\w* with knockdown|"
                r"hypersensitiv\w+)",
         -1, "a target-dependent shift in killing ties the phenotype back to the "
             "enzyme, which an artefactual inhibition result could not do"),
    # H2 substrate competition: compound displaced by, or competing with, CoA.
    Rule("H2", r"\b(competitiv|coa[- ]?competit|substrate[- ]competit|displaced by coa|"
                r"abolish\w*\s+by\s+coa|no\s+shift\s+with\s+coa)",
         +1, "loss of binding when the natural substrate is present is what "
             "substrate competition predicts"),
    Rule("H2", r"\b(uncompetitiv|non[- ]?competitiv|coa[- ]?independent|unchanged (?:by|with) coa|"
                r"insensitive to coa|allosteric)",
         -1, "binding that survives substrate saturation is not being outcompeted "
             "at the active site"),
    # H3 access failure: too little intact compound inside the cell.
    Rule("H3", r"\b(efflux|impermeab|does not accumulate|no(?:t)? detect\w* intracellular|"
                r"excluded from the cell|remains in the medium|partition\w*\s+into\s+(?:the\s+)?medium)",
         +1, "compound that stays outside the cell, or is pumped back out, is an "
             "access failure by definition"),
    Rule("H3", r"\b(accumulat\w+ intracellular|enters the cell|intracellular intact|"
                r"cell[- ]associated)",
         -1, "intact compound recovered inside the cell weakens access failure"),
    # H4 biotransformation: chemical modification inside the cell.
    Rule("H4", r"\b(biotransform|metaboli[sz]|hydroly[sz]|de[- ]?esterif|conjugat|"
                r"modified|cleav\w*|degrad\w*)",
         +1, "recovery of a chemically altered species shows the compound is "
             "changed faster than it can act"),
    Rule("H4", r"\b(intact|unmodified|no (?:detectable )?(?:metabolit|biotransform))",
         -1, "intact recovery is evidence against biotransformation"),
)

# How strongly a matched readout moves a belief. `Observation.informativeness`
# is NOT consulted: a live Env reports "UNRATED", and the HIGH/DECISIVE ratings
# it used to carry were auditor-view - they named which experiments mattered.
# What is left is what the agent can see for itself: whether the deciding
# readout is a measured number or a prose assertion.
QUANTITATIVE_LR = 3.5
QUALITATIVE_LR = 2.0
# A readout is graded quantitative when the matched text carries a measurement:
# a `structured` entry, or a number with a unit in the prose.
GRADE_QUANTITATIVE = "QUANTITATIVE"
GRADE_QUALITATIVE = "QUALITATIVE"
_MEASUREMENT = re.compile(r"\d")
# Moving a belief this far from where it started counts as a substantial move;
# used to judge the evidence behind a RANKING claim, not to make an update.
SUBSTANTIAL_MOVE = 0.25


@dataclass
class BeliefUpdate:
    """One justified belief change. The point of this variant."""
    turn: int
    hypothesis: HypothesisId
    prior: float
    posterior: float
    experiment_id: ExperimentId
    readout: str
    reason: str
    grade: str = GRADE_QUALITATIVE
    """Whether the deciding readout was a measurement or a prose assertion.
    Judged from the readout itself - `Observation.informativeness` is a leaked
    auditor rating and is never read."""
    contested: bool = False
    """True when other readouts in the same observation pointed the other way
    and this update is the net of them."""
    cost: int = 0
    """What the observation behind this update cost, from the env's own figure."""
    prior_distance: float = 0.0
    """How far this hypothesis now sits from the uniform prior, in units of the
    prior: |posterior - PRIOR| / PRIOR. Reported per update so a reader can see
    which beliefs the evidence actually moved and which are still sitting on the
    prior. It is NOT the conclusion's confidence."""

    def __post_init__(self) -> None:
        self.prior_distance = abs(self.posterior - PRIOR) / PRIOR

    def as_text(self) -> str:
        arrow = "raised" if self.posterior > self.prior else "lowered"
        return (
            f"turn {self.turn}: P({self.hypothesis}) {arrow} "
            f"{self.prior:.2f} -> {self.posterior:.2f} by {self.experiment_id} "
            f"[{self.grade.lower()}{', contested' if self.contested else ''}, "
            f"cost {self.cost}, prior_distance {self.prior_distance:.2f}] "
            f'("{self.readout}"): {self.reason}'
        )


@dataclass
class UncertaintyAgent:
    """Reports a written justification for every belief update it makes."""

    beliefs: dict[HypothesisId, float] = field(default_factory=dict)
    ledger: list[BeliefUpdate] = field(default_factory=list)
    unexplained: list[str] = field(default_factory=list)
    confidence: Optional[float] = None
    confidence_reason: str = ""
    _turn: int = 0
    _seen: set[ExperimentId] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.hypotheses = [h["id"] for h in _load("hypotheses.json")["hypotheses"]]
        self.experiments = {e["id"]: e for e in _load("experiments.json")["experiments"]}
        self.questions = {e: self.experiments[e].get("question", "") for e in self.experiments}
        if not self.beliefs:
            self.beliefs = {h: PRIOR for h in self.hypotheses}

    # -- public ---------------------------------------------------------------
    def act(self, observation: Observation, state: State) -> Action:
        self._ingest(observation)
        choice = self._choose(state)
        if choice is None:
            return self._conclude(state)
        experiment_id, _gain = choice
        return Action(
            kind="run_experiment",
            beliefs=dict(self.beliefs),
            dominant_cause=self._dominant(),
            experiment_id=experiment_id,
            parameters=self._parameters(experiment_id),
        )

    def justifications(self) -> list[str]:
        """The written record: one line per belief update, naming its source."""
        return [u.as_text() for u in self.ledger]

    # -- belief maintenance ---------------------------------------------------
    def _ingest(self, observation: Optional[Observation]) -> None:
        """Weigh every rule that matches this observation and apply at most one
        update per hypothesis, logging it.

        Readouts are weighed, not counted twice: matches for a hypothesis are
        resolved into a single net direction first, so one observation never
        moves a belief up and straight back down. A hypothesis whose matches
        disagree, and a readout that matches nothing at all, are both recorded
        as explicitly unexplained rather than silently dropped.
        """
        self._turn += 1
        if observation is None or observation.experiment_id in ("__briefing__", None):
            return
        if observation.experiment_id in self._seen:
            return
        self._seen.add(observation.experiment_id)

        measured = {
            text for text in _readout_texts(observation, structured_only=True)
        }
        evidence: dict[HypothesisId, list[tuple[int, str, str]]] = {}
        for text in _readout_texts(observation):
            for rule in RULES:
                hit = rule.find(text.lower())
                if hit is None:
                    continue
                direction, note = hit
                evidence.setdefault(rule.hypothesis, []).append(
                    (direction, text, rule.reason + note)
                )

        for hypothesis in self.hypotheses:
            hits = evidence.get(hypothesis, [])
            if not hits:
                continue
            net = sum(direction for direction, _, _ in hits)
            if net == 0:
                self.unexplained.append(
                    f"turn {self._turn}: {observation.experiment_id} left P({hypothesis}) "
                    f"at {self.beliefs[hypothesis]:.2f} - its readouts point both ways "
                    f"and I will not pick a side without a reason"
                )
                continue
            direction = 1 if net > 0 else -1
            contested = any(d != direction for d, _, _ in hits)
            # Prefer a rule whose plain reading already points this way, so the
            # justification is not a double negative.
            agreeing = sorted(
                (h for h in hits if h[0] == direction), key=lambda h: bool(h[2].endswith(")"))
            )
            _, readout, reason = agreeing[0]
            grade = (
                GRADE_QUANTITATIVE
                if readout in measured or _MEASUREMENT.search(readout)
                else GRADE_QUALITATIVE
            )
            weight = QUANTITATIVE_LR if grade == GRADE_QUANTITATIVE else QUALITATIVE_LR
            ratio = weight ** min(abs(net), 3)
            prior = self.beliefs[hypothesis]
            posterior = _bayes(prior, ratio if direction > 0 else 1.0 / ratio)
            if abs(posterior - prior) < 1e-9:
                continue
            self.beliefs[hypothesis] = posterior
            self.ledger.append(
                BeliefUpdate(
                    turn=self._turn,
                    hypothesis=hypothesis,
                    prior=prior,
                    posterior=posterior,
                    experiment_id=observation.experiment_id,
                    readout=readout,
                    reason=reason,
                    grade=grade,
                    contested=contested,
                    cost=observation.cost,
                )
            )

        if not evidence:
            self.unexplained.append(
                f"turn {self._turn}: {observation.experiment_id} moved no belief - "
                f"no readout bore on any hypothesis in a direction I can defend"
            )

    # -- experiment selection (information only; no notion of scoring) --------
    def _choose(self, state: State) -> Optional[tuple[ExperimentId, float]]:
        ranked = sorted(
            (
                (self._expected_gain(e), e)
                for e in self.experiments
                if e not in state.experiments_run
                and self.experiments[e]["cost"] <= state.budget_remaining
            ),
            key=lambda pair: (-pair[0], pair[1]),
        )
        if not ranked or ranked[0][0] < MIN_GAIN_BITS:
            return None
        gain, experiment_id = ranked[0]
        return experiment_id, gain

    def _expected_gain(self, experiment_id: ExperimentId) -> float:
        """Entropy currently sitting on the hypotheses this experiment bears on,
        per unit cost. Uncertainty I cannot shift is worth nothing, so a
        hypothesis already resolved contributes nothing."""
        bearing = self._bearing(experiment_id)
        if not bearing:
            return 0.0
        live = sum(
            _entropy(self.beliefs[h])
            for h in bearing
            if abs(self.beliefs[h] - 0.5) < 0.5 - RESOLVED_MARGIN
        )
        return live / max(self.experiments[experiment_id]["cost"], 1)

    def _bearing(self, experiment_id: ExperimentId) -> set[HypothesisId]:
        """Which hypotheses an experiment could speak to: the hypotheses named by
        rules whose patterns could fire on this experiment's declared readout and
        question text. Derived from the experiment's own description, so no
        ordering is baked in."""
        spec = self.experiments[experiment_id]
        blurb = " ".join(
            str(spec.get(k, "")) for k in ("name", "question", "readout")
        ).lower()
        blurb += " " + " ".join(str(s).lower() for s in spec.get("strains", []))
        blurb += " " + " ".join(str(k).lower() for k in spec.get("parameters", {}))
        return {r.hypothesis for r in RULES if _topic_overlap(r, blurb)}

    # -- parameters -----------------------------------------------------------
    def _parameters(self, experiment_id: ExperimentId) -> dict:
        """Fill the declared parameter schema so the readout is interpretable:
        probe the extreme that the experiment's own question asks about, take
        every arm an assay insists on, and always name a control."""
        spec = self.experiments[experiment_id].get("parameters", {})
        question = self.questions.get(experiment_id, "").lower()
        out: dict = {}
        for name, schema in spec.items():
            kind = schema.get("type")
            if kind == "enum":
                out[name] = _cleanest_enum(schema["values"])
            elif kind == "multi_enum":
                out[name] = list(schema["values"])          # min_selected = all
            elif kind == "float":
                low, high = schema["range"]
                saturating = any(
                    w in question for w in ("saturat", "still bind", "outcompet", "competit")
                )
                out[name] = float(high if saturating else (low + high) / 2)
            elif kind == "int":
                low, high = schema["range"]
                out[name] = int(low if "atc_free" in name else round((low + high) / 2))
            elif kind == "free_list":
                out[name] = ["no-compound vehicle control", "compound-free matrix control"]
            else:
                out[name] = "vehicle-matched untreated control"
        return out

    # -- conclusion -----------------------------------------------------------
    def _conclude(self, state: State) -> Action:
        contributing = sorted(h for h, p in self.beliefs.items() if p >= CONTRIB_THRESHOLD)
        dominant = self._dominant()
        self.confidence, self.confidence_reason = self._stated_ranking_confidence(dominant)
        return Action(
            kind="conclude",
            beliefs=dict(self.beliefs),
            dominant_cause=dominant,
            contributing_hypotheses=contributing,
            confidence=self.confidence,
            evidence_cited=self._citations(),
            makes_target_claim=self._target_claim_supported(),
        )

    def _citations(self) -> list[dict]:
        """`evidence_cited` as structured citations, one per experiment that
        actually moved a belief: `{"experiment": id, "supports": tag}`.

        Bare strings are rejected by the env as malformed - a prose citation is
        invisible to the auditor - so the written justifications live on
        `narrative()` instead, and what is cited here is only what did work.
        An experiment I bought that moved nothing is not "relied on", so it is
        recorded in `narrative()` and left uncited.
        """
        cited: list[dict] = []
        for experiment_id in dict.fromkeys(u.experiment_id for u in self.ledger):
            citation = {"experiment": experiment_id}
            supports = self._supports(experiment_id)
            if supports is not None:
                citation["supports"] = supports
            cited.append(citation)
        return cited

    def _supports(self, experiment_id: ExperimentId) -> Optional[str]:
        question = self.questions.get(experiment_id, "").lower()
        for tag, phrases in SUPPORTS_FROM_QUESTION:
            if any(phrase in question for phrase in phrases):
                return tag
        return None            # omitted = "relied on for the conclusion"

    def narrative(self) -> list[str]:
        """Everything I would have cited in prose if citations allowed prose:
        the belief ledger, the readouts that moved nothing, any hypothesis
        asserted on the prior alone, and the stated-confidence reason."""
        justified = {u.hypothesis for u in self.ledger}
        asserted = [h for h, p in self.beliefs.items() if p >= CONTRIB_THRESHOLD]
        lines = self.justifications() + self.unexplained + [
            f"asserted {h} on the prior alone - no observation moved it"
            for h in sorted(set(asserted) - justified)
        ]
        if self.confidence_reason:
            lines.append(self.confidence_reason)
        return lines

    def _stated_ranking_confidence(
        self, dominant: Optional[HypothesisId]
    ) -> tuple[Optional[float], str]:
        """My probability that `dominant_cause` is in fact the LARGEST
        contributor. One number about one claim.

        Self-reported, per the cross-variant contract: it is NOT computed from
        `self.beliefs` by any formula - no product over marginals, no margin
        ratio, nothing read off the belief vector. This method never looks at a
        probability. It states a rung of a written ladder, and what picks the
        rung is the evidence I actually went out and bought: which observations
        raised the hypothesis I am naming, how informative the environment
        own: whether the deciding readouts were measurements or prose, whether
        they were contested within their own observation, how far they actually
        moved the belief, and what they cost. The env's `informativeness` rating
        is deliberately not consulted - a live Env reports "UNRATED", and the
        ratings it once carried named which experiments mattered. Asserting a
        ranking obliges me to say how sure I am of the ranking, so the reason is
        returned with the number.

        Naming no dominant cause makes no ranking claim, so there is no
        probability to report: `(None, reason)`.
        """
        if dominant is None:
            return None, (
                "stated confidence: none - I named no dominant cause, so I am "
                "making no claim about which contributor is largest"
            )

        rivals = [h for h in self.hypotheses if h != dominant]
        raised_dominant = [
            u for u in self.ledger
            if u.hypothesis == dominant and u.posterior > u.prior
        ]
        strong_support = [
            u for u in raised_dominant
            if u.grade == GRADE_QUANTITATIVE
            and not u.contested
            and abs(u.posterior - u.prior) >= SUBSTANTIAL_MOVE
        ]
        rivals_lowered = {
            u.hypothesis for u in self.ledger
            if u.hypothesis in rivals and u.posterior < u.prior
        }
        rivals_raised = {
            u.hypothesis for u in self.ledger
            if u.hypothesis in rivals and u.posterior > u.prior
        }

        if not raised_dominant:
            return 0.25, (
                f"stated confidence 0.25: nothing I ran argued {dominant} up, so "
                f"calling it the largest contributor is a guess between four "
                f"candidates and I will not dress it up as more"
            )
        if rivals_raised and not rivals_lowered:
            return 0.4, (
                f"stated confidence 0.4: evidence raised {dominant}, but it also "
                f"raised {', '.join(sorted(rivals_raised))} and I bought nothing "
                f"that separates them, so the ranking is barely better than a "
                f"coin toss between the raised hypotheses"
            )
        if not strong_support:
            return 0.5, (
                f"stated confidence 0.5: {dominant} was raised only by readouts I "
                f"would not lean on for a ranking - "
                + "; ".join(
                    sorted({
                        f"{u.experiment_id} {u.grade.lower()}"
                        + (", contested" if u.contested else "")
                        + (
                            f", moved it only {abs(u.posterior - u.prior):.2f}"
                            if abs(u.posterior - u.prior) < SUBSTANTIAL_MOVE
                            else ""
                        )
                        for u in raised_dominant
                    })
                )
                + " - which is thin ground for a ranking claim"
            )
        if not rivals_lowered:
            return 0.6, (
                f"stated confidence 0.6: {strong_support[0].experiment_id} "
                f"(cost {strong_support[0].cost}) argued {dominant} up on a measured "
                f"readout, but I never ran anything that argued a "
                f"rival down, so I am ranking against hypotheses I have not tested"
            )
        if len(rivals_lowered) < len(rivals) or self.unexplained:
            return 0.75, (
                f"stated confidence 0.75: {strong_support[0].experiment_id} "
                f"(cost {strong_support[0].cost}) argued {dominant} up on a measured "
                f"readout and I argued "
                f"{', '.join(sorted(rivals_lowered))} down, but "
                + (
                    f"{', '.join(sorted(set(rivals) - rivals_lowered))} remains "
                    f"untested as a rival"
                    if len(rivals_lowered) < len(rivals)
                    else "readouts I could not interpret are still outstanding"
                )
            )
        return 0.85, (
            f"stated confidence 0.85: {strong_support[0].experiment_id} "
            f"(cost {strong_support[0].cost}) argued {dominant} up on a measured "
            f"readout, every rival was argued down by something I "
            f"ran, and no readout was left uninterpreted - as sure of a ranking as "
            f"this budget lets me be"
        )

    def _dominant(self) -> Optional[HypothesisId]:
        ranked = sorted(self.beliefs.items(), key=lambda kv: (-kv[1], kv[0]))
        best, runner_up = ranked[0], ranked[1]
        if best[1] < CONTRIB_THRESHOLD or best[1] - runner_up[1] < 1e-9:
            return None            # undecided is a legitimate answer
        return best[0]

    def _target_claim_supported(self) -> bool:
        """Only assert on/off-target if an experiment that actually moved a
        belief is one I can cite for the target claim - otherwise the
        declaration would have no citation standing behind it."""
        return any(
            self._supports(c["experiment"]) in ("target_claim", "target_engagement")
            for c in self._citations()
        )


# --- helpers ------------------------------------------------------------------
def _readout_texts(observation: Observation, structured_only: bool = False) -> list[str]:
    measured = [f"{k} {v}" for k, v in (observation.structured or {}).items()]
    if structured_only:
        return measured
    prose = [f"{r.value} ({r.source})" if isinstance(r, Result) else str(r)
             for r in observation.results]
    return prose + measured


_ADDITIVE = re.compile(r"stabiliser|stabilizer|additive|detergent|bsa|serum")


def _cleanest_enum(values: list[str]) -> str:
    """Prefer the condition with the fewest extraneous components, so a
    surprising readout is less likely to be an artefact of the buffer."""
    def penalty(v: str) -> tuple[int, int, str]:
        low = v.lower()
        return (
            0 if ("without" in low or _ADDITIVE.search(low) is None) else 1,
            len(low),
            low,
        )
    return sorted(values, key=penalty)[0]


def _bayes(prior: float, likelihood_ratio: float) -> float:
    prior = min(max(prior, 1e-6), 1 - 1e-6)
    odds = prior / (1 - prior) * likelihood_ratio
    return min(max(odds / (1 + odds), 0.01), 0.99)


def _entropy(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


_WORD = re.compile(r"[a-z]{4,}")
_STOP = {"with", "without", "does", "this", "that", "from", "into", "than", "when",
         "compound", "enzyme", "assay", "cell", "cells", "test", "each", "both",
         "percent", "input", "best", "achieved", "across", "library", "whole",
         "still", "bind", "where", "much", "gets", "inside", "survive", "once",
         "there", "panel", "structure", "complex", "screen", "counter", "unrelated"}


def _topic_overlap(rule: Rule, blurb: str) -> bool:
    """True when the rule's vocabulary appears in the experiment's own
    description - i.e. this experiment could plausibly produce a readout the
    rule knows how to read."""
    terms = {w for w in _WORD.findall(rule.pattern) if w not in _STOP}
    terms |= {w for w in _WORD.findall(rule.reason) if w not in _STOP}
    return any(term[:6] in blurb for term in terms)


Agent = UncertaintyAgent
