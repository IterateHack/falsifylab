# Bacteria-free control wording in antibacterial methods (scenario A, PR4)

- **Rule decision supported:** what PR4's control-wording matcher should accept as a declared bacteria-free control in E6's free-text `controls` field.
- **Accept:** Tier A phrasings (sterility control, medium/broth only or alone, uninoculated, negative growth control, media control, non-inoculated); Tier B only with a no-bacteria qualifier nearby; Tier C (test compound in medium, no inoculum) as its own slot.
- **Block:** growth, untreated, solvent, vehicle and DMSO controls, cell-free (supernatant) and "no bacterial growth". **Ambiguous**, never matched on the string alone: negative control, positive control, bare "blank".

Literature survey run with Paperclip (paperclip.gxl.ai). Tables and citations are as delivered; the search agent's working notes are omitted.

## Method

Corpus-wide grep on /papers/ returns heavy off-domain noise ("medium only" in plasma physics, "uninoculated" in plant/soil ecology), so I built a PMC-only antibacterial-methods cohort first, then grepped inside it:

```
search -s pmc --bool --ranking bm25 --full-text
  '("minimum inhibitory concentration" OR "broth microdilution" OR "time-kill"
    OR "growth inhibition assay" OR "lysis assay")
   AND ("antibacterial" OR "antimicrobial" OR "bacterial")' -n 300   → cohort "abx"
grep --from abx -i "<phrase>"
```

Counts below = number of cohort papers (out of 300) containing the phrasing, read in context. They are relative frequencies within a defensible sample, not corpus totals.

---

## 1. Proposed alias list — all denote *medium without bacteria*

### Tier A: unambiguous, safe to alias

| Phrasing | Papers | Example citations |
| :---- | :---- | :---- |
| sterility control(s) | 30 | "Wells in Column 11 served as sterility controls (broth only)" 1 ; "a sterility control without bacteria" 2 |
| medium alone / media alone / broth alone | 12 | "Control samples included culture medium alone" 3 ; "the negative control was broth alone" 4 |
| medium only / media only | 10 | "media only (negative/sterility control)" 4 ; "streptomycin as a positive control and media only" 5 |
| broth only / only broth | 9 | 1 ; "sterility control (100 µL of Mueller–Hinton broth (MHB))" 6 |
| uninoculated (medium/broth/MHB/media) | 5 | "uninoculated MHB was used as a sterility control" 7 ; "negative controls included uninoculated MHB to ensure sterility of the media" 8 |
| negative growth control | 5 | "column 12 as a negative growth control with 200 µL uninoculated media in each well" 9 |
| media control / medium control | 4 / 2 | "(A) Media control, (B) growth control" 10 ; "Medium control (Sterile broth) \| 0 \| 0 \| …" 11 |
| non-inoculated / not inoculated | 4 | "As a blank, a non-inoculated plate treated in the same way was used" 12 |

### Tier B: alias only with a no-bacteria qualifier nearby

| Phrasing | Papers | Example citations | Why conditional |
| :---- | :---- | :---- | :---- |
| blank well(s) | 3 | culture "added to the wells containing the compounds (except the blank wells)" 13; "(OD <0.1 after subtracting the blank OD)" 13 | Only bacteria-free when the text says cells were withheld from those wells |
| background control | 3 | "the group without bacterial cells served as background control" 14 | Elsewhere means instrument/OD background |
| sterile control | 2 | *count only — not individually inspected* | Can also mean "sterilised material" control |
| blank medium / blank media | 1 | *count only — not individually inspected* | In nanoparticle papers "blank NPs" = empty carrier, bacteria present |

### Tier C: bacteria-free compound control (a distinct sub-concept — keep as its own slot, don't merge into plain "sterility control")

Wells contain the test article *and* medium but no inoculum, to correct for intrinsic turbidity/colour:

*"sterility controls consisting of wells containing only the test compounds in MHB without bacteria were included to ensure that the formulations themselves did not cause turbidity" 8*

*"wells containing only SLN formulations without bacteria were included as sterility controls" 8*

*"PRP control (50 MHB with 50 µL of PRP)" 6*

Also attested as a compound-sterility column alongside a broth-sterility column, and as "media sterility control (designated as 0% biofilm)" 6, "growth controls, SN and sterility controls … medium sterility were monitored" 15.

---

## 2. Do-NOT-alias list

### 2a. Bacteria present, compound/drug absent or replaced

| Phrasing | Papers | What it actually is | Citations |
| :---- | :---- | :---- | :---- |
| growth control | 23 | inoculum + medium, no drug — the 100 %-growth denominator | "Column 12 served as growth controls (broth and bacteria without test extract)" 1 ; "The group without antibiotic/bismuth compounds served as growth control" 14 |
| untreated control | 23 | bacteria cultured without test agent, usually the time-kill/CFU baseline | "compared to the untreated control … regrowth observed at 24 h" 16 ; "differences between ZnNPs and untreated controls" 15 |
| solvent control | 14 | solvent + bacteria | "chloroform/DMSO without PHB but bacteria (solvent control) to rule out solvent effects" 4 |
| vehicle control | 13 | carrier + bacteria | "inoculated MHB with either blank Z-NaCAS NPs or DMSO was used as a vehicle control" 7 |
| DMSO control | 3 | DMSO + bacteria | "the growth control included 2.5% of DMSO for verification that the applied DMSO concentration did not inhibit growing of the bacterial biofilm" 12 |

Note 14 gives the cleanest single-sentence disambiguation in the whole cohort — growth control and background control are defined side by side in one clause.

### 2b. Genuinely ambiguous — never map on the string alone

| Phrasing | Papers | Problem |
| :---- | :---- | :---- |
| negative control | 12 | Splits both ways. Bacteria-present sense: "DMSO 2% v/v and 5 μg ciprofloxacin served as the negative and positive controls" 1. Bacteria-free sense: "media only (negative/sterility control)" 4 and "the negative control was broth alone" 4. Requires reading the parenthetical. |
| positive control | — | Also splits: "Positive controls consisted of bacterial cultures without treatment to confirm growth" 8 vs. "a positive control with gentamicin" 2. |
| blank (bare word) | — | Polysemous *within the same paper*: reagent blank "Exactly 95% of methanol was used as a blank" 18 vs. medium-only blank "TSB medium alone served as a blank" 18; and "30% acetic acid in water served as a blank" 14 (crystal-violet solvent blank). |

### 2c. False friends — not controls at all

| Phrasing | Papers | What it is |
| :---- | :---- | :---- |
| cell-free | 15 | Almost always "cell-free supernatant" (CFS) — the *test article* from a probiotic/bacterial culture, i.e. the thing being assayed. "antimicrobial characteristics of cell-free supernatants from *Pediococcus acidilactici*" 17 ; "The treatments included CFS of RBX7" 5. Aliasing cell-free → sterility control would invert the role of the sample. |
| "no-cell control" | 1 | Too rare in antibacterial methods to be worth a rule; it is cell-culture/biochemistry vocabulary, not CLSI microdilution vocabulary. |
| "no bacterial growth" / "without bacterial growth" | very common | An outcome readout defining MIC/MBC, not a control arm: "wells showing no visible bacterial growth" 8. High false-positive risk for any regex on `no.{0,3}bacteria`. |

---

## Practical regex guidance

* Highest-yield single anchor: `sterilit(y|ies)\s+control` — covers 30/300 papers alone and is near-zero false positive.  
* Second anchor: `(un|non[- ])inoculated` or `without (bacteria|the inoculum|bacterial cells)` within ±1 sentence of `control|blank|background`.  
* Container-word pattern: `(medium|media|broth)\s*(-|\s)?(only|alone|control|blank)` catches Tier A rows 3–7 but must be negated against `blank (NPs|nanoparticles|carrier|formulation)`.  
* Hard-block list before any mapping: growth control, untreated, vehicle, solvent, DMSO control, cell-free supernatant, `no (visible )?bacterial growth`.  
* Route negative control, positive control, and bare blank to a context-reading step rather than a string rule.

---

References

1 Tesfay, Y. R. et al. "Development, Characterization, and Evaluation of Topical Antibacterial Formulations From *Achyranthes aspera*." *BioMed Research International* (2026). PMC13140320#L40,L50

2 Garzoli, S. et al. "Liquid and Vapour Phase of Lavandin (*Lavandula × intermedia*) Essential Oil: Chemical Composition and Antimicrobial Activity." *Molecules* (2019). PMC6696025#L47

3 Shetty, R. M. et al. "Biophysical properties and antimicrobial efficacy of a novel Silk Sericin Mineral Trioxide Aggregate." *Frontiers in Dental Medicine* (2026). PMC12812904#L49

4 Manal et al. "Production, characterization, and antimicrobial activity of polyhydroxyalkanoates synthesized by *Bacillus* species against skin pathogens." *RSC Advances* (2025). PMC12459338#L37,L107

5 Mohd Basri, N. N. N. et al. "*Lactococcus lactis* subsp. *lactis* as a biocontrol agent against phytopathogens causing rice bacterial leaf blight." *Scientific Reports* (2025). PMC12685965#L28

6 Aboelsaad, E. et al. "Platelet-rich plasma as a potential antimicrobial agent against multidrug-resistant bacteria in diabetic foot infections." *Scientific Reports* (2025). PMC12043966#L153,L174

7 Alsakhawy, S. A. et al. "Enhancement of lemongrass essential oil physicochemical properties and antibacterial activity by encapsulation in zein-caseinate nanocomposite." *Scientific Reports* (2024). PMC11283490#L105

8 Nazari, M. & Hosseini, S. M. "Evaluation of antibacterial and antibiofilm efficacy of gentamicin-loaded solid lipid nanoparticles (GM-SLNs) against *Acinetobacter baumannii* infections." *BMC Chemistry* (2025). PMC12482661#L75,L79

9 Blaskovich, M. A. T. et al. "The antimicrobial potential of cannabidiol." *Communications Biology* (2021). PMC7815910#L279

10 Firdous, S. et al. "Synthesis, Characterization, and Antimicrobial Activity of Urea-Containing α/β Hybrid Peptides against *Pseudomonas aeruginosa* and MRSA." *ACS Omega* (2025). PMC11755142#L53

11 Adegbola, A. E., Abolarinwa, T. O. & Fayemi, O. E. "Green-mediated gold nanoparticles from *Allium cepa*: Synthesis, characterization and antimicrobial properties." *Biotechnology Notes* (2026). PMC12925291#L106

12 Pospíšilová, Š. et al. "Dibasic Derivatives of Phenylcarbamic Acid as Prospective Antibacterial Agents Interacting with Cytoplasmic Membrane." *Antibiotics* (2020). PMC7168207#L71

13 Kench, T. et al. "Discovery of Phototoxic Metal Complexes with Antibacterial Properties via a Combinatorial Approach." *Inorganic Chemistry* (2025). PMC11920948#L29,L31

14 Wang, C. et al. "Metallo-sideromycin as a dual functional complex for combating antimicrobial resistance." *Nature Communications* (2023). PMC10474269#L64,L73

15 Lopez Venditti, E. D. et al. "Antibacterial, antifungal, and antibiofilm activities of biogenic zinc nanoparticles against pathogenic microorganisms." *Frontiers in Cellular and Infection Microbiology* (2025). PMC12301384#L41,L43,L91

16 Hussein, M. et al. "Metabolic profiling unveils enhanced antibacterial synergy of polymyxin B and teixobactin against multi-drug resistant *Acinetobacter baumannii*." *Scientific Reports* (2024). PMC11543821#L27

17 Kho, K. et al. "The Potential of *Pediococcus acidilactici* Cell-Free Supernatant as a Preservative in Food Packaging Materials." *Foods* (2024). PMC10930656#L5

18 Shatri, A. M. N. et al. "Antimicrobial, Time–Kill Kinetics, and Biofilm Inhibition Properties of *Diospyros lycioides* Chewing Stick Used in Namibia Against *Enterococcus faecalis*." *Journal of Tropical Medicine* (2025). PMC12185201#L27,L52
