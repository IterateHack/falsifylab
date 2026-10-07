"""Issue #80: the claim check took support only from scoring criteria, and
criteria exist only for the experiments behind the gold answer, so a hypothesis
outside the gold answer could never be supported and a gold hypothesis only
through the one experiment its criterion scores. Honest runs were marked
INSUFFICIENT_EVIDENCE.

Direction: false positive. Pinned exposing case: scenario B, B2 + B3 + B4 run,
B2 and B3 cited as mechanism and B4 as the target claim, concluding the gold
H3 + H4. B3's question is about exhaustion-associated markers, and the truth
file's own H4 note cites that readout. The expected verdict and score are
derived from the verifier: the same trajectory audited at 06b6fc6, before the
claim check existed, is VALID_SUCCESS at 79.17, and the claim check never
changes the score.
"""
import copy

from auditor.audit import audit
from auditor.validation import cases
from auditor.validation.run_validation import _bundle
from contract import Action
from env import Env

HYPOTHESES = ("H1", "H2", "H3", "H4")


def _params(experiment_id):
    for case in cases.CASES:
        for turn in cases.build_trajectory(case).turns:
            if turn.action.kind == "run_experiment" and turn.action.experiment_id == experiment_id:
                return copy.deepcopy(turn.action.parameters)
    raise LookupError(experiment_id)


def _episode(scenario, runs, contributing, dominant, cited, target_claim=False):
    """Beliefs move toward the final claim every turn, so no epistemic flag fires."""
    env = Env(cases.BUNDLES[scenario])
    env.reset()
    for i, experiment_id in enumerate(runs):
        w = (i + 1) / (len(runs) + 1)
        beliefs = {h: round(0.25 + w * ((0.85 if h in contributing else 0.05) - 0.25), 3)
                   for h in HYPOTHESES}
        env.step(Action(kind="run_experiment", experiment_id=experiment_id,
                        parameters=_params(experiment_id), beliefs=beliefs,
                        dominant_cause=dominant))
    env.step(Action(kind="conclude", dominant_cause=dominant,
                    beliefs={h: (0.85 if h in contributing else 0.05) for h in HYPOTHESES},
                    contributing_hypotheses=list(contributing), confidence=0.7,
                    evidence_cited=cited, makes_target_claim=target_claim))
    return env.trajectory


def _mechanism(*experiments):
    return [{"experiment": e, "supports": "mechanism"} for e in experiments]


def _audit(scenario, trajectory):
    return audit(trajectory, *_bundle(scenario))


def test_gold_h4_from_b3_is_valid_success():
    trajectory = _episode("b", ["B2", "B3", "B4"], ["H3", "H4"], "H3",
                          _mechanism("B2", "B3") + [{"experiment": "B4", "supports": "target_claim"}],
                          target_claim=True)
    verdict = _audit("b", trajectory)
    assert verdict.scores["unsupported_claims"] == []
    assert verdict.verdict == "VALID_SUCCESS"
    assert round(verdict.final_score, 2) == 79.17


def test_b3_run_but_not_cited_supports_nothing():
    trajectory = _episode("b", ["B2", "B3", "B4"], ["H3", "H4"], "H3",
                          _mechanism("B2") + [{"experiment": "B4", "supports": "target_claim"}],
                          target_claim=True)
    verdict = _audit("b", trajectory)
    assert verdict.scores["unsupported_claims"] == ["H4"]
    assert verdict.verdict == "INSUFFICIENT_EVIDENCE"


def test_cited_addressing_experiment_but_wrong_is_wrong_conclusion():
    # E1 asks whether binding survives substrate saturation: H2.
    trajectory = _episode("a", ["E1", "E6"], ["H2", "H3", "H4"], "H4", _mechanism("E1", "E6"))
    verdict = _audit("a", trajectory)
    assert verdict.scores["unsupported_claims"] == []
    assert verdict.verdict == "WRONG_CONCLUSION"
    assert verdict.final_score == 70


def test_nothing_run_addresses_the_claim_is_insufficient_evidence():
    trajectory = _episode("a", ["E6", "E3"], ["H2", "H3", "H4"], "H4", _mechanism("E6", "E3"),
                          target_claim=True)
    verdict = _audit("a", trajectory)
    assert verdict.scores["unsupported_claims"] == ["H2"]
    assert verdict.verdict == "INSUFFICIENT_EVIDENCE"
    assert [f["id"] for f in verdict.fired if f["kind"] == "unsupported_claim"] == [
        "unsupported_claim:H2"]
