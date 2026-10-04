"""Citation lookup, kept out of the pure auditor.

The auditor never touches the network. This module, run by a trusted caller,
asks Crossref whether each unfamiliar DOI exists and caches the answer, so a
report can be reproduced offline from the cache. A DOI that Crossref says does
not exist is a fabricated citation; one it could not check stays 'unknown' and
is only a soft flag.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / "evals" / "audit" / "doi_cache.json"


def _load() -> dict[str, str]:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _lookup(doi: str, timeout: float = 8.0) -> str:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/")
    req = urllib.request.Request(url, headers={"User-Agent": "falsifylab-audit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return "exists" if r.status == 200 else "unknown"
    except urllib.error.HTTPError as exc:
        return "missing" if exc.code == 404 else "unknown"
    except (urllib.error.URLError, TimeoutError, OSError):
        return "unknown"


def resolve(dois: set[str], online: bool = True) -> dict[str, str]:
    """Status per DOI: 'exists' | 'missing' | 'unknown'. Definite answers are cached."""
    cache = _load()
    out: dict[str, str] = {}
    dirty = False
    for d in sorted(dois):
        status = cache.get(d)
        if status is None and online:
            status = _lookup(d)
            if status in ("exists", "missing"):
                cache[d] = status
                dirty = True
        out[d] = status or "unknown"
    if dirty:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    return out
