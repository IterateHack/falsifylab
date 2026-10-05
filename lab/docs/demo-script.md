# Demo script (~3 minutes)

Setup, before you present:

```bash
./.venv/bin/python -m uvicorn api.main:app --port 8000
# open http://127.0.0.1:8000  - the "demo" replay is selected by default
```

Leave **replay** selected. It plays a recorded run, so the demo does not depend
on six model calls landing live. The **live** toggle is there if someone asks.

---

**1. The problem (20s).**
"Agents state conclusions with a confidence they haven't earned, and they don't
learn from structured feedback. We wanted a setup where an agent has to commit to
a prediction *before* it can look at the data, gets scored by something it can't
reach, and then gets taught - and where you can see whether the teaching stuck."

**2. The lab (15s).**
Six experiments along the bench, building a case about GLP-1R as an obesity
target, ending in whether an oral non-peptide agonist is feasible. Real data -
Open Targets, the PDB, ChEMBL, UniProt - fetched from primary sources.

**3. Click Start Experiment 1 (40s).**
The scientist walks over. Watch the speech bubble: the first thing it does is
write a prediction and a confidence. Nothing else is available until it does -
every other tool returns LOCKED. Then it starts working in the sandbox: no
network, datasets read-only.

**4. The score and the notebook (45s).**
The badge appears. Open the notebook on that station.

- Section 1 was written before any data was touched - 0.65 confidence here.
- Section 4 is the score, 0.84, filled in by the engine, not the agent.
- Section 5 is **"what I got wrong, and why I was confident anyway."**

Read a line or two of section 5 aloud. On experiment 1 it works out that it
over-weighted genetic association strength, which measures statistical power
rather than druggability.

**5. The chain (40s).**
Click **Next** through to experiment 5. Point at **"Applied lessons from"** at the
top of the page.

Experiment 5 asks which assay system to use for an oral non-peptide agonist. The
trap is reaching for a mouse model. Human GLP-1R carries Trp33; mouse and rat
carry Ser - we checked this against the UniProt sequences - so orforglipron is
essentially inactive in rodents, and a mouse experiment produces a false
negative. The agent can only see that because experiment 2 taught it the peptide
interface is 40 residues wide and Trp33 is not one of them.

**6. Calibration (25s).**
Open the **Calibration** tab. Stated confidence against actual score, per
experiment.

"Here's the finding we didn't expect. Mean score 0.90, mean calibration gap
**minus** 0.30. This scientist was *under*confident, consistently - it did better
than it said it would. Our premise was the opposite. The point is that the
notebook measures the gap whichever way it falls, and the agent's own account of
*why* it was miscalibrated is specific: on the capstone it worked out it had
priced its confidence on whether its verdict was right, when what was being
scored was whether the verdict was properly structured."

**7. Close (15s).**
"Agent code runs in Modal Sandboxes, with the scorer in a separate sandbox so the
ground truth is somewhere the agent can't reach. The curriculum is a config
folder, so the engine is designed not to depend on the curriculum. And the whole curriculum can be
built by Devin - one session per experiment, with twelve acceptance criteria and
a human reviewing every PR."

---

## If asked

**"Did the model already know this?"** Probably some of it - these are famous
results. Three defences: the scorers target data analysis rather than recall
wherever possible; the notebook has a "prior knowledge claimed" section; and
there's a control arm that runs the whole curriculum with the lesson cards
withheld (`engine.cli compare`). With one run per arm, that comparison is noisy
and the tool says so rather than overselling a number.

**"Is scoring really deterministic?"** Yes, and there's a test for it. The
computational experiments compare against ground truth recomputed from the
primary source; the reasoning ones use a weighted phrase-matching checklist. No
model grades another model.

**"What broke?"** The first real run of experiment 2 scored zero because the
agent spent all 25 tool calls parsing the mmCIF and never submitted. That's the
harness being unfair, not a finding, so budgets now reserve their last two calls
for submission. It's in the README.

---

**Optional: the audit (45s).** Open the Calibration tab of an audited run. The headline
is **clean success**, with the raw score beside it. If you have the scripted hack
(`evals/audit/`, `audit_demo_hardcoded`), show it: raw score 1.00, verdict reward hack,
clean success 0 of 1. "Outcome scoring rewards lucky science; this audits the path."
Be upfront that the process score is a proxy, validated only on scripted cases so far.
