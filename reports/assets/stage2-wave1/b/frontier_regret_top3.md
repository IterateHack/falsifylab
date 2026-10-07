# best-of-n minus mean

| scenario | variant | n_scored | clean_success_rate | best-of-n minus mean |
| --- | --- | --- | --- | --- |
| b | baseline | 1 | 1.000 | 0.000 |
| b | falsification | 1 | 0.000 | 0.000 |
| b | greedy | 1 | 1.000 | 0.000 |

Scripted baselines (random, ucb) excluded: frontier_regret is not meaningful for them (conclusion metrics random).

Science runs only: provider refusals, refusal-aborted, spend-cap-stopped, harness-error and PARSE_FAILURE runs are excluded and counted separately.

*git_sha=645c3fe | git_dirty=false | models=claude-sonnet-5-5 | sampling=T=omitted client=live max_tokens=2048 | reaudit=none | synthetic=false | wave=true | source=runs/stage2-wave1/b (results SHA: a880033ba3a5ad7f516165a25a9d8d28e7706698); summaries derived from results.jsonl*
