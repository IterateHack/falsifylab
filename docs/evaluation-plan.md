# FalsifyLab: evaluation plan for "the agent improves"

> **Handoff note (read first).**
> - Paths below are relative to the lab tree root (`engine/`, `curricula/`, `evals/`, `docs/`). On `origin/main` this tree lives under `lab/`, so prefix every path with `lab/` (for example `lab/engine/agent.py`). The root instrument (`agent/`, `auditor/`, `runner/`, `CONTRACT.md`) is a separate instrument with its own protocol. Do not share code with it or merge the two claims.
> - `origin/main` has no `lab/` yet. The lab arrives as a subtree merge of `keshav-changes` at `cfaabf6` on branch `origin/merge/keshav-lab`. That snapshot still contains the WRN curriculum (`lab/curricula/wrn/`). This plan assumes WRN is deleted and that `pytest` testpaths no longer reference it. The deletion exists only as uncommitted changes in the author's working tree, so repeat it on the lab tree before starting.
> - Line numbers refer to `cfaabf6` and may have shifted. Locate by function name if they have.
> - Verified at `cfaabf6`: the engine passes every earned lesson card to later experiments (`engine/agent.py`, `available = earned_lessons`), so any comparison run before the relevant-lessons fix is not comparable to later results.
> - Not verified: any cold-baseline score cited elsewhere, and the issue numbers mentioned in review feedback (#38 sandbox thread fix, #44 scorer alias bug). If #38 touches the lab sandbox, merge it first.

This plan is hypothesis-agnostic. The engine and the protocol work for whichever single hypothesis the active curriculum (`curricula/<id>/`) defines. Facts about the current GLP-1R curriculum are confined to the appendix, so the plan can merge into a branch with a different hypothesis.

## Context
A supervisor asked: (1) how do we know the agent improves, from what baseline, by how much? (2) how do we know it isn't overfit to its training data?

State of the engine:
- The only thing that changes between runs is **human-written lesson cards** (`curricula/<id>/lessons/expN.md`), appended in `engine/runner.py:100-104` and read via `read_lessons` (`engine/tools.py:367`). Carry-forward lasts one run (`runner.py:77`). The agent's own `lesson_learned` notes are never fed forward.
- One comparison mechanism exists: lessons vs `--no-lessons` (`engine/compare.py`). It takes two runs, has no CI, and uses hand-picked 0.05/0.1 bands.
- **Relevance is not enforced.** `engine/agent.py:166` passes every earned card (`available = earned_lessons`); `requires_lessons` is only logged. Any comparison made before the fix below used all cards, and **is not comparable to results produced after it**.
- **No held-out data.** Every run sees the same experiments, data and answers, and cards and rubrics derive from the same sources that define the ground truth.
- Rubric scorers are phrase-match, so they can reward vocabulary.

## Claim (narrow, defensible)
"Given a curriculum of worked lessons, the agent scores and calibrates better on **held-out experiments of the same hypothesis** than the same agent without it, and than the same agent with content-free filler." This is learning-from-curriculum with transfer to unseen problems inside one hypothesis, not weight training. Transfer across hypotheses is out of scope: one hypothesis at a time. Agent-written lessons are a possible later arm.

## Arms (same model, settings and tools unless stated)
| Arm | What the agent gets | Purpose |
|---|---|---|
| A-cold | Hypothesis and experiment titles only. No data, no tools, no lessons. | The true floor: prior knowledge alone. |
| A0 | The lab (data, tools), no lessons | What the apparatus adds over prior knowledge. May be negative. |
| A1 | The lab plus length-matched, topic-irrelevant prose in the lesson slot | Controls for "more context". |
| A1b | The lab plus a lesson block of semantically null tokens, same length and formatting | Closes the "format effect, not content" loophole. |
| A2 | The lab plus human lessons, shown per the relevance rule | The treatment. |
| A3 (optional) | The lab plus agent-written lessons | Genuine self-improvement. |

Report each arm's score against A-cold, not only against A0. A cold score measured elsewhere must be reproduced in this repo before it is cited.

## Splits (within the one hypothesis)
Experiments are split by **instance**: new datasets, structures, entities or assays that test the same skill as a dev experiment but whose answers cannot be recalled from the dev material.
- **Dev:** the current experiments. Lessons and rubrics may be iterated here.
- **Validation:** a few extra instances, used to calibrate rubric thresholds and fix scorer bugs. May be touched.
- **Test:** the held-out instances. **Frozen**: lessons, rubrics, scorers and the analysis plan are committed and tagged before any test run, then run once.
- Add `split: dev|val|test` and `author:` to each experiment spec. Test instances are not shown to whoever writes the lesson cards.
- **Independent authorship:** the person who writes the test instances and their scorers is not the person who wrote the lesson cards.
- Prefer test instances built from real deposited data with no published answer, which gives nothing for a model to recall. Each needs a deterministic ground truth derivable from its data. Check this per candidate.
- Lessons state transferable principles, not answers. **Leakage ablation:** give lessons written for one experiment to a different one. A persisting gain is general skill. A vanishing gain is memorisation.

## Relevant-lessons rule (no tagging)
Relevance = the existing `requires_lessons` field in each experiment YAML.
- Filter `earned_lessons` to `spec.requires_lessons` before building `ToolContext` (`engine/agent.py:166`).
- Put the required cards **directly in the first prompt**. Keep `read_lessons` as a fallback.
- Make `lesson_hint` truthful: only say the experiment needs lessons when it lists some.
- Log which cards were shown, so results can be checked against what the agent saw.
- `engine/cli.py validate` fails if a curriculum references a lesson that doesn't exist.
- An experiment with no required lessons gets none in every arm, so its run-to-run difference is a direct noise estimate.

## Replication, metrics and stats
- >=10 runs per arm, with temperature and seed recorded in `engine/provider.py`.
- **Pre-registered primary endpoint:** test-split mean score, A2 minus A0, paired by experiment. Also report A2 minus A-cold, A2 minus A1 and A2 minus A1b.
- Effect size, paired bootstrap 95% CI, permutation p-value. Secondary: calibration gap, per-experiment deltas, reliability (share of runs above a threshold), tool calls and tokens.
- **Hard subset** = experiments where A-cold is low (not where A0 is low). Report it separately. Drop or harden experiments where A-cold is already near ceiling.
- Noise floor: A0 against A0.
- Audit verdicts (`engine/audit.py`) are mandatory per run. Exclude or flag `REWARD_HACK` runs.

## Budget
Do not estimate it. Run one full curriculum at current settings, record the cost, then multiply by arms x test instances x seeds. Start with a pilot at fewer seeds and use its noise to size the full run.

## Code and curriculum changes
- `engine/agent.py`, `engine/tools.py`: relevant-lessons rule.
- `engine/specs.py`: `split` and `author` fields on experiments.
- `engine/compare.py`: multi-run aggregator with CIs, permutation test and effect sizes. Replace the hand-picked bands.
- `engine/cli.py`, `engine/runner.py`: `--arm {cold,baseline,placebo,null,lessons}`, `--seed`, `--split`. Cold-arm prompt builder. Record arm, seed and split in `notebook.json`.
- `curricula/*/scorers/rubric.py`: calibrate thresholds on validation runs. Add a keyword-dump guard (`rubric_density`, `docs/eval-hygiene.md` V5). Every scorer that matches names or labels gets alias-spelling regression tests, so a correct answer written differently from the answer key still scores.

## Order of work
1. Reproduce the cold baseline and record the cost per run.
2. Land the relevant-lessons fix, with tests.
3. Aggregator, CLI arms and seeds, with a unit test on synthetic runs.
4. Run the dev split at n>=10 for A-cold/A0/A1/A1b/A2. Report the first real effect size.
5. Build validation and test instances under independent authorship. Calibrate on validation. Freeze. Run test once.
6. Report improvement with CIs on held-out experiments, the leakage ablation, and the audit results.

## Verification
- Aggregator: synthetic known deltas recover the right effect and CI. A0-vs-A0 gives a null result.
- Relevance: a test that an experiment sees only the cards it requires.
- Scorers: alias spellings of the gold answer score as the gold answer.
- Existing suite passes (`pytest`, including `evals/audit/`).
- Test instances run exactly once, and the freeze tag predates the first test run.

## Open items
- Who authors the validation and test instances.
- How many test instances the active hypothesis can support, and whether each has a derivable ground truth.
- Keep this evaluation protocol separate from any other instrument's protocol in the README, so the two aren't merged into one claim.

## Appendix: GLP-1R curriculum (current branch only)
- Six experiments. The first lessons-vs-no-lessons pair is n=1 per arm and predates the relevance fix: +0.109 on lesson-dependent experiments, +0.071 on independent ones, so inconclusive.
- Exp1 gets no lessons in either arm, and its +0.14 gap is run-to-run noise.
- Exps 2 and 3 sit at ceiling in both arms. The capstone (exp6) scored 0.79 in the no-lessons run, which may be below the cold score.
- Exp5's lesson card teaches the same fact its rubric rewards, so that gain is partly teaching to the test.
