---
name: access-qc
description: Post-run QC for biodb-fetch fetches — recompute md5 against manifest.tsv, verify contract_version column, non-empty payloads, manifest completeness (no rows missing path/md5), and domain sanity rules (fasta non-empty, FASTQ gzip integrity, JSON/TAB parses). Writes qc-report.md + evidence. Use after a fetch with >25 files or any empty/partial output.
version: 1.0.1
updated: "2026-11-17"
triggers:
  - "qc database access"
  - "verify manifest"
  - "check downloads"
disable-model-invocation: true
---

# Access QC (qc phase)

> The verification layer between a fetch and the consumer's pipeline. Every recommendation cites a measured value; the run phase hands files to a consumer only after this passes.

## Inputs / Outputs contract

### Inputs

| Path | Source | Required? |
| --- | --- | --- |
| `--outdir/manifest.tsv` (contract v2, with the `cache` column) | `run/access-builder` | yes |
| downloaded files referenced by the manifest | run | yes |

### Outputs

| Path | Owner | Format | Notes |
| --- | --- | --- | --- |
| `qc-report.md` | this skill | Markdown | PASS/WARN/FAIL verdict + evidence table |
| `qc-evidence.txt` | this skill | text | raw recomputation output |

## Procedure

```bash
# 1. Manifest sanity: header == CONTRACT_VERSION 1 column set; every row has path+md5
pixi run python3 scripts/qc_check.py --outdir ./work/biodb-fetch/
```

`scripts/qc_check.py` (shipped in the skill root) verifies, per manifest row:

1. **Recompute md5** of the local file; compare with the manifest value.
2. **Non-empty payloads** (≥ declared `min_file_bytes`); warn on any 0-byte file.
3. **Format sanity**: `fasta` → first byte non-empty, records parseable by simple regex; `fastq(.gz)` → gzip openable + 4-line periodicity on first 10k lines; `tsv/json` → parseable; marker-reference `fasta` → header contains a taxon separator (`>` line with taxonomy delimiters where the source promises them); taxonomy zips → openable + non-trivial size.
4. **Contract version**: column `contract_version` == 2 everywhere (v2 = contract v1 + `cache` column; v1 manifests predate the shared store and FAIL).
5. **Mirror honesty**: if preflight rerouted (SP2), `source` must name the mirror actually used.
6. **License honesty**: MIDORI2/BOLD-sourced rows must carry the source label only after the explicit `--i-accept-license` pass (the fetch refuses otherwise).
6. **SuperSeries honesty**: geo domain rows from a SuperSeries must say `geo-gsupers` and carry the SubSeries split in the run report.

### Verdict

| Verdict | Condition |
| --- | --- |
| `PASS` | all rows recompute + parse |
| `PASS-WITH-WARNINGS` | parses but ≥1 WARN (e.g. gzipped FASTQ not byte-verifiable, missing md5 for CLI-mediated local dumps) |
| `FAIL` | md5 mismatch, empty payload, unparseable file, missing manifest — consumer must NOT receive the outdir |

## Signature library

| Signature | Likely cause | Fix |
| --- | --- | --- |
| `md5 mismatch` | truncated transfer / partial `.part` rename race | re-fetch the row via the manifest URL; never hand-patch the manifest |
| `0-byte .fastq` | fasterq-dump scratch OOM mid-write (3× space trap) | re-run reads domain via ENA-first routing |
| `gzip Not a Gzip file` | ENA returned an HTML error page as the URL body | check `url` column; re-resolve accessions and mirror-retry |
| `contract_version` empty | manifest written by a pre-contract tool version | treat the outdir as legacy; re-run the fetch |

## Handoff

`PASS` / `PASS-WITH-WARNINGS` → consumer skill receives `--outdir` + `manifest.tsv`. `FAIL` → `debug/access-debug` with the failing row(s).