# Batch results

Each episode is a replicate. `job.seed`, `job.effective_seed`, and `job.repeat` label the replicate and select environment randomness only; `sampling.seed_applied_to_model` is false, so no seed is sent to the model and model output is not reproducible from a seed.

## Spend caps

- Per-episode cap: $0.25 (enforced inside each worker).
- Batch collection cap: $1.25 (checked after returned results are collected).
- Concurrent Modal workers do not share an in-flight ledger. A batch's hard arithmetic bound is per-episode cap × paid episodes in that batch; split waves must sum their separate batch bounds.

## Excluded outcomes

`provider_refusal` and `spend_cap_stop` retain charged token usage, the model call log, and any partial trajectory, but have no science metrics and are excluded from scored rates. `PARSE_FAILURE` rows are also excluded from science metrics; `HARNESS_ERROR` rows retain the worker failure and no trajectory.
