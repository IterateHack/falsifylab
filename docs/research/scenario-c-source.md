# Scenario C source extraction — Evans et al. 2021, Mtb CoaBC

Source of truth for a *possible* third scenario. Extraction only: nothing here is a scenario,
a hypothesis set, an answer key or a design decision, and no file outside this one was added or
changed. Sibling of `scenario-a-gold-check.md`; same conventions.

- **Paper:** Evans, J. C.; Murugesan, D.; Post, J. M.; Mendes, V.; Wang, Z.; Nahiyaan, N.;
  Lynch, S. L.; Thompson, S.; Green, S. R.; Ray, P. C.; Hess, J.; Spry, C.; Coyne, A. G.;
  Abell, C.; Boshoff, H. I. M.; Wyatt, P. G.; Rhee, K. Y.; Blundell, T. L.; Barry, C. E. III;
  Mizrahi, V. "Targeting *Mycobacterium tuberculosis* CoaBC through Chemical Inhibition of
  4′-Phosphopantothenoyl-l-cysteine Synthetase (CoaB) Activity." *ACS Infect. Dis.* 2021, 7 (6),
  1666–1679. doi:10.1021/acsinfecdis.0c00904. PMC8205227. PMID 33939919.
  Received 2020-12-23; issue date 2021-06-11.
- **Retrieved:** full text as JATS XML from Europe PMC (`PMC8205227/fullTextXML`).
  **The SI PDF was retrieved** — `id0c00904_si_001.pdf`, via the Europe PMC
  `PMC8205227/supplementaryFiles` archive, which also carries the seven article figure images.
  SI title page states: **Pages: 7, Figures: 8, Tables: 0.**
- **Extraction rule applied here:** every number and quote below is from the article text, a
  machine-readable table, or the SI text layer. Where a value exists only inside an image, this
  file names the image and does **not** state the value. Where a measurement does not exist,
  it says NOT MEASURED; where a replicate count is not stated, it says so.

## 1. Every experiment bearing on why a compound does or does not inhibit Mtb growth

Replicate counts are quoted as the paper states them. "Independent triplicates" is the paper's
phrase; it does not define whether the three are biological or technical replicates anywhere.

**E1 — High-throughput screen for CoaB inhibitors.** 215 000 small molecules from the DDU
compound collection, screened at 30 µM. Adaptation of the BIOMOL Green (Enzo Life Sciences)
end-point pyrophosphate quantification assay, as previously described (ref 41): decreased
phosphate production after addition of a pyrophosphatase indicates reduced pyrophosphate
production by CoaB, hence inhibition. Readout: absorbance; overall primary hit rate 0.6%; the
hit was compound **1a** (CoaB IC50 = 9.9 µM). Liquid dispensing on a Thermo Scientific Matrix
Wellmate; data processed in ActivityBase (IDBS). **n: NOT STATED for the primary screen.**

**E2 — Pyrophosphatase counter-screen (false-positive elimination).** 50 µL reactions,
0.5 U/mL pyrophosphatase and 2 µM pyrophosphate in 100 mM Tris-HCl pH 7.6 with 1 mM MgCl2 and
1 mM TCEP, 2 h at room temperature, 384-well plates (Greiner Bio-One). Control reactions
omitted the pyrophosphatase. Terminated with 50 µL BIOMOL Green; product formation read as
absorbance at 650 nm on a PHERAstar (BMG Labtech) after 20 min incubation. Readout: A650.
**n: NOT STATED.**

**E3 — Per-compound CoaB IC50 for the nine analogues (Table 1).** Same biochemical assay
format as E1. Readout: IC50 in µM. **n: NOT STATED** — Table 1's only footnote covers
intrinsic clearance and CHI, not replication, and the IC50 column carries no n, no SD and no
confidence interval anywhere in text, table or SI.

**E4 — EnzChek coupled-enzyme IC50 for 1f, Mtb CoaBC vs human CoaB.** EnzChek pyrophosphate
assay kit (E-6645, Life Technologies). 100 mM Tris pH 7.5, 1 mM TCEP, 2% DMSO, 1 mM MgCl2,
200 µM MSEG, 0.03 U/mL inorganic pyrophosphatase, 1 U/mL purine nucleoside phosphorylase,
32 nM Mtb CoaBC, 125 µM CTP, 125 µM PPA, 500 µM l-cysteine, 1f at 2–256 µM; human CoaB assays
used 1 µM enzyme. 1f was first confirmed inactive on the coupled reporter enzymes at 100 µM.
Readout: IC50 in µM — **24.3 µM** (Mtb CoaBC) and **23.4 µM** (human CoaB). Enzymes expressed
in *E. coli* BL21(DE3) from pET28aSUMO-CoaBC or a human CoaB construct with a cleavable
N-terminal 6×His tag, induced with 0.5 mM IPTG, 18 °C, 18–20 h. **n: "All reactions were
carried out in at least triplicate"; Figure 3's caption says "mean and SD of independent
triplicates". Fits calculated in GraphPad Prism.**

**E5 — Kinetics and substrate-competition (mode of inhibition).** Same conditions as E4 with
one substrate varied: CTP (31.25, 62.5, 125, 250, 500 µM), PPA (same five concentrations), or
l-cysteine (31.25, 62.5, 93.75, 125, 250 µM; l-cysteine competition used a CMP quantification
assay instead of EnzChek). Readouts: apparent Km — CTP 27.4 ± 2.6 µM, PPA 45.4 ± 5.3 µM,
l-cysteine 29.8 ± 3.0 µM (saturation curves in Figure S3); inhibition constants from
Lineweaver–Burk analysis (Figure 3c–e) — **uncompetitive** for PPA with αKi 19.0 ± 0.6 µM,
**noncompetitive** for CTP (Ki 10.1 ± 1.4 µM) and l-cysteine (Ki 22.7 ± 7.6 µM).
**n: "at least triplicate" (methods); Figure 3 caption "independent triplicates".**

**E6 — Differential scanning fluorimetry (ligand-dependence of 1f binding).** 96-well format,
CFX Connect (Bio-Rad). Each well: 5 µM Mtb CoaBC, 25 mM Tris pH 8.0, 150 mM NaCl, 1 mM MgCl2,
2.5% DMSO, 5× Sypro Orange; substrates/products at 1 mM individually and in the combinations
CMP+l-cysteine, CTP+l-cysteine, CMP+PPA, CTP+PPA, CMP+PPA+l-cysteine, PPA+l-cysteine, each
± 2.5 mM 1f; ligand-free unfolding measured in parallel. Readout: melting temperature, °C —
CoaBC Tm = 46 °C under assay conditions; per-condition thermal shifts are in **Table 2, which
is a real machine-readable table** (ΔTm = +7 °C for PPA, +7 °C for CMP+PPA, +6.5 °C for
CMP+PPA+l-cysteine, +7 °C for CTP+PPA, 0 °C for CTP, 0 °C for CTP+l-cysteine, +1 °C for CMP,
l-cysteine and CMP+l-cysteine, **−3 °C for l-cysteine+PPA**). **n: "Data are representative of
three independent triplicates. Where SD is not indicated, SD = 0."** Melting profile in
Figure S4.

**E7 — MICs against wild-type Mtb and the hypomorph.** Microbroth dilution with Alamar Blue
fluorescence as the growth readout, as previously described (ref 46). Two-fold serial
dilutions; inoculated with Mtb H37RvMA (~10^5 CFU/mL, from OD600 = 0.6) or the *coaBC*
hypomorph (~10^4 CFU/mL, from OD600 = 0.2); 100 µL final volume in U-bottom 96-well plates;
10 days at 37 °C; then 10 µL Alamar Blue and a further 24 h at 37 °C; fluorescence read on a
SpectraMax i3x in bottom-reading mode, excitation 544 nm, emission 590 nm. Growth medium:
Difco Middlebrook 7H9 + Middlebrook ADC enrichment, 0.2% glycerol, 0.05% Tween-80 (hygromycin
50 µg/mL, kanamycin 25 µg/mL, pantethine 2.5 mg/mL where required). Readout: MIC in µM.
**n: "All data are representative of independent triplicates."**

**E8 — Target-based whole-cell screening against the *coaBC* Tet-OFF hypomorph (checkerboard).**
See §4 for the full parameters. Readout: MIC shift (fold) as a function of ATc concentration.
**n: Figure 2 caption — "mean and SD of independent triplicates".**

**E9 — CoaBC-bypass rescue by pantethine, and the pantothenate control.** Exogenous pantethine
(PantS) at 2.5 mg/mL added to the MIC assay; the rationale is that PanK phosphorylates
pantetheine to P-PantSH and so bypasses CoaBC. Readouts: rescue of wild-type Mtb from 1f
toxicity (Figure 2c); 4-fold reduction in susceptibility of the hypomorph to 1f, with no rescue
at the highest 1f concentration tested, 125 µM (Figure 2b); MICs of 1f + PantS of **83.3 µM**
(wild type) and **77.2 µM** (hypomorph) when inoculated from OD600 = 0.2, rising to **>125 µM**
when inoculated from OD600 = 0.6; 1f alone unaffected by inoculum density (MIC = 25.9 µM at
either OD600). Separate control: pantothenate (Pan) at maximal silencing (ATc 200 ng/mL) fully
rescued a *panC* Tet-OFF hypomorph but did **not** restore growth of the *coaBC* hypomorph
(Figure S1; SI legend states Pan25 = pantothenate 25 µg/mL). **n: NOT STATED for Figure S1 or
Figure S2.**

**E10 — Metabolomic profiling after compound exposure.** Mtb-laden filters generated as
previously described (ref 53), incubated 4 days at 37 °C to expand biomass, then transferred
onto fresh 7H10 agar with or without 1f or 2b at 5 µM and 50 µM for a further 24 h; metabolite
extraction and LC-MS profiling as previously described (ref 33). Readout: relative metabolite
abundance from ion intensities, log2-transformed against an untreated (DMSO) control, rendered
as a heat map (Figure 4; Figure S6), clustered by uncentered Pearson correlation with centroid
linkage (Java TreeView). Stated findings: substantial accumulation of dephospho-CoA; notable
depletion of propionyl-CoA, succinyl-CoA and malonyl-CoA (dose-dependent for 1f); **no
detectable change in CoA** for either compound; ATP depletion (Figure 4); no accumulation of
PPA. **n: "All data obtained by metabolomics were the average of independent triplicates."**

**E11 — Intracellular accumulation of 1f and 2b.** Full detail in §3. **n: Figure S7 caption —
"Data are representative of 3 independent replicates"; the methods section states no n.**

**E12 — Pharmacological profiling.** HepG2 cytotoxicity, mouse liver microsomal intrinsic
clearance (CD1 mouse liver microsomes, per Table 1's footnote), kinetic solubility, and CHI
LogD, all "as previously described" (ref 66) with no method detail in this paper. Readouts:
IC50 (µM), Cli in (mL/min)/g, solubility in µM, CHI LogD (dimensionless). Prose-stated results:
no compound was overly lipophilic, all except 1i having CHI LogD ≤ 1.5; kinetic solubility
limits ranged between 55 and 219 µM; all clearance values ≤ 2.8 (mL/min)/g against an internal
threshold of < 5; no significant HepG2 cytotoxicity (IC50 > 50 µM) except 1i (IC50 = 40 µM).
**n: NOT STATED.**

**E13 — Comparator 2b.** Its CoaB IC50 (0.08 µM) and MIC (> 250 µM) are **quoted from ref 41,
not measured in this paper**; 2b was measured here only in E10 and E11.

**Not obtained:** "A crystal structure of CoaB with **1f** bound could not be obtained"
(Results, *Elucidation of the Mode of Inhibition and Selectivity of Compound 1f*, final
paragraph).

## 2. Per-compound data for 1a–1i and comparator 2b, with provenance

**Table 1 is an image.** It is supplied as the two graphics `id0c00904_0005.jpg` and
`id0c00904_0006.jpg`; the JATS record for `tbl1` contains a caption, those two `<graphic>`
elements and one footnote, and no table markup. Its columns are Compound ID, R1, R2, Mtb CoaB
IC50 (µM), Mtb H37Rv MIC (µM), HepG2 IC50 (µM), Mouse Cli (mL/min)/g, Kinetic Solubility (µM),
CHI LogD. Per the rule at the top of this file, **no per-compound value is transcribed here
from that image**, including for the compounds whose numbers appear nowhere else. (The image
was opened only to list the columns above and to confirm every row is present in it.)

Recoverable from running prose (Results §§ *High-Throughput Screening…*, *Whole-Cell
Screening…*, and Discussion):

| Compound | Value in prose | Where |
| --- | --- | --- |
| 1a | CoaB IC50 = 9.9 µM | Results HTS ¶1; Discussion ¶2 |
| 1a | MIC > 125 µM | Discussion ¶2 ("inactive against replicating Mtb (MIC > 125 µM)"); Results whole-cell ¶1 states all compounds except 1f and 1i were inactive "at concentrations up to 125 µM" |
| 1b, 1c, 1d | CoaB potency: "modest improvements" over 1a — **no numeric IC50 in prose** | Results HTS ¶1 |
| 1e | CoaB potency: "4-fold increase in potency" relative to 1a — **no numeric IC50 in prose** | Results HTS ¶1 |
| 1f | CoaB IC50 = 15.6 µM | Discussion ¶2 |
| 1f | MIC = 25.9 µM | Results whole-cell ¶1; Results §2.4; Results §2.6; Discussion ¶2 |
| 1f | EnzChek IC50 = 24.3 µM (Mtb), 23.4 µM (human CoaB) | Results §2.5 |
| 1g, 1h | CoaB activity "tolerated" — **no numeric IC50 in prose** | Results HTS ¶1 |
| 1g, 1h | MIC > 125 µM (via the "up to 125 µM" statement) | Results whole-cell ¶1 |
| 1i | "complete loss of inhibitory activity" in the CoaB assay — **no numeric IC50 in prose** | Results HTS ¶1; Results whole-cell ¶1 |
| 1i | MIC = 6.2 µM | Results whole-cell ¶1 |
| 1i | HepG2 IC50 = 40 µM; CHI LogD > 1.5 (stated only as the exception to "all except 1i having CHI LogD ≤ 1.5") | Results HTS ¶2 |
| 1a–1h | HepG2 IC50 > 50 µM | Results HTS ¶2 |
| all nine | Cli ≤ 2.8 (mL/min)/g; kinetic solubility between 55 and 219 µM (range only, not per compound) | Results HTS ¶2 |
| 2b | CoaB IC50 = 0.08 µM; MIC > 250 µM (both cited to ref 41) | Results §2.6 ¶1 |

**Cannot be recovered from prose, and therefore exist only inside the Table 1 images:** the
numeric CoaB IC50 of 1b, 1c, 1d, 1e, 1g, 1h and 1i; the per-compound HepG2 IC50, Cli, kinetic
solubility and CHI LogD for every compound (prose gives ranges and exceptions only, and Table 1
marks some cells "ND = not determined"); and the R1/R2 substituent structures, which are drawn
structures rather than text in any case. Compound identities themselves are text: the synthesis
section names each analogue in full (1b–1i; 1a is the screening hit) with yields, 1H NMR and
HRMS or LRMS.

Per-compound data for 1a–1i exists **only** in Table 1 (image) plus the prose above. There is
no per-compound accumulation, permeation, efflux or metabolism measurement for any analogue
(see §3 and §7).

## 3. The intracellular accumulation experiment (Figure S7)

**Compounds: 1f and 2b, and only those two.** Figure S7 has exactly two panels — (a) compound
1f (MW = 357.81 g/mol) and (b) 2b (MW = 286.24 g/mol). **Confirmed explicitly: the accumulation
experiment was NOT run on 1a, 1b, 1c, 1d, 1e, 1g or 1h.** Those seven compounds appear nowhere
in the uptake methods, in Figure S7, in Figure S8, or in any accumulation statement in the body
text; the body text's only accumulation comparison is 1f vs 2b.

**Filter-culture method** (Methods, *Mycobacterium tuberculosis Compound Uptake*; "as
previously described", refs 41 and 53): Mtb grown on nylon Durapore 0.22 µm membrane filters
placed on top of Middlebrook 7H11 agar plates supplemented with 0.2% glycerol and 10% OADC for
1 week at 37 °C to expand biomass. The membranes were then placed atop a reservoir containing
Middlebrook 7H9 broth with or without compound, so that the underside of the bacteria-laden
filter was in direct contact with the medium. After 24 h at 37 °C — "which we previously
determined to be pre-lethal for most frontline drugs" (ref 11) — filters were plunged into
40:40:20 methanol:acetonitrile:water precooled to −20 °C and cells were lysed with a bead
beater. Lysates were mixed with an equal volume of 50% acetonitrile and 0.2% formic acid, and
drug accumulation was measured by mass spectrometry in **both positive and negative ion mode**
(ref 53). Exposure concentrations, from the Figure S7 legend: **5 µM and 50 µM** of each
compound.

**Standard-addition quantification:** "Relative drug levels were quantified by comparison with
standard curves generated from bacterial lysates spiked with compound, using the method of
standard addition" (cited to Harris, *Quantitative Chemical Analysis*, 6th ed., ref 67).
"Internal standards were routinely included with each sample run, and data were additionally
normalized to sample protein biomass." The identity, concentration and recovery of those
internal standards are not stated.

**Ionisation-efficiency control (Figure S8):** standard curves of 1f and 2b spiked into
bacterial extracts, run to exclude the possibility that the observed difference in intracellular
abundance was due to inherent or bacterially induced differences in ionisation efficiency
between the two compounds. SI caption: "Standard curves showing comparable ionisation
efficiencies of compounds 1f and 2b spiked into bacterial extracts. Internal standards are
routinely included with each sample run, and data are normalised to sample protein biomass."
The axes of Figure S8 are concentration (µM) against ion counts. **No numeric slope,
sensitivity ratio, R², or limit of detection is reported anywhere.** The conclusion "comparable"
is asserted in the caption and body text, not quantified.

**Do numeric accumulation values exist anywhere?** **No.** Figure S7 is a pair of
chromatogram images inside the SI PDF; its caption states "X-axis is time (minutes), Y-axis is
ion counts", so the only quantities are unlabelled-in-text ion-count traces inside an image.
There is no accumulation table, no µM or pmol/mg intracellular concentration, no
cell-associated percentage of applied dose, no accumulation ratio, and no statistical
comparison. Outside the image, the entire result is the comparative statement in the body text
(Results, *Metabolic Consequences of Exposure of Mtb to Compound 1f*, final paragraph): both
compounds accumulated "in a dose-dependent manner, but the intracellular abundance of **1f**
was substantially greater than **2b** at both concentrations tested (Figure S7)". The word
"substantially" is the whole of the effect size. **n = 3 independent replicates** (Figure S7
caption); no dispersion is shown or stated, and the panels are described as "representative".

## 4. The *coaBC* Tet-OFF hypomorph experiment

- **Strain:** *coaBC* Tet-OFF hypomorph constructed as previously described (ref 33), derived
  from the virulent, PDIM-producing parental strain Mtb H37RvMA (ref 42). *coaBC* expression is
  under a tetracycline-regulated promoter, so progressive transcriptional silencing occurs on
  addition of increasing concentrations of the inducer anhydrotetracycline (ATc). All
  ATc-containing cultures were incubated in the dark.
- **Design:** checkerboard assays — the parent compound and all analogues against the hypomorph
  across an ATc gradient, read out as MIC shift. All nine analogues were screened.
- **ATc range tested:** the methods state cultures were diluted into 7H9 "containing the ATc
  inducer at concentrations up to 200 ng/mL in order to transcriptionally silence *coaBC*", and
  the Pan-rescue control was run at "maximal *coaBC* silencing (i.e., at an ATc concentration of
  200 ng/mL)". The ATc concentrations resolved in prose for the checkerboards are **0–3.2 ng/mL**
  (the range over which the hypomorph MIC equalled wild type) and **12.5 ng/mL** (the fold-shift
  point). The SI legend for Figure S2 lists the series **ATc0, ATc1.6, ATc3.2, ATc6.3, ATc12.5,
  ATc25 ng/mL** with 1f at 0–125 µM (0, 1.9, 3.9, 7.8, 15.6, 31.3, 62.5, 125 µM). The per-panel
  ATc gradient of Figure 2 itself is inside the figure image `id0c00904_0002.jpg` and is not
  stated in text beyond those values.
- **Fold shift for 1f:** "a ∼7-fold decrease in MIC in the presence of 12.5 ng/mL ATc"
  (Results, *Assessment of Target Selectivity in Mtb Using a coaBC Hypomorph*). The shifted MIC
  value itself is not given in text — only the fold change and the unshifted MIC (25.9 µM).
- **Specificity controls.** (i) **Wild-type + 1f:** "ATc had no effect on the activity of 1f
  against wild-type Mtb H37RvMA (Figure 2c)", whose MIC equalled the hypomorph's at 0–3.2 ng/mL
  ATc; separately, Figure S2 shows no ATc effect on wild-type susceptibility to 1f at low cell
  density (OD600 = 0.2). (ii) **Rifampicin and isoniazid against the hypomorph:** "ATc did not
  render the *coaBC* hypomorph more susceptible to the first-line antitubercular drugs
  rifampicin and isoniazid (Figure 2d,e) whose mechanisms of action are unrelated to CoA
  biosynthesis or utilization." No RIF or INH concentration or MIC is stated in the text; those
  axes are inside `id0c00904_0002.jpg`. (iii) **1i**, which lacks biochemical CoaB activity,
  showed no hypersensitisation (Figure 2a) — stated as the expected negative.
- **Concentration ceiling the negatives were read at:** "The presence of ATc had no discernible
  effect on the potency of 8 of the 9 compounds against the *coaBC* hypomorph at **inhibitor
  concentrations up to 125 µM**." The same 125 µM ceiling bounds the whole-cell MIC screen
  ("none of the compounds displayed whole-cell activity against replicating Mtb at
  concentrations up to 125 µM") and the PantS-rescue discrepancy ("the highest concentration of
  1f tested (125 µM)").
- **Caveat the authors attach to the strain:** because Mtb hypomorphs tend to acquire suppressor
  mutations that abrogate ATc responsiveness (ref 44), the hypomorph was grown to a lower cell
  density than the wild-type comparator for the MIC assays in Figure 2 — which is the reason the
  inoculum-effect experiment in E9 exists.

## 5. The three conclusion statements, verbatim

**(a) The 1f success.** Discussion, paragraph 2:

> "Limited exploration around compound **1a** led to the identification of an analogue, **1f**,
> which showed similar activity against the enzyme (IC50 = 15.6 μM) but displayed modest
> whole-cell inhibitory activity against Mtb (MIC = 25.9 μM). Importantly, the observed
> ATc-dependent hypersensitization of a *coaBC* hypomorph to this compound suggested that it
> engages CoaBC in whole Mtb cells. This conclusion is supported by two further lines of
> evidence: first, supplementation of the culture medium with PantS, which specifically enables
> CoaBC bypass, rescued Mtb from **1f** toxicity, thus establishing a direct link between CoaBC
> engagement and growth inhibition. Second, **1f** elicited a metabolomic profile with
> distinctive features consistent with CoA pathway disruption and reminiscent of that observed
> upon transcriptional silencing of *coaBC*, as evidenced by accumulation of dephospho-CoA and
> dose-dependent depletion of the thioesters, propionyl-, succinyl-, and malonyl-CoA, which are
> involved in multiple cellular processes."

Also Results, *Confirmation of the Target Selectivity of Compound 1f* (§2.4), paragraph 2,
final sentence:

> "Taken together with the ATc dose-dependent hypersensitization of the *coaBC* hypomorph, these
> results support the conclusion that the antibacterial activity of **1f** is mediated through
> inhibition of CoaBC."

**(b) The 2b failure.** Results, *Metabolic Consequences of Exposure of Mtb to Compound 1f*
(§2.6), final paragraph, final sentence:

> "It is therefore reasonable to conclude that the comparatively low intracellular level to
> which compound **2b** accumulates in Mtb over 24 h is sufficient to induce metabolomic
> perturbations but does not reach the threshold level required to manifest in a growth
> phenotype through inhibition of CoaBC."

The preceding sentence in the same paragraph carries the attribution:

> "The comparable ionization efficiencies observed for both compounds (Figure S8) further
> support our observation that the intracellular abundances of these compounds vary
> substantially, corroborating our previous observation that the phenotypic divergence between
> these compounds is likely due to the rapid biotransformation of **2b**."

**(c) The attribution for 1a–1e, 1g, 1h.** Results, *Assessment of Target Selectivity in Mtb
Using a coaBC Hypomorph* (§2.3), single paragraph:

> "While the lack of hypersensitization of the hypomorph in the case of compound **1i**
> (Figure 2a) is expected given its lack of biochemical activity against CoaB, the lack of
> hypersensitization of the hypomorph to **1a**–**1e**, **1g**, and **1h** suggests that the
> inability of these compounds to inhibit growth of Mtb is likely attributable to compound
> permeation, efflux, and/or metabolism."

That sentence is the paper's entire account of why those seven compounds fail. The
corresponding general statement is Discussion, paragraph 4, first sentence:

> "The lack of correlation between CoaBC inhibition and whole-cell activity observed for the
> other compounds investigated in this study provides yet another example of the profound
> challenges of target-based TB drug discovery."

## 6. The two conceded limitations, verbatim, plus the human-CoaB selectivity statement

**(a) Genetic-vs-chemical surrogate caveat.** Discussion, paragraph 2, final sentence:

> "However, unlike transcriptional silencing of *coaBC* for 3 days, exposure of Mtb to **1f**
> for 24 h had no discernible impact on the level of CoA. While this may reflect the longevity
> of this cofactor, it is worth noting that genetic inhibition of a target (via its depletion
> within the cell) is an imperfect surrogate for chemical inhibition of that target, which
> complicates direct comparison of the metabolic consequences of transcriptional silencing vs.
> drug treatment."

**(b) The unpredicted metabolite result.** Discussion, paragraph 3, first sentence and final
sentence:

> "As noted above, the substantial accumulation of dephospho-CoA and lack of accumulation of PPA
> following exposure of Mtb to compounds **1f** and **2b** as well as in response to *coaBC*
> silencing were not readily predicted, consistent with our assertion that the impact of CoaBC
> inhibition is more complex than alteration of its specific substrate and product levels alone."

> "Importantly, however, despite the induction of these unpredictable metabolomic alterations,
> the comparable signatures observed following exposure of Mtb to **1f** or **2b** and upon
> transcriptional silencing of *coaBC* provide further evidence in support of the target
> selectivity of these compounds."

The same paragraph states: "Together, these observations suggest that the regulatory mechanisms
mediating CoA biosynthesis in Mtb are complex and incompletely understood", and offers the
CTP/CoaE account explicitly as speculation ("it is interesting to speculate that…",
"This hypothesis is further supported by…").

**(c) Human CoaB selectivity.** Results §2.5:

> "To evaluate the selectivity of compound **1f**, the Mtb enzyme was substituted with human
> CoaB in the EnzChek coupled enzyme assay. A very similar dose–response profile was observed
> with an IC50 value of 23.4 μM, suggesting poor selectivity of this compound for the Mtb
> enzyme (Figure 3b)."

And Discussion, paragraph 4:

> "Although **1f** lacks selectivity with respect to the human enzyme, ongoing efforts to
> exploit additional chemical properties of these molecules are underway, with the aim of
> identifying compounds that not only show selectivity for Mtb CoaB but also demonstrate more
> potent inhibition of biochemical and phenotypic activity."

## 7. Permeation, efflux and intrabacterial metabolism: everything the paper says

Counts are over the article text excluding the reference list (abstract, body, figure and table
captions, methods, SI-availability statement, acknowledgements, author contributions,
glossary), and separately over the SI PDF's text layer. Reference-list hits are listed only
where they exist, since they are paper titles, not claims.

| Term | Article (excl. references) | SI | Where |
| --- | --- | --- | --- |
| "permeability" | 1 | 0 | Introduction, final paragraph: prior CoaB inhibitors "displayed limited whole-cell activity against Mtb due to impaired permeability/efflux and intracellular metabolism" (cited to ref 41) |
| "permeation" | 1 | 0 | Results §2.3: "likely attributable to compound permeation, efflux, and/or metabolism" |
| "efflux" | 2 | 0 | Exactly the two sentences above. Nowhere else |
| "metabolism" | 4 | 0 | Introduction ("CoA metabolism as antitubercular drug targets"; "intracellular metabolism"), Results §2.3 ("and/or metabolism"), Discussion ¶4 ("penetrate Mtb, evade metabolism, and engage its cellular target") |
| "metabolic" | 5 | 0 | Introduction (CoA-dependent "metabolic enzymes"), Results §2.6 heading sentence ("metabolic derangement"), Discussion ¶2 ("metabolic consequences"), figure/section titles |
| "metabolite(s)" | 9 | 1 | Results §2.6 and Figure 4 caption; Discussion ¶1/¶3; SI: Figure S6 caption |
| "metabolomic(s)" | 10 | 0 | Abstract, Results §2.6, Figure 4, Discussion ¶2–3, Methods *Metabolite Extraction and Metabolomic Profiling*, author contributions |
| "biotransformation" | 1 | 0 | Results §2.6, final paragraph: "likely due to the rapid biotransformation of **2b**" (cited to refs 41, 55, 56) |
| "uptake" | 3 | 0 | Methods heading *Mycobacterium tuberculosis Compound Uptake* and its first sentence; author contributions ("compound uptake experiments") |
| "accumulat*" | 12 | 1 | 5 refer to **compound** accumulation (3 in the final paragraph of Results §2.6, 1 in Methods *Compound Uptake*, 1 in the SI-availability statement; the SI hit is Figure S7's caption); the other 7 refer to **metabolite** accumulation (dephospho-CoA, PPA), not compound accumulation |
| "intracellular" | 9 | 1 | Abstract, Introduction, Results §2.6 (compound accumulation), Discussion ¶3 (CTP pools), SI-availability statement; SI: Figure S7 caption |
| "penetrat*" | 1 | 0 | Discussion ¶4: "a compound that can penetrate Mtb, evade metabolism, and engage its cellular target" |
| "intrabacterial" | 0 | 0 | — |

**Confirmed, not refuted: none of verapamil, reserpine, piperine, CCCP / carbonyl cyanide
*m*-chlorophenylhydrazone, valinomycin, "efflux pump", "transporter", "transport", "knockout"
or "knock-out" appears anywhere** — zero occurrences in the article text (including methods),
zero in the reference list, and zero in the SI PDF. "Mutant" occurs twice, both about the
Tet-OFF system itself ("conditional knockdown mutants (hypomorphs)" and the Figure 2 legend's
definition of Tet-OFF), never about a transporter or efflux mutant, and no efflux-deficient,
permeabilised or transporter-mutant strain is used anywhere in the paper. The only strains used
are Mtb H37RvMA (wild type), the *coaBC* Tet-OFF hypomorph, the *panC* Tet-OFF hypomorph
(ref 43, for the Pan control), and *E. coli* BL21(DE3) for protein expression.

So the paper's three candidate causes for the seven inactive analogues — permeation, efflux,
metabolism — are named in **one sentence each at most, are never separated experimentally, and
are never measured for any of those seven compounds.**

## 8. Data availability, SI figure inventory, SI retrieval

- **PDB accessions:** the article text contains **no** PDB code and no deposition statement.
  The SI contains exactly two codes, both pointing at previously deposited structures used for
  illustration in Figure S5: **6TH2** (*M. smegmatis* CoaB, with CTP and calcium bound) and
  **1U7Z** (*E. coli* CoaB after PPA binding, with the 4′-phosphopantothenoyl-CMP intermediate
  bound). No structure was deposited by this paper; "A crystal structure of CoaB with **1f**
  bound could not be obtained."
- **Repository DOI / data repository:** none. The article has **no Data Availability section**
  — the string does not appear — and no accession, repository DOI, or deposited dataset of any
  kind (no MetaboLights/Metabolomics Workbench deposit for the metabolomics or uptake data).
- **Supplementary data files:** one file only, `id0c00904_si_001.pdf`, declared as
  "(PDF)" in the Supporting Information Available statement; the ACS/figshare record for it is
  doi:10.1021/acsinfecdis.0c00904.s001 (figshare article 14531741). There are **no machine-
  readable supplementary data files** — no CSV, XLSX, raw MS data, or dose-response source data.
- **SI retrieval: successful.** The PDF was downloaded and read; its text layer carries the
  figure captions (quoted above) and the stray axis labels, while every data panel is an
  embedded image. Page/image inventory: p1 title page; p2 Figures S1–S2 (1 image); p3
  Figures S3–S4 (1 image); p4 Figure S5 (4 images); p5 Figure S6 (6 images); p6 Figure S7
  (2 images); p7 Figure S8 (0 embedded images, vector plot).
- **SI figures that exist** (8, as the title page declares; the body text references all of
  them):
  - **S1** — effect of exogenous pantothenate on growth of CoaBC- and PanC-deficient Mtb
    (legend: ATc in ng/mL; Pan25 = pantothenate 25 µg/mL).
  - **S2** — ATc has no effect on susceptibility of Mtb H37RvMA to 1f at low cell density
    (OD600 = 0.2).
  - **S3** — Mtb CoaBC saturation curves fitted to Michaelis–Menten, panels (a) CTP, (b) PPA,
    (c) l-cysteine, with the fixed and varied substrate concentrations given in the caption.
  - **S4** — DSF melting profile of CoaBC: no ligand, +PPA, +CTP, +CTP/PPA.
  - **S5** — movement of the flexible loop covering the PPA binding site; residues 361–378 in
    *M. smegmatis* CoaB (a–b, PDB 6TH2) and 352–370 in *E. coli* CoaB (c–d, PDB 1U7Z). The
    page also retains a superseded draft caption numbered "Figure S3" with "P-Pan" wording in
    its text layer.
  - **S6** — impact of exposure of Mtb H37Rv to 1f and 2b on acyl-CoA species and CoA pathway
    metabolites.
  - **S7** — total intracellular accumulation of (a) 1f (MW = 357.81 g/mol) and (b) 2b
    (MW = 286.24 g/mol); 5 µM and 50 µM; x-axis time (min), y-axis ion counts; n = 3
    independent replicates.
  - **S8** — standard curves showing comparable ionisation efficiencies of 1f and 2b spiked
    into bacterial extracts; x-axis concentration (µM), y-axis ion counts. No n stated.
- **Article figure images** (for the record, since several values live only inside them):
  Figure 1 `id0c00904_0001.jpg`, Figure 2 `id0c00904_0002.jpg`, Figure 3 `id0c00904_0003.jpg`,
  Figure 4 `id0c00904_0004.jpg`, Table 1 `id0c00904_0005.jpg` + `id0c00904_0006.jpg`, and
  `id0c00904_0007.jpg` (compound structures of 1f and 2b as shown with Figure 4).
  **Table 2 is the only machine-readable table in the paper.**
- **Funding/competing interests, for provenance:** Gates Foundation TB Drug Accelerator
  (OPP1024021 HIT-TB, OPP1158806 SHORTEN-TB), SAMRC, NRF South Africa, HHMI, NIAID intramural,
  SNSF, EU H2020 MSCA, Wellcome Trust, MRC-CinC MC_PC_14099. "The authors declare no competing
  financial interest."

## What this paper cannot support

Questions a scenario built only on this paper could **not** ask, because the measurement does
not exist in it:

1. **Why any of 1a–1e, 1g, 1h fails in whole cells.** Permeation, efflux and metabolism are
   named once, together, as an undifferentiated "and/or" in a single sentence. For those seven
   compounds there is **no** accumulation measurement, no efflux measurement, no metabolite
   identification and no permeability measurement. Nothing discriminates the three causes for
   any of them, and nothing even establishes that one of the three is the cause.
2. **How much 1f or 2b accumulates.** NOT MEASURED as a quantity: no intracellular
   concentration, no pmol/mg protein, no percentage of applied dose, no accumulation ratio, no
   1f:2b fold difference. The only statement is "substantially greater", and the underlying
   data are ion-count traces inside the Figure S7 image.
3. **Whether 2b's intracellular level is below a threshold.** The "threshold level required to
   manifest in a growth phenotype" is never defined, measured, or compared with the enzyme IC50.
   No free-cytoplasmic-concentration estimate exists for either compound, and the filter-culture
   readout is cell-associated compound, not free intracellular drug.
4. **Whether 2b is metabolised in this paper's experiments.** The rapid-biotransformation
   attribution is carried entirely by citation (refs 41, 55, 56). No metabolite of 2b (or 1f) is
   detected, identified or quantified here; no parent-vs-metabolite speciation was done, despite
   the LC-MS platform being in hand.
5. **Any efflux question.** No efflux inhibitor (verapamil, reserpine, piperine, CCCP,
   valinomycin), no efflux-deficient or transporter-mutant strain, and no bacteria-free filter
   control appear anywhere. Efflux is named twice and tested zero times.
6. **Any permeability question.** No logP/logD-vs-accumulation analysis beyond CHI LogD values
   in a table image, no liposome or membrane-partition assay, no permeabilised-cell arm.
7. **Target vulnerability / occupancy for CoaBC.** Not measured here. The paper notes PanC and
   PanK failures "might be explained, at least in part, by the relative invulnerability of the
   corresponding targets", but runs no vulnerability titration, no occupancy estimate, and no
   quantitative link between fractional CoaBC inhibition and growth inhibition.
8. **Resistance genetics / on-target confirmation by mutation.** No spontaneous-resistant
   mutants were raised against 1f, no target mutation was identified, and no overexpression arm
   exists. On-target evidence is the hypomorph shift, PantS bypass rescue, and the metabolomic
   signature only.
9. **Structural basis of 1f binding.** "A crystal structure of CoaB with 1f bound could not be
   obtained." The binding-mode account is inference from kinetics plus DSF plus previously
   deposited structures (6TH2, 1U7Z); no co-structure, no mutagenesis of the proposed site, and
   no direct binding affinity (no ITC, SPR or Kd).
10. **Potency of most analogues to any stated precision outside Table 1's image**, and the per
    compound ADME values (HepG2, Cli, solubility, CHI LogD), which exist only in that image and
    which Table 1 marks "ND" for some compounds — i.e. not determined at all for those.
11. **Replicate-level or statistical claims for the screens.** No n is stated for the primary
    HTS, the counter-screen, the Table 1 IC50s, the pharmacological profiling, Figure S1,
    Figure S2 or Figure S8; no p-values, confidence intervals or error bars are reported
    anywhere in the paper, and the triplicate data that are declared are labelled
    "representative". Nothing supports a question about statistical significance of any
    difference, including the 1f-vs-2b accumulation difference.
12. **Dose-, time- or kill-kinetics questions.** Accumulation and metabolomics were measured at
    a single 24 h time point at 5 µM and 50 µM; no time course, no MBC, no CFU kill curve, no
    intracellular (macrophage) or in vivo efficacy experiment was done in this paper.
13. **CoA-level questions.** Exposure to 1f and 2b produced "no detectable change in the level
    of CoA" at 24 h; CoA depletion at day 3 is from the earlier silencing work (ref 33), so no
    chemical-inhibition CoA-depletion measurement exists here, and the authors themselves flag
    the genetic-vs-chemical comparison as an imperfect surrogate.
14. **Selectivity beyond human CoaB.** One human orthologue IC50 (23.4 µM) and HepG2
    cytotoxicity; no selectivity panel, no other species, no mammalian-cell CoA measurement.
