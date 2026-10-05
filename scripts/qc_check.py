#!/usr/bin/env python3
"""QC checks over a database-access manifest.tsv (contract v1).

Usage: python3 qc_check.py --outdir ./work/database-access/
Verdict PASS / PASS-WITH-WARNINGS / FAIL printed last; also written to stdout as JSON.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys

COLUMNS = ["accession", "source", "url", "path", "md5", "bytes",
           "retrieval_date", "tool", "format", "contract_version", "cache"]


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def format_sanity(path: str, fmt: str, warns: list[str], fails: list[str]) -> None:
    try:
        if fmt == "fastq":
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt") as fh:
                for i, line in enumerate(fh):
                    if i > 40000:
                        break
                    if i % 4 in (0, 1, 3) and not line.strip():
                        fails.append(f"bad fastq periodicity: {path} line {i}")
                        return
        elif fmt == "fasta":
            with open(path, "rb") as fh:
                head = fh.read(200)
            if not head.startswith((b">",)):
                fails.append(f"fasta missing '>' header: {path}")
        elif fmt == "json":
            json.load(open(path))
        elif fmt == "tsv":
            first = open(path, encoding="utf-8").readline()
            if not first.strip():
                fails.append(f"empty tsv: {path}")
    except OSError as exc:
        fails.append(f"unopenable {fmt} {path}: {exc}")


def qc(outdir: str) -> tuple[str, list[dict]]:
    mpath = os.path.join(outdir, "manifest.tsv")
    checks, rows, fails, warns = [], [], [], []
    if not os.path.exists(mpath):
        return "FAIL", [{"name": "manifest exists", "verdict": "FAIL", "value": mpath}]
    lines = open(mpath, encoding="utf-8").read().splitlines()
    if not lines or lines[0].split("\t") != COLUMNS:
        return "FAIL", [{"name": "manifest header", "verdict": "FAIL", "value": "columns != contract v2 (v1 manifests predate the shared store)"}]
    for ln in lines[1:]:
        parts = ln.split("\t")
        if len(parts) != len(COLUMNS):
            fails.append(f"malformed row: {ln[:80]}")
            continue
        rows.append(dict(zip(COLUMNS, parts)))
    if any(p[9] != "1" for p in (r for r in (d.values() for d in rows)) for p in [r.get("contract_version", "")]) if rows else False:
        warns.append("some rows missing contract_version")
    for row in rows:
        path = row["path"]
        if path == "-":
            continue
        if not os.path.exists(path):
            fails.append(f"manifest references missing file: {path}")
            continue
        size = os.path.getsize(path)
        if size == 0:
            fails.append(f"0-byte file: {path}")
            continue
        if row["md5"] not in ("-", ""):
            if md5_of(path) != row["md5"]:
                fails.append(f"md5 mismatch: {path}")
        if row["contract_version"] != "2":
            fails.append(f"non-v2 manifest row: {path} (contract_version={row['contract_version']})")
        if row["cache"] not in ("hit", "miss", "-"):
            warns.append(f"unusual cache value: {row['cache']} on {path}")
        if row["cache"] == "hit" and row["md5"] in ("-", ""):
            warns.append(f"cache=hit without md5 to verify: {path}")
        else:
            warns.append(f"no md5 to verify (CLI-mediated dump): {path}")
        if row["format"]:
            format_sanity(path, row["format"], warns, fails)
    if fails:
        verdict = "FAIL"
    elif warns:
        verdict = "PASS-WITH-WARNINGS"
    else:
        verdict = "PASS"
    checks.append({"name": "rows checked", "verdict": verdict, "value": len(rows)})
    return verdict, checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()
    verdict, checks = qc(args.outdir)
    print(json.dumps({"verdict": verdict, "checks": checks}))
    print(verdict)
    return 0 if verdict != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())