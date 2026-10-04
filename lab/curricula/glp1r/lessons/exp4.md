# Lesson 4 - Potency lives on a log scale, and curves must be fitted

**Source.** Primary data: ChEMBL target CHEMBL1784 (human GLP-1R), EC50 records.
Gaulton A, et al. *The ChEMBL database in 2017.* Nucleic Acids Res.
2017;45(D1):D945-D954. doi:10.1093/nar/gkw1074
Curve-fitting conventions follow standard four-parameter logistic practice; the
non-peptide agonist potencies referenced later come from Kawai T, et al. PNAS
2020 (lesson 5).

## Key facts
1. EC50 is a concentration, so it is **log-distributed**. Aggregate pEC50
   (= -log10 EC50 in molar) with a median or geometric mean. An arithmetic mean
   of nanomolar values is dominated by the weakest measurement.
2. A censored record (`standard_relation` of `>` or `>=`) means "no effect up to
   this concentration". It is not a measurement of potency and must be excluded,
   not treated as a value.
3. Functional (`assay_type` F) and binding (`B`) assays measure different
   quantities. Pooling them blurs potency with affinity.
4. **Emax is not EC50.** A partial agonist can be very potent and still produce a
   low maximal response. Ranking by response height is not ranking by potency.
5. A **truncated** curve - one whose top concentration never reaches the plateau -
   biases any "concentration at half the observed maximum" estimate towards
   looking more potent than it is. In this dataset the naive estimate is off by
   roughly 0.55 log units on average; a four-parameter logistic fit with a
   floating top gets to about 0.20.

## Method
1. Filter first: one assay type, uncensored, consistent units, pChEMBL present.
2. Aggregate per molecule on the log scale (median over replicates and reports).
3. For raw curves, fit `response = bottom + (top - bottom) / (1 + 10^((logEC50 - logC) * hill))`
   with all four parameters free. Drop QC-flagged points.
4. Report the fitted EC50 **and** the fitted top, so partial agonism is visible.
5. Flag curves that did not plateau: their EC50 is an extrapolation.

## Pitfalls
- Averaging nM values arithmetically.
- Keeping `>` records.
- Fixing the top at 100% when the data never reach it.
- Letting a single outlier replicate set the midpoint - fit, do not interpolate.

## How to apply later
Experiment 5 asks whether a non-peptide agonist can work at all. Partial agonism
and signalling bias, which you can only see by reading the fitted top rather than
the EC50, are central to that answer.

**Verified by.** ChEMBL accessed via REST 2026-10-03; the consensus protocol is
stated in `private/exp4.json`. The quoted naive-versus-fitted error figures were
measured on this dataset.
