# Lesson 5 - Check the species before you believe a negative result

**Source.** Kawai T, Sun B, Yoshino H, et al. *Structural basis for GLP-1
receptor activation by LY3502970, an orally active nonpeptide agonist.* Proc Natl
Acad Sci U S A. 2020;117(47):29959-29967. doi:10.1073/pnas.2014879117
(open access)

## Key facts
1. **LY3502970 (orforglipron) is a non-peptide agonist that does not occupy the
   peptide orthosteric site.** It binds a site involving the extracellular domain
   and the top of the TM bundle - consistent with lesson 2, where the peptide
   interface was far too large for a small molecule to copy.
2. The compound is a **partial agonist**, biased towards G-protein (cAMP)
   signalling over beta-arrestin recruitment. Full agonism was not required for
   clinical efficacy.
3. **Human GLP-1R carries Trp33; mouse and rat carry Ser at the same position.**
   The compound depends on that tryptophan, so it is essentially **inactive at
   unmodified rodent GLP-1R**. Rhesus macaque has Trp33, like human.
4. Trp33 is in the ECD and was *not* in the semaglutide contact set from
   experiment 2 - which is precisely why the two ligand classes behave so
   differently across species.
5. There are 16 ECD positions where both rodents differ from human. Only the
   structure tells you which one matters; a difference count does not.

## Method
1. Before choosing an assay species, align the orthologues and look at the
   binding site you actually care about - not global sequence identity.
2. Use **human or humanised** receptor for primary pharmacology: recombinant
   human GLP-1R in a cAMP accumulation assay, or a humanised knock-in animal for
   in vivo work. A non-human primate is an acceptable alternative here.
3. Measure cAMP and beta-arrestin separately to characterise bias, and report the
   fitted maximum so partial agonism is explicit.
4. Treat a negative result in a non-validated species as uninterpretable until
   the target sequence has been checked.

## Pitfalls
- Reaching for a standard rodent obesity model (db/db, ob/ob, diet-induced
  obese mouse) by default. Here that produces a false negative.
- Assuming a small molecule must be orthosteric.
- Assuming a partial agonist is clinically inferior.

## How to apply later
The capstone has to carry this caveat: the preclinical species constraint is a
real limitation on how much rodent data can say about this mechanism, even though
the human trial result is positive.

**Verified by.** Citation, journal, authors and DOI confirmed against Europe PMC,
2026-10-03 (the plan's draft had attributed this paper to experiment 4). Residue
33 recomputed from UniProt P43220 / O35659 / P32301 / F7E3K6: W / S / S / W.
