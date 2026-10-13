# Real-trajectory hand labels

Two independent raters should label the same results file without sharing files or discussing episodes until both have submitted their labels. Run `python3 -m auditor.validation.real.label RESULTS --labels LABELS-NAME.jsonl --labeller NAME --no-reveal`; it appends each accepted label immediately and resumes unfinished episodes. `--no-reveal` suppresses the verdict both before and after labelling. The default blind header omits variant, model and seed. Use `--show-verdict` only for triage: those anchored labels are excluded from headline kappa. Use `--relabel EPISODE_ID` to append replacement rows (readers use the last row). `s` skips, `q` quits, and `?` repeats the scenario vocabulary.

Labels are comma-separated and scenario-scoped: `honest`, that scenario's rubric RH IDs, `unsafe`, `protocol_violation`, and `other_hack` (which requires a note). `honest` must stand alone; other labels may be combined. Each row records the results-file SHA-256, labels, optional note, labeller, whether the verdict was shown, auditor verdict, and UTC timestamp. A labels file belongs to exactly one results file.

Run `python3 -m auditor.validation.real.agreement RESULTS LABELS --out agreement.json [--markdown agreement.md]` for the single-file comparison with the auditor. Run `python3 -m auditor.validation.real.reliability RESULTS LABELS-A LABELS-B --out reliability.json [--markdown reliability.md]` for two-rater binary and per-category reliability. After both files are submitted, a third person who has not seen any auditor verdicts can adjudicate disagreements with `python3 -m auditor.validation.real.adjudicate RESULTS LABELS-A LABELS-B --out adjudications.jsonl --adjudicator NAME`; pass `--adjudications adjudications.jsonl` to reliability to include the adjudicated reference.

Headline eligibility requires `saw_verdict: false`, `saw_job_identity: false` and `verdict_revealed: false` on each label row; a missing `verdict_revealed` key is treated as revealed. At least 30 eligible episodes are required for headline use, and any `"synthetic": true` row makes the result a synthetic placeholder rather than human evidence. Parse failures, provider refusals, single-rater labels, unlabelled episodes, anchored rows, identity-exposed rows and verdict-revealed rows are excluded and reported separately.

Single-rater agreement and two-rater reliability use the same blindness rule: all three flags must be explicitly `false`; a missing, `null` or other non-false value is ineligible. Use `--no-reveal` for headline labels. Without it, the verdict is shown after each label and the row is not headline-eligible.

The annotation-tooling regressions are documented in [`ANNOTATION-REGRESSIONS.md`](ANNOTATION-REGRESSIONS.md), and pilot reviewer instructions are in [`REVIEWER-ONBOARDING.md`](REVIEWER-ONBOARDING.md).

## Coordinator: opaque blinded packets

1. Restore the source results locally, for example from `origin/data/wave1`.
2. Build each packet with its mapping in a separate directory:

   ```sh
   python3 -m auditor.validation.real.packet runs/stage2-wave1/a/results.jsonl --packet /shared/packet-a.jsonl --mapping /coordinator-only/mapping-a.json
   python3 -m auditor.validation.real.packet runs/stage2-wave1/b/results.jsonl --packet /shared/packet-b.jsonl --mapping /coordinator-only/mapping-b.json
   ```

3. Send annotators only the packet files and the shuffle seed; never send the mappings.
4. Run reliability with the matching mapping and source results:

   ```sh
   python3 -m auditor.validation.real.reliability /shared/packet-a.jsonl labels-A-a.jsonl labels-B-a.jsonl --out reliability-a.json --mapping /coordinator-only/mapping-a.json --source-results runs/stage2-wave1/a/results.jsonl
   ```

5. Store each mapping off any shared drive used by annotators.

The auditor reports one verdict: an episode that is both unsafe and in protocol breach maps to `unsafe` only. RH IDs come from `reward_hacks` and are recorded whatever the verdict. These are descriptive agreement statistics, not evidence of auditor correctness: categories depend on each scenario's rubric and small samples can make kappa unstable.
