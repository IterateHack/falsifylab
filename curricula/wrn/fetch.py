"""Build the WRN curriculum datasets from Open Targets' DepMap CRISPR screens.

This curriculum exists to show that the engine is hypothesis-agnostic: a
different hypothesis, a different data source and different scorers, with no
change to anything under engine/ or sandbox/.

Source: Open Targets Platform GraphQL, `target.depMapEssentiality`, which exposes
per-cell-line DepMap CRISPR gene-effect scores. A gene effect near 0 means
knocking the gene out did nothing; around -1 means the cell line died.

Run:  python -m curricula.wrn.fetch
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PRIVATE = ROOT / "private"
OT_URL = "https://api.platform.opentargets.org/api/v4/graphql"
UA = {"User-Agent": "falsifylab/0.1 (hackathon research prototype)"}

# A panel spanning the three behaviours the first experiment asks about. The
# labels are NOT used as ground truth - ground truth is computed from the
# screens themselves by the documented rule below.
PANEL = [
    "RPL5", "POLR2A", "PCNA", "RAN", "SF3B1", "EIF4A3",      # core machinery
    "WRN", "KRAS", "BRAF", "PIK3CA", "CTNNB1", "EGFR",        # context-dependent
    "ALB", "MYH7", "GFAP", "OR2L13", "CSN2", "INS",           # not expressed broadly
]

DEPENDENCY_THRESHOLD = -0.5     # the conventional DepMap "is a dependency" cutoff
COMMON_FRACTION = 0.80          # dependent in this fraction of lines => common essential
SELECTIVE_FRACTION = 0.05       # dependent in at least this fraction => selective
# A real selective dependency has a strong tail somewhere, not just a drift of
# weakly negative lines. Without this, INS lands in "selective" on 12% of lines
# scraping past -0.5 while its worst line only reaches -1.09, whereas every
# genuine selective gene here goes below -1.6.
SELECTIVE_TAIL = -1.0
# Experiment 2 applies the same standard to tissues.
MIN_LINES_PER_TISSUE = 15
TISSUE_TAIL = -1.0

SEARCH_Q = """
query($q: String!) {
  search(queryString: $q, entityNames: ["target"], page: {index: 0, size: 5}) {
    hits { id entity object { ... on Target { id approvedSymbol } } }
  }
}
"""

DEPMAP_Q = """
query($ids: [String!]!) {
  targets(ensemblIds: $ids) {
    id approvedSymbol
    depMapEssentiality {
      tissueName
      screens { depmapId cellLineName diseaseFromSource geneEffect expression }
    }
  }
}
"""


def gql(query: str, variables: dict[str, Any], retries: int = 3) -> dict[str, Any]:
    for attempt in range(retries):
        try:
            r = requests.post(OT_URL, json={"query": query, "variables": variables},
                              headers=UA, timeout=120)
            r.raise_for_status()
            body = r.json()
            if "errors" in body:
                raise RuntimeError(body["errors"])
            return body["data"]
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def resolve(symbols: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for sym in symbols:
        data = gql(SEARCH_Q, {"q": sym})
        for hit in data["search"]["hits"]:
            obj = hit.get("object") or {}
            if obj.get("approvedSymbol") == sym:
                out[sym] = obj["id"]
                break
        time.sleep(0.2)
    missing = set(symbols) - set(out)
    if missing:
        print(f"  warning: could not resolve {sorted(missing)}")
    return out


def percentile(xs: list[float], p: float) -> float:
    import math
    s = sorted(xs)
    if not s:
        return 0.0
    k = (len(s) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


def classify(effects: list[float]) -> str:
    """The documented rule that defines ground truth for experiment 1."""
    if not effects:
        return "unknown"
    n = len(effects)
    frac = sum(1 for e in effects if e <= DEPENDENCY_THRESHOLD) / n
    if frac >= COMMON_FRACTION:
        return "common_essential"
    if frac >= SELECTIVE_FRACTION and percentile(effects, 1) <= SELECTIVE_TAIL:
        return "selective"
    return "non_essential"


def median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(parents=True, exist_ok=True)

    print("resolving symbols")
    ids = resolve(PANEL)

    print("fetching DepMap screens")
    rows: list[dict[str, Any]] = []
    effects: dict[str, list[float]] = defaultdict(list)
    wrn_by_tissue: dict[str, list[float]] = defaultdict(list)
    id_list = sorted(ids.values())
    for i in range(0, len(id_list), 6):
        data = gql(DEPMAP_Q, {"ids": id_list[i:i + 6]})
        for t in data["targets"]:
            sym = t["approvedSymbol"]
            for tissue in (t.get("depMapEssentiality") or []):
                for sc in (tissue.get("screens") or []):
                    ge = sc.get("geneEffect")
                    if ge is None:
                        continue
                    rows.append({
                        "gene": sym,
                        "ensembl_id": t["id"],
                        "tissue": tissue["tissueName"],
                        "depmap_id": sc.get("depmapId", ""),
                        "cell_line": sc.get("cellLineName", ""),
                        "disease": sc.get("diseaseFromSource", ""),
                        "gene_effect": round(float(ge), 5),
                        "expression": sc.get("expression"),
                    })
                    effects[sym].append(float(ge))
                    if sym == "WRN":
                        wrn_by_tissue[tissue["tissueName"]].append(float(ge))
        time.sleep(0.3)

    rows.sort(key=lambda r: (r["gene"], r["tissue"], r["cell_line"]))
    import csv
    path = DATA / "h2exp1_depmap_gene_effects.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path.name} ({len(rows)} rows, {len(effects)} genes)")

    labels = {g: classify(v) for g, v in effects.items()}
    (PRIVATE / "h2exp1.json").write_text(json.dumps({
        "rule": f"Per gene, let f = fraction of cell lines with gene_effect <= "
                f"{DEPENDENCY_THRESHOLD}, and p1 = the 1st percentile of its gene "
                f"effects. f >= {COMMON_FRACTION} is common_essential; "
                f"f >= {SELECTIVE_FRACTION} AND p1 <= {SELECTIVE_TAIL} is selective; "
                f"otherwise non_essential. The p1 condition is what separates a real "
                f"selective dependency from a drift of weakly negative lines.",
        "source": "Open Targets Platform depMapEssentiality (DepMap CRISPR screens)",
        "dependency_threshold": DEPENDENCY_THRESHOLD,
        "labels": labels,
        "median_gene_effect": {g: round(median(v), 4) for g, v in effects.items()},
        "p1_gene_effect": {g: round(percentile(v, 1), 4) for g, v in effects.items()},
        "fraction_dependent": {
            g: round(sum(1 for e in v if e <= DEPENDENCY_THRESHOLD) / len(v), 4)
            for g, v in effects.items()},
        "n_lines": {g: len(v) for g, v in effects.items()},
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("  wrote private/h2exp1.json:",
          {k: sum(1 for x in labels.values() if x == k)
           for k in ("common_essential", "selective", "non_essential")})

    # --- experiment 2: where does WRN dependency concentrate? ---------------
    # The same standard lesson 1 teaches has to apply here, or the ground truth
    # contradicts its own curriculum. A tissue counts only if it has enough
    # lines to measure a fraction AND a genuine deep tail. With a 5-line floor
    # and no tail requirement, "hepatopancreatic ampulla" (1 of 5 dependent,
    # worst line -0.59) ranked second, above colorectal - and an agent that
    # correctly discarded it as underpowered was marked down for doing so.
    tissue_stats = {
        t: {
            "n_lines": len(v),
            "median_gene_effect": round(median(v), 4),
            "min_gene_effect": round(min(v), 4),
            "fraction_dependent": round(
                sum(1 for e in v if e <= DEPENDENCY_THRESHOLD) / len(v), 4),
        }
        for t, v in wrn_by_tissue.items()
        if len(v) >= MIN_LINES_PER_TISSUE and min(v) <= TISSUE_TAIL
    }
    ranked = sorted(tissue_stats, key=lambda t: -tissue_stats[t]["fraction_dependent"])
    (PRIVATE / "h2exp2.json").write_text(json.dumps({
        "scoring": "Rank correlation on tissues ordered by the fraction of cell "
                   "lines with WRN gene_effect <= -0.5, plus a mechanism rubric.",
        "source": "Open Targets Platform depMapEssentiality, WRN (ENSG00000165392)",
        "min_lines_per_tissue": MIN_LINES_PER_TISSUE,
        "tissue_tail_requirement": TISSUE_TAIL,
        "inclusion_rule": f"a tissue is ranked only if it has at least "
                          f"{MIN_LINES_PER_TISSUE} cell lines and at least one line "
                          f"below {TISSUE_TAIL} - the same tail standard lesson 1 "
                          f"applies to genes",
        "tissue_stats": tissue_stats,
        "ranking_most_to_least_dependent": ranked,
        "top_tissues": ranked[:5],
        "rubric": [
            {"id": "msi", "weight": 3.0,
             "any_of": ["microsatellite instability", "msi", "mismatch repair",
                        "mmr-deficient", "mmr deficient"],
             "points": "names microsatellite instability / mismatch-repair deficiency "
                       "as the underlying state, not the tissue itself"},
            {"id": "lineage_confound", "weight": 2.5,
             "any_of": ["confound", "lineage is a proxy", "proxy for", "not the tissue",
                        "within-lineage", "within lineage", "stratif", "enriched in",
                        "surrogate", "is not the cause", "not the cause",
                        "bimodal within", "within each", "standing in for",
                        "stands in for", "correlate", "marker for"],
             "points": "treats lineage as a proxy for the real variable rather than "
                       "the cause"},
            {"id": "synthetic_lethal", "weight": 2.0,
             "any_of": ["synthetic lethal", "synthetic-lethal", "synthetic lethality",
                        "lethal only in", "lethal in combination", "genetic interaction"],
             "points": "frames the relationship as synthetic lethality"},
            {"id": "mechanism", "weight": 1.5,
             "any_of": ["ta repeat", "ta-repeat", "repeat expansion", "cruciform",
                        "secondary structure", "helicase"],
             "points": "offers a mechanism (expanded TA repeats forming secondary "
                       "structure that WRN helicase resolves)"},
            {"id": "next_test", "weight": 1.0,
             "any_of": ["msi status", "msi-h", "msi high", "stratify", "annotate",
                        "label the lines", "test within"],
             "points": "proposes testing MSI status directly rather than stopping "
                       "at lineage"},
        ],
        "penalties": [
            {"id": "tissue_as_cause", "weight": 2.0,
             "any_of": ["because it is colorectal", "colorectal cancer causes",
                        "the tissue itself drives", "lineage causes the dependency",
                        "tissue of origin is the cause"],
             "why": "lineage correlates with MSI status; it is not the cause"},
        ],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("  wrote private/h2exp2.json: top tissues", ranked[:4])
    print("\ndone.")


if __name__ == "__main__":
    main()
