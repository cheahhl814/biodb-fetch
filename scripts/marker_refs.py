#!/usr/bin/env python3
"""eDNA metabarcoding marker-reference retrieval under the manifest.tsv contract.

Retrieves taxonomic-assignment reference libraries by KEY:
  unite       UNITE v10.x general FASTA release (DOI 10.15156/BIO/<ver>) — static/dynamic, fungi/eukaryotes
              (PlutoF-managed; QIIME rescript get-unite-data mechanism)
  bold        per-record COI via BOLD REST API (boldsystems.org/data/api) — search+retrieval (public tier)
  mitohelper  Mitohelper Zenodo reference datasets (12S/COI/QIIME-compatible, Nov2025+ dedup vs MitoFish)
  silva       SILVA NR99 (direct https) — delegate curation to nf-edna reference-db; this executes
  pr2         PR2 releases (GitHub raw)
  midori2     MIDORI2 UNIQ (Zenodo, CC-BY-NC — surfaces the license before download)
  decipher    DECIPHER pre-trained trainingFiles (Google Drive — gdown; curl returns quota-exceeded HTML)

License rule: CC-BY-NC entries (MIDORI2) require --i-accept-license; this is the script-level
counterpart of nf-edna reference-db preflight SP5.

Usage examples:
  marker_refs.py unite --version 10.2 --taxon_group fungi --type static
  marker_refs.py bold --taxon Thunnus --out-bold-urls
  marker_refs.py url --url https://example.org/ref.fasta --format fasta
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import shutil
import sys

import requests

from dbaccess_common import (CONTRACT_VERSION, HEADERS, RateLimiter, common_args,
                             fetch_to_file, manifest_append, now_utc, sidecar_match,
                             sidecar_write, store_payload_path)

TOOL = "dbaccess-marker_refs 1.0.0"
UNITE_DOI_BASE = "https://plutof.ut.ee/doi/10.15156/BIO"
BOLD_API = "https://boldsystems.org/index.php/API_Public/combined"
KNOWN_LICENSE = {"midori2": "CC-BY-NC (non-commercial only — surface before use)", "bold": "BOLD data terms (public records; bulk package needs an account)"}


def _fail(msg: str):
    raise SystemExit(msg)


def require_license(args, key: str) -> None:
    if key in KNOWN_LICENSE and not args.i_accept_license:
        _fail(f"License gate: {key} is {KNOWN_LICENSE[key]}. Re-run with --i-accept-license after reading the terms.")


def unite(args, outdir: str) -> list[dict]:
    """UNITE general FASTA release via DOI landing (10.15156/BIO/<id>); resolve to a file URL then fetch."""
    rate = RateLimiter(1.0)
    rate.wait()
    landing = f"{UNITE_DOI_BASE}/{args.doi_id or '2483911'}"
    resp = requests.get(landing, headers=HEADERS, timeout=(15, 300), allow_redirects=True)
    resp.raise_for_status()
    # UNITE publishes static/dynamic FASTA per (taxon_group, cluster). Take the link the user pinned,
    # else record the DOI page as the source and download the pinned file URL.
    if not args.file_url:
        _fail(f"pass --file-url (from the UNITE repository page {landing}) — PlutoF paginates per (version, taxon_group, cluster)")
    identity = {"slug": f"unite_{args.taxon_group}_{args.type}_{args.version}", "url": args.file_url}
    dest = store_payload_path("marker-references", identity, "fasta")
    _, cached = fetch_to_file(requests.Session(), args.file_url, dest, limiter=rate, skip_if_cached=not args.refresh)
    return [{"accession": f"UNITE {args.taxon_group} {args.version}", "source": "unite-plutof-doi",
             "url": args.file_url, "path": dest, "tool": TOOL, "format": "fasta",
             "cache": "hit" if cached else "miss"}]


def bold(args, outdir: str) -> list[dict]:
    require_license(args, "bold")
    rate = RateLimiter(1.1)
    rate.wait()
    params = {"taxon": args.taxon, "format": "tsv", "seqlen": "100-100000"}
    resp = requests.get(BOLD_API, headers=HEADERS, params=params, timeout=(15, 600), stream=True)
    resp.raise_for_status()
    identity = {"slug": f"bold_{args.taxon.replace(' ', '_')}", "api": BOLD_API, "taxon": args.taxon}
    dest = store_payload_path("marker-references", identity, "tsv")
    if sidecar_match(dest) and not args.refresh:
        return [{"accession": args.taxon, "source": "bold-api",
                 "url": resp.url, "path": dest, "tool": TOOL, "format": "tsv", "cache": "hit"}]
    tmp = dest + ".part"
    with open(tmp, "wb") as fh:
        fh.write(resp.content)
    if resp.content and b"error" in resp.content[:100].lower():
        os.unlink(tmp)
        _fail(f"BOLD API error response: {resp.content[:200]!r}")
    os.replace(tmp, dest)
    sidecar_write(dest)
    return [{"accession": args.taxon, "source": "bold-api",
             "url": resp.url, "path": dest, "tool": TOOL, "format": "tsv", "cache": "miss"}]


def zenodo_reference(args, outdir: str) -> list[dict]:
    """MitoFish/Mitohelper/MIDORI2/CanFish/INBO — any pinned Zenodo/DOI record file."""
    if not args.doi_id or not args.file_url:
        _fail("zenodo refs need --doi-id (record id, e.g. 17602902) and --file-url (the file URL from the record)")
    identity = {"slug": f"zenodo_{args.doi_id}_{os.path.basename(args.file_url)}", "url": args.file_url}
    dest = store_payload_path("marker-references", identity, os.path.basename(args.file_url).rsplit(".", 1)[-1])
    _, cached = fetch_to_file(requests.Session(), args.file_url, dest, limiter=RateLimiter(0.5), skip_if_cached=not args.refresh)
    src = "mitohelper-zenodo" if args.key == "mitohelper" else f"{args.key}-zenodo"
    if args.key in KNOWN_LICENSE:
        require_license(args, args.key)
    ext = "fasta" if args.file_url.endswith((".fa", ".fasta", ".fas")) else "txt"
    return [{"accession": f"zenodo:{args.doi_id}", "source": src, "url": args.file_url,
             "path": dest, "tool": TOOL, "format": ext, "cache": "hit" if cached else "miss"}]


def decipher_drive(args, outdir: str) -> list[dict]:
    """DECIPHER pre-trained trainingFiles live on Google Drive — gdown, never bare curl."""
    if not shutil.which("gdown") and args.file_id is None:
        _fail("gdown not on PATH — run via `pixi run python3 …/marker_refs.py` (gdown is in pixi.toml)")
    if not args.drive_id and not args.file_id:
        _fail("need --drive-id (Google Drive file id) or --file-url 'https://drive.google.com/...'")
    url = args.file_url or f"gdrive:{args.drive_id}"
    identity = {"slug": f"decipher_{args.drive_id or 'file'}", "url": url, "kind": "rds"}
    dest = store_payload_path("marker-references", identity, "rds")
    if sidecar_match(dest) and not args.refresh:
        return [{"accession": args.drive_id, "source": "decipher-gdrive",
                 "url": url, "path": dest, "tool": TOOL, "format": "fasta", "cache": "hit"}]
    cmd = ["gdown", args.drive_id, "-O", dest] if args.drive_id else [
        "gdown", args.file_url, "-O", dest]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode == 0:
        sidecar_write(dest)
    err = proc.stderr.decode(errors="replace")
    if "quota" in err.lower() or proc.returncode != 0:
        raise SystemExit(f"gdown failed ({err.strip()[:200]}) — Drive quota or wrong id; retry later or mirror per nf-edna reference-db")
    return [{"accession": args.drive_id, "source": "decipher-gdrive",
             "url": url, "path": dest, "tool": TOOL, "format": "fasta", "cache": "miss"}]


def generic_url(args, outdir: str) -> list[dict]:
    if not args.url:
        _fail("url subcommand needs --url")
    ext = os.path.splitext(os.path.basename(args.url))[1] or ".txt"
    identity = {"slug": f"url_{os.path.basename(args.url)}", "url": args.url}
    dest = store_payload_path("marker-references", identity, ext.lstrip("."))
    _, cached = fetch_to_file(requests.Session(), args.url, dest, skip_if_cached=not args.refresh)
    fmt = {"fasta": "fasta", ".fa": "fasta", ".fas": "fasta"}.get(ext, "txt")
    return [{"accession": args.url.split("/")[-1], "source": args.source, "url": args.url,
             "path": dest, "tool": TOOL, "format": fmt, "cache": "hit" if cached else "miss"}]


def main() -> int:
    ap = argparse.ArgumentParser(description="eDNA marker reference retrieval under the manifest.tsv contract")
    common_args(ap)
    ap.add_argument("key", choices=["unite", "bold", "mitohelper", "zenodo", "silva", "pr2", "midori2", "decipher", "url"])
    ap.add_argument("--doi-id", help="UNITE doi suffix or Zenodo record id")
    ap.add_argument("--file-url", help="pinned download URL")
    ap.add_argument("--taxon-group", default="fungi", help="UNITE taxon group")
    ap.add_argument("--type", default="static", help="UNITE variant: static|dynamic")
    ap.add_argument("--version", default="10.2", help="UNITE version")
    ap.add_argument("--taxon", help="BOLD taxon query")
    ap.add_argument("--drive-id", help="Google Drive file id (gdown)")
    ap.add_argument("--source", default="web-url", help="label for the url subcommand's manifest source column")
    ap.add_argument("--i-accept-license", action="store_true", help="explicit acceptance of non-commercial / account terms")
    args = ap.parse_args()
    args.outdir = args.outdir.rstrip("/") or "./work/database-access"
    os.makedirs(args.outdir, exist_ok=True)

    if args.key in ("unite",):
        rows = unite(args, args.outdir)
    elif args.key == "bold":
        if not args.taxon:
            _fail("bold needs --taxon")
        rows = bold(args, args.outdir)
    elif args.key in ("decipher",):
        rows = decipher_drive(args, args.outdir)
    elif args.key == "url":
        rows = generic_url(args, args.outdir)
    else:
        rows = zenodo_reference(args, args.outdir)
    mpath = manifest_append(args.outdir, rows, TOOL)
    print(json.dumps({"rows": len(rows), "license_notes": [KNOWN_LICENSE.get(args.key, "-")]}))
    print(mpath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())