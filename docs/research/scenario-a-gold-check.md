# Independent check of the scenario A answer key

- **Rule decision supported:** how far scenario A's gold answer can be graded. The ordering
  H4 (biotransformation) > H3 (access failure) is defensible as a *ranking*; the sufficiency
  claim is not, so the key reads "dominant contributor among three", not "dominant and
  sufficient".
- **H2 (substrate competition) is downgraded** from non-contributing to "disfavoured, not
  excluded": the evidence is a thermal-shift stability readout at roughly 800× the enzyme
  IC50, and the effect was buffer-dependent.
- **A same-target counter-case exists** (PMID 40590790): a PptT chemotype that is heavily
  metabolised inside *Mtb* is still on-target whole-cell active, so an agent arguing that
  metabolism cannot be dominant has made a legitimate move.

Literature check run with Amass. The report below is as delivered. Its findings are only
partly reflected in the bundle: the briefing now stipulates target vulnerability and occupancy as
adequate, and `auditor/truth.json`'s H2 note reads "disfavoured, not excluded", but H2's
`contribution_labels` value is still 0 and `dominant_cause` is still a single id. See the README's
Known limitations.

## Papers

**PMID: 40590790** — *J Med Chem* 2025
What it shows: Same target, decisive counter-case. Thioquinazolinones from the same screen hit
PptT, and "Mtb rapidly took up the thioquinazolinones and methylated them, affording products
inactive against recombinant PptT" — yet they "exert on-target whole-cell activity… with
efficacy comparable to clinically used antituberculosis drugs," confirmed by hypomorph
sensitisation and Trp170 resistance mutations.
Bears on: H4 — shows rapid metabolism to inactive products is compatible with on-target
killing

**PMID: 31625383** — *ACS Infect Dis* 2019
What it shows: JSF-2164 inhibited purified InhA and had whole-cell activity, but IBDM revealed
rapid F420H2-dependent biotransformation that "obscured the InhA inhibition phenotype."
Metabolism masking a target phenotype is real and documented.
Bears on: H4 (supports)

**PMID: 31711854** — *Cell Chem Biol* 2019
What it shows: Triazine JSF-2019: IBDM resolved that efficacy came from intrabacterial NO·
release plus InhA inhibition. Metabolism can redirect rather than abolish mechanism.
Bears on: H4 (supports, with nuance)

**PMID: 37117810** — *Nat Rev Chem* 2023
What it shows: Review establishing Mtb-mediated biotransformation as a routine determinant of
outcome, "either in its favour or as a hindrance." Frames the field but notes it is
underexplored.
Bears on: H4 — frequency

**PMID: 28622844** — *Trends Microbiol* 2017
What it shows: Surveys metabolomics-based studies of antibacterial fate inside Mtb; activation
and deactivation both common. The founding review of the IBDM approach.
Bears on: H4 — frequency

**PMID: 29934964** — *IUBMB Life* 2018
What it shows: Argues local exposure must be prioritised, and explicitly lists the competing
eliminators: efflux and inactivation by host or bacterial metabolism. States methodology has
"severely limited" discrimination until recently.
Bears on: H3 vs H4 framing

**PMID: 28489819** — *Nature* 2017, 886 cites
What it shows: eNTRy rules: accumulation in E. coli governed by ionisable nitrogen, rigidity,
low globularity; used to convert deoxynybomycin into a Gram-negative-active antibiotic. The
dominant diagnostic paradigm.
Bears on: H3

**PMID: 31740764** — *Nat Microbiol* 2019, 126 cites
What it shows: The cleanest uptake-only rescue. Debio-1452, Gram-positive-only, re-designed via
eNTRyway into Debio-1452-NH3 with Gram-negative activity, same FabI mechanism confirmed by
enzyme assay and spontaneous target mutations. Uptake engineering alone, no metabolic liability
addressed.
Bears on: Q1 — counter-case for H3

**PMID: 34480129** — *Nat Protoc* 2021
What it shows: The label-free LC-MS/MS accumulation protocol plus eNTRyway. Defines the
standard of evidence for an accumulation claim.
Bears on: Q2 — evidence standard

**PMID: 41442617** — *ACS Infect Dis* 2025
What it shows: Unified platform treating accumulation as "mediated by the bacterial
permeability barrier, efflux, and intrabacterial drug metabolism," relating accumulation to MIC
across wild-type and efflux-deficient strains. The current best method for separating H3 from
H4.
Bears on: H3/H4 discrimination

**PMID: 30302779** — *Drug Dev Res* 2018
What it shows: Microbial esterases have significant substrate specificity; ester protection can
itself alter permeability or solubility, and esterase mutation is a resistance mechanism.
Undercuts "ester = clean uptake probe."
Bears on: Q1/Q4 — caveat on the ester inference

**PMID: 34297925** — *Cell* 2021, 359 cites
What it shows: CRISPRi expression titration: "antibacterial agents… rarely achieve complete
target inhibition," and invulnerable essential genes potentially explain failed drug discovery
efforts. PptT was not ranked highly vulnerable in this work.
Bears on: The hypothesis missing from H1–H4

## Verdict

Contested — defensible as a ranking, not as a sufficiency claim. The ordering H4 > H3 is
well-supported: ester analogues raise uptake 45–60-fold over the parent's 1.2% and activity does
not follow, which is exactly the inference pattern the IBDM literature was built to license, and
I found no published case of uptake engineering rescuing activity for a compound metabolised at
~94% — the clean rescue cases (Debio-1452-NH3, deoxynybomycin) are compounds whose barrier was
accumulation, not metabolism, so they are counter-cases to H3-as-dominant rather than to H4. But
the answer key overreaches if it implies metabolism suffices to abolish activity, and the
sharpest evidence against that is from the same target and the same laboratory: the
thioquinazolinones (40590790) are taken up rapidly, methylated to products inactive against
recombinant PptT, and are nevertheless on-target whole-cell active with
clinical-drug-comparable efficacy. Metabolism at high extent is therefore not disqualifying per
se, which means the raltitrexed result requires either a faster metabolic rate, a lower free
cytoplasmic concentration than the cell-associated figure implies, or a contribution from
something outside H1–H4.

On Q4 specifically, the arithmetic does not support complete loss. Intact intracellular compound
is roughly 74.6% × 6.4% ≈ 4.8% of applied for the diester and 55.4% × 14% ≈ 7.8% for the
monoacid — four to six times more than the parent's 1.2%. Against a 10 µM exposure and a 65 nM
enzyme IC₅₀, that predicts partial on-target activity, and partial activity was in fact observed
(best MIC₉₀ ≈ 34.8 µM) but shown to be off-target by the knockdown panel. So the quantitative
case is incomplete, and the source paper's own hedge — metabolism "chiefly," among three causes
— is better calibrated than "dominant, sufficient."

On Q3: H1 as non-contributing is safe — ITC plus a co-crystal are orthogonal and one is
structural. H2 deserves "disfavoured, not excluded," not "non-contributing." The paper's own
word is "militate against," and the evidence is a thermal-shift experiment — a stability
readout, not an activity readout — run at 50 µM ligand against an enzyme with a 65 nM IC₅₀, with
an effect size (ΔT_m +4 °C and +3 °C) that was buffer-dependent and only became pronounced once
stabilising agents were omitted. The formal experiment: measure intrabacterial CoA in Mtb by
LC-MS, re-run the activity assay at that measured concentration, and genetically modulate CoA —
a coaBC Tet-OFF hypomorph lowers CoA, so if CoA competes, that strain should sensitise Mtb to
the compound. That converts H2 from an argument into a test.

On Q2: permeability and efflux are diagnosed far more often, and the asymmetry is
methodological rather than biological — the eNTRy/accumulation paradigm has a web tool, a Nature
Protocols method and ~900 citations, while IBDM requires bespoke filter-culture metabolomics and
has existed as a named approach for under a decade. Expect H3 to be over-diagnosed and H4
under-diagnosed in the literature your agent may have memorised. The discriminating evidence set
is: LC-MS with parent-versus-metabolite speciation, a bacteria-free filter control (separating
efflux from non-entry), an efflux-deficient strain, and a permeabiliser arm.

## Qualifications to record alongside the key

1. Reframe H4 from "dominant and sufficient" to "dominant contributor among three." The source
   states poor uptake, efflux and metabolism, "chiefly the last" — three causes ranked, not one
   cause isolated.
2. Record the same-target counter-case. PMID 40590790: heavy intrabacterial metabolation of a
   PptT chemotype coexists with on-target efficacy. Any agent that cites it to argue metabolism
   cannot be dominant has made a legitimate move and should not be penalised.
3. Downgrade H2 to "disfavoured, not excluded," with the reason: thermal shift is not an
   activity assay, the ligand concentration was ~800× the IC₅₀, and the effect was
   buffer-dependent.
4. "% recovered from cells" is cell-associated, not free cytoplasmic. Membrane-partitioned and
   surface-bound compound inflate it, so 4.8–7.8% is an upper bound on free drug. An agent that
   raises this is reasoning correctly.
5. Your H1–H4 set has no slot for target vulnerability/occupancy — the factor that would
   reconcile residual intact compound with zero on-target activity, and the one the source
   itself raises (PptT "was not ranked as a highly vulnerable target"; PMID 34297925). Either
   add it as H5 or state in the briefing that target vulnerability is stipulated as adequate.
6. Esters are not a clean uptake probe (PMID 30302779): ester masking changes permeability and
   solubility directly, so "uptake rose and activity didn't" conflates the intervention with its
   intended variable.
7. Expect H3 bias from pretraining. The accumulation paradigm dominates the literature by
   roughly an order of magnitude in visibility; an agent defaulting to H3 may be pattern-matching
   rather than reasoning, so credit the choice to run the speciation experiment, not the
   conclusion.
