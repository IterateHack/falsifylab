# GLP-1R curriculum: scientific provenance

This file records what the GLP-1R curriculum's science rests on, and how its
answer keys were produced. Dataset provenance (what was fetched, computed,
derived, reused or transcribed, and from where) is in
[`data/PROVENANCE.json`](data/PROVENANCE.json) and is not repeated here.

## References and answer keys

Each experiment's lesson card (`lessons/expN.md`) and `teaching.papers` entry
cite the reference below. The references for experiments 1-3, 5 and 6 are
verified against Europe PMC (2026-10-03) in
[`lab/docs/references.md`](../../docs/references.md), which also records two
corrections to the original plan. Experiment 4 cites the ChEMBL database paper,
which is not in that verification table.

| Exp | Reference | Answer key, and its type |
|---|---|---|
| 1 | Minikel et al. *Nature* 2024. doi:10.1038/s41586-024-07316-0 | Database labels: a target counts as validated if Open Targets lists a drug at stage `APPROVAL` or `PHASE_4` (`private/exp1.json`). Depends on the Open Targets release. |
| 2 | Zhang et al. *Cell Rep* 2021. doi:10.1016/j.celrep.2021.109374 | Computed from structure: semaglutide contact residues recomputed from PDB 7KI0 at 4.0 A. |
| 3 | Lau et al. *J Med Chem* 2015. doi:10.1021/acs.jmedchem.5b00726 | Duration-class ordering plus a mechanism rubric. The half-lives are transcribed from literature and labels, are pending a human sign-off, and are not scored. |
| 4 | Gaulton et al. *Nucleic Acids Res* 2017. doi:10.1093/nar/gkw1074 (ChEMBL) | Consensus pEC50 for 14 molecules, computed from ChEMBL EC50 records for CHEMBL1784. The dose-response points are simulated from those potencies. |
| 5 | Kawai et al. *PNAS* 2020. doi:10.1073/pnas.2014879117 | Computed from sequence: residue 33 of human, mouse, rat and macaque GLP1R (UniProt), plus a rubric with a penalty for the rodent trap. |
| 6 | Wharton et al. *N Engl J Med* 2025. doi:10.1056/NEJMoa2511774 (ATTAIN-1) | **A phase 3 clinical trial endpoint.** See below. |

## The capstone's answer key is a phase 3 clinical trial endpoint

Experiment 6 has no data: its spec lists no datasets, and `audit/exp6.yaml`
says the sandbox is empty by design. Its answer key is the result of the
ATTAIN-1 phase 3 trial. In the words of its lesson card, an oral non-peptide
GLP-1R agonist "produces clinically meaningful weight reduction in people with
obesity". That is a phase 3 clinical trial endpoint: a published outcome in
humans, not something the agent measures or derives from data in the lab.

`scorers/exp6.py` scores the answer with a phrase-matched rubric. Each item in
`private/exp6.json` is a list of phrases; for example, the `verdict` item is
earned by phrases such as "supported" or "confirmed". The file's `scoring` field
reads "Rubric against the ATTAIN-1 phase 3 result and the five earlier lessons."

## How this differs from scenario A's answer key

Scenario A's answer key went through two documented steps. Scenario A is the
PptT / *M. tuberculosis* question, from Singh et al., *Sci. Adv.* 10:eadj6406, 2024
(see the [root README](../../../README.md)).

- [`docs/scenario-a-design-history.md`](../../../docs/scenario-a-design-history.md)
  records the defects in the first draft, how each was fixed, and the source
  verification.
- [`docs/research/scenario-a-gold-check.md`](../../../docs/research/scenario-a-gold-check.md)
  is an independent literature check of the key. The root README lists its
  findings as Known limitations.

This curriculum's answer keys did not go through that process. The repository
records reference verification for them (`lab/docs/references.md`) and dataset
provenance (`data/PROVENANCE.json`). No document in the repository checks them
against the literature the way `scenario-a-gold-check.md` checks scenario A's.

## Contamination

- The lab README's Caveats say: "Pretraining leakage is real. These are famous
  results."
- [`lab/docs/evaluation-plan.md`](../../docs/evaluation-plan.md) records that
  there is no held-out data: every run sees the same experiments, data and
  answers, and the cards and rubrics derive from the same sources that define
  the ground truth.
- The capstone's cold-answer score is **unmeasured on main**. This is the score
  for the capstone answered with no data, tools or lessons. The `cold` arm
  exists to measure it (`engine/cold.py`, `--arm cold`). A figure is reported
  only in open PR #43, and the evaluation plan says to reproduce it in this
  tree before citing it.

## What this curriculum is for

This curriculum exercises the lab's engine and protocol. No result from it is
offered as evidence about the PptT question.
