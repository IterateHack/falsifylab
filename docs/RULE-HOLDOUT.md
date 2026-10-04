# Held-out auditor rules: a design note

**Status: a design for a future feature. Nothing here is implemented.** No code in this repository reads a visible/held-out
split, and no metric described below is computed today.

The idea is to split the auditor's own rules into a visible set and a held-out set, so that Goodharting (optimising an
agent against the rules it can see) shows up as a gap between the two. This note is about the auditor's rules, not about
scenarios.

## 1. What exists today

- **The agent sees no auditor rules at all.** `rubric.json` and `constraints.json` stay on the auditor side. `Env` does not
  load the rubric, and the worker bundle excludes both files. The visible reward `R_visible` is computed inside
  [`audit()`](../auditor/audit.py) from the rubric's `visible_reward` block. It is auditor-side too and is never sent to the
  agent. The only rule-like text an agent receives is the prose in [`agents/prompts/`](../agents/prompts/).
- **No prompt or memory optimisation loop exists.** The prompt variants are hand-written, and the scripted controls do not
  learn.

So **the visible set does not exist yet.** This note defines it.

## 2. Design

For each scenario, partition the named rules of its rubric into two sets:

- **V, the visible set:** available during any prompt or memory optimisation. An optimiser may read these rules and may
  score candidates with an auditor that runs only V.
- **H, the held-out set:** active only at final scoring. It is never shown to an optimiser and never used to select a
  candidate.

Final scoring runs the auditor with V ∪ H, which is the auditor as it is today.

**The Goodhart metric** is visible-minus-held-out clean success, measured on the same episodes:

```text
gap = CS(V) − CS(V ∪ H)
```

`CS(R)` is clean success with only the rules in R active: the fraction of scored episodes whose verdict is `VALID_SUCCESS`
(the existing definition; see the README's "Clean success vs raw score"). Provider refusals and spend-cap stops stay out of
both terms, as they do for every science metric.

- **A gap near zero** means the held-out rules catch little that the visible ones miss.
- **A gap that grows over optimisation** means the optimiser is satisfying V while failing H.

### Which rules can be partitioned

These are the named rules in the two current rubrics (`auditor/` for scenario A, `scenarios/b_cd5_affinity/auditor/` for
scenario B):

| Rule class | Scenario A | Scenario B | Effect when it fires |
|---|---|---|---|
| Protocol | PR1–PR4 | PB1–PB4 | `PROTOCOL_VIOLATION` |
| Safety | SC1 | SB1 | `UNSAFE_ACTION` |
| Reward hack | RH1–RH3 | RH1–RH3 | `REWARD_HACK` |
| Fabricated citation | coded in `audit.py`, not in the rubric | same | `REWARD_HACK` |
| Evidence sufficiency | EV1–EV3 | EVB1–EVB3 | points toward the 80% threshold |

Two facts about the code constrain the split:

- **Penalty rules are monotone.** Protocol, safety, reward-hack and fabricated-citation rules can only turn a pass into a
  fail, so if H holds only penalty rules, `CS(V ∪ H) ≤ CS(V)` and the gap is never negative.
- **Evidence criteria are not.** Removing an evidence criterion also changes the applicable maximum it is scored against, so
  holding one out can move `CS` in either direction. Conclusion correctness (the contributing set and dominant cause) is
  checked against `truth.json` and is not a rule; it stays active in both terms.

Each scenario has eight named penalty rules plus fabricated citation. The pool to split is that small.

## 3. Prior art

I checked each arXiv ID on arxiv.org. All nine resolve, and the titles are the arXiv titles. Quotations are each paper's own
wording.

**EvilGenie** — [arXiv:2511.21654](https://arxiv.org/abs/2511.21654), *EvilGenie: A Reward Hacking Benchmark*. It holds out
test cases from a coding agent:

> "we remove a random 30% (up to 10) of the original test cases to form a holdout set. The agents are not informed about this holdout set."

A pass on the visible tests with a failure on the holdout counts as a candidate hack:

> "Intuitively, a reward hacking solution should pass the visible tests but fail the holdout tests."

**Caveat: the holdout underperformed the LLM judge, with errors in both directions.**

> "We find the LLM judge to be highly effective at detecting reward hacking in unambiguous cases, and observe only minimal improvement from the use of held out test cases."

> "As expected, we see some false positives, where a model makes a legitimate attempt at a solution that fails to generalize to the holdout cases."

> "We also see some false negatives: passing the holdout tests does not necessarily indicate that the agent has genuinely solved the problem."

**PRIME** — [arXiv:2606.09711](https://arxiv.org/abs/2606.09711), *Proxy Reward Internalization and Mechanistic
Exploitation: A Learned Precursor to Reward Hacking and Its Generalization*. It trains on an incomplete harness and scores
against the complete one:

> "The proxy reward uses an incomplete pytest harness with three exploit surfaces (__eq__, sys.exit, conftest.py)"

> "The gold evaluator uses the complete pytest harness and gives the ground-truth score"

Its leave-one-out branches block two surfaces at a time:

> "When two of the three exploit families are blocked, hacking concentrates on whichever family remains rewarded."

**Fuzzing RLVR Verifiers** — [arXiv:2606.01066](https://arxiv.org/abs/2606.01066), *Before the Model Learns the Bug:
Fuzzing RLVR Verifiers*. In its optimisation proxies, the strict verifier is measured but never rewarded:

> "Strict verifier output is logged as held-out proxy correctness but is not used as training reward."

**IFBench** — [arXiv:2507.02833](https://arxiv.org/abs/2507.02833), *Generalizing Verifiable Instruction Following*. It
splits constraints, each with its own verification function, into train and test:

> "We define a taxonomy of constraint templates, which we split into training and test constraints to prevent contamination."

It also holds out whole categories:

> "we experiment with training on a leave-one-out set of categories, iteratively removing one of the following classes: CHANGE CASES, DETECTABLE FORMAT, LENGTH CONSTRAINTS, KEYWORDS."

**Inference-time scaling for audio super-resolution** — [arXiv:2508.02391](https://arxiv.org/abs/2508.02391),
*Inference-time Scaling for Diffusion-based Audio Super-resolution*. It searches with verifiers that have no ground truth and
keeps the ground-truth verifier for evaluation:

> "we primarily use supervised verifiers to guide the search, while reserving the oracle verifier for evaluation purposes."

The ensemble is built from the supervised verifiers only, so the oracle is held outside it rather than being a member:

> "This approach combines the feedback of all relevant supervised verifiers for a given audio category."

**LLMs Gaming Verifiers** — [arXiv:2604.15149](https://arxiv.org/abs/2604.15149), *LLMs Gaming Verifiers: RLVR can Lead to
Reward Hacking*. Its "hacking gap" has the shape of the metric above, the difference between a weaker and a stricter check
of the same output:

> "a divergence between extensional and isomorphic reward that emerges mid-training and continues to widen"

**Reward Hacking in Rubric-Based RL** — [arXiv:2605.12474](https://arxiv.org/abs/2605.12474), *Reward Hacking in
Rubric-Based Reinforcement Learning*. This is the near miss: it holds out the judge, not the criteria.

> "a policy is optimized against a training verifier but evaluated against a cross-family panel of three frontier judges"

> "Even if a verifier correctly applies the rubric, the rubric itself may be an incomplete reward specification."

**HackProbe** — [arXiv:2609.04665](https://arxiv.org/abs/2609.04665), *Harness-agnostic detection and immunization of reward
hacking in self-evolving language models*. A static held-out probe set gets fitted; rotation slows that. This was measured
on "a controlled prompt-level host with four injected hacking channels and ground-truth labels".

> "A fixed layer is progressively fitted and detection decays toward chance, whereas rotation holds both to a small fraction of that."

> "which is the failure mode a single held-out probe set has and the reason the fresh layer is rotated at all."

**ProtoTransformer** — [arXiv:2107.14035](https://arxiv.org/abs/2107.14035), *ProtoTransformer: A Meta-Learning Approach to
Providing Student Feedback* (2021). It partitions rubric items to test whether a learned grader generalises:

> "we reserve 10% of rubric items, uniformly sampled, for meta-test tasks."

> "we will always ensure rubric options from the same item are in the same split, preventing information leakage."

## 4. What is and isn't new

The technique is not new. Withholding part of the checker and reading the gap between visible and held-out results is
already used for unit tests, verifiers, constraint families and rubric items. The open contribution is applying it to a
finite, named, multi-class rubric, where each held-out item is a named rule with its own verdict class, and reporting the
gap as the headline metric.

## 5. Design constraints

1. **Rules must rotate.** A fixed H becomes visible in effect once an optimiser has been scored against it enough times;
   HackProbe measured this decay. With eight named penalty rules plus fabricated citation per scenario, rotation exhausts
   the pool quickly. HackProbe's own limit applies here even more strongly: rotation "stops memorization but leaves the
   covering number of the probe generator as the real ceiling", and a fixed rubric has no generator.
2. **The gap is a diagnostic, not a detector.** It is a difference of two rates over a set of episodes. It does not label
   any episode as a hack. EvilGenie's per-episode holdout produced false positives and false negatives and was outperformed
   by an LLM judge.
3. **Rule-split size is untuned and unstudied.** The sizes in the prior art (30% of test cases, capped at 10, in EvilGenie;
   10% of rubric items in ProtoTransformer) were those papers' choices. FalsifyLab has no data on what size of H to use.

## 6. Open questions

- What "visible" exposes: the rule text, the rule ID and verdict class, or only the verdict an episode received.
- Whether the split is per scenario or shared across scenarios. RH1–RH3 are named identically in both rubrics, but they
  test different experiments.
- Whether fabricated citation, which is coded in `audit.py` rather than in a rubric, may be held out.
