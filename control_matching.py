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

# A leading qualifier attaches to the control noun through at most two medium or
# matrix descriptors from an allow-list; an open gap lets it modify an unrelated
# word ("no cell lysis control", "cell free spent medium").
# Known ambiguity, accepted on purpose: "no bacteria growth medium" can mean
# medium in which no bacteria grow (a valid control) or a "no bacterial growth"
# readout followed by "medium".
_BACTERIA_FREE_NOUNS = r"(?:filters?|incubations?|controls?|medium|media|broth|buffers?|pbs|stability)"
_LEADING_NO_BACTERIA = r"(?:bacteria free|cell free|without bacteria|no bacteria|no cells?)"
_TRAILING_NO_BACTERIA = r"(?:without bacteria|no bacteria|no cells|bacteria free)"
_MEDIUM_DESCRIPTORS = (
    r"(?:7h9|middlebrook|growth|assay|complete|culture|compound|drug|spiked|test"
    r"|fresh|sterile|basal|minimal|defined|liquid)"
)
_TAIL_PREPOSITIONS = r"(?:in|at|for|over|during|from|of|to|with|under|on|across|throughout)"
_PRESENT_MATERIAL = r"(?:bacteria|bacterial|cells?|lysates?|mycobacteria|h37rv)"

# A part that says bacteria, cells or lysate are present is not a bacteria-free control, unless the mention is negated ("no cells added") or removed ("cells omitted").
_PRESENCE = tuple(re.compile(pattern) for pattern in (
    r"(?<!non )(?<!not )\binoculated\b",
    r"\bwith live\b",
    rf"\b(?:spiked with|containing|plus|with|added)(?: (?!no\b|without\b)\w+){{0,2}} {_PRESENT_MATERIAL}\b(?! free)",
    rf"\b{_PRESENT_MATERIAL} added\b",
    r"(?<!no )\blysates?\b",
))
# Supernatant is taken from a culture, so no qualifier makes it a bacteria-free control.
_CULTURE_DERIVED = re.compile(r"\bsupernatants?\b")
_NEGATORS = frozenset({"no", "without", "not", "minus"})
_REMOVAL_AFTER = re.compile(r"^ (?:omitted|removed|absent|excluded)\b")

_ACCEPTED = tuple(re.compile(pattern) for pattern in (
    r"\bsterility controls?\b",
    r"\b(?:medium|media|broth) (?:alone|only)\b",
    r"\bonly (?:broth|medium|media)\b",
    r"\buninoculated\b",
    r"\b(?:non inoculated|not inoculated) (?:medium|media|broth)\b",
    r"\bnegative growth controls?\b",
    r"\b(?:media|medium) controls?\b",
    rf"\b{_LEADING_NO_BACTERIA}(?: {_MEDIUM_DESCRIPTORS}){{0,2}}(?: (?:only|alone))?(?: {_BACTERIA_FREE_NOUNS})+\b",
    rf"\b{_BACTERIA_FREE_NOUNS}\b(?: \w+){{0,4}} {_TRAILING_NO_BACTERIA}\b(?= ?$| {_TAIL_PREPOSITIONS}\b| (?:present|added|omitted|absent)\b)",
))

_AMBIGUOUS = re.compile(r"\b(?:negative|background) controls?\b|\bblanks?\b")
_NO_BACTERIA_QUALIFIER = re.compile(
    r"\b(?:without bacteria|no bacteria|bacteria free|uninoculated|non inoculated|not inoculated)\b"
)


def _says_bacteria_present(normalised):
    for pattern in _PRESENCE:
        for match in pattern.finditer(normalised):
            if _NEGATORS.intersection(normalised[:match.start()].split()[-2:]):
                continue
            if _REMOVAL_AFTER.match(normalised[match.end():]):
                continue
            return True
    return False


def _is_accepted_control_part(normalised):
    if any(pattern.search(normalised) for pattern in _BLOCKED):
        return False
    if _says_bacteria_present(normalised):
        return False
    if _CULTURE_DERIVED.search(normalised):
        return False
    if any(pattern.search(normalised) for pattern in _ACCEPTED):
        return True
    return bool(_AMBIGUOUS.search(normalised) and _NO_BACTERIA_QUALIFIER.search(normalised))


def _control_parts(text) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"[,;]|\band\b", str(text), flags=re.IGNORECASE)
        if part.strip()
    ]


def _is_bacteria_free_control(text) -> bool:
    parts = _control_parts(text)
    normalised_parts = [_normalise(part) for part in parts]
    if any(_is_accepted_control_part(part) for part in normalised_parts):
        return True
    if any(
        any(pattern.search(part) for pattern in _BLOCKED)
        for part in normalised_parts
    ):
        return False
    return _is_accepted_control_part(_normalise(text))


def _blocked_bacteria_free(text) -> list[str]:
    matches = []
    for part in _control_parts(text):
        normalised = _normalise(part)
        for pattern in _BLOCKED:
            match = pattern.search(normalised)
            if match:
                matches.append(match.group(0).strip())
                break
    return matches


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
        for phrase in blocker(text):
            hits.append((str(text), phrase))
    return hits
