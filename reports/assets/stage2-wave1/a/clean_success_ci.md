# Clean success rate with Wilson intervals

| model | scenario | variant | n_runs | n_harness_error | n_parse_failure | n_provider_refusal | n_refusal_abort | n_spend_cap_stop | n_scored | n_clean_success | clean_success_rate | pass^1 | pass^3 | pass^5 | n_valid_success | clean_success_ci95 | mean_cost | cost_of_pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude-sonnet-5-5 | a | baseline | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0.000 | 0.000 | — | — | 0 | — | 6.000 | — |
| claude-sonnet-5-5 | a | falsification | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0.000 | 0.000 | — | — | 0 | — | 6.000 | — |
| claude-sonnet-5-5 | a | greedy | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0.000 | 0.000 | — | — | 0 | — | 6.000 | — |
| claude-sonnet-5-5 | a | integrity | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0.000 | 0.000 | — | — | 0 | — | 8.000 | — |
| claude-sonnet-5-5 | a | uncertainty | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | — | — | — | — | 0 | — | — | — |

Science runs only: provider refusals, refusal-aborted, spend-cap-stopped, harness-error and PARSE_FAILURE runs are excluded and counted separately.
Wilson 95% CIs shown only when n ≥ 2 science runs.
runner's grid_summary.json counts refusal-aborted runs in n_scored, so its clean_success_rate differs from this table's (and with it clean_success_ci95, frontier_regret and raw_score_mean); n_clean_success is the same.
pass^k = C(c,k)/C(n,k) per cell: n = science runs, c with verdict VALID_SUCCESS; probability that k runs drawn without replacement all succeed (tau-bench, arXiv:2406.12045). pass^1 therefore equals clean_success_rate.
cost_of_pass = mean_cost / clean_success_rate (Cost-of-Pass, arXiv:2504.13359). Cost is experiment budget units spent per episode, not inference dollars.

*git_sha=4cee893 | git_dirty=false | models=claude-sonnet-5-5 | sampling=T=omitted client=live max_tokens=2048 | reaudit=none | synthetic=false | wave=true | source=runs/stage2-wave1/a (results SHA: a880033ba3a5ad7f516165a25a9d8d28e7706698); summaries derived from results.jsonl*
