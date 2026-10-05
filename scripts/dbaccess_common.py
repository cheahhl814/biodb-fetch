#!/usr/bin/env python3
"""Shared library for database-access fetch scripts: the manifest.tsv contract.

Contract v2 columns (exact order, tab-separated):
accession  source  url  path  md5  bytes  retrieval_date  tool  format  contract_version  cache

Contract v1→v2 change: added the `cache` column (`hit` = served from the shared store,
`miss` = freshly downloaded, `-` = not applicable). No consumers existed on v1, so the
bump is free; v1 manifests lack the column and are rejected by qc.

Every fetch script in this skill writes ONLY through manifest_append(); consumers
rely on the manifest, never on the skill's internals.

THE SHARED STORE
================
All fetched payloads live in one canonical store directory so multiple consumer
skills / batches reuse the same data instead of re-downloading:

  store root = $BIODB_FETCH_STORE   (override)
             or <skill_dir>/store/ (sub-folder inside the skill's folder)

Layout is content-addressed per request identity:

  <store>/<domain>/<slug>-<sha16>.<ext>     (deterministic name — no timestamps)
  same path + '.sha256' sidecar             (md5, verified on cache hits)

Dedup rule: before fetching, scripts call store_lookup(identity); an existing file
with a matching sidecar is served as cache=hit (path still recorded, no download).
`--refresh` (in common_args) forces a miss. Occurrence-style sources whose data grows
over time: cache rows carry retrieval_date — consumers choose freshness windows.

Deploy guard: the store lives INSIDE the skill folder, so rsync-based updates of the
skill MUST exclude it:

  rsync -av --delete --exclude='store/' src/ ~/.pi/agent/skills/<skill>/

And store/ is gitignored — data is never committed.
"""
from __future__ import annotations

import argparse
import datetime
import email.utils
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse

import requests

CONTRACT_VERSION = "2"
MANIFEST_COLUMNS = [
    "accession", "source", "url", "path", "md5", "bytes",
    "retrieval_date", "tool", "format", "contract_version", "cache",
]

HEADERS = {"User-Agent": "database-access skill (contract v1)"}


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------- shared store (data lake) -------------------------

STORE_ENV = "BIODB_FETCH_STORE"


def store_root() -> str:
    """Store root: $BIODB_FETCH_STORE, else <skill_dir>/store (sub-folder of the skill)."""
    env = os.environ.get(STORE_ENV, "").strip()
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "store")


def _slug(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-")
    return (s[:max_len].rstrip("-")) or "data"


def store_payload_path(domain: str, identity: dict, ext: str) -> str:
    """Deterministic content-addressed path inside the store for one request identity."""
    canonical = json.dumps(identity, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    slug = _slug(identity.get("slug") or identity.get("accession") or domain)
    safe_ext = ext if ext and re.fullmatch(r"[a-z0-9.]{1,8}", ext) else "txt"
    return os.path.join(store_root(), _slug(domain, 32), f"{slug}-{digest}.{safe_ext}")


def sidecar_write(path: str) -> None:
    """Write md5 sidecar next to a store file so cache hits can verify integrity cheaply."""
    md5 = md5_of(path)
    with open(path + ".sha256", "w") as fh:
        fh.write(md5 + "\n")


def sidecar_match(path: str) -> bool:
    side = path + ".sha256"
    if not os.path.exists(side) or not os.path.exists(path):
        return False
    recorded = open(side).read().split()[0]
    return recorded == md5_of(path)


def store_lookup(path: str) -> bool:
    """Return True if the payload already exists in the store and passes its sidecar."""
    return sidecar_match(path)


def store_register(path: str) -> None:
    """After a fresh fetch, write/refresh the sidecar + append to the store-global manifest."""
    sidecar_write(path)


def now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date_header(value: str) -> str:
    return email.utils.parsedate_to_datetime(value).strftime("%Y-%m-%dT%H:%M:%SZ") if value else "-"


class RateLimiter:
    """Token spacing: anonymous NCBI = 3 req/s (>=0.34s), keyed = 10 req/s (>=0.11s)."""

    def __init__(self, min_interval: float = 0.34):
        self.min_interval = float(min_interval)
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


def ncbi_creds() -> tuple[str, str]:
    """(email, api_key) from env; email falls back to a skill-owned placeholder."""
    return os.environ.get("NCBI_EMAIL", ""), os.environ.get("NCBI_API_KEY", "")


def ncbi_rate_limiter() -> RateLimiter:
    return RateLimiter(min_interval=0.11 if ncbi_creds()[1] else 0.34)


def fetch_to_file(
    session: requests.Session,
    url: str,
    dest: str,
    limiter: RateLimiter | None = None,
    chunk: int = 1 << 20,
    min_file_bytes: int = 1,
    skip_if_cached: bool = False,
) -> tuple[str, bool]:
    """Stream a URL to dest with retry/backoff (2 attempts). Raises on empty payload.

    If skip_if_cached and dest already passes its md5 sidecar, returns (dest, True) — a
    cache hit, no network. Otherwise (dest, False). Registers the sidecar on a fresh fetch.
    """
    if skip_if_cached and sidecar_match(dest):
        return dest, True
    limiter = limiter or RateLimiter(0.0)
    last_err: Exception | None = None
    for attempt in range(2):
        limiter.wait()
        try:
            resp = session.get(url, headers=HEADERS, stream=True, timeout=(15, 300))
            resp.raise_for_status()
            written = 0
            tmp = dest + ".part"
            with open(tmp, "wb") as fh:
                for data in resp.iter_content(chunk):
                    fh.write(data)
                    written += len(data)
            if written < min_file_bytes:
                raise RuntimeError(f"empty payload ({written} bytes) from {url}")
            os.replace(tmp, dest)
            sidecar_write(dest)
            return dest, False
        except Exception as err:  # noqa: BLE001 - surfaced via retry then final raise
            last_err = err
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed after retry: {url}: {last_err}")


def manifest_append(outdir: str, rows: list[dict], tool: str) -> str:
    """Append rows to <outdir>/manifest.tsv, de-duplicated on (accession, source, path)."""
    os.makedirs(outdir, exist_ok=True)
    mpath = os.path.join(outdir, "manifest.tsv")
    existing = set()
    if os.path.exists(mpath):
        with open(mpath, "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == len(MANIFEST_COLUMNS):
                    existing.add((parts[0], parts[1], parts[3]))
    fresh = []
    for row in rows:
        row.setdefault("tool", tool)
        row["contract_version"] = CONTRACT_VERSION
        row.setdefault("cache", "-")
        row.setdefault("retrieval_date", now_utc())
        if os.path.exists(row.get("path", "")) and "md5" not in row:
            row["md5"] = md5_of(row["path"])
            row["bytes"] = os.path.getsize(row["path"])
        elif row.get("path") == "-":
            row.update({"md5": "-", "bytes": "-"})
        key = (row["accession"], row["source"], row["path"])
        if key not in existing:
            existing.add(key)
            fresh.append(row)
    if not fresh:
        return mpath
    new_file = not os.path.exists(mpath)
    with open(mpath, "a", encoding="utf-8") as fh:
        if new_file:
            fh.write("\t".join(MANIFEST_COLUMNS) + "\n")
        for row in fresh:
            fh.write("\t".join(str(row.get(c, "-")) for c in MANIFEST_COLUMNS) + "\n")
    # every payload row is mirrored into the store-global manifest (cross-skill inventory)
    try:
        store_manifest_append(fresh)
    except OSError:
        pass  # store manifest is an inventory aid; per-request manifest is authoritative
    return mpath


def store_manifest_append(rows: list[dict]) -> str:
    """Append identical rows to <store>/manifest.tsv — the cross-skill data inventory."""
    outdir = store_root()
    os.makedirs(outdir, exist_ok=True)
    mpath = os.path.join(outdir, "manifest.tsv")
    if not rows:
        return mpath
    existing = set()
    if os.path.exists(mpath):
        with open(mpath, "r", encoding="utf-8") as fh:
            existing.update(fh.read().splitlines())
    with open(mpath, "a", encoding="utf-8") as fh:
        if not existing:
            fh.write("\t".join(MANIFEST_COLUMNS) + "\n")
        for row in rows:
            line = "\t".join(str(row.get(c, "-")) for c in MANIFEST_COLUMNS)
            if line not in existing:
                existing.add(line)
                fh.write(line + "\n")
    return mpath


def common_args(parser: argparse.ArgumentParser, default_outdir: str = "./work/database-access/") -> None:
    parser.add_argument("--outdir", default=default_outdir, help="directory for per-request manifest.tsv (payloads go to the shared store)")
    parser.add_argument("--email", default=os.environ.get("NCBI_EMAIL", ""), help="NCBI email (or NCBI_EMAIL env)")
    parser.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY", ""), help="NCBI api_key (or NCBI_API_KEY env)")
    parser.add_argument("--refresh", action="store_true", help="bypass the shared-store cache and re-download (store row records cache=miss)")


def tool_banner(name: str, version: str) -> str:
    return f"{name} {version}"