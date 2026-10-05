#!/usr/bin/env python3
"""Taxonomy backbone retrieval under the manifest.tsv contract.

Three sources, deliberately small and fetch-only:
  ncbi     NCBI Datasets v2 taxonomy (summary/names/children) — via `datasets` CLI, already in pixi.toml
  colxr    Catalogue of Life Extended Release via ChecklistBank API (api.checklistbank.org)
           — the NEW GBIF default backbone (GBIF Backbone frozen 2023; rgbif 3.9 migration documents it)
  worms    World Register of Marine Species REST (marinespecies.org/rest) — the marine backbone;
           OBIS records key on AphiaIDs; fuzzy matching + synonym flattening + vernaculars

Consumers use this to resolve name → canonical ID, synonym flattening, or children lists.

Usage:
  taxonomy.py ncbi --query "Canis lupus" [--children]
  taxonomy.py ncbi --taxid 9612
  taxonomy.py colxr --name "Panthera leo" [--dataset 7ddf754f-d193-4cc9-b351-99906754a03b]
  taxonomy.py worms --name "Thunnus thynnus" [--fuzzy] [--synonyms] [--vernacular]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess

import requests

from dbaccess_common import (CONTRACT_VERSION, HEADERS, RateLimiter, common_args, manifest_append,
                             now_utc, sidecar_match, sidecar_write, store_payload_path)

TOOL = "dbaccess-taxonomy 1.0.0"
COL_XR_KEY = "7ddf754f-d193-4cc9-b351-99906754a03b"  # GBIF's migration post points here


def ncbi_tax(args, outdir: str) -> list[dict]:  # store-aware
    if not shutil.which("datasets"):
        raise SystemExit("datasets CLI not on PATH — run via `pixi run python3 …/taxonomy.py`")
    proc_args = ["datasets", "summary", "taxonomy", "taxon"]
    proc_args.append(args.taxid if args.taxid else f'"{args.query}"')
    if args.children:
        proc_args = ["datasets", "download", "taxonomy", "taxon", args.taxid or args.query, "--children"]
    key = args.taxid or args.query.replace(" ", "_")
    identity = {"slug": f"ncbi_tax_{key}", "children": args.children}
    dest_est = store_payload_path("taxonomy", identity, "zip" if args.children else "jsonl")
    if sidecar_match(dest_est) and not args.refresh:
        return [{"accession": key, "source": "ncbi-datasets-taxonomy", "url": "-",
                 "path": dest_est, "tool": TOOL, "format": "json", "cache": "hit"}]
    proc = subprocess.run(proc_args, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"datasets taxonomy failed: {proc.stderr.decode(errors='replace')[:300]}")
    payload = proc.stdout or proc.stderr
    dest = store_payload_path("taxonomy", identity, "zip" if args.children else "jsonl")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "wb").write(payload)
    sidecar_write(dest)
    return [{"accession": key, "source": "ncbi-datasets-taxonomy", "url": "-",
             "path": dest, "tool": TOOL, "format": "json", "cache": "miss"}]


def worms(args, outdir: str) -> list[dict]:
    """WoRMS REST: name→AphiaID (+accepted name, synonyms, fuzzy matches, vernaculars)."""
    base = "https://marinespecies.org/rest"
    rate = RateLimiter(0.2)
    lookup = {}
    names = [args.name]
    if args.names_file:
        names += [ln.strip() for ln in open(args.names_file, encoding="utf-8") if ln.strip()]
    for name in names:
        rate.wait()
        if args.fuzzy:
            resp = requests.post("https://marinespecies.org/rest/AphiaRecordsByMatchNames",
                                 data={"scientificnames[]": name, "fuzzy": "true", "marine_only": "true"},
                                 headers=HEADERS, timeout=(15, 120))
        else:
            resp = requests.get(f"{base}/AphiaRecordsByName/{requests.utils.quote(name)}",
                                headers=HEADERS, timeout=(15, 120), params={"marine_only": "true"})
        resp.raise_for_status()
        try:
            lookup[name] = resp.json()
        except json.JSONDecodeError:
            lookup[name] = ["empty (name not found)"]
        aphia = None
        rec = lookup[name]
        if isinstance(rec, list) and rec and isinstance(rec[0], dict):
            aphia = rec[0].get("AphiaID")
        if aphia and args.synonyms:
            rate.wait()
            lookup[name + " [synonyms]"] = requests.get(
                f"{base}/AphiaSynonymsByID/{aphia}", headers=HEADERS, timeout=(15, 120)).json()
        if aphia and args.vernacular:
            rate.wait()
            lookup[name + " [vernaculars]"] = requests.get(
                f"{base}/AphiaVernacularsByID/{aphia}", headers=HEADERS, timeout=(15, 120)).json()
    identity = {"slug": f"worms_{args.name.replace(' ', '_')}", "fuzzy": args.fuzzy,
                "synonyms": args.synonyms, "vernacular": args.vernacular}
    dest, hit = write_out(outdir, f"worms_{args.name.replace(' ', '_')}", json.dumps(lookup),
                          identity=identity, refresh=args.refresh)
    return [{"accession": args.name, "source": "worms-rest-aphia",
             "url": base, "path": dest, "tool": TOOL, "format": "json", "cache": "hit" if hit else "miss"}]


def write_out(outdir: str, basename: str, content, fmt: str = "json", identity: dict | None = None,
              refresh: bool = False) -> tuple[str, bool]:
    """Write to the shared store (deterministic path); returns (dest, hit)."""
    identity = identity or {"slug": basename}
    dest = store_payload_path("taxonomy", identity, fmt)
    if sidecar_match(dest) and not refresh:
        return dest, True
    with open(dest + ".part", "w", encoding="utf-8") as fh:
        fh.write(content if isinstance(content, str) else json.dumps(content))
    os.replace(dest + ".part", dest)
    sidecar_write(dest)
    return dest, False


def colxr(args, outdir: str) -> list[dict]:
    """ChecklistBank name-usage lookup (COL XR). GET /nameusage/search?q=<name>&dataset=<key>."""
    rate = RateLimiter(0.2)
    rate.wait()
    params = {"q": args.name, "dataset": args.dataset or COL_XR_KEY, "limit": 20}
    resp = requests.get("https://api.checklistbank.org/nameusage/search", headers=HEADERS, params=params, timeout=(15, 120))
    resp.raise_for_status()
    data = resp.json()
    identity = {"slug": f"colxr_{args.name.replace(' ', '_')}", "dataset": args.dataset or COL_XR_KEY}
    dest, hit = write_out(outdir, f"colxr_{args.name.replace(' ', '_')}", json.dumps(data),
                          identity=identity, refresh=args.refresh)
    return [{"accession": args.name, "source": "checklistbank-colxr",
             "url": str(resp.url), "path": dest, "tool": TOOL, "format": "json", "cache": "hit" if hit else "miss"}]


def main() -> int:
    ap = argparse.ArgumentParser(description="Taxonomy backbone retrieval under the manifest.tsv contract")
    common_args(ap)
    ap.add_argument("src", choices=["ncbi", "colxr", "worms"])
    ap.add_argument("--query", help="NCBI scientific/common name")
    ap.add_argument("--taxid", help="NCBI taxonomy id")
    ap.add_argument("--name", help="COL XR scientific name")
    ap.add_argument("--children", action="store_true", help="download taxonomy data package with all children")
    ap.add_argument("--dataset", default=None, help="ChecklistBank dataset UUID (default: GBIF's COL XR checklistKey)")
    ap.add_argument("--fuzzy", action="store_true", help="WoRMS: fuzzy/near name matching")
    ap.add_argument("--synonyms", action="store_true", help="WoRMS: also fetch synonym list for the resolved AphiaID")
    ap.add_argument("--vernacular", action="store_true", help="WoRMS: also fetch vernacular (common) names")
    ap.add_argument("--names-file", help="WoRMS: additional names, one per line, appended to --name")
    args = ap.parse_args()
    args.outdir = args.outdir.rstrip("/") or "./work/database-access"
    os.makedirs(args.outdir, exist_ok=True)
    if args.src == "ncbi" and not (args.taxid or args.query):
        raise SystemExit("ncbi needs --taxid or --query")
    if args.src == "colxr" and not args.name:
        raise SystemExit("colxr needs --name")
    if args.src == "worms" and not args.name:
        raise SystemExit("worms needs --name")
    rows = {"ncbi": ncbi_tax, "colxr": colxr, "worms": worms}[args.src](args, args.outdir)
    mpath = manifest_append(args.outdir, rows, TOOL)
    print(mpath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())