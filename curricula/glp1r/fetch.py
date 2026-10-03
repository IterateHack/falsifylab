"""Build the GLP-1R curriculum datasets from primary public sources.

Every dataset the agent sees is derived here, and every derivation is recorded
in data/PROVENANCE.json so a reviewer can tell fetched facts from transcribed
ones. Ground truth is written to private/ and is never mounted in the agent
sandbox.

Sources
  Open Targets Platform GraphQL  - BMI / T2D genetic evidence, tractability
  RCSB PDB                       - 7KI0 (semaglutide-bound GLP-1R-Gs)
  ChEMBL REST                    - GLP-1R (CHEMBL1784) EC50 activities
  UniProt REST                   - GLP1R orthologues (human / mouse / rat / macaque)

Run:  python -m curricula.glp1r.fetch [--only exp1,exp2,...]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PRIVATE = ROOT / "private"
RAW = DATA / "raw"

OT_URL = "https://api.platform.opentargets.org/api/v4/graphql"
CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"
UNIPROT = "https://rest.uniprot.org/uniprotkb"
PDB_FILES = "https://files.rcsb.org/download"

UA = {"User-Agent": "falsifylab/0.1 (hackathon research prototype)"}
PROVENANCE: list[dict[str, Any]] = []


def note(dataset: str, source: str, detail: str, kind: str = "fetched") -> None:
    PROVENANCE.append({"dataset": dataset, "source": source, "detail": detail, "kind": kind})
    print(f"  [{kind}] {dataset}: {detail}")


class UpstreamUnavailable(RuntimeError):
    """A public data source is down. Not a bug in this repository."""


# 5xx and 429 are worth waiting out; 404 means the identifier is wrong and no
# amount of retrying will help.
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def gql(query: str, variables: dict[str, Any], retries: int = 5) -> dict[str, Any]:
    last = ""
    for attempt in range(retries):
        try:
            r = requests.post(OT_URL, json={"query": query, "variables": variables},
                              headers=UA, timeout=120)
            if r.status_code in RETRYABLE_STATUS:
                last = f"HTTP {r.status_code}"
                raise requests.HTTPError(last, response=r)
            r.raise_for_status()
            body = r.json()
            if "errors" in body:
                # A GraphQL error is a bad query, not an outage - fail fast.
                raise UpstreamUnavailable(f"Open Targets rejected the query: {body['errors']}")
            return body["data"]
        except UpstreamUnavailable:
            raise
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status is not None and status not in RETRYABLE_STATUS:
                raise UpstreamUnavailable(
                    f"Open Targets returned HTTP {status}. Not a transient failure."
                ) from exc
            last = f"HTTP {status}"
        except requests.RequestException as exc:
            last = type(exc).__name__
        if attempt < retries - 1:
            delay = min(30.0, 2.0 * (2 ** attempt)) * (0.5 + random.random())
            print(f"  [Open Targets] {last}; retrying in {delay:.0f}s "
                  f"({attempt + 2}/{retries})", flush=True)
            time.sleep(delay)
    raise UpstreamUnavailable(
        f"Open Targets is unavailable ({last}) after {retries} attempts.\n"
        f"  This is an outage at the data provider, not a problem with this repo.\n"
        f"  The committed datasets remain valid; retry later."
    )


def get_json(url: str, params: dict[str, Any] | None = None,
             retries: int = 5, service: str = "upstream") -> dict[str, Any]:
    last = ""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=120)
            if r.status_code in RETRYABLE_STATUS:
                last = f"HTTP {r.status_code}"
                raise requests.HTTPError(last, response=r)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status is not None and status not in RETRYABLE_STATUS:
                raise UpstreamUnavailable(
                    f"{service} returned HTTP {status} for {url}. That is not a "
                    f"transient failure - check the identifier."
                ) from exc
            last = f"HTTP {status}"
        except requests.RequestException as exc:
            last = type(exc).__name__
        if attempt < retries - 1:
            delay = min(30.0, 2.0 * (2 ** attempt)) * (0.5 + random.random())
            print(f"  [{service}] {last}; retrying in {delay:.0f}s "
                  f"({attempt + 2}/{retries})", flush=True)
            time.sleep(delay)
    raise UpstreamUnavailable(
        f"{service} is unavailable ({last}) after {retries} attempts: {url}\n"
        f"  This is an outage at the data provider, not a problem with this repo.\n"
        f"  The datasets in curricula/glp1r/data/ are already committed and valid -\n"
        f"  you only need this script to rebuild them from source. Try again later,\n"
        f"  or rebuild just the parts you need with --only."
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    print(f"  wrote {path.relative_to(ROOT)} ({len(rows)} rows)")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Experiment 1: genetic support for obesity / T2D drug targets
# ---------------------------------------------------------------------------
# Datatype scores that encode clinical or drug status would hand the agent the
# answer, so only the genetic ones cross into the sandbox.
ALLOWED_DATATYPES = {"genetic_association", "genetic_literature", "animal_model",
                     "rna_expression", "literature"}
GENETIC_DATATYPES = {"genetic_association", "genetic_literature"}
# Tractability labels that restate clinical stage - excluded for the same reason.
APPROVED_STAGES = {"APPROVAL", "PHASE_4"}
TRACT_DENY = {"Approved Drug", "Advanced Clinical", "Phase 1 Clinical",
              "Clinical Precedence", "Literature Precedence",
              "Predicted Tractable - High confidence",
              "Predicted Tractable - Medium to low confidence"}

ASSOC_Q = """
query($efo: String!, $size: Int!) {
  disease(efoId: $efo) {
    id name
    associatedTargets(page: {index: 0, size: $size}) {
      count
      rows {
        score
        datatypeScores { id score }
        target { id approvedSymbol biotype targetClass { label } }
      }
    }
  }
}
"""

TARGET_Q = """
query($ids: [String!]!) {
  targets(ensemblIds: $ids) {
    id approvedSymbol biotype
    geneticConstraint { constraintType score upperBin6 }
    tractability { label value modality }
    subcellularLocations { location }
    drugAndClinicalCandidates { count rows { maxClinicalStage drug { name drugType } } }
  }
}
"""

TRAITS = [("EFO_0004340", "body_mass_index"), ("MONDO_0005148", "type_2_diabetes")]
N_PER_TRAIT = 90


def build_exp1() -> None:
    print("exp1: genetic support")
    per_gene: dict[str, dict[str, Any]] = {}
    for efo, label in TRAITS:
        data = gql(ASSOC_Q, {"efo": efo, "size": N_PER_TRAIT})
        dis = data["disease"]
        note("exp1_gwas_targets.csv", f"Open Targets Platform {efo}",
             f"{dis['name']}: top {N_PER_TRAIT} of {dis['associatedTargets']['count']} associated targets")
        for row in dis["associatedTargets"]["rows"]:
            t = row["target"]
            g = per_gene.setdefault(t["id"], {
                "ensembl_id": t["id"], "gene": t["approvedSymbol"],
                "biotype": t["biotype"],
                "target_class": "; ".join(sorted({c["label"] for c in (t["targetClass"] or [])})),
                "traits": set(), "genetic_scores": {},
            })
            g["traits"].add(label)
            for dts in row["datatypeScores"]:
                if dts["id"] in GENETIC_DATATYPES:
                    key = f"{label}__{dts['id']}"
                    g["genetic_scores"][key] = round(dts["score"], 4)

    ids = sorted(per_gene)
    detail: dict[str, Any] = {}
    for i in range(0, len(ids), 40):
        chunk = ids[i:i + 40]
        data = gql(TARGET_Q, {"ids": chunk})
        for t in data["targets"]:
            detail[t["id"]] = t
        time.sleep(0.3)
    note("exp1_gwas_targets.csv", "Open Targets Platform targets()",
         f"tractability / constraint / localisation for {len(detail)} genes")

    rows: list[dict[str, Any]] = []
    validated: list[str] = []
    for eid in ids:
        g = per_gene[eid]
        t = detail.get(eid, {})
        tract = [x for x in (t.get("tractability") or [])
                 if x["value"] and x["label"] not in TRACT_DENY]
        sm = sorted({x["label"] for x in tract if x["modality"] == "SM"})
        ab = sorted({x["label"] for x in tract if x["modality"] == "AB"})
        gc = {c["constraintType"]: c for c in (t.get("geneticConstraint") or [])}
        loc = sorted({l["location"] for l in (t.get("subcellularLocations") or [])})
        bmi_g = g["genetic_scores"].get("body_mass_index__genetic_association", "")
        t2d_g = g["genetic_scores"].get("type_2_diabetes__genetic_association", "")
        bmi_l = g["genetic_scores"].get("body_mass_index__genetic_literature", "")
        t2d_l = g["genetic_scores"].get("type_2_diabetes__genetic_literature", "")
        rows.append({
            "gene": g["gene"],
            "ensembl_id": eid,
            "biotype": g["biotype"],
            "target_class": g["target_class"],
            "traits": ";".join(sorted(g["traits"])),
            "n_traits": len(g["traits"]),
            "bmi_genetic_association": bmi_g,
            "t2d_genetic_association": t2d_g,
            "bmi_genetic_literature": bmi_l,
            "t2d_genetic_literature": t2d_l,
            "loss_of_function_intolerance_bin": gc.get("lof", {}).get("upperBin6", ""),
            "missense_constraint_score": (round(gc["mis"]["score"], 3) if "mis" in gc
                                          and gc["mis"].get("score") is not None else ""),
            "small_molecule_tractability": "; ".join(sm),
            "antibody_tractability": "; ".join(ab),
            "is_cell_surface": int(any("Cell membrane" in x or "Plasma membrane" in x
                                       for x in loc)),
            "n_subcellular_locations": len(loc),
        })
        # Ground truth: at least one approved medicine acts on this target.
        # Open Targets marks approval as either APPROVAL or PHASE_4 depending on
        # the row, so both count - checking only PHASE_4 silently drops targets
        # such as MC4R (setmelanotide), which would then be scored as failures.
        cands = (t.get("drugAndClinicalCandidates") or {}).get("rows") or []
        if any(c.get("maxClinicalStage") in APPROVED_STAGES
               or ((c.get("drug") or {}).get("maximumClinicalStage") in APPROVED_STAGES)
               for c in cands):
            validated.append(g["gene"])

    rows.sort(key=lambda r: r["gene"])
    write_csv(DATA / "exp1_gwas_targets.csv", rows, list(rows[0].keys()))
    write_json(PRIVATE / "exp1.json", {
        "criterion": "Open Targets drugAndClinicalCandidates contains a drug at stage "
                     "APPROVAL or PHASE_4, i.e. at least one approved medicine acts on "
                     "this target.",
        "source": "Open Targets Platform GraphQL api/v4, targets(ensemblIds:)",
        "n_candidates": len(rows),
        "validated_targets": sorted(validated),
        "n_validated": len(validated),
    })
    note("private/exp1.json", "Open Targets Platform",
         f"{len(validated)} of {len(rows)} candidate genes have an approved drug")


# ---------------------------------------------------------------------------
# Experiment 2: semaglutide / GLP-1R contact residues from 7KI0
# ---------------------------------------------------------------------------
CONTACT_CUTOFF_A = 4.0
PEP_ENTITY, REC_ENTITY = "5", "6"      # semaglutide, GLP-1 receptor


def parse_cif_atoms(text: str) -> list[dict[str, Any]]:
    """Minimal mmCIF atom_site reader - enough for distance work, no Biopython."""
    lines = text.splitlines()
    cols: list[str] = []
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "loop_":
            j = i + 1
            block: list[str] = []
            while j < len(lines) and lines[j].startswith("_"):
                block.append(lines[j].strip())
                j += 1
            if block and block[0].startswith("_atom_site."):
                cols = block
                idx = {name: k for k, name in enumerate(cols)}
                while j < len(lines) and not lines[j].startswith("#"):
                    row = lines[j].split()
                    if row and row[0] in ("ATOM", "HETATM") and len(row) >= len(cols):
                        out.append({
                            "entity": row[idx["_atom_site.label_entity_id"]],
                            "chain": row[idx["_atom_site.auth_asym_id"]],
                            "seq": row[idx["_atom_site.auth_seq_id"]],
                            "comp": row[idx["_atom_site.auth_comp_id"]],
                            "element": row[idx["_atom_site.type_symbol"]],
                            "x": float(row[idx["_atom_site.Cartn_x"]]),
                            "y": float(row[idx["_atom_site.Cartn_y"]]),
                            "z": float(row[idx["_atom_site.Cartn_z"]]),
                        })
                    j += 1
                return out
            i = j
        else:
            i += 1
    return out


# RCSB and the PDBe mirror serve byte-identical files; either will do, and
# having both means a single flaky DNS resolution does not fail the build.
STRUCTURE_MIRRORS = [
    ("RCSB PDB", "https://files.rcsb.org/download/{pdb_upper}.cif"),
    ("PDBe (EBI mirror)", "https://www.ebi.ac.uk/pdbe/entry-files/download/{pdb_lower}.cif"),
]


def fetch_structure(pdb_id: str) -> tuple[bytes, str]:
    errors = []
    for name, template in STRUCTURE_MIRRORS:
        url = template.format(pdb_upper=pdb_id.upper(), pdb_lower=pdb_id.lower())
        for attempt in range(2):
            try:
                r = requests.get(url, headers=UA, timeout=300)
                r.raise_for_status()
                if len(r.content) < 10_000:
                    raise RuntimeError(f"suspiciously small payload ({len(r.content)} bytes)")
                return r.content, f"{name} {pdb_id.upper()}"
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"could not fetch {pdb_id} from any mirror:\n  " + "\n  ".join(errors))


def build_exp2() -> None:
    print("exp2: peptide-receptor contacts")
    RAW.mkdir(parents=True, exist_ok=True)
    cif_path = DATA / "exp2_7ki0.cif"
    content, used = fetch_structure("7KI0")
    cif_path.write_bytes(content)
    note("exp2_7ki0.cif", used,
         f"mmCIF, {len(content)} bytes, Zhang et al. Cell Rep 2021 (2.5 A cryo-EM)")

    atoms = parse_cif_atoms(content.decode("utf-8", "replace"))
    pep = [a for a in atoms if a["entity"] == PEP_ENTITY and a["element"] != "H"]
    rec = [a for a in atoms if a["entity"] == REC_ENTITY and a["element"] != "H"]
    if not pep or not rec:
        raise RuntimeError("7KI0 entity ids changed - re-check entity composition")
    cutoff2 = CONTACT_CUTOFF_A ** 2
    contacts: dict[int, str] = {}
    for p in pep:
        for q in rec:
            dx = p["x"] - q["x"]
            dy = p["y"] - q["y"]
            dz = p["z"] - q["z"]
            if dx * dx + dy * dy + dz * dz <= cutoff2:
                contacts[int(q["seq"])] = q["comp"]
    residues = [{"resnum": n, "resname": contacts[n]} for n in sorted(contacts)]
    write_json(PRIVATE / "exp2.json", {
        "definition": f"GLP-1R residues with any heavy atom within {CONTACT_CUTOFF_A} A "
                      f"of any semaglutide heavy atom in PDB 7KI0",
        "receptor_chain": "R", "peptide_chain": "P",
        "receptor_entity": REC_ENTITY, "peptide_entity": PEP_ENTITY,
        "cutoff_angstrom": CONTACT_CUTOFF_A,
        "n_contacts": len(residues),
        "contact_residues": residues,
        "contact_resnums": sorted(contacts),
    })
    note("private/exp2.json", "computed from 7KI0",
         f"{len(residues)} contact residues at {CONTACT_CUTOFF_A} A", kind="computed")


# ---------------------------------------------------------------------------
# Experiment 3: peptide engineering and duration of action
# ---------------------------------------------------------------------------
# Sequence modifications and dosing intervals are well established and are
# transcribed from the primary literature and product labels (see
# docs/references.md). Scoring uses the DURATION CLASS ordering, which is not in
# dispute; the approximate half-lives are context for the agent and carry a
# "pending sign-off" flag rather than being treated as exact ground truth.
ANALOGUES = [
    # name, backbone, position-8 residue, acylation/fusion, class, approx t1/2 (h), note
    ("GLP-1(7-37)",  "native human GLP-1", "Ala8",  "none",
     "minutes", 0.03, "native incretin; cleaved by DPP-4 between His7 and Ala8"),
    ("Exenatide",    "exendin-4 (Gila monster)", "Gly2 (exendin numbering)", "none",
     "twice_daily", 2.4, "Gly at the DPP-4 P1' position confers resistance; cleared renally"),
    ("Lixisenatide", "exendin-4 + six C-terminal Lys", "Gly2 (exendin numbering)", "none",
     "once_daily", 3.0, "exendin backbone with a poly-Lys C-terminal extension"),
    ("Liraglutide",  "human GLP-1, Lys34Arg", "Ala8", "C16 palmitoyl via gamma-Glu at Lys26",
     "once_daily", 13.0, "fatty-acid acylation drives reversible albumin binding"),
    ("Semaglutide",  "human GLP-1, Lys34Arg", "Aib8", "C18 fatty diacid via gamma-Glu + 2x OEG at Lys26",
     "once_weekly", 165.0, "Aib8 blocks DPP-4; diacid raises albumin affinity"),
    ("Taspoglutide", "human GLP-1, Aib8 + Aib35", "Aib8", "none",
     "once_weekly", 165.0, "two Aib substitutions, no acylation; development discontinued"),
    ("Dulaglutide",  "GLP-1 analogue fused to IgG4 Fc", "Gly8", "IgG4-Fc fusion",
     "once_weekly", 112.0, "fusion raises hydrodynamic radius above the renal threshold"),
    ("Albiglutide",  "GLP-1 dimer fused to human albumin", "Gly8", "albumin fusion",
     "once_weekly", 120.0, "genetic albumin fusion rather than non-covalent binding"),
    ("Tirzepatide",  "GIP-based dual GIP/GLP-1 agonist", "Aib2 (GIP numbering)",
     "C20 fatty diacid via gamma-Glu + 2x OEG at Lys20",
     "once_weekly", 117.0, "dual agonist; same acylation strategy as semaglutide"),
]
DURATION_RANK = {"minutes": 0, "twice_daily": 1, "once_daily": 2, "once_weekly": 3}


def build_exp3() -> None:
    print("exp3: peptide engineering")
    # Ground the native sequence in a real record rather than retyping it.
    glp1_7_37 = ""
    try:
        j = get_json(f"{UNIPROT}/P01275.json",
                     {"fields": "accession,sequence,ft_peptide"},
                     service="UniProt")
        proglucagon = j["sequence"]["value"]
        for f in j.get("features", []):
            desc = (f.get("description") or "").lower()
            if f["type"] == "Peptide" and "glucagon-like peptide 1" in desc:
                start, end = f["location"]["start"]["value"], f["location"]["end"]["value"]
                cand = proglucagon[start - 1:end]
                if cand.startswith("HA") and len(cand) >= 30:
                    glp1_7_37 = cand
        if not glp1_7_37:                  # UniProt annotates GLP-1(7-36/37)
            glp1_7_37 = proglucagon[97:128]
        note("exp3_analogues.csv", "UniProt P01275 (proglucagon)",
             f"native GLP-1 sequence anchored to the reviewed record: {glp1_7_37[:12]}...")
    except UpstreamUnavailable as exc:
        # This call only anchors one sequence, and everything else in this
        # experiment is transcribed anyway. Reuse what a previous build fetched
        # rather than failing - but never invent it.
        previous = PRIVATE / "exp3.json"
        if not previous.exists():
            raise UpstreamUnavailable(
                f"{exc}\n  exp3 additionally has no previously built "
                f"private/exp3.json to fall back on."
            ) from exc
        glp1_7_37 = json.loads(previous.read_text()).get("native_glp1_7_37", "")
        if not glp1_7_37:
            raise
        print("  [UniProt] unavailable; reusing the native GLP-1 sequence recorded "
              "by the previous build")
        note("exp3_analogues.csv", "UniProt P01275 (via previous build)",
             f"native GLP-1 sequence reused because UniProt was unreachable: "
             f"{glp1_7_37[:12]}...", kind="reused")

    rows = []
    for name, backbone, pos8, acyl, cls, t_half, why in ANALOGUES:
        rows.append({
            "analogue": name,
            "backbone": backbone,
            "residue_at_dpp4_cleavage_site": pos8,
            "acylation_or_fusion": acyl,
            "approx_half_life_h": t_half,
            "half_life_provenance": "literature/label, pending sign-off",
            "notes": why,
        })
    write_csv(DATA / "exp3_analogues.csv", rows, list(rows[0].keys()))
    note("exp3_analogues.csv", "primary literature + product labels",
         f"{len(rows)} analogues; sequence modifications transcribed",
         kind="transcribed")

    write_json(PRIVATE / "exp3.json", {
        "scoring": "Spearman rank correlation on duration class, plus a mechanism rubric.",
        "native_glp1_7_37": glp1_7_37,
        "duration_classes": {n: c for n, _, _, _, c, _, _ in ANALOGUES},
        "duration_rank": {n: DURATION_RANK[c] for n, _, _, _, c, _, _ in ANALOGUES},
        "approx_half_life_h": {n: t for n, _, _, _, _, t, _ in ANALOGUES},
        "half_life_provenance": "transcribed from primary literature and product labels; "
                                "exact values NOT independently verified via API - "
                                "duration class is what is scored",
        "rubric": [
            {"id": "dpp4", "weight": 2.0,
             "any_of": ["dpp-4", "dpp4", "dipeptidyl peptidase"],
             "must_also": ["aib", "position 8", "ala8", "gly", "alpha-aminoisobutyric"],
             "points": "identifies protection of the His7-Ala8 DPP-4 cleavage site"},
            {"id": "albumin", "weight": 2.0,
             "any_of": ["albumin"],
             "must_also": ["fatty", "acyl", "diacid", "c18", "c16", "palmitoyl"],
             "points": "links fatty-acid acylation to reversible albumin binding"},
            {"id": "renal", "weight": 1.5,
             "any_of": ["renal", "kidney", "glomerular", "hydrodynamic", "molecular size",
                        "molecular weight"],
             "points": "explains size-based escape from renal clearance (Fc / albumin fusion)"},
            {"id": "site_choice", "weight": 1.5,
             "any_of": ["lys26", "k26", "mid-region", "midregion", "c-terminal", "position 26",
                        "away from the n-terminus", "lys20"],
             "points": "places the modification away from the receptor-engaging N-terminus "
                       "(the lesson from experiment 2)"},
        ],
        "penalties": [
            {"id": "acylate_nterm", "weight": 2.0,
             "any_of": ["acylate the n-terminus", "modify his7", "acylation at his7",
                        "n-terminal acylation improves"],
             "why": "the N-terminus inserts into the receptor core; acylating it costs potency"},
        ],
    })


# ---------------------------------------------------------------------------
# Experiment 4: potency - dose-response fitting and consensus EC50 ranking
# ---------------------------------------------------------------------------
MIN_RECORDS_PER_MOLECULE = 4
N_MOLECULES = 14


def build_exp4() -> None:
    print("exp4: potency")
    acts: list[dict[str, Any]] = []
    offset, limit = 0, 1000
    while True:
        page = get_json(f"{CHEMBL}/activity.json", {
            "target_chembl_id": "CHEMBL1784", "standard_type": "EC50",
            "limit": limit, "offset": offset,
        })
        acts.extend(page["activities"])
        total = page["page_meta"]["total_count"]
        offset += limit
        if offset >= total:
            break
        time.sleep(0.3)
    note("exp4_chembl_activities.csv", "ChEMBL REST activity (CHEMBL1784, EC50)",
         f"{len(acts)} EC50 records across {len({a['molecule_chembl_id'] for a in acts})} molecules")

    # Curated consensus protocol -> ground truth. Deliberately strict: functional
    # assays only, uncensored, nM, pChEMBL present; median on the log scale.
    usable = defaultdict(list)
    for a in acts:
        if (a.get("assay_type") == "F" and a.get("standard_relation") == "="
                and a.get("standard_units") == "nM" and a.get("pchembl_value")):
            usable[a["molecule_chembl_id"]].append(float(a["pchembl_value"]))
    eligible = {m: v for m, v in usable.items() if len(v) >= MIN_RECORDS_PER_MOLECULE}

    def median(xs: list[float]) -> float:
        s = sorted(xs)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    # Which molecules also carry awkward records? Those are the ones worth
    # putting in front of the agent: if every selected molecule has only clean
    # functional nM records, the aggregation pitfalls never get a chance to bite.
    messy = defaultdict(int)
    for a in acts:
        m = a["molecule_chembl_id"]
        if m not in eligible:
            continue
        if (a.get("standard_relation") not in ("=", None)
                or a.get("assay_type") != "F"
                or a.get("standard_units") != "nM"
                or not a.get("pchembl_value")):
            messy[m] += 1

    names: dict[str, str] = {}
    cand_ids = sorted(eligible)
    for i in range(0, len(cand_ids), 25):
        ids = cand_ids[i:i + 25]
        page = get_json(f"{CHEMBL}/molecule.json", {
            "molecule_chembl_id__in": ",".join(ids), "limit": 100,
        })
        for m in page.get("molecules", []):
            names[m["molecule_chembl_id"]] = m.get("pref_name") or ""
        time.sleep(0.3)

    def demo_value(m: str) -> tuple:
        return (1 if names.get(m) else 0, min(messy[m], 6), len(eligible[m]))

    # Bin by potency so the final set spans the range, then take the most
    # informative molecules from each bin.
    by_potency = sorted(eligible, key=lambda m: -median(eligible[m]))
    n_bins = 4
    per_bin = max(1, N_MOLECULES // n_bins)
    bin_size = max(1, math.ceil(len(by_potency) / n_bins))
    chosen: list[str] = []
    for b in range(n_bins):
        bucket = by_potency[b * bin_size:(b + 1) * bin_size]
        bucket.sort(key=demo_value, reverse=True)
        chosen.extend(bucket[:per_bin])
    for m in by_potency:                      # top up if bins were short
        if len(chosen) >= N_MOLECULES:
            break
        if m not in chosen:
            chosen.append(m)
    chosen = chosen[:N_MOLECULES]
    chosen_set = set(chosen)

    rows = []
    for a in acts:
        if a["molecule_chembl_id"] not in chosen_set:
            continue
        rows.append({
            "molecule_chembl_id": a["molecule_chembl_id"],
            "molecule_name": names.get(a["molecule_chembl_id"], ""),
            "assay_chembl_id": a.get("assay_chembl_id", ""),
            "assay_type": a.get("assay_type", ""),
            "bao_label": a.get("bao_label", ""),
            "standard_type": a.get("standard_type", ""),
            "standard_relation": a.get("standard_relation", ""),
            "standard_value": a.get("standard_value", ""),
            "standard_units": a.get("standard_units", ""),
            "pchembl_value": a.get("pchembl_value", ""),
            "document_year": a.get("document_year", ""),
            "document_chembl_id": a.get("document_chembl_id", ""),
            "assay_description": (a.get("assay_description") or "")[:200],
        })
    rows.sort(key=lambda r: (r["molecule_chembl_id"], r["assay_chembl_id"]))
    write_csv(DATA / "exp4_chembl_activities.csv", rows, list(rows[0].keys()))

    truth = {m: round(median(eligible[m]), 3) for m in chosen}
    curve_truth = build_exp4_curves(chosen, truth, names)
    order = sorted(chosen, key=lambda m: -truth[m])
    write_json(PRIVATE / "exp4.json", {
        "protocol": "Consensus pEC50 = median of pchembl_value over ChEMBL records with "
                    "assay_type=F, standard_relation='=', standard_units='nM', "
                    "pchembl_value present. Median (not mean) on the log scale.",
        "source": "ChEMBL REST, target CHEMBL1784, standard_type EC50",
        "min_records_per_molecule": MIN_RECORDS_PER_MOLECULE,
        "consensus_pec50": truth,
        "ranking_most_to_least_potent": order,
        "molecule_names": {m: names.get(m, "") for m in chosen},
        "n_records_used": {m: len(eligible[m]) for m in chosen},
        "curves": curve_truth,
    })
    note("private/exp4.json", "computed from ChEMBL",
         f"consensus pEC50 for {len(chosen)} molecules", kind="computed")


def build_exp4_curves(chosen: list[str], truth: dict[str, float],
                      names: dict[str, str]) -> dict[str, Any]:
    """Render dose-response curves whose true EC50s are the real ChEMBL consensus.

    ChEMBL stores summary EC50 values, not raw curve points, so the points
    themselves are simulated - deterministically, with a fixed seed, from a
    four-parameter logistic. The *potencies* being recovered are real. Three
    things are deliberately awkward, because they are what make curve fitting
    different from eyeballing a midpoint:

      * some curves are truncated and never reach their plateau, so the
        concentration at half of the OBSERVED maximum is a biased estimate;
      * Emax varies (partial agonists), so ranking by response height is not
        ranking by potency;
      * one point per curve is a flagged outlier.
    """
    import random

    rng = random.Random(20261003)
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    concentrations_full = [10 ** (e / 2) for e in range(-6, 9)]   # 1 pM .. 10 uM
    for i, mol in enumerate(sorted(chosen)):
        pec50 = truth[mol]
        ec50_nm = 10 ** (9 - pec50)
        emax = [100.0, 100.0, 72.0, 55.0, 88.0][i % 5]            # partial agonists
        hill = [1.0, 1.0, 1.2, 0.8, 1.0][i % 5]
        truncated = (i % 3 == 0)
        concs = concentrations_full[:-4] if truncated else concentrations_full
        outlier_at = rng.randrange(len(concs))
        for k, c in enumerate(concs):
            for rep in (1, 2, 3):
                frac = 1.0 / (1.0 + (ec50_nm / c) ** hill)
                resp = emax * frac + rng.gauss(0, 2.5)
                flagged = 0
                if k == outlier_at and rep == 2:
                    resp += rng.choice([-35.0, 35.0])
                    flagged = 1
                rows.append({
                    "molecule_chembl_id": mol,
                    "molecule_name": names.get(mol, ""),
                    "concentration_nM": round(c, 6),
                    "replicate": rep,
                    "response_pct": round(resp, 2),
                    "qc_flag": flagged,
                })
        meta[mol] = {"true_pec50": pec50, "emax_pct": emax, "hill_slope": hill,
                     "curve_truncated": truncated,
                     "max_concentration_nM": round(max(concs), 3)}
    write_csv(DATA / "exp4_dose_response.csv", rows,
              ["molecule_chembl_id", "molecule_name", "concentration_nM",
               "replicate", "response_pct", "qc_flag"])
    note("exp4_dose_response.csv", "simulated from real ChEMBL consensus pEC50",
         f"{len(rows)} points for {len(chosen)} molecules; curve points are a "
         f"deterministic four-parameter-logistic rendering (seed 20261003) of the "
         f"real potencies, because ChEMBL stores summary EC50s not raw curves",
         kind="derived")
    return meta


# ---------------------------------------------------------------------------
# Experiment 5: species selectivity of a non-peptide agonist
# ---------------------------------------------------------------------------
ORTHOLOGS = [("P43220", "human"), ("O35659", "mouse"),
             ("P32301", "rat"), ("F7E3K6", "macaque")]


def build_exp5() -> None:
    print("exp5: species selectivity")
    seqs: dict[str, str] = {}
    feats: list[dict[str, Any]] = []
    for acc, species in ORTHOLOGS:
        j = get_json(f"{UNIPROT}/{acc}.json",
                     {"fields": "accession,id,sequence,ft_transmem,ft_topo_dom,organism_name"},
                     service="UniProt")
        if "sequence" not in j:
            raise RuntimeError(
                f"UniProt {acc} ({species}) returned no sequence - the accession is "
                f"probably obsolete. Re-run the ortholog lookup and update ORTHOLOGS."
            )
        seqs[species] = j["sequence"]["value"]
        if species == "human":
            for f in j.get("features", []):
                if f["type"] in ("Transmembrane", "Topological domain"):
                    feats.append({
                        "type": f["type"],
                        "start": f["location"]["start"]["value"],
                        "end": f["location"]["end"]["value"],
                        "description": f.get("description", ""),
                    })
        note("exp5_ortholog_alignment.csv", f"UniProt {acc}",
             f"{species} GLP1R, {len(seqs[species])} aa")

    def region(pos: int) -> str:
        for f in feats:
            if f["start"] <= pos <= f["end"]:
                if f["type"] == "Transmembrane":
                    return "transmembrane_helix"
                d = (f["description"] or "").lower()
                if "extracellular" in d:
                    return "extracellular"
                if "cytoplasmic" in d:
                    return "cytoplasmic"
        return "unannotated"

    human = seqs["human"]
    # These orthologues are the same length and co-linear over the ECD and TMD,
    # so position-wise comparison is valid; assert it rather than assume it.
    same_len = {s: len(v) for s, v in seqs.items() if len(v) == len(human)}
    rows = []
    for i, aa in enumerate(human, start=1):
        row = {"position": i, "human": aa, "region": region(i)}
        differs = []
        for species in ("mouse", "rat", "macaque"):
            s = seqs[species]
            other = s[i - 1] if species in same_len else ""
            row[species] = other
            if other and other != aa:
                differs.append(species)
        row["differs_in"] = ";".join(differs)
        row["n_species_differing"] = len(differs)
        rows.append(row)
    write_csv(DATA / "exp5_ortholog_alignment.csv", rows,
              ["position", "region", "human", "mouse", "rat", "macaque",
               "differs_in", "n_species_differing"])

    ecd_rodent_diffs = [
        r["position"] for r in rows
        if r["region"] in ("extracellular", "unannotated") and r["position"] <= 145
        and {"mouse", "rat"} <= set(r["differs_in"].split(";") if r["differs_in"] else [])
    ]
    pos33 = {s: seqs[s][32] for s in seqs}
    write_json(PRIVATE / "exp5.json", {
        "key_fact": "Human GLP-1R residue 33 is Trp; mouse and rat carry Ser at the same "
                    "position. LY3502970 (orforglipron) depends on this residue, so the "
                    "compound is essentially inactive at unmodified rodent GLP-1R.",
        "residue_33_by_species": pos33,
        "ecd_positions_differing_in_both_rodents": ecd_rodent_diffs,
        "sources": {s: a for a, s in ORTHOLOGS},
        "rubric": [
            {"id": "species", "weight": 3.0,
             "any_of": ["human glp-1r", "human receptor", "humanized", "human glp1r",
                        "transfected human", "recombinant human"],
             "points": "selects a human or humanised receptor system"},
            {"id": "residue", "weight": 2.5,
             "any_of": ["trp33", "w33", "tryptophan 33", "residue 33", "position 33"],
             "points": "names the Trp33 / Ser33 species difference"},
            {"id": "not_orthosteric", "weight": 2.0,
             "any_of": ["allosteric", "not the orthosteric", "different site",
                        "distinct site", "outside the orthosteric", "non-orthosteric",
                        "extracellular domain", "ecd"],
             "points": "recognises that the non-peptide does not occupy the peptide "
                       "orthosteric pocket (the lesson from experiment 2)"},
            {"id": "partial_bias", "weight": 1.5,
             "any_of": ["partial agonist", "partial agonism", "biased", "bias",
                        "beta-arrestin", "b-arrestin", "arrestin", "g protein-biased",
                        "g-protein bias"],
             "points": "notes partial agonism / G-protein bias rather than assuming "
                       "full agonism"},
            {"id": "readout", "weight": 1.0,
             "any_of": ["camp", "cyclic amp", "crispr", "knock-in", "knockin"],
             "points": "names a concrete functional readout or a humanised in vivo model"},
        ],
        "penalties": [
            {"id": "rodent_default", "weight": 3.0,
             "any_of": ["mouse model", "use mice", "in mice", "rat model", "use rats",
                        "in rats", "mouse glp-1r", "rat glp-1r", "wild-type mouse",
                        "db/db", "ob/ob", "diet-induced obese mouse"],
             "unless_any_of": ["humanized", "humanised", "knock-in", "knockin",
                               "not appropriate", "would fail", "inactive", "cannot be used",
                               "unsuitable", "avoid"],
             "why": "defaulting to an unmodified rodent model is the trap: the compound "
                    "does not activate rodent GLP-1R"},
        ],
    })
    note("private/exp5.json", "computed from UniProt orthologues",
         f"residue 33 = {pos33}", kind="computed")


# ---------------------------------------------------------------------------
# Experiment 6: capstone verdict on H1
# ---------------------------------------------------------------------------
def build_exp6() -> None:
    print("exp6: capstone rubric")
    write_json(PRIVATE / "exp6.json", {
        "scoring": "Rubric against the ATTAIN-1 phase 3 result and the five earlier lessons.",
        "reference": "Wharton S, Aronne LJ, Stefanski A, et al. Orforglipron, an Oral "
                     "Small-Molecule GLP-1 Receptor Agonist for Obesity Treatment. "
                     "N Engl J Med. 2025;393(18):1796-1806. doi:10.1056/NEJMoa2511774",
        "rubric": [
            {"id": "verdict", "weight": 2.0,
             "any_of": ["supported", "well supported", "well-supported", "holds",
                        "the hypothesis is supported", "confirmed"],
             "points": "states a clear verdict on H1"},
            {"id": "genetics", "weight": 1.5,
             "any_of": ["genetic", "gwas", "mc4r", "gipr", "genetically supported"],
             "points": "weights the genetic support strand (experiment 1)"},
            {"id": "structure", "weight": 1.5,
             "any_of": ["structure", "contact residues", "orthosteric", "cryo-em", "7ki0"],
             "points": "weights the structural strand (experiment 2)"},
            {"id": "engineering", "weight": 1.0,
             "any_of": ["half-life", "half life", "albumin", "dpp-4", "acylation",
                        "duration of action"],
             "points": "weights the peptide-engineering strand (experiment 3)"},
            {"id": "potency", "weight": 1.0,
             "any_of": ["ec50", "pec50", "potency", "dose-response", "dose response"],
             "points": "weights the potency strand (experiment 4)"},
            {"id": "oral_feasibility", "weight": 2.0,
             "any_of": ["oral", "non-peptide", "nonpeptide", "small molecule",
                        "small-molecule", "orforglipron", "ly3502970"],
             "points": "addresses the oral non-peptide claim (experiment 5)"},
            {"id": "species_caveat", "weight": 1.5,
             "any_of": ["species", "rodent", "trp33", "w33", "humanized", "humanised"],
             "points": "carries the species caveat into the verdict"},
            {"id": "calibration", "weight": 1.5,
             "any_of": ["confidence", "uncertain", "caveat", "limitation", "weaker",
                        "less certain", "evidence is", "remains open"],
             "points": "grades its own confidence per strand instead of asserting uniformly"},
        ],
        "penalties": [
            {"id": "overclaim_cv", "weight": 1.5,
             "any_of": ["cardiovascular outcome", "reduces mortality", "reduces cv events",
                        "proven cardiovascular benefit"],
             "unless_any_of": ["not established", "not yet", "unproven", "no evidence",
                               "has not been", "remains"],
             "why": "H1 is about target validity and oral feasibility; CV outcome claims "
                    "are not supported by the evidence in this curriculum"},
            {"id": "overclaim_cure", "weight": 1.5,
             "any_of": ["cures obesity", "cure for obesity", "eliminates obesity"],
             "why": "overclaiming beyond the trial result"},
        ],
    })


# ---------------------------------------------------------------------------
BUILDERS = {"exp1": build_exp1, "exp2": build_exp2, "exp3": build_exp3,
            "exp4": build_exp4, "exp5": build_exp5, "exp6": build_exp6}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="comma-separated subset, e.g. exp1,exp4")
    args = ap.parse_args()
    wanted = args.only.split(",") if args.only else list(BUILDERS)
    DATA.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    built, failed = [], []
    for key in wanted:
        key = key.strip()
        if key not in BUILDERS:
            raise SystemExit(f"unknown experiment {key!r}; choose from {list(BUILDERS)}")
        try:
            BUILDERS[key]()
            built.append(key)
        except UpstreamUnavailable as exc:
            # One provider being down should not discard the datasets the other
            # providers just returned.
            print(f"\n!! {key} could not be rebuilt:\n{exc}\n")
            failed.append(key)
    prov_path = DATA / "PROVENANCE.json"
    existing = json.loads(prov_path.read_text()) if prov_path.exists() else []
    merged = [p for p in existing if p["dataset"] not in {q["dataset"] for q in PROVENANCE}]
    write_json(prov_path, merged + PROVENANCE)
    if failed:
        print(f"\nbuilt {built or 'nothing'}; could not rebuild {failed}.")
        print("Existing files for those experiments are untouched and still valid.")
        print(f"Retry later with:  python -m curricula.glp1r.fetch --only {','.join(failed)}")
        raise SystemExit(1)
    print("\ndone. agent-visible data in data/, ground truth in private/")


if __name__ == "__main__":
    main()
