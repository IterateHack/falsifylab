"""Prompt audit: no system prompt may steer the model toward the scenario.

A variant in agents/prompts/ may differ from the others only in epistemic
discipline ("buy the most discrimination per unit cost"). It must never name a
hypothesis, an experiment or an outcome. This test fails on any such mention so
that every future prompt is held to the same rule.

The vocabulary comes from two sources: a fixed list of scenario terms, and the
ids and names in the agent-facing bundle (agent/*.json), so a renamed or added
hypothesis or experiment is covered without editing this file. Citation
examples must use placeholder ids (EN, EX), as CONTRACT.md does. The contract's
`supports` tags are field vocabulary, so they are allowed when written as
backticked or quoted tags.
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS = sorted((REPO_ROOT / "agents" / "prompts").glob("*.md"))

# The original audit regex, kept verbatim.
AUDIT = r"metabolis|biotransform|uptake|efflux|permeab|degrad|\bH[1-4]\b|\bE[1-6]\b|dominant cause is|the answer"

# Scenario vocabulary the original regex misses: the experiments' subject
# matter and the hypotheses' names, written the way a prompt would phrase them.
SCENARIO_TERMS = [
    r"thermal", r"crystal", r"\bMIC", r"strain", r"pharmacokin", r"\bPK\b",
    r"counter-?screen", r"\bCoA\b", r"potency", r"\bIC50", r"artefact", r"artifact",
    r"substrate", r"competition", r"\baccess", r"PptT", r"engagement", r"intrabacterial",
    r"whole-cell", r"on-target", r"off-target", r"\bpanel\b",
]

CONTRACT_TAGS = ("mechanism", "target_claim", "potency", "target_engagement")


def _bundle_terms() -> list[str]:
    agent = REPO_ROOT / "agent"
    hyps = json.loads((agent / "hypotheses.json").read_text())["hypotheses"]
    exps = json.loads((agent / "experiments.json").read_text())["experiments"]
    terms = []
    for item in hyps + exps:
        terms.append(rf"\b{re.escape(item['id'])}\b")
        label = item.get("label") or item.get("name")   # hypotheses: label; experiments: name
        if label:
            terms.append(re.escape(label))
    return terms


PATTERN = re.compile("|".join([AUDIT, *SCENARIO_TERMS, *_bundle_terms()]), re.IGNORECASE)
TAG_LITERAL = re.compile(r"[`\"](?:%s)[`\"]" % "|".join(CONTRACT_TAGS))


def test_there_are_prompts_to_audit():
    assert PROMPTS, "agents/prompts/ has no .md prompts; the audit would pass vacuously"


@pytest.mark.parametrize("prompt", PROMPTS, ids=lambda p: p.name)
def test_prompt_names_no_hypothesis_experiment_or_outcome(prompt):
    hits = []
    for n, line in enumerate(prompt.read_text().splitlines(), 1):
        scrubbed = TAG_LITERAL.sub("``", line)
        for m in PATTERN.finditer(scrubbed):
            hits.append(f"{prompt.name}:{n}: {m.group(0)!r} in {line.strip()!r}")
    assert not hits, "scenario steer in a system prompt:\n" + "\n".join(hits)
