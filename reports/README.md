# Slide assets

From the repository root, run:

```sh
python -m reports.slide_assets --batch runs/example --validation auditor/validation/REPORT.md --output slides
python -m reports.slide_assets --synthetic --output slides-demo
```

Repeat `--batch` to combine several batch directories. Each batch gets clean-success Wilson intervals, a raw-score-versus-clean-success figure, a cost-of-pass figure, an experiment-selection comparison, and a top-three frontier-regret table. Experiment selection compares per-episode cost and decisive-experiment purchases, both with and without the evidence-sufficiency parameter rules. The validation report produces a pattern table with its Cohen's kappa rows. PNGs are 16:9 at 200 dpi; CSVs include a stamp column, and each Markdown table ends with the stamp.

The clean-success table adds `mean_cost`, `cost_of_pass`, `n_valid_success`, and per-cell `pass^1`, `pass^3`, and `pass^5`. Its pass^k caption is: "pass^k = C(c,k)/C(n,k) per cell: n counted runs (seeds), c with verdict VALID_SUCCESS; probability that k runs drawn without replacement all succeed (tau-bench, arXiv:2406.12045). Because pass^k counts VALID_SUCCESS runs, it can differ from clean_success_rate where a run aborted on refusals."

`cost_of_pass.png` plots clean-success rate against cost_of_pass and marks Wilson intervals; zero-success cells are omitted because cost_of_pass is undefined. Its caption is: "cost_of_pass = mean_cost / clean_success_rate (Cost-of-Pass, arXiv:2504.13359). Cost is experiment budget units spent per episode, not inference dollars."

The stamp records the report Git SHA and dirty state, models, sampling settings, source, re-audit metadata, and whether the input is synthetic. It is computed once before output is written, so an output directory inside the repository does not make its own stamp dirty. Synthetic batch assets are watermarked and stamped `SYNTHETIC DATA`; auditor validation always uses the real report and is not marked synthetic. A Git SHA with `-dirty` means the report was generated from a modified working tree.

Markdown and PNG rates and regret use three decimals, with confidence intervals shown as `[low, high]`; CSV values retain full precision.

Experiment-selection captions explain: "bought = ran the experiment; w/ params = the evidence-sufficiency rules for that experiment also pass, evaluated with the auditor's predicate evaluator (auditor.audit.eval_pred)". The Markdown table lists the criterion IDs for each experiment's parameter rules. In the chart, "bought" bars are pale (30% fill, coloured outline) and "w/ params" bars are solid, so the pair stays distinguishable at small values.

The `reports/` pipeline reads rubrics and imports the auditor's private `_Ctx` and `eval_pred` on the evaluation side only; nothing under `runner/` or `agents/` imports `reports/`.
