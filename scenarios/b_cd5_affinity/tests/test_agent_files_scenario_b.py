"""Agent-facing files must carry no auditor content.

The hard rule for this bundle: agent/*.json carries no truth labels, no
informativeness, no experiment roles and no auditor notes. This applies
tests/test_prompt_audit.py's patterns to the scenario B agent files.

Three deliberate differences from that module, documented rather than silently
dropped:

1. Its SCENARIO_TERMS list is scenario A's subject-matter vocabulary (thermal,
   MIC, potency, panel, ...). Several of those words ARE scenario B's own
   agent-facing subject matter — "binding affinity panel" is the name of an
   experiment the agent must be able to read — so applying that list verbatim
   to this bundle would fail on correct content. The leak-marker half of its
   AUDIT regex (answer-naming phrases) IS applied here, being
   scenario-independent.
2. It audits agents/prompts/*.md. Those are shared across scenarios and are
   already covered by the existing test; this module audits the bundle.
3. The phrase scan runs over the AGENT VIEW — the parsed document with every
   key beginning "_" recursively removed — not over raw file text. Underscore
   keys are loader-stripped metadata by the bundle contract, so they never
   reach the agent, and each of these files opens with one stating the
   prohibition itself ("AGENT VIEW: no informativeness ratings, no roles..."). A
   raw-text scan flags that sentence as a leak, which is exactly backwards.
   Scanning the agent view tests what the agent can actually read.

The structural half — auditor-only KEYS must not appear in the agent-facing
JSON — is what actually catches an answer-key leak, and it is deliberately
checked over the WHOLE parsed tree including underscore keys, so a leak cannot
hide behind a "_" prefix.
"""
import json
import re
from pathlib import Path

import pytest

BUNDLE = Path(__file__).resolve().parents[1]
AGENT_DIR = BUNDLE / "agent"
AGENT_FILES = sorted(AGENT_DIR.glob("*.json"))

# Auditor-side keys. Any of these inside an agent-facing file is a leak: they
# name which hypotheses are true, which purchases matter, or what each
# experiment is for.
FORBIDDEN_KEYS = (
    "informativeness", "bears_on", "belief_should_move", "establishes", "reveals",
    "contribution_labels", "label_notes", "dominance_basis", "gold_answer",
    "verbatim", "evidence_class", "source_doi", "source_citation", "clone_key",
    "truth", "rubric", "role", "roles", "predicate", "breach", "trigger",
    "acceptance_tests", "reward_hack_detection", "expected_verdict",
    "expected_final_score", "is_primary_demo_exploit", "points", "structured",
)

# The scenario-independent half of tests/test_prompt_audit.py's AUDIT regex:
# phrases that name an answer rather than describe the scenario.
LEAK_PHRASES = re.compile(
    r"dominant cause is|the answer is|the correct answer|the gold answer"
    r"|\bthe trap\b|decisive|uninformative|reward hack|ground truth"
    r"|informativeness|bears_on|belief_should_move",
    re.IGNORECASE,
)

# Terms that would let the agent identify and look up the source paper, plus
# the paper's own term for the gold dominant cause (the agent-facing H3 is
# deliberately worded neutrally). "Exhaustion" is NOT here: it is the name of a
# standard assay on the menu, and PD-1/LAG-3/TOX cannot be described without
# it. Naming an assay reveals no answer; H4 is worded as chronic activation.
SOURCE_TERMS = (
    "10.1016", "omton", "jeong", "molecular therapy", "cd5", "fratricid",
    "jurkat", "nalm", "hut78", "ccrf", "rpmi8402", "h65", "magenta",
)


def _agent_view(node):
    """The document as the agent receives it: every key beginning '_' removed,
    recursively. Mirrors the loader contract stated in each file's own header."""
    if isinstance(node, dict):
        return {k: _agent_view(v) for k, v in node.items() if not k.startswith("_")}
    if isinstance(node, list):
        return [_agent_view(v) for v in node]
    return node


def _walk(node, path="$"):
    """Yield (path, key, value) for every mapping key in the parsed tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield path, k, v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_there_are_agent_files_to_audit() -> None:
    assert {p.name for p in AGENT_FILES} == {"briefing.json", "experiments.json", "hypotheses.json"}


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.name)
def test_no_auditor_keys_anywhere_in_agent_file(path: Path) -> None:
    hits = [
        f"{path.name}: {where}.{key}"
        for where, key, _ in _walk(_load(path))
        if key.lstrip("_").lower() in FORBIDDEN_KEYS
    ]
    assert not hits, "auditor content in an agent-facing file:\n" + "\n".join(hits)


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.name)
def test_no_answer_naming_phrases_in_agent_view(path: Path) -> None:
    view = json.dumps(_agent_view(_load(path)), indent=1)
    hits = []
    for n, line in enumerate(view.splitlines(), 1):
        for m in LEAK_PHRASES.finditer(line):
            hits.append(f"{path.name} (agent view) L{n}: {m.group(0)!r} in {line.strip()!r}")
    assert not hits, "answer-naming phrase visible to the agent:\n" + "\n".join(hits)


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.name)
def test_agent_file_does_not_name_the_source(path: Path) -> None:
    """The agent must not be able to look the answer up: no DOI, no title, no
    author, no cell-line name, and not the paper's term for the gold cause.
    Checked over the RAW file, not the agent view — a reader of the repo should
    not find the source named in an agent-facing file either."""
    text = path.read_text(encoding="utf-8").lower()
    hits = [t for t in SOURCE_TERMS if t in text]
    assert not hits, f"{path.name} names the source: {hits}"


def test_scenario_id_is_neutral() -> None:
    """The scenario_id reaches the agent through the briefing, so it must not
    name the antigen or the paper either."""
    sid = _load(AGENT_DIR / "briefing.json")["scenario_id"].lower()
    assert sid == "falsifylab.v0_1.binder_affinity_durability"
    assert not [t for t in SOURCE_TERMS if t in sid]


def test_experiment_descriptions_do_not_rank_the_purchases() -> None:
    """Every experiment is presented the same way: id, name, question, cost,
    readout, parameters. No extra key could hint that one purchase is the
    decisive one or that another is the trap."""
    exps = _load(AGENT_DIR / "experiments.json")["experiments"]
    allowed = {"id", "name", "question", "cost", "readout", "parameters"}

    assert len(exps) == 6
    for e in exps:
        assert set(e) <= allowed, f"{e['id']} carries unexpected keys: {set(e) - allowed}"
        assert allowed - {"parameters"} <= set(e), f"{e['id']} is missing a standard key"


def test_hypotheses_are_presented_as_independent_and_unlabelled() -> None:
    doc = _load(AGENT_DIR / "hypotheses.json")
    assert "not mutually exclusive" in doc["instruction"]
    assert [h["id"] for h in doc["hypotheses"]] == ["H1", "H2", "H3", "H4"]
    for h in doc["hypotheses"]:
        assert set(h) == {"id", "label", "claim"}


def test_underscore_keys_are_the_only_meta_and_are_stripped() -> None:
    """Guards the assumption the phrase scan rests on: the prohibition text
    lives in '_' keys, and stripping them removes it from the agent view."""
    for path in AGENT_FILES:
        raw, view = _load(path), None
        view = _agent_view(raw)
        assert "_" in raw, f"{path.name} lost its loader-stripped header"
        assert "_" not in view
        assert "AGENT VIEW" in raw["_"]
        assert "AGENT VIEW" not in json.dumps(view)
