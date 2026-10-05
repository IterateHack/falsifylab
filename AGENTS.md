# Project verification

- Install development and runner dependencies in an isolated virtual environment: `python -m pip install -r requirements-dev.txt -r runner/requirements.txt`.
- Run the full offline suite from the repository root: `python -m pytest -q`. It includes the agent, runner, re-audit, and golden auditor tests; live API calls are not needed.
- On Windows, the virtual environment interpreter is `.venv/Scripts/python.exe`.
- The pinned Anthropic SDK 1.11.0 removed the `temperature` keyword. For API models that still support sampling parameters, use the SDK's `extra_body` transport; omit those parameters for Sonnet 5 models.
- Keep provider-refusal episode outcomes separate from audited scientific verdicts. Preserve usage and partial trajectories, and exclude provider refusals from science metrics during collection and re-audit.
- Every PR that fixes a verifier bug (auditor rule, control matcher, scorer, sandbox) must add the exact exposing case as a test under `tests/regression/` and a row to `docs/VERIFIER-REGRESSIONS.md`. A regression test for a fix that is not yet on main is marked `pytest.mark.xfail(strict=True, reason="fixed by #NN, not merged")`; whoever merges the fix removes the marker.
- A PR that changes the test count re-measures every count it makes stale, in the same PR. Do not add bare totals ("N tests pass") to docs; keep a number only where it is diagnostic, such as the count that fails with numpy only in the user site.
