import re


def _normalise(text):
    return " " + re.sub(r"[\W_]+", " ", str(text).lower()).strip() + " "


_BLOCKED = tuple(re.compile(pattern) for pattern in (
    r"(?<!negative )growth controls?\b",
    r"\buntreated controls?\b",
    r"\b(?:vehicle|solvent|dmso) controls?\b",
    r"\b(?:cell free supernatant|cfs)\b",
    r"\bno(?: visible)? bacterial growth\b",
))

_ACCEPTED = tuple(re.compile(pattern) for pattern in (
    r"\bsterility controls?\b",
    r"\b(?:medium|media|broth) (?:alone|only)\b",
    r"\buninoculated\b",
    r"\b(?:non inoculated|not inoculated) (?:medium|media|broth)\b",
    r"\bnegative growth controls?\b",
    r"\b(?:media|medium) controls?\b",
    r"\bno cells?\b(?: \w+){0,4} (?:incubations?|controls?)\b",
    r"\b(?:bacteria free|cell free|without bacteria|no bacteria)\b(?: \w+){0,4} "
    r"(?:filters?|incubations?|controls?|medium|media|broth)\b",
    r"\b(?:filters?|incubations?|controls?|medium|media|broth)\b(?: \w+){0,4} "
    r"(?:bacteria free|cell free|without bacteria|no bacteria)\b",
))

_AMBIGUOUS = re.compile(r"\b(?:negative|background) controls?\b|\bblanks?\b")
_NO_BACTERIA_QUALIFIER = re.compile(
    r"\b(?:without bacteria|no bacteria|bacteria free|uninoculated|non inoculated|not inoculated)\b"
)


def _is_bacteria_free_control(text) -> bool:
    normalised = _normalise(text)
    if any(pattern.search(normalised) for pattern in _BLOCKED):
        return False
    if any(pattern.search(normalised) for pattern in _ACCEPTED):
        return True
    return bool(_AMBIGUOUS.search(normalised) and _NO_BACTERIA_QUALIFIER.search(normalised))


def _blocked_bacteria_free(text) -> str | None:
    normalised = _normalise(text)
    for pattern in _BLOCKED:
        match = pattern.search(normalised)
        if match:
            return match.group(0).strip()
    return None


CONTROL_MATCHERS = {
    "bacteria_free_control": _is_bacteria_free_control,
}

CONTROL_BLOCKERS = {
    "bacteria_free_control": _blocked_bacteria_free,
}


def matches_control_aliases(value, alias_set: str) -> bool:
    matcher = CONTROL_MATCHERS[alias_set]
    values = value if isinstance(value, list) else [value]
    return any(matcher(text) for text in values if text is not None)


def blocked_control_wordings(value, alias_set: str) -> list[tuple[str, str]]:
    blocker = CONTROL_BLOCKERS.get(alias_set)
    if blocker is None:
        return []
    values = value if isinstance(value, list) else [value]
    hits = []
    for text in values:
        if text is None:
            continue
        phrase = blocker(text)
        if phrase is not None:
            hits.append((str(text), phrase))
    return hits
