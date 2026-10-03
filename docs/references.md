# Reference verification

The plan (section 4.2) marked six references **(verify)** and required that they
be checked before they went into lesson cards. All six were verified against the
Europe PMC REST API on **2026-10-03**. Two were wrong in the draft plan.

| # | Reference | Status |
|---|---|---|
| 1 | Minikel EV, Painter JL, Dong CC, Nelson MR. *Refining the impact of genetic evidence on clinical success.* Nature. 2024;629(8012):624-629. doi:10.1038/s41586-024-07316-0 | **Verified.** Open access. Preprint: medRxiv doi:10.1101/2023.06.23.23291765 |
| 2 | Zhang X, Belousoff MJ, Liang YL, Danev R, Sexton PM, Wootten D. *Structure and dynamics of semaglutide- and taspoglutide-bound GLP-1R-Gs complexes.* Cell Rep. 2021;36(2):109374. doi:10.1016/j.celrep.2021.109374 | **Verified.** Author list confirmed independently against the PDB 7KI0 deposition. Not open access; preprint at bioRxiv doi:10.1101/2021.01.12.426449 |
| 3 | Lau J, Bloch P, Schaffer L, et al. *Discovery of the Once-Weekly Glucagon-Like Peptide-1 (GLP-1) Analogue Semaglutide.* J Med Chem. 2015;58(18):7370-7380. doi:10.1021/acs.jmedchem.5b00726 | **Verified.** Not open access |
| 4 | Kawai T, Sun B, Yoshino H, et al. *Structural basis for GLP-1 receptor activation by LY3502970, an orally active nonpeptide agonist.* Proc Natl Acad Sci U S A. 2020;117(47):29959-29967. doi:10.1073/pnas.2014879117 | **Verified, and re-assigned.** Open access |
| 5 | Wharton S, Aronne LJ, Stefanski A, et al. *Orforglipron, an Oral Small-Molecule GLP-1 Receptor Agonist for Obesity Treatment.* N Engl J Med. 2025;393(18):1796-1806. doi:10.1056/NEJMoa2511774 | **Verified.** This is the phase 3 (ATTAIN-1) trial |
| 6 | Yengo L, Sidorenko J, Kemper KE, et al. *Meta-analysis of genome-wide association studies for height and body mass index in ~700000 individuals of European ancestry.* Hum Mol Genet. 2018;27(20):3641-3649. doi:10.1093/hmg/ddy271 | **Verified**, but **not used** - see "Dataset choices" below |

## Corrections to the plan

**1. The LY3502970 paper was attached to the wrong experiment.** The plan listed
experiment 4's teaching source as "Orforglipron discovery / mechanism paper
(likely Kawai et al., PNAS 2020)" and experiment 5's as a separate "Structural
basis paper for LY3502970". These are the same paper: Kawai et al. PNAS 2020
*is* the LY3502970 structural paper. It is now experiment 5's source, which is
where the structural and species argument belongs. Experiment 4 cites the ChEMBL
database paper instead, since its lesson is about potency measurement, not about
any one compound.

**2. The capstone reference was the phase 2 trial, not phase 3.** The plan cited
"Wharton et al., NEJM 2023" as the Phase 3 obesity trial. Wharton et al. NEJM
2023 (doi:10.1056/NEJMoa2302392, *Daily Oral GLP-1 Receptor Agonist Orforglipron
for Adults with Obesity*) exists, but it is the **phase 2** dose-finding study.
The phase 3 trial is Wharton et al. NEJM **2025** (ATTAIN-1). Both have the same
first author, which is probably how the two got conflated. The capstone lesson
card cites the 2025 paper for the headline result and names the 2023 paper
explicitly so the distinction is on the record.

## Dataset choices

| Experiment | Source | How |
|---|---|---|
| 1 | Open Targets Platform GraphQL `api/v4` | BMI (EFO_0004340) and T2D (MONDO_0005148) associated targets, top 90 each, 174 unique genes |
| 2 | RCSB PDB (PDBe mirror as fallback) | 7KI0 mmCIF, contacts recomputed at a 4.0 A heavy-atom cutoff |
| 3 | UniProt P01275 + primary literature | Native GLP-1 sequence fetched; sequence modifications and dosing intervals transcribed |
| 4 | ChEMBL REST | All 2365 EC50 records for CHEMBL1784; dose-response curves rendered from the real consensus potencies |
| 5 | UniProt P43220 / O35659 / P32301 / F7E3K6 | Human, mouse, rat and rhesus macaque GLP1R, aligned position by position |
| 6 | - | No new data; rubric against the ATTAIN-1 result |

**Why not the Yengo BMI GWAS.** The plan proposed Yengo et al. 2018 for
experiment 1. The reference is real and was verified, but the GWAS Catalog
association endpoint streams the full association set for a trait with no
practical page limit (over 5 MB and still going on a 60-second timeout), and the
GIANT summary statistics are hundreds of megabytes. Open Targets provides the
same thing - genes at BMI and T2D associated loci with genetic evidence scores -
in two queries, and additionally supplies the validated-target labels that
experiment 1 is scored against. The Yengo meta-analysis is upstream of the Open
Targets genetic evidence either way.

## Known soft spots

- **Half-lives in `exp3_analogues.csv` are transcribed, not API-verified.** They
  carry `half_life_provenance: "literature/label, pending sign-off"`, and the
  scorer deliberately ignores them: experiment 3 is scored on the duration-class
  ordering (minutes / twice daily / once daily / once weekly), which is not in
  dispute, plus a mechanism rubric. The numbers are context for the agent.
  **Needs a human sign-off before the lesson card is presented as authoritative.**
- **Experiment 1's ground truth depends on an Open Targets release.** "Validated
  target" means the platform lists a drug at stage `APPROVAL` or `PHASE_4`.
  A release change can move a gene across that line; `private/exp1.json` records
  the criterion with the labels so a diff is visible. An earlier version of this
  code checked only `PHASE_4` and so scored MC4R (setmelanotide) as a failure.
- **Experiment 4's curve points are simulated.** The potencies are real ChEMBL
  consensus values; ChEMBL stores summary EC50s rather than raw curves, so the
  points are a deterministic four-parameter-logistic rendering of those values
  (seed 20261003). This is recorded in `data/PROVENANCE.json` as `derived`.
- **Lesson cards are paraphrases with citations, never excerpts**, per the plan's
  copyright mitigation. Three of the six sources are not open access; the cards
  carry the citation and DOI so a reader can go to the source.

---

# WRN curriculum (H2) references

Verified against Europe PMC on **2026-10-03**.

| # | Reference | Status |
|---|---|---|
| 1 | Tsherniak A, Vazquez F, Montgomery PG, et al. *Defining a Cancer Dependency Map.* Cell. 2017;170(3):564-576.e16. doi:10.1016/j.cell.2017.06.010 | **Verified.** Not open access |
| 2 | Chan EM, Shibue T, McFarland JM, et al. *WRN helicase is a synthetic lethal target in microsatellite unstable cancers.* Nature. 2019;568(7753):551-556. doi:10.1038/s41586-019-1102-x | **Verified.** Open access |
| 3 | van Wietmarschen N, Sridharan S, Nathan WJ, et al. *Repeat expansions confer WRN dependence in microsatellite-unstable cancers.* Nature. 2020;586(7828):292-298. doi:10.1038/s41586-020-2769-8 | **Verified.** Not open access |

Behan et al. Nature 2019, listed in the plan for H2 experiment 2, is not used:
the two experiments built here are the dependency-class distinction and the
lineage confounder, and those are covered by Tsherniak and Chan.

## Data

All DepMap CRISPR gene-effect values come from the Open Targets Platform field
`target.depMapEssentiality`, which exposes per-cell-line Chronos scores
(21,108 measurements, 17 genes, ~1250 lines). Nothing is transcribed.

**Known soft spot: no MSI annotation.** Open Targets exposes tissue and disease
name per cell line but not microsatellite-instability status, so experiment 2
asks about the *lineage* distribution of WRN dependency and about what that
distribution stands for, rather than scoring an MSI-stratified analysis
directly. The lesson card says so explicitly, and the rubric rewards proposing
MSI annotation as the next measurement. A fuller version would pull the DepMap
sample-info table and score the within-lineage MSI comparison, which is the
actual Chan et al. result.
