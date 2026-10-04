# Slide assets

From the repository root, run:

```sh
python -m reports.slide_assets --batch runs/example --validation auditor/validation/REPORT.md --output slides
python -m reports.slide_assets --synthetic --output slides-demo
```

Repeat `--batch` to combine several batch directories. Each batch gets clean-success Wilson intervals, a raw-score-versus-clean-success figure, and a top-three frontier-regret table. The validation report produces a pattern table with its Cohen's kappa rows. PNGs are 16:9 at 200 dpi; CSVs include a stamp column, and each Markdown table ends with the stamp.

The stamp records the report Git SHA and dirty state, models, sampling settings, source, re-audit metadata, and whether the input is synthetic. Synthetic assets are watermarked and stamped `SYNTHETIC DATA`. A Git SHA with `-dirty` means the report was generated from a modified working tree.
