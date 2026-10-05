#!/usr/bin/env python3
"""Pre-computed ortholog retrieval (OrthoDB / Ensembl Compara / NCBI Datasets).

NEVER computes orthologs de novo — that is the separate `ortholog-inference`
skill (OrthoFinder3/HOGs/species trees). This script only RETRIEVES existing
pre-computed orthology entries.

Source selection (pick by taxonomic scope + confidence needs):
  - ncbi-datasets ortholog report: fast, broad, no confidence score
  - ensembl-compara: high/low confidence, singlelink/treeb methods, good for vertebrates
  - orthodb: deepest precomputed coverage (HOGs), broad eukaryotes

Subcommands:
  orthodb --gene <id|acc> [--level <taxlevel>]
  compara --gene <ensembl_id> --type orthologues
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import requests

from dbaccess_common import (CONTRACT_VERSION, HEADERS, RateLimiter, common_args, manifest_append,
                             now_utc, sidecar_match, sidecar_write, store_payload_path)

TOOL = "dbaccess-orthologs_fetch 1.0.0"


def orthodb_lookup(gene: str, taxlevel: str | None, outdir: str, args=None):
    """OrthoDB REST: https://www.orthodb.org/v12/search?query=<gene>&level=<taxid>."""
    rate = RateLimiter(0.5)
    rate.wait()
    params = {"query": gene}
    if taxlevel:
        params["level"] = taxlevel
    resp = requests.get("https://www.orthodb.org/v12/search", headers=HEADERS, params=params, timeout=(15, 120))
    resp.raise_for_status()
    data = resp.json()
    identity = {"slug": f"orthodb_{gene}_{taxlevel or 'root'}", "cmd": "orthodb"}
    out = store_payload_path("orthologs-precomputed", identity, "json")
    if sidecar_match(out) and not getattr(args, 'refresh', False):
        return out, data
    with open(out, "w") as fh:
        json.dump(data, fh)
    sidecar_write(out)
    return out, data


def compara_lookup(gene: str, ortho_type: str, outdir: str, args=None):
    """Ensembl Compara homology REST: /homology/id/geneId with type filter."""
    rate = RateLimiter(0.1)  # REST limit ~15 req/s
    rate.wait()
    resp = requests.get(
        f"https://rest.ensembl.org/homology/id/{gene}",
        headers={**HEADERS, "Accept": "application/json"},
        params={"type": ortho_type},
        timeout=(15, 120),
    )
    resp.raise_for_status()
    data = resp.json()
    identity = {"slug": f"compara_{gene}_{ortho_type}", "cmd": "compara"}
    out = store_payload_path("orthologs-precomputed", identity, "json")
    if sidecar_match(out) and not getattr(args, 'refresh', False):
        return out, data
    with open(out, "w") as fh:
        json.dump(data, fh)
    sidecar_write(out)
    return out, data


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-computed ortholog retrieval under the manifest.tsv contract")
    common_args(ap)
    ap.add_argument("cmd", choices=["orthodb", "compara"])
    ap.add_argument("--gene", required=True)
    ap.add_argument("--level", default=None, help="OrthoDB taxonomic level (NCBI taxid)")
    ap.add_argument("--type", default="orthologues", dest="ortho_type")
    args = ap.parse_args()
    args.outdir = args.outdir.rstrip("/") or "./work/database-access"
    os.makedirs(args.outdir, exist_ok=True)

    if args.cmd == "orthodb":
        out, data = orthodb_lookup(args.gene, args.level, args.outdir, args)
        source = "orthodb-v12-rest"
    else:
        out, data = compara_lookup(args.gene, args.ortho_type, args.outdir, args)
        source = "ensembl-compara-rest"
    rows = [{"accession": args.gene, "source": source, "url": "-", "path": out,
             "tool": TOOL, "format": "json", "cache": "hit" if sidecar_match(out) and not args.refresh else "miss"}]
    mpath = manifest_append(args.outdir, rows, TOOL)
    print(json.dumps(data)[:400])
    print(mpath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())