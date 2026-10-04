# Lesson 2 - The peptide orthosteric site is not the only druggable site

**Source.** Zhang X, Belousoff MJ, Liang YL, Danev R, Sexton PM, Wootten D.
*Structure and dynamics of semaglutide- and taspoglutide-bound GLP-1R-Gs
complexes.* Cell Rep. 2021;36(2):109374. doi:10.1016/j.celrep.2021.109374
Structure: **PDB 7KI0**, 2.5 A cryo-EM. (Preprint: bioRxiv
doi:10.1101/2021.01.12.426449)

## Key facts
1. GLP-1R is a class B1 GPCR: a large extracellular domain (ECD) plus a
   seven-helix transmembrane domain. Peptide agonists use **both** - the
   C-terminal half is captured by the ECD, the N-terminus inserts deep into the
   TM core and drives activation. This is the "two-domain" binding model.
2. In 7KI0 the deposited complex has six polymer chains. Semaglutide is chain
   **P** (entity 5) and the receptor is chain **R** (entity 6); the rest are Gs
   alpha/beta/gamma and the stabilising nanobody Nb35. Picking the wrong pair of
   chains is the most common way to get this analysis wrong.
3. At a 4.0 A heavy-atom cutoff the peptide contacts **40** receptor residues,
   spread across the ECD, the extracellular loops and the TM bundle - a long
   interface, not a compact pocket.
4. Because the interface is large and partly ECD-mediated, a small molecule
   cannot realistically reproduce it. A non-peptide agonist must act somewhere
   else.
5. Trp33 sits in the ECD at the edge of this interface but is **not** a
   semaglutide contact at this cutoff. Remember that residue.

## Method
1. Identify chains by entity description, never by assuming chain letters.
2. Take heavy atoms only (ignore hydrogens, waters and ligands).
3. Compute all peptide-atom to receptor-atom distances; keep receptor residues
   with any atom within the stated cutoff.
4. State the cutoff with the result - "contact" is a definition, not a fact.

## Pitfalls
- Reporting Gs-interface or nanobody-interface residues as peptide contacts.
- Using CA-CA distances, which miss side-chain contacts entirely.
- Quoting a contact set without its cutoff, which makes it unreproducible.

## How to apply later
Experiment 3: the N-terminus is spoken for, so engineer duration of action in the
mid-region. Experiment 5: an orally active non-peptide must bind outside this
orthosteric interface - and Trp33 is the clue.

**Verified by.** Citation confirmed against Europe PMC, 2026-10-03. Chain and
entity composition and the 40-residue contact set recomputed from the deposited
mmCIF by `curricula/glp1r/fetch.py`.
