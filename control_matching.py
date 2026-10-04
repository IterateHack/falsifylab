import re


CONTROL_ALIASES = {
    "bacteria_free_control": (
        "bacteria-free", "cell-free", "no bacteria", "without bacteria", "acellular",
        "medium-only", "no-cell", "sterile-medium", "media-only", "no cells", "sterile media",
        "bacteria absent", "lacking bacteria", "sans bacteria",
    ),
}


def matches_control_aliases(value, alias_set: str) -> bool:
    aliases = CONTROL_ALIASES[alias_set]
    values = value if isinstance(value, list) else [value]

    def normalise(text):
        return " " + re.sub(r"[\W_]+", " ", str(text).lower()).strip() + " "

    return any(normalise(alias) in normalise(text) for text in values for alias in aliases)
