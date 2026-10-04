# Stage 2 wave 1

FROZEN auditor + prompts SHA: `a880033ba3a5ad7f516165a25a9d8d28e7706698`

Until explicitly changed, agent prompts and auditor rules are frozen at this SHA. Bug fixes only may be made between waves, and each must be logged with what changed and why.

Each row is a replicate. `sampling.seed_applied_to_model` is false for `claude-sonnet-5-5`; the job seed selects environment randomness only and does not seed or reproduce model output.

Authorized wave scope: replicate 0 only, scenario A × five LLM variants plus scenario B × five LLM variants, one invocation per scenario. Per-episode cap `$0.25`; per-invocation batch cap `$1.25`; arithmetic wave ceiling `$2.50`. No additional scenarios or renamed-entity held-out cells are included.
