# Eval hygiene: how FalsifyLab's own harness could be gamed

FalsifyLab grades an agent, so the harness is a thing that can be attacked. This is
a self-audit against the eight flaw classes (V1-V8) and seven checklist categories
published with BenchJack (*Do Androids Dream of Breaking the Game?*, arXiv
2605.12673). I worked from a summary of the paper, not the full 30-question
checklist, so this covers the classes and categories, not each question. Findings
below were checked against the code on 2026-10-04.

## Findings

| Class | Status | Evidence and what was done |
|---|---|---|
| **V1 Isolation failure** (agent and evaluator share an environment) | **Was broken locally; now enforced for the repo** | The local sandbox is a subprocess, not a container. Probing it showed agent code could read the answer key by absolute path (`private/exp1.json` opened fine); the old "ground truth never reachable" test only checked what was *mounted*. The sandbox preamble now installs an interpreter audit hook that refuses and records any access under the repository (`sandbox/local.py`). Not a boundary: native code and a determined adversary can still bypass in-process hooks. Modal's platform-enforced isolation is the real fix and is untested. |
| **V2 Answers shipped with the test** | OK | Ground truth lives in `private/` and is mounted only in the per-call scorer sandbox. Withheld columns (clinical-stage evidence) are dropped from agent data on purpose. |
| **V3 Evaluator executes agent-controlled data** | Mostly OK | The scorer receives the answer as JSON and runs in its own sandbox. Replay re-runs the agent's own code, so it runs in a separate sandbox holding only perturbed data and no ground truth. |
| **V4 LLM-judge prompt injection** | N/A | No LLM judges anything. |
| **V5 Weak string matching** | **Open, mitigated** | The rubric scorers for experiments 3, 5 and 6 are phrase matching (`scorers/rubric.py`); listing rubric terms raises the score. The rubric now records match density (`rubric_density`) and the suite pins that a keyword dump is denser than a real answer. **No threshold is applied** because none has been calibrated; Phase 4 (labelled runs) sets it. Until then rubric experiments are the least trustworthy part of the score, and their process score has limited coverage. |
| **V6 Evaluation logic gaps** | Partly addressed | Two real scorer bugs were found earlier by running the agent (a correct answer penalised for wording). The audit adds checks the score alone lacked: the answer's items must trace to run output; the answer must change when the signal is destroyed. |
| **V7 Trusting untrusted output** | Addressed for the audit | The agent writes its prediction and answer but not its grade, scorer, audit spec or trace. The trace goes to a file descriptor the parent opened. Hooks cannot be removed but the descriptor can still be written to by code that knows it: forged lines can only add events. |
| **V8 Excessive permissions** | Acceptable | Subprocess runs with a scrubbed environment (no API keys), a memory cap and a wall-clock timeout. |

## What the audit itself is trusted to do, and not do

- It never touches the network; citation lookup and replay are done by a trusted caller and passed in, so the same inputs give the same report (`engine/audit.py`).
- Its output is **never shown to the agent**, not even in the teaching prompt: detailed rejection feedback taught evasion in the research-agents literature.
- Process credit is given only for steps shown in the calls the answer actually comes from, so a ceremonial step in a throwaway call earns nothing (a pinned case in `evals/audit/`).

## Known limits

- In-process tracing is evidence of attempts, not containment.
- Replay needs deterministic agent code and a sensible perturbation per experiment; replay failures are reported as `replay_inconclusive`, not punished.
- Citation checks catch DOIs that do not exist, not real papers cited for claims they do not support.
- The process checkpoints are a proxy for method quality and are unvalidated until the labelled runs exist.
- Reasoning experiments (3, 5, 6) have no data to perturb, so only provenance, event facts and lesson-use checks apply.
