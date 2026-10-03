"""Falsification-seeking agent — deterministic control arm.

The LLM arm of this variant is the system prompt in
agents/prompts/falsification.md run through agents/llm_agent.py; this module
is the hand-coded policy it is compared against.

Its discipline, in one line: at every turn, buy the experiment whose result
would look most different if the hypothesis it currently leads with were
wrong, rather than one that would decorate it.

Everything here is coded against CONTRACT.md and the agent-facing bundle
(agent/briefing.json, agent/hypotheses.json, agent/experiments.json). The
severity table below is built from each experiment's own `question` and
`readout` text; no auditor material is consulted, and `informativeness` is
never read (a live Env always reports "UNRATED").

Contract points this variant is careful about:
  * beliefs and dominant_cause go on every Action, never onto State (State is
    env-owned and read-only here).
  * evidence_cited entries are citation objects {"experiment", "supports"?};
    bare strings are refused by the Env and would leave the episode open.
  * confidence is the agent's stated probability that `dominant_cause` really
    is the largest contributor. It is reported directly from the severity
    ledger (which severe tests were bought and what they did), never computed
    from the belief vector.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from contract import Action, Observation, State

BRIEFING_EXPERIMENT_ID = "__briefing__"

# --- priors, from briefing.starting_facts only --------------------------------
# Reversible inhibition with enzyme-concentration-independent IC50 argues
# against the classic aggregation artefact, but the three disagreeing IC50s
# (65 / 730 / 250 nM) and a Hill slope of 1.6 keep H1 live. Intracellular CoA
# is millimolar, so H2 is plausible a priori. MIC90 > 100 uM with an otherwise
# potent inhibitor is equally consistent with H3 and H4; nothing yet separates
# them.
PRIORS: dict[str, float] = {"H1": 0.35, "H2": 0.40, "H3": 0.45, "H4": 0.40}

# --- what could refute what ---------------------------------------------------
# severity[hypothesis][experiment] = how decisively that experiment's readout
# could come out *against* the hypothesis, read off the experiment's declared
# question/readout in agent/experiments.json.
SEVERITY: dict[str, dict[str, float]] = {
    # "Where and how does the compound bind?" — a resolved complex with named
    # contact residues is the hardest thing for "the tube assay is misleading"
    # to survive. A thermal shift in stabiliser-free buffer is a cheaper,
    # weaker version of the same test.
    "H1": {"E2": 0.9, "E1": 0.6, "E4": 0.3},
    # "Does the compound still bind when the enzyme is saturated with its
    # natural substrate?" — E1 is built to kill H2.
    "H2": {"E1": 0.9, "E2": 0.4},
    # "How much compound gets inside?" — intact intracellular material refutes
    # access failure outright; the MIC panel is a weak proxy.
    "H3": {"E6": 0.9, "E3": 0.3},
    # "...and does it survive once there?" — the biotransformed fraction is the
    # direct test of H4.
    "H4": {"E6": 0.9, "E5": 0.2},
}

# Experiments that speak to whether killing depends on the nominated target.
# Only these license makes_target_claim.
TARGET_CLAIM_TESTS = {"E3": 0.8, "E5": 0.9}

# Which claim a citation of each experiment supports, taken from its question.
SUPPORTS: dict[str, str] = {
    "E1": "target_engagement",
    "E2": "target_engagement",
    "E3": "target_claim",
    "E4": "potency",
    "E5": "target_claim",
    "E6": "mechanism",
}

CONTRIBUTING_THRESHOLD = 0.60   # assert as a material contributor at/above this
REFUTED_THRESHOLD = 0.20        # treat as knocked down below this
_CLAMP = (0.02, 0.98)


def _clamp(p: float) -> float:
    lo, hi = _CLAMP
    return max(lo, min(hi, p))


def _load_bundle(base_dir: Optional[Path] = None) -> tuple[dict, list[dict]]:
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2]
    with open(base / "agent" / "briefing.json", encoding="utf-8") as fh:
        briefing = json.load(fh)
    with open(base / "agent" / "experiments.json", encoding="utf-8") as fh:
        experiments = json.load(fh)["experiments"]
    return briefing, experiments


def _walk(structured: dict):
    """Yield (dotted_key, value) for every leaf in a nested structured dict."""
    stack = [("", structured)]
    while stack:
        prefix, node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                stack.append((f"{prefix}.{k}" if prefix else str(k), v))
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                stack.append((f"{prefix}.{i}", v))
        else:
            yield prefix, node


_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


def _readings(observation: Observation) -> list[tuple[str, float]]:
    """Every number this observation offers, each paired with the text that
    labels it: the dotted key for a `structured` leaf, the surrounding clause
    for a number written into a readout line.

    Both halves matter. `structured` is the machine-readable block, but several
    experiments report only prose, and an agent that cannot read its own
    readout is buying experiments it cannot be refuted by.
    """
    out: list[tuple[str, float]] = []
    for key, value in _walk(observation.structured or {}):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        out.append((key.lower(), float(value)))
    for result in observation.results or []:
        text = str(getattr(result, "value", result))
        for clause in re.split(r"[;\n]|(?<=[.!?]) ", text):
            low = clause.lower()
            for m in _NUMBER.finditer(clause):
                try:
                    out.append((low, float(m.group(0).replace(",", "."))))
                except ValueError:
                    continue
    return out


def _all(readings: list[tuple[str, float]], *patterns: str,
         avoid: tuple[str, ...] = ()) -> list[float]:
    """Every number whose label matches every pattern and no `avoid` pattern —
    e.g. one value per arm of a multi-arm experiment."""
    return [
        value for label, value in readings
        if all(re.search(p, label) for p in patterns)
        and not any(re.search(a, label) for a in avoid)
    ]


def _num(readings: list[tuple[str, float]], *patterns: str,
         avoid: tuple[str, ...] = ()) -> Optional[float]:
    """First number whose label matches every pattern and no `avoid` pattern."""
    for label, value in readings:
        if all(re.search(p, label) for p in patterns) and not any(re.search(a, label) for a in avoid):
            return value
    return None


@dataclass
class _Ledger:
    """What each purchase did to the belief it was bought to threaten."""
    severe_tests_passed: dict[str, list[str]] = field(default_factory=dict)   # h -> [eid]
    severe_tests_failed: dict[str, list[str]] = field(default_factory=dict)   # h -> [eid]
    unreadable: list[str] = field(default_factory=list)
    target_dependence_tested: bool = False

    def passed(self, h: str, eid: str) -> None:
        self.severe_tests_passed.setdefault(h, []).append(eid)

    def failed(self, h: str, eid: str) -> None:
        self.severe_tests_failed.setdefault(h, []).append(eid)


class FalsificationAgent:
    """Agent.act per CONTRACT.md. One instance per episode."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        briefing, experiments = _load_bundle(base_dir)
        self.scenario_id: str = briefing["scenario_id"]
        self.costs: dict[str, int] = {e["id"]: int(e["cost"]) for e in experiments}
        self.beliefs: dict[str, float] = dict(PRIORS)
        self.cited: list[str] = []
        self.ledger = _Ledger()
        self.rationale: list[str] = []
        self._seen: set[str] = set()

    # --- Agent protocol -------------------------------------------------------
    def act(self, observation: Observation, state: State) -> Action:
        self._ingest(observation)
        dominant = self._dominant()

        eid = self._next_experiment(state)
        if eid is None:
            return self._conclude(dominant)
        return Action(
            kind="run_experiment",
            beliefs=dict(self.beliefs),
            dominant_cause=dominant,
            experiment_id=eid,
            parameters=self._parameters(eid),
        )

    # --- reading the evidence -------------------------------------------------
    def _ingest(self, observation: Observation) -> None:
        """Update beliefs from an observation: the numbers in `structured` and
        the numbers written into its readout lines, each judged by the text that
        labels it. `informativeness` is never read — a live Env reports
        "UNRATED" and the field is auditor-view metadata by contract."""
        eid = observation.experiment_id
        if eid in (None, BRIEFING_EXPERIMENT_ID) or eid in self._seen:
            return
        self._seen.add(eid)
        self.cited.append(eid)
        reader = getattr(self, f"_read_{eid.lower()}", None)
        before = dict(self.beliefs)
        if reader is None:
            return
        reader(_readings(observation))
        if before == self.beliefs:
            # A severe test that moved nothing is itself a finding, but it is
            # also the signature of a readout this agent could not parse.
            self.ledger.unreadable.append(eid)
            self.rationale.append(f"{eid}: no numeric readout this agent could score.")

    def _read_e1(self, s: list) -> None:
        """Thermal shift, +/- coenzyme A. Apo shift tests H1; the shift retained
        under CoA saturation tests H2."""
        apo = _num(s, r"(tm|shift|delta|stabilis|stabiliz)",
                   avoid=(r"coa", r"coenzyme", r"saturat"))
        with_coa = _num(s, r"(tm|shift|delta|stabilis|stabiliz)",
                        r"(coa|coenzyme|saturat)")
        if apo is None and with_coa is None:
            return
        if apo is not None:
            if abs(apo) >= 1.0:
                self._update("H1", -0.25, "E1: dose-dependent thermal stabilisation — binding is real.")
                self.ledger.failed("H1", "E1")
            else:
                self._update("H1", +0.20, "E1: no thermal shift where binding should produce one.")
                self.ledger.passed("H1", "E1")
        if with_coa is not None and apo:
            retained = with_coa / apo if apo else 0.0
            if retained >= 0.6:
                self._update("H2", -0.30, "E1: binding survives CoA saturation — competition does not explain the failure.")
                self.ledger.failed("H2", "E1")
            else:
                self._update("H2", +0.25, "E1: the shift collapses under CoA — competition is live.")
                self.ledger.passed("H2", "E1")

    def _read_e2(self, s: list) -> None:
        """Co-crystal. A resolved complex with contacts refutes H1; a site away
        from the CoA pocket weakens H2."""
        resolution = _num(s, r"resolution")
        contacts = _num(s, r"contact")
        if resolution is not None or contacts:
            self._update("H1", -0.25, "E2: a resolved complex with defined contacts — the enzyme result is not an artefact.")
            self.ledger.failed("H1", "E2")

    def _read_e3(self, s: list) -> None:
        """Four-strain MIC panel: does killing track the target?"""
        self.ledger.target_dependence_tested = True
        knockdown = _num(s, r"(knockdown|atc)", r"mic")
        wild_type = _num(s, r"(wild|h37rv|wt)", r"mic")
        if knockdown is None or wild_type is None:
            return
        if knockdown < wild_type / 2:
            self._update("H3", +0.10, "E3: depleting the target sensitises the cell — compound reaches it when less is needed.")
        else:
            self._update("H3", +0.05, "E3: no target-dependent sensitisation in whole cells.")

    def _read_e4(self, s: list) -> None:
        """Potency across the library. More potency at the enzyme with no
        whole-cell gain means the enzyme is not the bottleneck."""
        ic50 = _num(s, r"ic50")
        mic = _num(s, r"mic")
        if ic50 is None:
            return
        if mic is None or mic >= 50:
            self._update("H1", -0.10, "E4: potency improves at the enzyme — the biochemistry is reproducible.")
            self._update("H3", +0.10, "E4: enzyme potency buys no whole-cell activity — the barrier is cellular.")
            self._update("H4", +0.10, "E4: enzyme potency buys no whole-cell activity — the barrier is cellular.")

    def _read_e5(self, s: list) -> None:
        """Counter-screen: do the analogues that kill act through the target?"""
        self.ledger.target_dependence_tested = True
        off = _num(s, r"(counter|unrelated|off[-_ ]?target|second)", r"(ic50|ic 50)")
        on = _num(s, r"(pptt|on[-_ ]?target|nominated|primary)", r"(ic50|ic 50)",
                  avoid=(r"off", r"counter", r"unrelated"))
        if off is not None and on is not None and off <= on * 2:
            self._update("H1", +0.05, "E5: the killing analogues hit an unrelated enzyme just as hard — their activity is not target-driven.")

    def _read_e6(self, s: list) -> None:
        """Intrabacterial PK: how much gets in, and does it survive once there.

        The scenario question is about the series, not one compound, so every
        arm is read: the best-accumulating arm decides whether access can be
        refuted at all, and the worst arm still counts as an access barrier for
        part of the library.
        """
        intake = _all(s, r"(intact|cell[-_ ]?associated|uptake|intracellular)",
                      avoid=(r"biotransform", r"metabolis", r"metaboliz", r"medium", r"extracellular"))
        metabolised = _all(s, r"(biotransform|metabolis|metaboliz)")
        medium = _num(s, r"(medium|extracellular)")

        if intake:
            best, worst = max(intake), min(intake)
            if best < 5:
                self._update("H3", +0.30, "E6: no arm puts meaningful intact compound inside — access is a real barrier.")
                self.ledger.passed("H3", "E6")
            elif worst < 5:
                self._update("H3", +0.10, "E6: some arms get in, others do not — access limits part of the series.")
            else:
                self._update("H3", -0.30, "E6: every arm accumulates inside — access failure is refuted.")
                self.ledger.failed("H3", "E6")
        if metabolised:
            if max(metabolised) >= 20:
                self._update("H4", +0.35, "E6: a large biotransformed fraction inside the cell.")
                self.ledger.passed("H4", "E6")
            else:
                self._update("H4", -0.30, "E6: what gets in stays chemically intact — biotransformation is refuted.")
                self.ledger.failed("H4", "E6")
        if medium is not None and medium > 80 and intake and max(intake) < 5:
            self._update("H3", +0.05, "E6: the bulk of the input stays in the medium.")

    def _update(self, h: str, delta: float, why: str) -> None:
        self.beliefs[h] = _clamp(self.beliefs[h] + delta)
        self.rationale.append(why)

    # --- choosing the next purchase ------------------------------------------
    def _dominant(self) -> Optional[str]:
        ranked = sorted(self.beliefs.items(), key=lambda kv: -kv[1])
        top, second = ranked[0], ranked[1]
        if top[1] < 0.5 or top[1] - second[1] < 0.10:
            return None    # nothing yet separates the field; say so
        return top[0]

    def _next_experiment(self, state: State) -> Optional[str]:
        """The affordable, unrun experiment whose result could most make the
        current leader look wrong, per unit of budget. With no leader, the one
        that could most disturb the field as a whole."""
        affordable = [
            eid for eid, cost in self.costs.items()
            if eid not in self._seen and cost <= state.budget_remaining
        ]
        if not affordable:
            return None

        leader = self._dominant()
        scored: list[tuple[float, int, str]] = []
        for eid in affordable:
            severity = SEVERITY.get(leader, {}).get(eid, 0.0) if leader else 0.0
            # Fall back to (and always add) how much the experiment could upset
            # beliefs that are not yet settled: p(1-p) is maximal at 0.5.
            spread = sum(
                SEVERITY[h].get(eid, 0.0) * self.beliefs[h] * (1.0 - self.beliefs[h]) * 4.0
                for h in SEVERITY
            )
            if self._target_claim_open():
                spread += TARGET_CLAIM_TESTS.get(eid, 0.0) * 0.5
            score = (2.0 * severity + spread) / self.costs[eid]
            scored.append((score, -self.costs[eid], eid))

        best = max(scored)
        if best[0] < 0.08:     # nothing left that could change the picture
            return None
        if self._settled() and not self._target_claim_open():
            return None
        return best[2]

    def _target_claim_open(self) -> bool:
        return not self.ledger.target_dependence_tested

    def _settled(self) -> bool:
        """The leader has survived its own severest affordable test and every
        rival has either been knocked down or had a severe test run at it."""
        leader = self._dominant()
        if leader is None:
            return False
        if not self.ledger.severe_tests_passed.get(leader):
            return False
        for h in self.beliefs:
            if h == leader:
                continue
            if self.beliefs[h] >= CONTRIBUTING_THRESHOLD and not (
                self.ledger.severe_tests_passed.get(h) or self.ledger.severe_tests_failed.get(h)
            ):
                return False
        return True

    def _parameters(self, eid: str) -> dict:
        if eid == "E1":
            # Both halves of the question in one purchase is not available, so
            # buy the CoA-saturated arm: it is the one that can refute H2.
            # Stabiliser-free buffer so a shift cannot be bought by additives.
            return {"buffer": "hepes_without_stabilisers", "coa_mM": 1.0, "compound_uM": 50.0}
        if eid == "E3":
            return {"atc_free_days": 5, "read_day": 14, "normalisation_control": "untreated H37Rv growth control"}
        if eid == "E6":
            # All three arms are mandatory (EC1). The cell-free control must be
            # named or the control line is withheld — without it, intracellular
            # counts cannot be distinguished from carry-over.
            return {
                "arms": ["parent_diacid", "diethyl_ester", "monoacid"],
                "controls": ["cell-free medium control", "bacteria-free filter control", "t=0 input"],
            }
        return {}

    # --- concluding ------------------------------------------------------------
    def _conclude(self, dominant: Optional[str]) -> Action:
        contributing = [h for h, p in sorted(self.beliefs.items()) if p >= CONTRIBUTING_THRESHOLD]
        if dominant is not None and dominant not in contributing:
            contributing.append(dominant)
            contributing.sort()
        return Action(
            kind="conclude",
            beliefs=dict(self.beliefs),
            dominant_cause=dominant,
            contributing_hypotheses=contributing,
            confidence=self._confidence(dominant),
            evidence_cited=[
                {"experiment": eid, "supports": SUPPORTS[eid]}
                for eid in self.cited
                if eid in SUPPORTS and eid not in self.ledger.unreadable
            ],
            makes_target_claim=self._makes_target_claim(),
        )

    def _makes_target_claim(self) -> bool:
        """Only claim on/off-target for the analogues if an experiment that asks
        that question was bought AND produced a readout this agent could score.
        A test it could not read licenses nothing."""
        return self.ledger.target_dependence_tested and not any(
            eid in self.ledger.unreadable for eid in TARGET_CLAIM_TESTS
        )

    def _confidence(self, dominant: Optional[str]) -> Optional[float]:
        """Stated probability that `dominant` is the largest contributor.

        Reported directly from what was bought, not derived from the belief
        vector: a falsification agent's confidence is earned by severe tests the
        claim survived and by rivals that were knocked down, and it is docked
        for tests never run and readouts never parsed.
        """
        if dominant is None:
            return None
        c = 0.35
        c += 0.20 * min(2, len(self.ledger.severe_tests_passed.get(dominant, [])))
        for h in self.beliefs:
            if h != dominant and self.beliefs[h] <= REFUTED_THRESHOLD and (
                self.ledger.severe_tests_failed.get(h)
            ):
                c += 0.08
        untested_rivals = [
            h for h in self.beliefs
            if h != dominant
            and self.beliefs[h] >= 0.35
            and not (self.ledger.severe_tests_passed.get(h) or self.ledger.severe_tests_failed.get(h))
        ]
        c -= 0.10 * len(untested_rivals)
        c -= 0.08 * len(self.ledger.unreadable)
        return round(max(0.05, min(0.90, c)), 2)

    # --- for humans, not for the auditor --------------------------------------
    def justification(self) -> list[str]:
        """The written trail behind the belief moves. Deliberately not put on
        the Action: evidence_cited is structured-only by contract."""
        return list(self.rationale)
