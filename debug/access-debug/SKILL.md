---
name: access-debug
description: Failure interpreter for biodb-fetch fetches — signature library over network (HTTP codes, DNS, redirects), rate limits (429/502), credential (401/403 + api_key), mirror outages (ENA ↔ SRA ↔ STRIDES), stale WebEnv history, weekly NCBI index lag, UniProt/Ensembl endpoint migrations. Writes debug-report.md with RECOVERABLE/BLOCKED verdict. Use when a fetch script fails and the signature is not obvious.
version: 1.0.0
updated: "2026-10-05"
triggers:
  - "database access failed"
  - "efetch error"
  - "uniprot 404"
  - "biomart empty"
disable-model-invocation: true
---

# Access Debug (debug phase)

> **v1.0.0.** Reads the failing stderr / HTTP evidence, matches the signature library, and returns a concrete fix (command + tool/version). Never retries blind in a loop — every retry changes one variable.

## Inputs / Outputs contract

### Inputs

| Path | Source | Required? |
| --- | --- | --- |
| Failing stderr / the specific command | run or qc | yes |
| `<outdir>/manifest.tsv` (the rows that failed) | run | yes |
| `contract.json` | access-preflight | yes |

### Outputs

| Path | Owner | Format | Notes |
| --- | --- | --- | --- |
| `debug-report.md` | this skill | Markdown | diagnosis + fix, RECOVERABLE/BLOCKED |

## Signature library

| Signature in stderr / log | Likely cause | Suggested fix |
| --- | --- | --- |
| `HTTP 429` (eutils or UniProt) | rate budget exceeded; anonymous NCBI = 3 req/s | space calls ≥0.4 s; set `NCBI_API_KEY` for 10 req/s; for UniProt respect 1 req/s burst policy |
| `HTTP 401/403` on eutils | malformed api_key, or key expired | re-issue key at NCBI account settings; never log the key |
| `HTTP 404` from rest.uniprot.org | pre-2022 endpoint string | use post-2022 path (`rest.uniprot.org/idmapping/…`, `/uniprotkb/…`) |
| `HTTP 301 → www.uniprot.org/help` | same as above, older client | same fix |
| `MaxRetryError … ensembl.org` | Ensembl REST overload or mirror down | back off 8 s; bulk work → BioMart; alternate mirror `useast.ensembl.org` |
| BioMart empty for valid IDs | mirror outage or wrong dataset/mart | list marts via pybiomart; retry alternate BioMart mirror |
| `Not Found` on `ena/portal/api/filereport` for a real SRR | metadata lag (run too new) or wrong result-set field | try `SRA` result / fall through to prefetch SRA direct (mirror order) |
| `WebEnv expired` | history lost after ~2h idle | re-run esearch; keep the fetch batch in one session |
| Record known to exist but ESearch returns 0 hits | weekly NCBI index lag | verify via `--db <db> --uid <known id>`; document lag in the manifest; retry next week |
| `HTTP 5xx` from api.ncbi.nlm.nih.gov/datasets | service blip | retry once after 10 s; route through E-utilities if persistent |
| `datasets` segfault / empty output | binary build mismatch | pin a different `ncbi-datasets-cli` build in pixi.toml (never hand-swap binaries) |
| `fasterq-dump: read error` mid-write | scratch OOM (3× uncompressed FASTQ) | ENA-first routing (SP2/SP3) or bigger scratch |
| gzip "Not a Gzip file" | HTML error page saved as payload | see qc signature; re-resolve and mirror-retry |
| `KeyError: 'jobId'` (UniProt idmapping) | POST body wrong / IDs > limit 100k | chunk IDs ≤100k per job; check `/idmapping/run` response |

## Investigation loop (when no signature matches)

1. Reproduce the exact failing command with `--verbose`-equivalent; capture the full stderr, not a summary.
2. Check the corresponding `docs-corpus/<tool>/` entry — is the invoked flag real for the pinned version?
3. Compare versions: pinned (pixi.toml) vs upstream latest (update-check); an API migration may have landed upstream.
4. Change ONE variable per retry (mirror, spacing, credentials, query form) — record each attempt in the evidence.
5. If still unexplained: BLOCKED; escalate with full evidence output.

## Handoff

- `RECOVERABLE` → re-run `run/access-builder` with the fix applied.
- `BLOCKED` → stop; deliver debug-report.md to the user with the full evidence.