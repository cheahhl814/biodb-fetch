#!/usr/bin/env python3
"""NCBI Datasets v2 CLI wrapper (genome / gene / ortholog reports).

The modern bulk path per the routing rule: genomes, gene records, and
precomputed orthologs go to `datasets`; everything else stays with E-utilities.
Wraps the version-pinned `datasets` binary via pixi env (must be on PATH via
`pixi run python3 scripts/ncbi_datasets.py …`).

Subcommands:
  genome   --accession <GCA|GCF> --include genome,gff3,cds,protein
  gene     --taxon | --gene-id <id> [gene fields]
  ortholog --gene-id <id>
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from dbaccess_common import (common_args, manifest_append, now_utc, sidecar_match,
                             sidecar_write, store_payload_path)

TOOL = "dbaccess-ncbi_datasets 1.0.0"


def cli() -> str:
    exe = shutil.which("datasets")
    if not exe:
        raise SystemExit("datasets CLI not on PATH — run via `pixi run python3 …/ncbi_datasets.py`")
    return exe


def run_datasets(cmd: list[str], identity: dict) -> tuple[str, bool]:
    """Run the datasets CLI into the shared store (deterministic path); returns (path, cached)."""
    out = store_payload_path("ncbi", identity, "zip")
    if sidecar_match(out) and not identity.pop("_refresh", False):
        return out, True
    identity.pop("_refresh", None)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part"
    with open(tmp, "wb") as fh:
        proc = subprocess.run([cli(), *cmd], stdout=fh, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        os.unlink(tmp)
        raise SystemExit(f"datasets failed: {proc.stderr.decode(errors='replace')[:500]}")
    if os.path.getsize(tmp) < 10:
        os.unlink(tmp)
        raise SystemExit("datasets returned an empty payload (no data for that accession)")
    os.replace(tmp, out)
    sidecar_write(out)
    return out, False


def main() -> int:
    ap = argparse.ArgumentParser(description="NCBI Datasets v2 CLI wrapper under the manifest.tsv contract")
    common_args(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("genome"); g.add_argument("--accession", required=True)
    g.add_argument("--include", default="genome,gff3,cds,protein")
    ge = sub.add_parser("gene"); ge.add_argument("--taxon"); ge.add_argument("--gene-id")
    o = sub.add_parser("ortholog"); o.add_argument("--gene-id", required=True)
    o.add_argument("--taxon")
    args = ap.parse_args()
    args.outdir = args.outdir.rstrip("/") or "./work/database-access"

    if args.cmd == "genome":
        cmd = ["download", "genome", "accession", args.accession,
               "--include", args.include, "--filename", "-"]
        source = f"datasets-genome-{args.accession}"
        acc = args.accession
        identity = {"slug": f"datasets_genome_{args.accession}", "include": args.include}
    elif args.cmd == "gene":
        if args.gene_id:
            cmd = ["download", "gene", "gene-id", args.gene_id, "--filename", "-"]
            acc = args.gene_id
        elif args.taxon:
            cmd = ["download", "gene", "taxon", args.taxon, "--filename", "-"]
            acc = args.taxon
        else:
            raise SystemExit("gene needs --gene-id or --taxon")
        source = f"datasets-gene-{acc}"
        identity = {"slug": f"datasets_gene_{acc}"}
    else:
        cmd = ["download", "gene", "ortholog", "gene-id", args.gene_id, "--filename", "-"]
        source = f"datasets-ortholog-{args.gene_id}"
        acc = args.gene_id
        identity = {"slug": f"datasets_ortholog_{args.gene_id}"}

    identity["_refresh"] = args.refresh
    path, cached = run_datasets(cmd, identity)
    rows = [{"accession": acc, "source": source, "url": "-", "path": path,
             "tool": TOOL, "format": "json", "cache": "hit" if cached else "miss"}]
    mpath = manifest_append(args.outdir, rows, TOOL)
    print(path)
    print(mpath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())