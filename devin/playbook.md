# Devin playbook: building one experiment for FalsifyLab

You are adding one experiment to a curriculum in this repository. A curriculum is
a config folder, not code - you should not need to touch `engine/` or `sandbox/`.

## What one experiment consists of

| File | Purpose |
|---|---|
| `curricula/<id>/experiments/NN_<name>.yaml` | The spec: task text, answer format, limits, scorer and teaching pointers |
| `curricula/<id>/scorers/expN.py` | `score(answer, ground_truth) -> dict` |
| `curricula/<id>/private/expN.json` | Ground truth. **Never** mounted in the agent sandbox |
| `curricula/<id>/lessons/expN.md` | The lesson card, max ~400 words |
| `curricula/<id>/fetch.py` | A `build_expN()` that writes the dataset and the ground truth from primary sources |
| `curricula/<id>/tests/test_scorers.py` | Golden pass and fail fixtures for the new scorer |

Read `curricula/glp1r/experiments/02_structure_contacts.yaml` and
`curricula/glp1r/scorers/exp2.py` first. Experiment 2 is the reference
implementation: a deterministic scorer over ground truth recomputed from a
primary source.

## Acceptance criteria

A pull request is not ready until all of these hold.

1. **`python -m engine.cli validate --curriculum curricula/<id>` passes.**
2. **The scorer is deterministic.** Same answer, same score, every time. No
   clocks, no RNG without a fixed seed, no network, no LLM calls. There is a test
   for this; do not delete it.
3. **Golden fixtures exist and pass**: a perfect answer scores 1.0, a
   deliberately wrong answer scores low, and malformed input (`{}`, `None`, a
   string where a list belongs) scores 0.0 **without raising**. The engine
   contains a scorer error, but a scorer that throws tells the agent nothing.
4. **The trap bites.** Write a test showing that the naive approach your lesson
   card warns against actually scores materially worse than the correct one. A
   pitfall nobody is penalised for teaches nothing.
5. **No network at scoring time.** Everything the scorer needs is in
   `private/expN.json`. `fetch.py` is the only place that touches the internet.
6. **The ground truth is not reachable from the agent's sandbox.** It must not be
   listed in the spec's `inputs.datasets`.
7. **No answer leakage into the agent's data.** Check every column you expose. If
   a feature encodes the outcome - a clinical-stage flag when the question is
   "will this become a drug", a tractability label that restates approval - drop
   it and say so in a comment. This is the single most common way to build an
   experiment that measures nothing.
8. **Runtime under 90 seconds** for the scorer, and the experiment's
   `limits.max_tool_calls` is justified in the PR description. Budget for an
   agent that explores: the last two calls are reserved for submission, so the
   working budget is `max_tool_calls - 2`.
9. **The lesson card** is at most ~400 words and carries a full citation with a
   DOI, key facts, a method, pitfalls, how it applies later, and a "Verified by"
   line. Paraphrase; never paste excerpts. Prefer open-access sources.
10. **Every reference is verified**, not recalled. Check the title, authors,
    journal, year and DOI against Europe PMC or the publisher before writing the
    card, and record the check in `docs/references.md`. Two of six references in
    the original project plan were wrong in ways that looked plausible.
11. **`requires_lessons` points only at earlier experiments**, and the task is
    genuinely harder without them. Say in the PR description what the dependency
    is for.
12. **Provenance recorded.** Each `note(...)` call in `fetch.py` must classify the
    data as `fetched`, `computed`, `derived` or `transcribed`.

## Running it

```bash
python -m curricula.<id>.fetch --only expN   # build the dataset + ground truth
python -m engine.cli validate --curriculum curricula/<id>
python -m pytest curricula/<id>/tests -q
python -m engine.cli run --run-id dev_expN --only <experiment_id> --force
```

## PR description must list

- The primary sources, with DOIs and the date you verified them.
- The scoring rule in one sentence, and why it is the right one.
- **Assumptions you made**, especially anything transcribed rather than fetched.
- The trap, and the measured gap between the naive and correct approaches.
- Anything you deliberately withheld from the agent's data, and why.
