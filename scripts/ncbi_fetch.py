#!/usr/bin/env python3
"""Entrez E-utilities wrapper (ESearch/EFetch/ELink) with Biopython.

Subcommands:
  search --db <db> --query <term> [--retstart N] [--retmax N] [--history]
  fetch  --db <db> (--uids <a,b,c> | --query <term> --retmax N) --rettype <t> [--retmode <m>]
  link   --db-from <db> --db-to <db> (--uids <ids> | --query <term> --retmax N)

Writes fetched payload(s) under --outdir and appends manifest.tsv rows.
Key facts encoded: ESearch returns UIDs (not records); >10K results use the
history server (WebEnv/QueryKey); retmax caps apply per database.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse

from Bio import Entrez

from dbaccess_common import (HEADERS, common_args, common_parser, manifest_append, now_utc,
                             ncbi_rate_limiter, parse_date_header, sidecar_match, store_payload_path)

TOOL = "dbaccess-ncbi_fetch 1.0.0"


def require_email(args) -> None:
    if not args.email:
        print("WARN: no NCBI_EMAIL — anonymous 3 req/s; set NCBI_EMAIL (and NCBI_API_KEY for 10 req/s)", file=sys.stderr)
    Entrez.email = args.email or "database-access-skill@example.org"
    if args.api_key:
        Entrez.api_key = args.api_key
    Entrez.tool = "database-access"


def safe_entrez(fn, *a, **kw):
    err, out = None, None
    for attempt in range(2):
        try:
            time.sleep(0.6)  # NCBI recommends <=3 req/s incl. metadata; limiter applied too
            out = fn(*a, **kw)
            return out
        except Exception as exc:  # noqa: BLE001
            err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Entrez call failed after retry: {err}")


def do_search(args) -> int:
    require_email(args)
    kw = {"db": args.db, "term": args.query, "retstart": args.retstart,
          "retmax": args.retmax, "retmode": "json"}
    if args.retmax > 10000 or args.history:
        kw["usehistory"] = "y"
    if args.date_from:
        kw["mindate"], kw["maxdate"], kw["datetype"] = args.date_from, args.date_to or args.date_from, args.date_type
    h = safe_entrez(Entrez.esearch, **kw)
    rec = json.load(h)
    h.close()
    print(rec.get("esearchresult", {}).get("querytranslation", "NO-TRANSLATION"))
    print(json.dumps(rec["esearchresult"].get("idlist", [])))
    print("count=%s webenv=%s querykey=%s" % (
        rec["esearchresult"].get("count", "0"),
        rec["esearchresult"].get("webenv", "-"),
        rec["esearchresult"].get("querykey", "-")))
    return 0


def do_fetch(args) -> int:
    require_email(args)
    rows = []
    kw: dict = {"db": args.db, "rettype": args.rettype or "json",
                "retmode": args.retmode or "xml"}
    if args.uids:
        kw["id"] = args.uids
    elif args.query:
        # single-pass: esearch then efetch on retmax IDs (history server for large sets)
        h = safe_entrez(Entrez.esearch, db=args.db, term=args.query,
                        retmax=args.retmax, usehistory="y", retmode="json")
        es = json.load(h)["esearchresult"]; h.close()
        if int(es["count"]) > args.retmax:
            print(f"WARN: {es['count']} hits; fetched only first {args.retmax}', file=sys.stderr")
        kw.update({"WebEnv": es["webenv"], "query_key": es["querykey"]})
    else:
        raise SystemExit("need --uids or --query")
    ext = {"fasta": "fasta", "ft": "txt", "ipg": "tsv", "json": "json", "xml": "xml",
           "gb": "gb", "docsum": "json"}.get(args.rettype or "xml", "txt")
    key = args.uids or f"q:{args.query}:{args.retmax}"
    identity = {"slug": f"eutils_{args.db}_{key[:40]}", "rettype": args.rettype or "xml"}
    out = store_payload_path("ncbi", identity, ext)
    cached = sidecar_match(out) and not args.refresh
    if not cached:
        h = safe_entrez(Entrez.efetch, **kw)
        payload = h.read(); h.close()
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").write(payload)
        sidecar_write(out)
    source = f"eutils-{args.db}-{args.rettype or 'xml'}"
    rows.append({"accession": args.uids or args.query, "source": source, "url": "-",
                 "path": out, "tool": TOOL, "format": ext if ext in ("fasta", "gff", "tsv", "json", "xml") else "txt",
                 "cache": "hit" if cached else "miss"})
    print(manifest_append(args.outdir, rows, TOOL)); return 0


def do_link(args) -> int:
    require_email(args)
    h = safe_entrez(Entrez.elink, dbfrom=args.db_from, db=args.db_to, id=args.uids)
    rec = json.load(h); h.close()
    linked = {ls["DbTo"]: lnk.get("IdNumList", [])
              for item in rec.get("links", [])
              for ls in item.get("LinkSetDb", [])
              for lnk in [ls]}
    identity = {"slug": f"elink_{args.db_from}_to_{args.db_to}", "uids": args.uids}
    out = store_payload_path("ncbi", identity, "json")
    cached = sidecar_match(out) and not args.refresh
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if not cached:
        with open(out, "w") as fh:
            json.dump(rec, fh)
        sidecar_write(out)
    print(manifest_append(args.outdir, [
        {"accession": args.uids, "source": f"elink-{args.db_from}-{args.db_to}",
         "url": "-", "path": out, "tool": TOOL, "format": "json",
         "cache": "hit" if cached else "miss"}], TOOL))
    print(json.dumps(linked))
    return 0


def main() -> int:
    common = common_parser()
    ap = argparse.ArgumentParser(description="Entrez E-utilities wrapper under the manifest.tsv contract", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", parents=[common]); s.add_argument("--db", required=True); s.add_argument("--query", required=True)
    s.add_argument("--retstart", type=int, default=0); s.add_argument("--retmax", type=int, default=20)
    s.add_argument("--history", action="store_true")
    s.add_argument("--date-from"); s.add_argument("--date-to"); s.add_argument("--date-type", default="pdat")
    f = sub.add_parser("fetch", parents=[common]); f.add_argument("--db", required=True); f.add_argument("--uids")
    f.add_argument("--query"); f.add_argument("--retmax", type=int, default=500)
    f.add_argument("--rettype"); f.add_argument("--retmode")
    l = sub.add_parser("link", parents=[common]); l.add_argument("--db-from", required=True); l.add_argument("--db-to", required=True)
    l.add_argument("--uids", required=True)
    args = ap.parse_args()
    args.outdir = args.outdir.rstrip("/") or "./work/database-access"
    return {"search": do_search, "fetch": do_fetch, "link": do_link}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())