# Lesson 3 - Duration of action is engineered by clearance, not by potency

**Source.** Lau J, Bloch P, Schaffer L, et al. *Discovery of the Once-Weekly
Glucagon-Like Peptide-1 (GLP-1) Analogue Semaglutide.* J Med Chem.
2015;58(18):7370-7380. doi:10.1021/acs.jmedchem.5b00726

## Key facts
1. Native GLP-1 survives minutes. Two routes destroy it: **DPP-4** cleaves
   between His7 and Ala8, and the kidney clears the small peptide quickly.
2. Blocking DPP-4 means changing the residue at the cleavage site. Semaglutide
   uses **Aib8** (alpha-aminoisobutyric acid); exendin-based drugs have Gly in
   the equivalent position naturally; dulaglutide uses Gly8.
3. Escaping renal clearance means getting bigger or hitching a ride.
   Acylation with a fatty acid (liraglutide, C16 palmitoyl) or a **fatty diacid**
   (semaglutide, C18 via a gamma-Glu + 2x OEG linker) gives reversible albumin
   binding. Fusion to IgG4-Fc (dulaglutide) or albumin (albiglutide) does it by
   size.
4. Those two changes together move the half-life from ~2 minutes to ~13 hours
   (once daily) to roughly a week (once weekly). The acylation does most of the
   work; DPP-4 resistance alone is not enough.
5. **Potency and duration are separate axes.** The acyl chain slightly reduces
   intrinsic potency; it is accepted because exposure matters more.

## Method
1. Identify the proteolytic liability and protect it with a minimal substitution.
2. Choose the attachment point from the structure: modify where the receptor
   does not look. Lys26 is in the mid-region, away from the N-terminus that
   inserts into the TM core (lesson 2).
3. Tune the linker and chain length to trade albumin affinity against potency.
4. Predict duration from clearance mechanism, not from EC50.

## Pitfalls
- Acylating the N-terminus. It is the activation trigger; modifying it costs
  potency, which is exactly what lesson 2's contact map predicts.
- Assuming a more potent analogue lasts longer.
- Comparing half-lives across species or formulations without saying so.

## How to apply later
Experiment 4 separates potency from duration explicitly: it asks only about
EC50, measured in vitro, where clearance plays no part.

**Verified by.** Citation and DOI confirmed against Europe PMC, 2026-10-03.
Sequence modifications and dosing intervals are transcribed from the primary
literature and product labels. The approximate half-life figures in
`exp3_analogues.csv` are **not independently verified** and are not what is
scored - the duration-class ordering is.
