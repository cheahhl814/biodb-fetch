#!/usr/bin/env python3
"""OBIS (Ocean Biodiversity Information System) occurrence retrieval under the manifest.tsv contract.

Public API (api.obis.org/v3) via the pyobis client (iobis/pyobis, MIT) — no credentials for the
search/download tier. Filters: scientificname, taxonid, datasetid, nodeid, dates, depths,
geometry (WKT polygon/box), and extended measurement/mof data.

Subcommands:
  occurrence  --name "Chelonia mydas" [--wkt POLYGON(...)] [--from-year 2010] [--to-year] [--datasetid] [--deep-only]
  checklist   --name "Perciformes"          (species checklist under a taxon)
  datasets    --name "Chelonia mydas"       (dataset metadata feeding the region/coverage tables)

OBIS↔GBIF duality note: OBIS is the marine complement to GBIF occurrence data; consumers
(occurrence-crosscheck, edna-gbif-publish) join on scientific name + AphiaID↔GBIF taxonKey.
"""
from __future__ import annotations

import argparse
import json
import os

from pyobis import occurrences as obis_occ
from pyobis import checklist as obis_chk
from pyobis import dataset as obis_ds

from dbaccess_common import (CONTRACT_VERSION, common_args, manifest_append, now_utc,
                             sidecar_match, sidecar_write, store_payload_path)

TOOL = "dbaccess-occurrence_marine 1.0.0"


def _frames_to_json(obj) -> str:
    """pyobis returns pandas/records-ish structures; serialize plainly."""
    try:
        import pandas as pd
        if isinstance(obj, pd.DataFrame):
            return obj.to_json(orient="records", lines=True)
        if hasattr(obj, "data"):
            return _frames_to_json(obj.data)
    except ImportError:
        pass
    if isinstance(obj, (list, dict)):
        return json.dumps(obj)
    return json.dumps(str(obj))


def write_out(outdir: str, basename: str, content: str, fmt: str = "json", identity: dict | None = None,
              refresh: bool = False) -> tuple[str, bool]:
    """Write to the shared store (deterministic path); returns (dest, hit).

    CAVEAT baked into the runbook: OBIS occurrence data grows over time — a cache hit
    reflects retrieval_date in the manifest; consumers set freshness windows and use
    --refresh for re-pulls."""
    os.makedirs(outdir, exist_ok=True)
    identity = identity or {"slug": basename}
    dest = store_payload_path("occurrence-marine", identity, fmt)
    if sidecar_match(dest) and not refresh:
        return dest, True
    with open(dest + ".part", "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(dest + ".part", dest)
    sidecar_write(dest)
    return dest, False


def do_occurrence(args, outdir: str) -> list[dict]:
    kw = {"scientificname": args.name}
    if args.wkt:
        kw["geometry"] = args.wkt
    if args.from_year and args.to_year:
        kw["startdate"] = f"{args.from_year}-01-01"
        kw["enddate"] = f"{args.to_year}-12-31"
    if args.datasetid:
        kw["datasetid"] = args.datasetid
    identity = {"slug": f"obis_{args.name.replace(' ', '_')}", "wkt": args.wkt,
                "years": [args.from_year, args.to_year], "datasetid": args.datasetid,
                "limit": args.limit}
    dest = store_payload_path("occurrence-marine", identity, "json")
    if sidecar_match(dest) and not args.refresh:
        return [{"accession": args.name, "source": "obis-api-occurrence",
                 "url": "-", "path": dest, "tool": TOOL, "format": "json", "cache": "hit"}]
    q = obis_occ.search(limit=args.limit, **kw)
    q.execute()
    payload = _frames_to_json(q.data)
    dest = write_out(outdir, f"obis_{args.name.replace(' ', '_')}", payload,
                     identity=identity, refresh=args.refresh)
    return [{"accession": args.name, "source": "obis-api-occurrence",
             "url": q.api_url, "path": dest, "tool": TOOL, "format": "json", "cache": "miss"}]


def do_checklist(args, outdir: str) -> list[dict]:
    identity = {"slug": f"obis_checklist_{args.name.replace(' ', '_')}", "limit": args.limit}
    dest = store_payload_path("occurrence-marine", identity, "json")
    if sidecar_match(dest) and not args.refresh:
        return [{"accession": args.name, "source": "obis-api-checklist",
                 "url": "-", "path": dest, "tool": TOOL, "format": "json", "cache": "hit"}]
    q = obis_chk.list(scientificname=args.name)
    q.execute()
    payload = _frames_to_json(q.data)
    dest = write_out(outdir, f"obis_checklist_{args.name.replace(' ', '_')}", payload,
                     identity=identity, refresh=args.refresh)
    return [{"accession": args.name, "source": "obis-api-checklist",
             "url": q.api_url, "path": dest, "tool": TOOL, "format": "json", "cache": "miss"}]


def do_datasets(args, outdir: str) -> list[dict]:
    identity = {"slug": f"obis_datasets_{args.name.replace(' ', '_')}", "limit": args.limit}
    dest = store_payload_path("occurrence-marine", identity, "json")
    if sidecar_match(dest) and not args.refresh:
        return [{"accession": args.name, "source": "obis-api-dataset",
                 "url": "-", "path": dest, "tool": TOOL, "format": "json", "cache": "hit"}]
    q = obis_ds.search(scientificname=args.name, limit=args.limit)
    q.execute()
    payload = _frames_to_json(q.data)
    dest = write_out(outdir, f"obis_datasets_{args.name.replace(' ', '_')}", payload,
                     identity=identity, refresh=args.refresh)
    return [{"accession": args.name, "source": "obis-api-dataset",
             "url": q.api_url, "path": dest, "tool": TOOL, "format": "json", "cache": "miss"}]


def main() -> int:
    ap = argparse.ArgumentParser(description="OBIS marine occurrence retrieval under the manifest.tsv contract")
    common_args(ap)
    ap.add_argument("cmd", choices=["occurrence", "checklist", "datasets"])
    ap.add_argument("--name", required=True, help="scientific name (species or taxon)")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--wkt", help="WKT polygon/bounding box, e.g. 'POLYGON((x y, ...))'")
    ap.add_argument("--from-year", type=int)
    ap.add_argument("--to-year", type=int)
    ap.add_argument("--datasetid", help="OBIS dataset uuid")
    args = ap.parse_args()
    args.outdir = args.outdir.rstrip("/") or "./work/database-access"
    fn = {"occurrence": do_occurrence, "checklist": do_checklist, "datasets": do_datasets}[args.cmd]
    rows = fn(args, args.outdir)
    mpath = manifest_append(args.outdir, rows, TOOL)
    print(mpath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())