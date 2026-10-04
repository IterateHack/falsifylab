# Lesson 1 - Genetic support predicts clinical success, but p-value does not

**Source.** Minikel EV, Painter JL, Dong CC, Nelson MR. *Refining the impact of
genetic evidence on clinical success.* Nature. 2024;629(8012):624-629.
doi:10.1038/s41586-024-07316-0 (open access)

## Key facts
1. Drug mechanisms with human genetic support succeed in clinical development
   about **2.6x** more often than those without. Genetic support raises the prior;
   it does not guarantee success.
2. The strength of a GWAS association reflects statistical power - sample size,
   allele frequency, effect size - not how good a drug target the gene is.
3. The gene nearest a lead variant is often not the causal gene. Assignment
   needs coding-variant evidence, fine-mapping or functional data.
4. Genetic support and **tractability** are independent axes. A gene can be
   beautifully associated and undruggable (FTO), or modestly associated and a
   validated target (GLP1R, GIPR, SLC5A2).
5. Direction of effect matters: the allele that raises a trait tells you which
   way a drug must push the target.

## Method
1. Collect candidate genes at associated loci, with the evidence that assigns
   each variant to a gene.
2. Score genetic support separately from druggability.
3. Combine: require both genetic support **and** a plausible modality (small
   molecule pocket, cell-surface accessibility for a biologic).
4. Rank on the combination, and report what the ranking would be on genetics
   alone so the contribution of each axis stays visible.

## Pitfalls
- Ranking by association score alone. In this dataset that puts FTO first - no
  approved drug acts on FTO.
- Treating a transcription factor or a nuclear structural protein as equivalent
  to a cell-surface receptor.
- Using evidence that already encodes the answer. Clinical and known-drug
  evidence is circular when the question is "will this become a drug target";
  it was deliberately withheld from the dataset you were given.

## How to apply later
GLP1R is the worked example of the combination: real genetic support for
BMI/T2D, a cell-surface class B GPCR with a ligand-bound structure, and approved
medicines. Experiment 2 looks at that structure.

**Verified by.** Citation and DOI confirmed against Europe PMC, 2026-10-03.
Validated-target labels derived from Open Targets Platform (stage APPROVAL or
PHASE_4); re-check if the Open Targets release changes.
