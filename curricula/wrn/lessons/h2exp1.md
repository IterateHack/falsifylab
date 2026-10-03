# Lesson 1 - A drug target is a selective dependency, not an essential gene

**Source.** Tsherniak A, Vazquez F, Montgomery PG, et al. *Defining a Cancer
Dependency Map.* Cell. 2017;170(3):564-576.e16.
doi:10.1016/j.cell.2017.06.010

## Key facts
1. Genome-scale CRISPR screens across cell line panels produce a **gene effect**
   per gene per line. Around 0 means no effect; around -1 means the knockout was
   lethal. The scale is normalised so that common essentials sit near -1.
2. Most genes fall into three groups. **Common essentials** (ribosome,
   spliceosome, replication - here RAN, PCNA, RPL5, EIF4A3, SF3B1) are required
   almost everywhere. **Non-essentials** sit near zero everywhere.
   **Selective dependencies** are required by a subset.
3. Only the third group is a drug target. A common essential would be toxic in
   normal tissue; a non-essential does nothing when inhibited.
4. **The mean hides the shape.** A selective dependency can have a median close
   to zero and still kill a fifth of the panel. WRN's median gene effect is about
   -0.12 - it looks inert on average - while its worst lines reach below -4.
5. A scatter of weakly negative lines is not a dependency. In this panel INS has
   12% of lines below -0.5, more than WRN, but its most affected line only
   reaches -1.09, whereas every genuine selective gene goes below -1.6. Screen
   noise produces drift; a real dependency produces a tail.

## Method
1. Pool each gene's effects across all lines; do not average by tissue first.
2. Compute the fraction of lines below the dependency threshold (-0.5 is the
   usual convention) **and** a low percentile such as the 1st.
3. Common essential: dependent in almost every line. Selective: dependent in a
   meaningful minority *and* with a strong tail. Non-essential: neither.
4. Plot the distribution before trusting any summary statistic.

## Pitfalls
- Ranking by mean or median gene effect. That finds common essentials and misses
  every selective dependency - the only kind worth drugging.
- Using a single threshold on the average rather than looking at the tail.
- Treating a low-count group as evidence.

## How to apply later
WRN is the selective dependency to carry forward. Experiment 2 asks *which* lines
depend on it, which is where the hypothesis is actually decided.

**Verified by.** Citation and DOI confirmed against Europe PMC, 2026-10-03.
Class labels recomputed from Open Targets DepMap data by
`curricula/wrn/fetch.py`; the quoted INS and WRN figures are from this dataset.
