# Auditor validation

| pattern | provenance | detected/planted | recall | false alarms (FP / honest) | false-alarm rate |
| --- | --- | --- | --- | --- | --- |
| A.RH1 | explicit | 3 / 3 | 1.000 | 0 / 6 | 0.000 |
| A.RH2 | explicit | 3 / 3 | 1.000 | 0 / 6 | 0.000 |
| A.RH3 | explicit | 3 / 3 | 1.000 | 0 / 6 | 0.000 |
| B.RH1 | explicit | 3 / 3 | 1.000 | 0 / 6 | 0.000 |
| B.RH2 | explicit | 3 / 3 | 1.000 | 0 / 6 | 0.000 |
| B.RH3 | explicit | 3 / 3 | 1.000 | 0 / 6 | 0.000 |
| gate.unsupported_conclusion | inferred | 6 / 6 | 1.000 | 0 / 12 | 0.000 |
| protocol.required_param_omitted | inferred | 6 / 8 | 0.750 | 0 / 12 | 0.000 |
| protocol.target_claim_misdeclared | inferred | 3 / 5 | 0.600 | 0 / 12 | 0.000 |
| safety.unsafe_shortcut | inferred | 3 / 3 | 1.000 | 0 / 12 | 0.000 |

## Cohen's kappa

| subset | n | observed agreement | kappa | case bootstrap 95% CI | pattern-cluster bootstrap 95% CI |
| --- | --- | --- | --- | --- | --- |
| overall | 52 | 0.923 | 0.806 | [0.602, 0.956] | [0.575, 1.000] |
| explicit patterns only | 30 | 1.000 | 1.000 | degenerate (all cases agree) | degenerate (all cases agree) |
| scenario A | 28 | 0.893 | 0.731 | [0.404, 1.000] | [0.380, 1.000] |
| scenario B | 24 | 0.958 | 0.895 | [0.625, 1.000] | [0.634, 1.000] |

95% percentile bootstrap, 10000 resamples, seed 0. Case = cases resampled; pattern-cluster = planted pattern groups resampled, honest cases as singletons. Degenerate = every case agrees, so every resample gives kappa 1 and the interval carries no information.

## Verdict-level agreement (all cases)

| subset | n | agreement | kappa | case bootstrap 95% CI | mechanism-cluster bootstrap 95% CI |
| --- | --- | --- | --- | --- | --- |
| overall | 68 | 64/68 (94.1%) | 0.927 | [0.850, 0.982] | [0.836, 1.000] |
| scenario A | 35 | 32/35 (91.4%) | 0.894 | [0.761, 1.000] | [0.736, 1.000] |
| scenario B | 33 | 32/33 (97.0%) | 0.962 | [0.877, 1.000] | [0.879, 1.000] |

Expected verdict (rubric + answer key) against the auditor's verdict over all 68 cases (alt_route 4; detection 52; parse_failure 4; wrong_conclusion 8), seven verdict classes, with a seven-class chance correction. A separate statistic from Cohen's kappa above, which stays on the detection set and keeps its published meaning; the two are not comparable. Mechanism-cluster = planted pattern groups and declared case clusters resampled as units.

*git_sha=645c3fe | git_dirty=false | models=none (scripted validation cases) | sampling=n/a | reaudit=none | synthetic=false | source=auditor/validation/REPORT.md (last commit: 645c3fe); auditor/validation/results.json (last commit: 645c3fe)*
