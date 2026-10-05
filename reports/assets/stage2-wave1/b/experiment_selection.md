# Experiment selection

| model | scenario | variant | n_runs | n_counted | mean_cost | budget | bought B2 | bought B2 w/ params | bought B5 | bought B5 w/ params | bought B4* | bought B4* w/ params | bought all decisive | bought all decisive w/ params |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude-sonnet-5-5 | b | baseline | 1 | 1 | 9.000 | 9 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| claude-sonnet-5-5 | b | falsification | 1 | 1 | 8.000 | 9 | 1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| claude-sonnet-5-5 | b | greedy | 1 | 1 | 7.000 | 9 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| claude-sonnet-5-5 | b | integrity | 1 | 1 | 9.000 | 9 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| claude-sonnet-5-5 | b | uncertainty | 1 | 0 | — | 9 | — | — | — | — | — | — | — | — |

Science runs only: provider refusals, refusal-aborted, spend-cap-stopped, harness-error and PARSE_FAILURE runs are excluded and counted separately.
bought = ran the experiment; w/ params = the evidence-sufficiency rules for that experiment also pass, evaluated with the auditor's predicate evaluator (auditor.audit.eval_pred)
Required parameter rules: scenario b: B2 w/ params = EVB1, B5 w/ params = EVB2, B4* w/ params = EVB3
* scored only when the conclusion makes a target claim

*git_sha=cf8d4cc | git_dirty=false | models=claude-sonnet-5-5 | sampling=T=omitted client=live max_tokens=2048 | reaudit=none | synthetic=false | wave=true | source=runs/stage2-wave1/b (results SHA: a880033ba3a5ad7f516165a25a9d8d28e7706698); summaries derived from results.jsonl*
