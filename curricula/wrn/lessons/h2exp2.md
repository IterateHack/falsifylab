# Lesson 2 - Lineage is a proxy. Find the variable it stands for

**Sources.** Chan EM, Shibue T, McFarland JM, et al. *WRN helicase is a synthetic
lethal target in microsatellite unstable cancers.* Nature.
2019;568(7753):551-556. doi:10.1038/s41586-019-1102-x (open access)

van Wietmarschen N, Sridharan S, Nathan WJ, et al. *Repeat expansions confer WRN
dependence in microsatellite-unstable cancers.* Nature. 2020;586(7828):292-298.
doi:10.1038/s41586-020-2769-8

## Key facts
1. WRN dependency concentrates in **uterus (endometrial) and intestine
   (colorectal)** lines - the two lineages in which **microsatellite instability
   (MSI)** is most common. Tissue is the visible variable; MSI is the real one.
2. MSI arises from defective **DNA mismatch repair**. The dependency tracks MSI
   status, not tissue: MSI-high lines from other lineages are also WRN-dependent,
   and microsatellite-stable colorectal lines are not.
3. This is **synthetic lethality**: neither losing mismatch repair nor losing WRN
   is lethal alone, but together they are. That is what makes WRN a target in a
   defined population rather than a general cytotoxic.
4. Mechanism: MSI-high genomes accumulate **expanded TA dinucleotide repeats**,
   which can adopt cruciform secondary structures. WRN's helicase activity
   resolves them. Without WRN the structures are cleaved and the genome
   shatters.
5. Lineage looks like a cause here and is not one. Confusing the two is how a
   target gets developed for the wrong population.

## Method
1. Rank groups by the fraction of lines that are dependent, not by the mean, and
   set a minimum group size - a tissue with two lines tops any ranking by chance.
2. When a dependency clusters by lineage, ask what else clusters that way.
   Lineage correlates with mutational process, expression programme and genotype.
3. Get the candidate variable annotated directly - here, MSI status per line -
   and test within lineage, so lineage cannot explain the result.
4. Only then look for a mechanism that predicts the association.

## Pitfalls
- Stopping at "it is a colorectal dependency". That is the observation, not the
  finding, and it defines the wrong patient population.
- Ranking tissues without a minimum line count.
- Accepting a correlation that lineage alone could produce.

**Verified by.** All three citations confirmed against Europe PMC, 2026-10-03.
Tissue ranking recomputed from Open Targets DepMap data by
`curricula/wrn/fetch.py`.
