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

| subset | n | observed agreement | kappa |
| --- | --- | --- | --- |
| overall | 52 | 0.920 | 0.806 |
| explicit patterns only | 30 | 1.000 | 1.000 |

*git_sha=1f44b07 | git_dirty=false | models=none (scripted validation cases) | sampling=n/a | reaudit=none | synthetic=false | source=/home/ubuntu/repos/falsifylab/auditor/validation/REPORT.md (last commit: 12c29ce)*
