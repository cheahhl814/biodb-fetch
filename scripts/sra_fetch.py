#!/usr/bin/env python3
"""SRA/ENA read download with mirror routing: ENA-first → SRA direct (prefetch/fasterq-dump).

Routing rule: ENA portal API first (plain HTTPS, md5 in the metadata — simplest,
no sra-tools needed); fall back to SRA direct via sra-tools when ENA lacks the run.

Subcommands:
  resolve   --srr <SRR…>            (writes per-run metadata JSON + manifest rows)
  download  --srr <SRR…> [--keep-gz] (downloads FASTQ(+GZ) under --outdir)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

import requests

from dbaccess_common import (CONTRACT_VERSION, HEADERS, RateLimiter, common_args,
                             fetch_to_file, manifest_append, md5_of, now_utc,
                             sidecar_match, sidecar_write, store_payload_path)

TOOL = "dbaccess-sra_fetch 1.0.0"
ENA_PORTAL = "https://www.ebi.ac.uk/ena/portal/api/filereport"
ENA_FIELDS = "run_accession,submitted_ftp,md5_ftp,submitted_bytes,library_name,scientific_name,fastq_ftp,fastq_md5,fastq_bytes"
SRA_FIELDS = "run_accession,scientific_name,library_strategy,library_selection,source_name,platform,submitted_ftp,sra_ftp,ena_fastq_ftp,ena_fastq_md5,ena_fastq_bytes"


def resolve_runs(srr: str) -> list[dict]:
    """Query the ENA portal for a run accession (or SRA-study/experiment prefix)."""
    rate = RateLimiter(0.15)
    rate.wait()
    resp = requests.post(
        ENA_PORTAL,
        headers=HEADERS,
        data={"accession": srr, "result": "read_run", "fields": ENA_FIELDS,
              "format": "tsv", "limit": "50"},
        timeout=(15, 300),
    )
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or "No results" in text:
        return []
    lines = text.splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]


def download_via_ena(meta: dict, outdir: str, refresh: bool = False) -> list[dict]:
    rows = []
    for url, md5 in zip(meta["fastq_ftp"].split(";"), meta["fastq_md5"].split(";")):
        if not url:
            continue
        full = f"https://{url}" if not url.startswith("http") else url
        basename = url.rsplit("/", 1)[-1]
        identity = {"slug": basename, "accession": meta["run_accession"], "url": full}
        ext = ".fastq.gz" if basename.endswith(".gz") else ".fastq"
        dest = store_payload_path("reads", identity, ext.lstrip("."))
        # shared store: skip the download when the run's file already passed its md5 sidecar
        # (or when ENA metadata carries the md5 — cross-check either sidecar or metadata)
        cached = (sidecar_match(dest) or (os.path.exists(dest) and md5 and md5_of(dest) == md5)) and not refresh
        if not cached:
            _, cached = fetch_to_file(requests.Session(), full, dest, skip_if_cached=not refresh)
            if md5 and cached is False and os.path.exists(dest) and md5_of(dest) != md5:
                raise SystemExit(f"md5 mismatch vs ENA metadata: {dest}")
        rows.append({"accession": meta["run_accession"], "source": "ena-portal-api",
                     "url": full, "path": dest, "tool": TOOL, "format": "fastq",
                     "cache": "hit" if cached else "miss"})
    return rows


def download_via_sra_direct(srr: str, outdir: str, refresh: bool = False) -> list[dict]:
    """Fallback: sra-tools prefetch + fasterq-dump (needs the pixi sra-tools env).

    Shared-store fast path: deterministic store paths per SRR; identical runs already
    in the store (sidecar-verified) skip prefetch/fasterq-dump entirely."""
    scratch = outdir if os.path.isdir(outdir) and os.access(outdir, os.W_OK) else "."
    rows = []
    for split in (1, 2, 3):  # fasterq-dump emits ≤3 split files; deterministic names
        name = f"{srr}_{split}.fastq" if split > 1 else f"{srr}.fastq"
        dest = store_payload_path("reads", {"slug": name, "accession": srr, "kind": "fasterq"}, "fastq")
        if sidecar_match(dest) and not refresh:
            rows.append({"accession": srr, "source": "sra-fasterq-dump",
                         "url": "-", "path": dest, "tool": TOOL, "format": "fastq", "cache": "hit"})
            continue
        if not shutil.which("prefetch"):
            raise SystemExit("sra-tools not on PATH — run via `pixi run python3 …/sra_fetch.py`")
        subprocess.run(["prefetch", srr, "--output-directory", scratch], check=True)
        subprocess.run(["fasterq-dump", srr, "--outdir", scratch, "--progress", "off"], check=True)
        shutil.rmtree(os.path.join(scratch, srr), ignore_errors=True)
        produced = os.path.join(scratch, name)
        if not os.path.exists(produced) or os.path.getsize(produced) == 0:
            continue  # split not produced for single-file runs
        os.replace(produced, dest)
        sidecar_write(dest)
        rows.append({"accession": srr, "source": "sra-fasterq-dump",
                     "url": "-", "path": dest, "tool": TOOL, "format": "fastq", "cache": "miss"})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="SRA/ENA fetch under the manifest.tsv contract")
    common_args(ap)
    ap.add_argument("cmd", choices=["resolve", "download"])
    ap.add_argument("--srr", required=True, help="SRA run accession (comma-separated allowed)")
    args = ap.parse_args()
    args.outdir = args.outdir.rstrip("/") or "./work/database-access"
    os.makedirs(args.outdir, exist_ok=True)

    srr_list = [a.strip() for a in args.srr.split(",") if a.strip()]
    all_rows = []
    metadata = {}
    for srr in srr_list:
        metas = resolve_runs(srr)
        if args.cmd == "resolve":
            stamp = now_utc().replace(":", "").replace("-", "")
            mpath = os.path.join(args.outdir, f"ena_metadata_{stamp}.json")
            with open(mpath, "w") as fh:
                json.dump(metas, fh)
            all_rows.append({"accession": srr, "source": "ena-portal-api", "url": ENA_PORTAL,
                             "path": mpath, "tool": TOOL, "format": "json"})
            metadata[srr] = metas
        else:
            if metas:
                for meta in metas:
                    all_rows.extend(download_via_ena(meta, args.outdir, refresh=args.refresh))
            else:
                print(f"ENAFALLBACK {srr}", file=sys.stderr)
                all_rows.extend(download_via_sra_direct(srr, args.outdir, refresh=args.refresh))
    if args.cmd == "resolve":
        out = os.path.join(args.outdir, f"ena_resolved_{now_utc().replace(':','').replace('-','')}.json")
        with open(out, "w") as fh:
            json.dump(metadata, fh)
        all_rows = [{"accession": ",".join(srr_list), "source": "ena-portal-api", "url": ENA_PORTAL,
                     "path": out, "tool": TOOL, "format": "json"}]
    mpath = manifest_append(args.outdir, all_rows, TOOL)
    print(mpath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())