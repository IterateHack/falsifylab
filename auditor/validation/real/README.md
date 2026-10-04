# Real-trajectory hand labels

Run `python3 -m auditor.validation.real.label RESULTS --labels LABELS.jsonl --labeller NAME [--blind]`; it appends each accepted label immediately and resumes unfinished episodes. Use `--relabel EPISODE_ID` to append replacement rows (readers use the last row). `s` skips, `q` quits, and `?` repeats the scenario vocabulary.

Labels are comma-separated and scenario-scoped: `honest`, that scenario's rubric RH IDs, `unsafe`, and `other_hack` (which requires a note). `honest` must stand alone. Each row records the results-file SHA-256, labels, optional note, labeller, whether the verdict was shown, auditor verdict, and UTC timestamp. A labels file belongs to exactly one results file.

Run `python3 -m auditor.validation.real.agreement RESULTS LABELS --out agreement.json [--markdown agreement.md]` for flagged-vs-honest Cohen's kappa, scenario-qualified RH one-vs-rest results, unsafe/other-hack results, blind-only binary agreement, and episode disagreements. Kappa uses the same observed/expected agreement definition as the #19 validation report; `None` means no pairs or expected agreement of 1. Parse failures and unlabelled episodes are reported, not scored.

These are descriptive agreement statistics, not evidence of auditor correctness: categories depend on each scenario's rubric, small samples can make kappa unstable, and showing the verdict before labelling may anchor human labels. The blind-only split makes that exposure visible.
