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
    r"\bonly (?:broth|medium|media)\b",
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


def _is_accepted_control_part(normalised):
    if any(pattern.search(normalised) for pattern in _BLOCKED):
        return False
    if any(pattern.search(normalised) for pattern in _ACCEPTED):
        return True
    return bool(_AMBIGUOUS.search(normalised) and _NO_BACTERIA_QUALIFIER.search(normalised))


def _is_bacteria_free_control(text) -> bool:
    parts = [
        part.strip()
        for part in re.split(r"[,;]|\band\b", str(text), flags=re.IGNORECASE)
        if part.strip()
    ]
    normalised_parts = [_normalise(part) for part in parts]
    if any(_is_accepted_control_part(part) for part in normalised_parts):
        return True
    if any(
        any(pattern.search(part) for pattern in _BLOCKED)
        for part in normalised_parts
    ):
        return False
    return _is_accepted_control_part(_normalise(text))


CONTROL_MATCHERS = {
    "bacteria_free_control": _is_bacteria_free_control,
}


def matches_control_aliases(value, alias_set: str) -> bool:
    matcher = CONTROL_MATCHERS[alias_set]
    values = value if isinstance(value, list) else [value]
    return any(matcher(text) for text in values if text is not None)
