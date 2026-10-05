#!/usr/bin/env python3
"""ID mapping: BioMart (bulk, thousands of IDs) / UniProt REST (async job, protein-centric).

Routing rule: BioMart for bulk (>5K IDs — one query, never a per-ID REST loop);
UniProt for protein-centric mappings and current-accession resolution; Ensembl
REST for single lookups only.

Subcommands:
  biomart  --ids-file <txt one-per-line> --from <attr> --to <attr> [--dataset dataset_name]
  uniprot  --ids-file <txt one-per-line> [--from-id <db>] [--to-id <db>]
"""
from __future__ import annotations

import argparse
import json
import os
import time

import requests

from dbaccess_common import (CONTRACT_VERSION, HEADERS, RateLimiter, common_args, manifest_append,
                             now_utc, sidecar_match, sidecar_write, store_payload_path)

TOOL = "dbaccess-idmap 1.0.0"


def read_ids(path: str) -> list[str]:
    return [ln.strip() for ln in open(path, encoding="utf-8") if ln.strip() and not ln.startswith("#")]


def biomart_map(ids: list[str], from_attr: str, to_attr: str, dataset_name: str, outdir: str, refresh: bool = False):
    from pybiomart import Dataset

    ds = Dataset(name=dataset_name, host="http://www.ensembl.org")
    table = ds.query(attributes=[from_attr, to_attr], filters={from_attr: ids})
    identity = {"slug": f"biomart_{from_attr}_to_{to_attr}_{dataset_name}",
                "ids": sorted(set(ids)), "ids_n": len(ids)}
    out = store_payload_path("id-mapping", identity, "tsv")
    hit = sidecar_match(out) and not refresh
    if not hit:
        table.to_csv(out, sep="\t", index=False)
        sidecar_write(out)
    return out, table


def uniprot_async(ids: list[str], from_db: str, to_db: str, outdir: str, refresh: bool = False):
    """UniProt's post-2022 async ID-mapping endpoints; poll the job URL until done.

    Shared-store fast path: identical (from, to, sorted-ids) requests already sidecar-verified
    in the store skip the job submission entirely."""
    identity = {"slug": f"uniprot_{from_db}_to_{to_db}", "ids": sorted(set(ids)), "ids_n": len(ids)}
    cached_path = store_payload_path("id-mapping", identity, "tsv")
    if sidecar_match(cached_path) and not refresh:
        return cached_path, "cache"
    url = "https://rest.uniprot.org/idmapping/run"
    rate = RateLimiter(1.1)
    rate.wait()
    identity = {"slug": f"uniprot_{from_db}_to_{to_db}", "ids": sorted(set(ids)), "ids_n": len(ids)}
    resp = requests.post(url, headers=HEADERS, json={"ids": ",".join(ids), "from": from_db, "to": to_db}, timeout=(15, 60))
    resp.raise_for_status()
    job_id = resp.json().get("jobId", "")
    poll = f"https://rest.uniprot.org/idmapping/status/{job_id}"
    while True:
        rate.wait()
        status = requests.get(poll, headers=HEADERS, timeout=(15, 60)).json()
        if status.get("jobStatus") == "COMPLETED":
            break
        if status.get("jobStatus") in ("FAILED", "ERROR"):
            raise SystemExit(f"idmapping failed: {status}")
        time.sleep(3)
    rate.wait()
    dl = requests.get(f"https://rest.uniprot.org/idmapping/uniprotkb/results/stream/{job_id}",
                      headers=HEADERS, timeout=(15, 600))
    dl.raise_for_status()
    stamp = now_utc().replace(":", "").replace("-", "")
    out = store_payload_path("id-mapping", identity, "tsv")
    hit = sidecar_match(out) and not refresh
    if not hit:
        with open(out, "w") as fh:
            fh.write(dl.text)
        sidecar_write(out)
    return out, job_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Bulk ID mapping under the manifest.tsv contract")
    common_args(ap)
    ap.add_argument("cmd", choices=["biomart", "uniprot"])
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--from", dest="from_attr", default="ensembl_gene_id")
    ap.add_argument("--to", dest="to_attr", default="hgnc_symbol")
    ap.add_argument("--dataset", default="hsapiens_gene_ensembl")
    args = ap.parse_args()
    args.outdir = args.outdir.rstrip("/") or "./work/database-access"
    os.makedirs(args.outdir, exist_ok=True)

    ids = read_ids(args.ids_file)
    rows = []
    extra = {}
    if args.cmd == "biomart":
        out, table = biomart_map(ids, args.from_attr, args.to_attr, args.dataset, args.outdir, args.refresh)
        rows.append({"accession": f"{len(ids)} ids", "source": "pybiomart-web", "url": "-",
                     "path": out, "tool": TOOL, "format": "tsv", "cache": "hit" if sidecar_match(out) and not args.refresh else "miss"})
        extra = {"n_ids": len(ids), "n_rows": len(table), "cache": rows[0]["cache"]}
    else:
        out, job_id = uniprot_async(ids, args.from_attr, args.to_attr, args.outdir, args.refresh)
        rows.append({"accession": f"{len(ids)} ids", "source": "uniprot-idmapping-async",
                     "url": f"https://rest.uniprot.org/idmapping/run/jobId={job_id}",
                     "path": out, "tool": TOOL, "format": "tsv", "cache": "hit" if sidecar_match(out) and not args.refresh else "miss"})
        extra = {"n_ids": len(ids), "job_id": job_id, "cache": rows[0]["cache"]}
    mpath = manifest_append(args.outdir, rows, TOOL)
    print(json.dumps(extra, sort_keys=True))
    print(mpath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())