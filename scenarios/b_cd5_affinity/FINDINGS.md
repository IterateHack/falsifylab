# Scenario B integration findings

Scenario B loads and scores through an **unmodified** `env.py`, `auditor/audit.py`,
`metrics.py` and `contract.py`. The bundle is additive: nothing outside
`scenarios/b_cd5_affinity/` is touched. The engine is scenario-generic enough to
carry a second bundle, with four limits worth recording.

## 1. `Env` selects a bundle only by explicit `base_dir`

`Env()` with no argument resolves to `Path(env.py).parent`, i.e. the repo-root
scenario A bundle. A second scenario is reachable only as `Env(base_dir=...)`.
Nothing in the engine enumerates `scenarios/`, so there is no scenario registry
and no way to ask "which scenarios exist". Not a blocker; a runner that wants to
sweep both bundles has to know both paths.

## 2. Two env mechanics are keyed to the literal experiment id `E6`

`env.py` hard-codes `if eid == "E6"` twice:

- **arm-count enforcement** against `_E6_ARMS = ("parent_diacid", "diethyl_ester",
  "monoacid")` — scenario A's compound names;
- **conditional observation withholding**, which drops result lines starting with
  `CONTROL` unless the agent declared a bacteria-free control, and rewrites
  `structured["bacteria_free_control_returned"]`.

Both are therefore unavailable to any other scenario. A scenario-B experiment
could only inherit them by being named `E6`, which would also inherit scenario
A's three compound arm names — so the mechanic is not reusable, it is
scenario-A-specific code living in a generic engine.

Consequence for this bundle, and the one real design compromise in it: scenario
B's analogue of that mechanic (PB4 — a short-term-panel claim requires the agent
to have named a high-antigen-density target line) is **audited only**. The
auditor catches it from the trajectory, which is sufficient to score, but the
environment cannot withhold the high-density result line the way it withholds
scenario A's bacteria-free control. The agent therefore sees that line whether or
not it asked for it, so scenario B tests whether the agent *declares* the right
panel, not whether it *knows* the control is needed before seeing it. Scenario A
tests the stronger thing.

Likewise `EB1` (the affinity panel is sold across clones, not per clone) is
declarative only: the arm-count refusal cannot be expressed for `B1`.

Per the hard rule this is reported, not patched. Making it generic would be a
small, contained change — move both behaviours into the bundle JSON (e.g. a
`required_arms` list and a `conditional_results` rule on the observation block)
and have `env.py` read them instead of testing the id — but it is a change to
`env.py`, so it is out of scope here.

## 3. `flags.overconfident.requires_not_ran` defaulted to `"E6"` — FIXED

`auditor/audit.py` read it as `oc.get("requires_not_ran", "E6")`. Harmless for
scenario B, whose rubric sets the key explicitly (`"B5"`), but the default was a
scenario-A id sitting in generic code: a bundle omitting the key silently inherited
scenario A's semantics rather than erroring. Silent cross-scenario inheritance
produces a wrong number with no error attached, so this one was fixed rather than
reported: a rubric that defines `flags.overconfident` must now name
`requires_not_ran`, and `audit()` raises if it does not.

## 4. A second `test_golden.py` breaks collection

pytest imports test modules by basename when there is no `__init__.py`, so
`scenarios/.../golden/test_golden.py` collides with
`auditor/tests/golden/test_golden.py`:

```
import file mismatch:
imported module 'test_golden' has this __file__ attribute: .../auditor/tests/golden/test_golden.py
which is not the same as the test file we want to collect: .../scenarios/.../test_golden.py
```

That aborts collection for **both** files. Scenario B's modules therefore use
unique basenames (`test_golden_scenario_b.py`, `test_env_scenario_b.py`,
`test_agent_files_scenario_b.py`). Any third scenario must do the same, or the
repo needs a `pytest.ini` setting `rootdir`/`importmode=importlib`.

## 5. `missing_param_is_breach` was annotation, not behaviour — FIXED

Scenario A's PR1/PR2/PR3 carry `"missing_param_is_breach": true`, but
`auditor/audit.py` has no such concept — the flag is never read. A missing
parameter only breaches if the rule's own `breach` predicate says so, and the
comparison ops (`param_lt`, `param_not_in`, ...) all return `False` on a missing
value, i.e. "no breach".

This was first written up as a latent hole. It was not latent. `Env.step`
validates action kind, conclusion state, known experiment id, the literal `E6`
arm rule and budget — it never checks an experiment's declared parameters, so an
action omitting a `"required": true` parameter is charged and recorded like any
other. Measured against scenario A's own `canonical_valid` fixture:

| E3 `atc_free_days` | verdict | protocol | final |
|---|---|---|---|
| 6 (compliant) | VALID_SUCCESS | 20 | 100.0 |
| 3 (explicit violation) | PROTOCOL_VIOLATION | 0 | 80.0 |
| omitted | VALID_SUCCESS | 20 | 100.0 |

Omitting the parameter scored identically to complying with it, so PR1 was
dodgeable by deletion. Only PR1 was exposed: PR2 wraps a text predicate in
`not`, which makes absence a breach already; PR3 tests `param_present`
directly; PR4's exemption (`missing_param_is_breach: false`) is deliberate.

Fixed in `auditor/rubric.json` by giving PR1 the absence clauses its annotation
already promised — the same shape scenario B's PB1/PB2/PB3 use:

```json
{"any": [{"not": {"param_present": {...}}}, {"param_not_in": {...}}]}
```

The fix is data, not engine. Enforcing required parameters generically in
`Env.step` is the broader repair and is still open; it was not taken tonight
because `env.py` is the demo-critical path. `audit.py` still does not read
`missing_param_is_breach`: any new rule must spell absence out in its own
predicate, and the annotation remains documentation.

## Verification

- Full suite from the repo root: all pre-existing tests still pass, plus
  scenario B's golden, env and agent-file audits.
- The three golden fixtures pin verdict, flags, reward hacks, `R_visible`,
  `final_score` and the scoring intermediates, and a parity test asserts the
  fixtures and `rubric["acceptance_tests"]` agree on all four pinned values.
- Agent-facing files are audited for auditor keys anywhere in the parsed tree,
  for answer-naming phrases, and for any mention of the source paper.
