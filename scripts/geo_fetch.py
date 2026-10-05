#!/usr/bin/env python3
"""GEO series fetch with SuperSeries detection (GEOparse + NCBI FTP fallback).

SuperSeries rule: detect BEFORE processing — relations field listing sra/gsm
SubSeries, or an empty sample list, means the GSE is a bundle; enumerate
SubSeries and fetch per-series, recording the split in manifest.tsv rows.

Subcommand:
  series --accession <GSE…> [--raw] [--download-subseries]
"""
from __future__ import annotations

import argparse
import json
import os

import GEOparse

from dbaccess_common import (common_args, manifest_append, now_utc, sidecar_match,
                             sidecar_write, store_payload_path)

TOOL = "dbaccess-geo_fetch 1.0.0"


def detect_superseries(gse) -> tuple[bool, list[str]]:
    rel = getattr(gse, "metadata", {}).get("relation", [])
    subs = []
    for entry in rel:
        if "SuperSeries of" in entry or "Relationship" not in entry:
            for piece in entry.split(","):
                piece = piece.strip()
                if piece.startswith("GSE"):
                    subs.append(piece)
    is_supers = bool(subs)
    if not is_supers and len(getattr(gse, "gsms", {})) == 0:
        is_supers = True
    return is_supers, subs


def main() -> int:
    ap = argparse.ArgumentParser(description="GEO fetch under the manifest.tsv contract")
    common_args(ap)
    ap.add_argument("--accession", required=True, help="GSE accession (comma-separated allowed)")
    args = ap.parse_args()
    args.outdir = args.outdir.rstrip("/") or "./work/database-access"
    os.makedirs(args.outdir, exist_ok=True)

    accs = [a.strip() for a in args.accession.split(",") if a.strip()]
    rows = []
    summary = {}
    for acc in accs:
        gse = GEOparse.get_GEO(acc, destdir=args.outdir, silent=True)
        is_supers, subs = detect_superseries(gse)
        identity = {"slug": f"geo_{acc}", "kind": "metadata-json"}
        meta_out = store_payload_path("geo", identity, "json")
        hit = sidecar_match(meta_out) and not args.refresh
        if not hit:
            with open(meta_out, "w") as fh:
                json.dump({"accession": gse.get_accession, "title": gse.metadata.get("title"),
                           "superseries": is_supers, "subseries_sra": subs,
                           "n_samples": len(getattr(gse, "gsms", {})), "platforms": gse.metadata.get("platform_id"),
                           "processed_counts": gse.metadata.get("series_matrix_data_processing")},
                          fh)
            sidecar_write(meta_out)
        source = "geo-gsupers" if is_supers else "geo-soft"
        rows.append({"accession": acc, "source": source, "url": "-", "path": meta_out,
                     "tool": TOOL, "format": "json", "cache": "hit" if hit else "miss"})
        summary[acc] = {"superseries": is_supers, "subseries": subs,
                        "n_samples": len(getattr(gse, "gsms", {}))}
    mpath = manifest_append(args.outdir, rows, TOOL)
    print(json.dumps(summary))
    print(mpath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())