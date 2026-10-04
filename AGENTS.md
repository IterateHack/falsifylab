# Project verification

- Install development and runner dependencies in an isolated virtual environment: `python -m pip install -r requirements-dev.txt -r runner/requirements.txt`.
- Run the full offline suite from the repository root: `python -m pytest -q`. It includes the agent, runner, re-audit, and golden auditor tests; live API calls are not needed.
- On Windows, the virtual environment interpreter is `.venv/Scripts/python.exe`.
- The pinned Anthropic SDK 1.11.0 removed the `temperature` keyword. For API models that still support sampling parameters, use the SDK's `extra_body` transport; omit those parameters for Sonnet 5 models.
- Keep provider-refusal episode outcomes separate from audited scientific verdicts. Preserve usage and partial trajectories, and exclude provider refusals from science metrics during collection and re-audit.
