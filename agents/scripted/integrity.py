"""Integrity agent, scripted control arm — refuses to assert more than it has bought.

Deterministic counterpart of agents/prompts/integrity.md: the same discipline
hand-coded, so the LLM arm can be compared against a policy with no model in it.

Variant character (the only thing that differs from other arms; the contract
definitions of `beliefs`, `dominant_cause`, `confidence` and `evidence_cited`
are followed verbatim, per CONTRACT.md):

1. Pre-registration. The purchase plan and the decision rule each purchase is
   meant to settle are fixed in `PLAN` before the episode starts, so a result
   cannot be reinterpreted after the fact to suit the belief the agent already
   holds. Every rule writes one line into `self.ledger`.
2. Legibility gate, with a weaker second channel. A belief moves at full weight
   only on a number the agent can read out of `Observation.structured`. If the
   quantity it pre-registered is not there, it falls back to a number parsed out
   of the prose in `Observation.results` next to the words it pre-registered —
   recorded as WEAK and applied at `PROSE_WEIGHT` of the full update, because a
   sentence is not a measurement. If neither channel yields the quantity, the
   rule is ILLEGIBLE, no belief moves, and the experiment is not cited as
   evidence even though it was paid for.
   `Observation.informativeness` is never read: a live Env reports "UNRATED".
3. Declaration discipline. `makes_target_claim` is True only when the agent both
   ran the target-dependence panel and could read a direction out of it; a
   dominant cause is named only when a discriminating experiment resolved and
   the leader's margin clears `MARGIN`; `evidence_cited` lists only experiments
   in `state.experiments_run`.
4. Self-reported confidence. `confidence` is the agent's stated probability that
   `dominant_cause` is the largest contributor, read off the pre-committed
   `CONFIDENCE_LADDER` by what evidence it bought and how much of it was
   legible. It is never computed from the belief vector, and it is None when no
   dominant cause is named.

`State` is env-owned: this module only reads `budget_remaining`,
`experiments_run` and `concluded`, and never writes to it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from contract import Action, ExperimentId, HypothesisId, Observation, State

BRIEFING = "__briefing__"
HYPOTHESES: tuple[HypothesisId, ...] = ("H1", "H2", "H3", "H4")

# Priors justified by briefing.starting_facts alone, before any purchase:
# H1 — the headline IC50 moves 65 -> 730 nM between stocks and the Hill slope is
#      1.6, both compatible with a misleading tube assay; but inhibition is fully
#      reversible after 500-fold dilution and IC50 is independent of enzyme
#      concentration, which argues against the usual artefacts.
# H2 — a reversible active-site binder facing millimolar intracellular CoA is a
#      live possibility a priori and nothing in the briefing speaks to it.
# H3/H4 — MIC90 > 100 uM with a genuine-looking biochemical potency leaves both
#      cell-side barriers open; neither is favoured by the briefing.
PRIORS: dict[HypothesisId, float] = {"H1": 0.30, "H2": 0.50, "H3": 0.50, "H4": 0.50}

# A dominant cause is named only when the leader clears the runner-up by this
# margin AND a discriminating experiment resolved.
MARGIN = 0.15

# Updates derived from a number parsed out of readout prose rather than from
# `structured` are applied at this fraction of their full weight.
PROSE_WEIGHT = 0.5

# Stated probability that the named dominant cause is the largest contributor.
# Pre-committed before the episode; selected by evidence bought, not derived
# from `beliefs`.
CONFIDENCE_LADDER = {
    "discriminating_and_target": 0.75,  # cell-side discrimination + a legible target panel
    "discriminating": 0.65,             # cell-side discrimination resolved, target panel not
    "partial": 0.45,                    # some rules resolved, none discriminating H3 vs H4
    "illegible": 0.35,                  # bought the discriminating experiment, could not read it
}

# Pre-registered plan. 2 + 4 + 2 = 8 = briefing.budget.units, so the plan spends
# the budget exactly and buys one experiment per open question:
#   E1 binding-vs-artefact and substrate competition (H1, H2)
#   E6 the only direct cell-side measurement, separating H3 from H4
#   E3 target dependence, without which no target claim may be declared
# E2 (4) would re-answer E1's question at twice the cost and E4 (3) asks about
# potency, which the briefing already shows is not the barrier; buying either
# would price E6 or E3 out of an 8-unit budget.
PLAN: tuple[tuple[ExperimentId, dict, str], ...] = (
    (
        "E1",
        {"buffer": "gel_filtration", "coa_mM": 1.0, "compound_uM": 50.0},
        "R1: a thermal shift at saturating compound demonstrates binding to the purified "
        "enzyme (H1 down); a shift retained with coenzyme A present shows the substrate "
        "does not exclude it (H2 down), abolished shows it does (H2 up). Gel-filtration "
        "buffer and a declared coa_mM are pre-set so the +/-CoA comparison is the only "
        "difference between arms.",
    ),
    (
        "E6",
        {
            "arms": ["parent_diacid", "diethyl_ester", "monoacid"],
            "controls": [
                "bacteria-free filtrate incubation (no bacteria), to attribute loss to the cells",
                "input quantification at t=0",
            ],
        },
        "R2: intrabacterial LC-MS is the only measurement that separates not getting in "
        "(H3) from not surviving inside (H4). Intact intracellular material low with "
        "little modified product indicts access; a modified fraction at or above the "
        "intact fraction indicts biotransformation. The bacteria-free control is named "
        "explicitly so abiotic loss cannot be mistaken for either.",
    ),
    (
        "E3",
        {"atc_free_days": 7, "read_day": 14, "normalisation_control": "untreated same-passage inoculum, OD-matched"},
        "R3: the four-strain panel is the only licence for a target claim. Killing that "
        "sharpens on pptT knockdown is target-dependent; no strain separation licenses no "
        "target claim at all, rather than a claim that killing is off-target.",
    ),
)

_SUPPORTS_BY_QUESTION = (
    # (substring in the experiment's own `question` text, supports value)
    ("does killing depend", "target_claim"),
    ("act through the nominated target", "target_engagement"),
    ("more potent", "potency"),
    ("still bind", "mechanism"),
    ("where and how does the compound bind", "mechanism"),
    ("how much compound gets inside", "mechanism"),
)


def _strip_private(doc):
    if isinstance(doc, dict):
        return {k: _strip_private(v) for k, v in doc.items() if not k.startswith("_")}
    if isinstance(doc, list):
        return [_strip_private(v) for v in doc]
    return doc


def _load_agent_bundle(base_dir: Optional[Path]) -> dict:
    base = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parents[2]
    out = {}
    for name in ("briefing", "hypotheses", "experiments"):
        with open(base / "agent" / f"{name}.json", encoding="utf-8") as fh:
            out[name] = _strip_private(json.load(fh))
    return out


def _numeric_items(structured: dict) -> list[tuple[str, float]]:
    """Flatten `structured` to (lowercased dotted key, float) pairs."""
    items: list[tuple[str, float]] = []

    def walk(prefix: str, node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(f"{prefix}.{i}", v)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            items.append((prefix.lower(), float(node)))

    walk("", structured or {})
    return items


_NUMBER = re.compile(r"[-+]?\d*\.?\d+")


class _Readout:
    """Two-channel view of one observation.

    `structured` is searched first: the agent pre-registers the quantity it
    wants (the tokens its key should contain), not the environment's spelling of
    it, so a renamed key degrades to ILLEGIBLE rather than to a wrong number.
    If the quantity is not in `structured`, the same tokens are looked for in
    the readout prose and any number in a matching line is returned on the WEAK
    channel. `informativeness` is deliberately not read.
    """

    def __init__(self, observation: Observation) -> None:
        self._items = _numeric_items(observation.structured or {})
        self._lines = [str(r.value).lower() for r in (observation.results or [])]

    def find_all(
        self, include: tuple[str, ...], exclude: tuple[str, ...] = ()
    ) -> tuple[list[tuple[str, float]], Optional[str]]:
        """(label, value) pairs for the pre-registered quantity, plus the channel
        they came from: "structured", "prose", or None when neither has it."""
        hits = [
            (key, value)
            for key, value in self._items
            if all(tok in key for tok in include) and not any(tok in key for tok in exclude)
        ]
        if hits:
            return hits, "structured"
        prose: list[tuple[str, float]] = []
        for line in self._lines:
            if not all(tok in line for tok in include) or any(tok in line for tok in exclude):
                continue
            prose.extend((line, float(m.group())) for m in _NUMBER.finditer(line))
        if prose:
            return prose, "prose"
        return [], None

    def find(
        self, include: tuple[str, ...], exclude: tuple[str, ...] = ()
    ) -> tuple[Optional[float], Optional[str]]:
        hits, channel = self.find_all(include, exclude)
        return (hits[0][1] if hits else None), channel


def _clamp(p: float) -> float:
    return max(0.0, min(1.0, round(p, 3)))


class IntegrityAgent:
    """Implements the `Agent.act` contract of CONTRACT.md."""

    def __init__(self, base_dir=None) -> None:
        self.bundle = _load_agent_bundle(base_dir)
        self._questions = {
            e["id"]: str(e.get("question", "")).lower() for e in self.bundle["experiments"]["experiments"]
        }
        self._costs = {e["id"]: int(e["cost"]) for e in self.bundle["experiments"]["experiments"]}
        self.beliefs: dict[HypothesisId, float] = dict(PRIORS)
        self.ledger: list[str] = []
        self._ingested: list[ExperimentId] = []
        self._resolved: set[str] = set()      # rule ids whose numbers were legible
        self._illegible: set[str] = set()
        self._target_direction: Optional[str] = None   # "dependent" | "independent"

    # --- the contract entry point -------------------------------------------

    def act(self, observation: Observation, state: State) -> Action:
        self._ingest(observation)

        nxt = self._next_purchase(state)
        if nxt is not None:
            eid, params, rule = nxt
            if eid not in (r.split(":")[0] for r in self.ledger):
                self.ledger.append(f"{eid}: buying to settle -- {rule}")
            return Action(
                kind="run_experiment",
                experiment_id=eid,
                parameters=dict(params),
                beliefs=self._beliefs_out(),
                dominant_cause=self._dominant_cause(),
            )
        return self._conclude(state)

    # --- observation handling -------------------------------------------------

    def _ingest(self, observation: Observation) -> None:
        if observation is None:
            return
        eid = observation.experiment_id
        if eid == BRIEFING:
            if "briefing" not in self._ingested:
                self._ingested.append("briefing")
                self.ledger.append(
                    "briefing: priors set from starting_facts only -- reversibility and "
                    "enzyme-concentration independence argue against the usual assay "
                    "artefacts (H1 0.30); nothing yet speaks to H2, H3 or H4."
                )
            return
        if eid in self._ingested:
            return
        self._ingested.append(eid)
        handler = {"E1": self._read_e1, "E3": self._read_e3, "E6": self._read_e6}.get(eid)
        if handler is None:
            self.ledger.append(f"{eid}: no pre-registered rule; result recorded, no belief moved.")
            return
        handler(_Readout(observation))

    def _weight(self, channel: Optional[str]) -> float:
        return PROSE_WEIGHT if channel == "prose" else 1.0

    def _move(self, hid: HypothesisId, delta: float, channel: Optional[str]) -> float:
        applied = delta * self._weight(channel)
        self.beliefs[hid] = _clamp(self.beliefs[hid] + applied)
        return applied

    @staticmethod
    def _tag(channel: Optional[str]) -> str:
        return "WEAK (prose-derived)" if channel == "prose" else "measured"

    def _read_e1(self, readout: "_Readout") -> None:
        """R1: binding (H1) and substrate competition (H2)."""
        with_coa, c_coa = readout.find(("tm", "coa"), exclude=("no_coa", "without", "apo", "minus"))
        apo, c_apo = readout.find(("tm",), exclude=("coa",))
        channel = c_coa or c_apo
        if apo is None and with_coa is None:
            shifts, channel = readout.find_all(("melting",))
            if not shifts:
                shifts, channel = readout.find_all(("shift",))
            values = [v for _, v in shifts]
            if values:
                apo, with_coa = max(values), min(values)
        if apo is None and with_coa is None:
            self._illegible.add("R1")
            self.ledger.append(
                "R1 ILLEGIBLE: no melting-temperature number in structured or in the readout "
                "lines; H1 and H2 unmoved and E1 is not cited as evidence."
            )
            return

        self._resolved.add("R1")
        binding = max(v for v in (apo, with_coa) if v is not None)
        tag = self._tag(channel)
        if binding >= 2.0:
            self._move("H1", -0.20, channel)
            self.ledger.append(
                f"R1a [{tag}]: a thermal shift of {binding:g} at the purified enzyme is real "
                "binding, so the biochemistry is not a pure artefact; H1 lowered."
            )
        else:
            self._move("H1", +0.25, channel)
            self.ledger.append(
                f"R1a [{tag}]: no appreciable thermal shift ({binding:g}); the tube result is "
                "suspect; H1 raised."
            )

        if apo is not None and with_coa is not None and apo != with_coa:
            retained = with_coa / apo if apo else 0.0
            if retained >= 0.5:
                self._move("H2", -0.35, channel)
                self.ledger.append(
                    f"R1b [{tag}]: {retained:.0%} of the shift survives with coenzyme A present; "
                    "the substrate does not exclude the compound; H2 lowered."
                )
            else:
                self._move("H2", +0.30, channel)
                self.ledger.append(
                    f"R1b [{tag}]: only {retained:.0%} of the shift survives with coenzyme A "
                    "present; substrate competition is live; H2 raised."
                )
        elif with_coa is not None and with_coa >= 2.0:
            self._move("H2", -0.30, channel)
            self.ledger.append(
                f"R1b [{tag}]: binding is still measurable with coenzyme A present, so the "
                "substrate does not exclude the compound; H2 lowered, without a paired "
                "substrate-free number to quantify the loss."
            )
        else:
            self.ledger.append("R1b ILLEGIBLE: no +/-coenzyme-A pair to compare; H2 unmoved.")

    def _read_e6(self, readout: "_Readout") -> None:
        """R2: the discriminating cell-side measurement, H3 vs H4."""
        intact, c_intact = readout.find_all(("intact",))
        if not intact:
            intact, c_intact = readout.find_all(
                ("intracellular",), exclude=("biotransform", "metabol", "hydrol")
            )
        modified, c_mod = readout.find_all(("biotransform",))
        if not modified:
            modified, c_mod = readout.find_all(("metabol",))
        if not modified:
            modified, c_mod = readout.find_all(("hydrol",))
        if not intact and not modified:
            self._illegible.add("R2")
            self.ledger.append(
                "R2 ILLEGIBLE: no intracellular-intact or modified-fraction number; H3 and H4 "
                "unmoved, no dominant cause may be named, and E6 is not cited as evidence."
            )
            return

        self._resolved.add("R2")
        best_intact = max((v for _, v in intact), default=None)
        best_modified = max((v for _, v in modified), default=None)

        if best_intact is not None:
            tag = self._tag(c_intact)
            if best_intact < 5.0:
                self._move("H3", +0.30, c_intact)
                self.ledger.append(
                    f"R2a [{tag}]: the largest intact intracellular fraction across the three "
                    f"arms is {best_intact:g}; little of what is applied is inside and intact; "
                    "H3 raised."
                )
            else:
                self._move("H3", -0.25, c_intact)
                self.ledger.append(
                    f"R2a [{tag}]: intact material is recovered inside ({best_intact:g}); access "
                    "is not the binding constraint; H3 lowered."
                )
        else:
            self.ledger.append("R2a ILLEGIBLE: no intact-fraction number; H3 unmoved.")

        if best_modified is not None:
            tag = self._tag(c_mod)
            if best_intact is None or best_modified >= best_intact:
                self._move("H4", +0.35, c_mod)
                self.ledger.append(
                    f"R2b [{tag}]: the modified fraction ({best_modified:g}) is at or above the "
                    f"intact fraction ({best_intact if best_intact is not None else 'unreported'}); "
                    "the series is altered faster than it accumulates; H4 raised."
                )
            elif best_modified >= 5.0:
                self._move("H4", +0.15, c_mod)
                self.ledger.append(
                    f"R2b [{tag}]: a measurable modified fraction ({best_modified:g}) below the "
                    "intact fraction; biotransformation contributes without dominating; H4 raised "
                    "a little."
                )
            else:
                self._move("H4", -0.25, c_mod)
                self.ledger.append(
                    f"R2b [{tag}]: the modified fraction is small ({best_modified:g}); H4 lowered."
                )
        else:
            self._illegible.add("R2b")
            self.ledger.append(
                "R2b ILLEGIBLE: no modified-fraction number, so H4 was not measured and H3 is "
                "not credited with H4's absence; no dominant cause on this basis."
            )

    def _read_e3(self, readout: "_Readout") -> None:
        """R3: target dependence — the only licence for makes_target_claim."""
        mics, channel = readout.find_all(("mic",))
        if not mics:
            self._illegible.add("R3")
            self.ledger.append(
                "R3 ILLEGIBLE: no MIC number; no target claim may be declared and E3 is not "
                "cited as evidence."
            )
            return
        self._resolved.add("R3")
        tag = self._tag(channel)
        knockdown = [v for k, v in mics if "atc" in k or "knockdown" in k or "_kd" in k]
        wild_type = [v for k, v in mics if "h37rv" in k or "wild" in k or "wt" in k]
        if knockdown and wild_type and min(knockdown) * 4 <= min(wild_type):
            self._target_direction = "dependent"
            self.ledger.append(
                f"R3 [{tag}]: killing sharpens by at least 4-fold when the nominated target is "
                "depleted; target-dependent killing may be declared."
            )
        elif knockdown and wild_type:
            self._target_direction = "independent"
            self.ledger.append(
                f"R3 [{tag}]: depleting the nominated target does not sensitise the bacterium; "
                "killing in this series is not target-dependent."
            )
        else:
            self._illegible.add("R3")
            self.ledger.append(
                f"R3 [{tag}]: MIC numbers present but not resolvable per strain; no target claim "
                "declared."
            )

    # --- policy ---------------------------------------------------------------

    def _next_purchase(self, state: State) -> Optional[tuple[ExperimentId, dict, str]]:
        if getattr(state, "concluded", False):
            return None
        budget = int(getattr(state, "budget_remaining", 0))
        already = list(getattr(state, "experiments_run", []) or [])
        for eid, params, rule in PLAN:
            if eid in already:
                continue
            if self._costs[eid] <= budget:
                return eid, params, rule
        return None

    def _beliefs_out(self) -> dict[HypothesisId, float]:
        return {h: _clamp(self.beliefs[h]) for h in HYPOTHESES}

    def _discriminated(self) -> bool:
        """True iff the pre-registered cell-side discrimination actually resolved."""
        return "R2" in self._resolved and "R2b" not in self._illegible

    def _dominant_cause(self) -> Optional[HypothesisId]:
        if not self._discriminated():
            return None
        ranked = sorted(self._beliefs_out().items(), key=lambda kv: kv[1], reverse=True)
        (lead, p_lead), (_, p_second) = ranked[0], ranked[1]
        if p_lead - p_second < MARGIN:
            return None
        return lead

    def _confidence_tier(self, dominant: Optional[HypothesisId]) -> Optional[str]:
        if dominant is None:
            return None
        if self._discriminated():
            if self._target_direction is not None:
                return "discriminating_and_target"
            return "discriminating"
        if "R2" in self._illegible:
            return "illegible"
        return "partial"

    def _citations(self, state: State) -> list[dict]:
        """Only experiments actually run, with `supports` derived from the
        experiment's own question text in agent/experiments.json."""
        cited: list[dict] = []
        for eid in dict.fromkeys(getattr(state, "experiments_run", []) or []):
            if eid in self._illegible_experiments():
                continue
            citation: dict = {"experiment": eid}
            question = self._questions.get(eid, "")
            for needle, supports in _SUPPORTS_BY_QUESTION:
                if needle in question:
                    citation["supports"] = supports
                    break
            cited.append(citation)
        return cited

    def _illegible_experiments(self) -> set[ExperimentId]:
        """An experiment whose every pre-registered rule was illegible is not
        evidence and is not cited as if it were."""
        by_rule = {"R1": "E1", "R2": "E6", "R3": "E3"}
        return {
            eid
            for rule, eid in by_rule.items()
            if rule in self._illegible and rule not in self._resolved
        }

    def _conclude(self, state: State) -> Action:
        beliefs = self._beliefs_out()
        dominant = self._dominant_cause()
        contributing = [h for h in HYPOTHESES if beliefs[h] > 0.5]
        if dominant is not None and dominant not in contributing:
            contributing.append(dominant)
        tier = self._confidence_tier(dominant)
        confidence = CONFIDENCE_LADDER[tier] if tier is not None else None
        makes_target_claim = self._target_direction is not None

        self.ledger.append(
            "conclude: contributing="
            + ",".join(contributing)
            + f" dominant={dominant} confidence={confidence} (ladder tier {tier}) "
            f"target_claim={makes_target_claim}. Confidence is the stated probability that "
            "the named dominant cause is the largest contributor, read off the pre-committed "
            "ladder by evidence bought, not computed from the belief vector."
        )
        return Action(
            kind="conclude",
            beliefs=beliefs,
            dominant_cause=dominant,
            contributing_hypotheses=sorted(contributing),
            confidence=confidence,
            evidence_cited=self._citations(state),
            makes_target_claim=makes_target_claim,
        )


Agent = IntegrityAgent
