"""The validation set is a measurement, not a spec: these tests pin its shape
and that the committed results are reproducible, never that the auditor scores
well on it. A genuine auditor miss is recorded in results.json, not a failure here."""
from collections import Counter

from auditor.validation import run_validation
from auditor.validation.cases import CASES, HONEST, PATTERNS


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_every_label_is_honest_or_a_known_pattern() -> None:
    for c in CASES:
        assert c.label == HONEST or c.label in PATTERNS, c.id
        assert c.label == HONEST or c.scenario in PATTERNS[c.label]["scenarios"], c.id


def test_at_least_three_planted_cases_per_pattern() -> None:
    counts = Counter(c.label for c in CASES)
    assert all(counts[pid] >= 3 for pid in PATTERNS), counts


def test_honest_cases_cover_both_scenarios() -> None:
    assert {c.scenario for c in CASES if c.label == HONEST} == {"a", "b"}


def test_inferred_patterns_say_why() -> None:
    for pid, p in PATTERNS.items():
        assert p["provenance"] in ("explicit", "inferred"), pid
        assert (p["provenance"] == "inferred") == bool(p.get("inference")), pid


def test_committed_results_are_current() -> None:
    assert run_validation.main(["--check"]) == 0
