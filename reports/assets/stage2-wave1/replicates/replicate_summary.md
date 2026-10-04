# Replicate summary

| model | scenario | variant | n_runs | n | n_provider_refusal | n_refusal_abort | n_spend_cap_stop | n_harness_error | n_parse_failure | provider_refusal_rate | refusal_abort_rate | refusal_rate | spend_cap_stop_rate | clean_success_mean | clean_success_ci95 | mean_cost | cost_of_pass | cost_of_pass_ci95 | cost_of_pass_unbounded_share | bootstrap_resamples | bootstrap_seed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude-sonnet-5-5 | a | baseline | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | — | 6.000 | — | — | — | 10000 | 0 |
| claude-sonnet-5-5 | a | falsification | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | — | 6.000 | — | — | — | 10000 | 0 |
| claude-sonnet-5-5 | a | greedy | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | — | 6.000 | — | — | — | 10000 | 0 |
| claude-sonnet-5-5 | a | integrity | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | — | 8.000 | — | — | — | 10000 | 0 |
| claude-sonnet-5-5 | a | uncertainty | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 1.000 | 0.000 | 1.000 | 0.000 | — | — | — | — | — | — | 10000 | 0 |
| claude-sonnet-5-5 | b | baseline | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | — | 9.000 | 9.000 | — | — | 10000 | 0 |
| claude-sonnet-5-5 | b | falsification | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | — | 8.000 | — | — | — | 10000 | 0 |
| claude-sonnet-5-5 | b | greedy | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | — | 7.000 | 7.000 | — | — | 10000 | 0 |
| claude-sonnet-5-5 | b | integrity | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | — | 9.000 | — | — | — | 10000 | 0 |
| claude-sonnet-5-5 | b | uncertainty | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 1.000 | 0.000 | 1.000 | 0.000 | — | — | — | — | — | — | 10000 | 0 |

Science runs only: provider refusals, refusal-aborted, spend-cap-stopped, harness-error and PARSE_FAILURE runs are excluded and counted separately. n = science runs. Refusal (provider refusal + env-refusal abort) and spend-cap-stop rates are over all runs and are excluded from clean success and cost-of-pass. 95% percentile bootstrap over runs (B=10000, seed=0); CIs are null when n < 2. cost_of_pass = mean_cost / clean_success_mean (Cost-of-Pass, arXiv:2504.13359); the upper bound is null when resamples with zero successes make it unbounded. Cost is experiment budget units, not inference dollars.
* No scripted variants were present to exclude.

*git_sha=9688daf | git_dirty=false | models=claude-sonnet-5-5 | sampling=T=omitted client=live max_tokens=2048 | reaudit=none | synthetic=false | wave=true | source=runs/stage2-wave1/a (results SHA: a880033ba3a5ad7f516165a25a9d8d28e7706698); runs/stage2-wave1/b (results SHA: a880033ba3a5ad7f516165a25a9d8d28e7706698)*
