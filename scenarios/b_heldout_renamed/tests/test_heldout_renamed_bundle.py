import json
from pathlib import Path
import re
import subprocess
import sys

from env import Env


REPO_ROOT = Path(__file__).resolve().parents[3]
BUNDLE = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "scenarios" / "b_cd5_affinity"
BANNED_TOKENS = ("MAGENTA", "NCT03081910", "Jeong", "10.1016", "omton")


def _rename_map():
    provenance = json.loads(
        (BUNDLE / "auditor" / "provenance.json").read_text(encoding="utf-8")
    )
    return tuple(
        (entry["from"], entry["to"])
        for entry in provenance["rename_map"]
    )


def _patterns():
    left_sides = [before for before, _ in _rename_map()]
    tokens = [*left_sides, *BANNED_TOKENS]
    return [
        (
            token,
            re.compile(
                r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])"
            ),
        )
        for token in tokens
    ]


def _hits(text, patterns):
    return [token for token, pattern in patterns if pattern.search(text)]


def _scan_structured(node, path, patterns, hits):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                hits.extend((f"{path}.{key}", token) for token in _hits(key, patterns))
            _scan_structured(value, f"{path}.{key}", patterns, hits)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _scan_structured(value, f"{path}[{index}]", patterns, hits)
    elif isinstance(node, str):
        hits.extend((path, token) for token in _hits(node, patterns))


def _schema_shape(value):
    if isinstance(value, dict):
        return {
            key: _schema_shape(child)
            for key, child in value.items()
            if key not in {
                "description", "enum", "values", "default", "examples", "title"
            }
        }
    if isinstance(value, list):
        return [_schema_shape(child) for child in value]
    return value


def test_generated_bundle_is_current():
    result = subprocess.run(
        [sys.executable, str(BUNDLE / "build_bundle.py"), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_agent_and_observation_text_has_no_source_names():
    patterns = _patterns()
    hits = []

    for path in sorted((BUNDLE / "agent").glob("*.json")):
        text = path.read_text(encoding="utf-8")
        hits.extend(
            (str(path.relative_to(BUNDLE)), token)
            for token in _hits(text, patterns)
        )

    observations = json.loads(
        (BUNDLE / "auditor" / "expected_observations.json").read_text(encoding="utf-8")
    )["observations"]
    for experiment_id, block in observations.items():
        for index, result in enumerate(block.get("results", [])):
            value = result.get("value")
            if isinstance(value, str):
                hits.extend(
                    (f"observations.{experiment_id}.results[{index}].value", token)
                    for token in _hits(value, patterns)
                )
        _scan_structured(
            block.get("structured", {}),
            f"observations.{experiment_id}.structured",
            patterns,
            hits,
        )

    assert not hits, "renamed bundle leaks source names:\n" + "\n".join(
        f"{path}: {token}" for path, token in hits
    )


def test_renamed_bundle_loads_in_env_with_same_menu_and_hypotheses():
    original_env = Env(base_dir=SOURCE)
    renamed_env = Env(base_dir=BUNDLE)
    original_env.reset()
    renamed_env.reset()

    original_briefing = json.loads(
        (SOURCE / "agent" / "briefing.json").read_text(encoding="utf-8")
    )
    renamed_briefing = json.loads(
        (BUNDLE / "agent" / "briefing.json").read_text(encoding="utf-8")
    )
    original_experiments = json.loads(
        (SOURCE / "agent" / "experiments.json").read_text(encoding="utf-8")
    )["experiments"]
    renamed_experiments = json.loads(
        (BUNDLE / "agent" / "experiments.json").read_text(encoding="utf-8")
    )["experiments"]
    original_hypotheses = json.loads(
        (SOURCE / "agent" / "hypotheses.json").read_text(encoding="utf-8")
    )["hypotheses"]
    renamed_hypotheses = json.loads(
        (BUNDLE / "agent" / "hypotheses.json").read_text(encoding="utf-8")
    )["hypotheses"]

    assert original_env.state.scenario_id != renamed_env.state.scenario_id
    assert original_env.state.budget_remaining == renamed_env.state.budget_remaining
    assert original_briefing["budget"] == renamed_briefing["budget"]
    assert original_env._costs == renamed_env._costs
    assert [experiment["id"] for experiment in original_experiments] == [
        experiment["id"] for experiment in renamed_experiments
    ]
    assert [experiment["cost"] for experiment in original_experiments] == [
        experiment["cost"] for experiment in renamed_experiments
    ]
    assert {
        experiment["id"]: _schema_shape(experiment["parameters"])
        for experiment in original_experiments
    } == {
        experiment["id"]: _schema_shape(experiment["parameters"])
        for experiment in renamed_experiments
    }
    assert [hypothesis["id"] for hypothesis in original_hypotheses] == [
        hypothesis["id"] for hypothesis in renamed_hypotheses
    ]
