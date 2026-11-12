---
name: access-builder
description: Execute database retrieval under the manifest.tsv contract across five domains with source-routing rules — ncbi (Entrez + Datasets CLI), reads (ENA-first → SRA → STRIDES), geo (SuperSeries detection), id-mapping (BioMart bulk, REST single, UniProt async), orthologs-precomputed (OrthoDB/Compara/OMA/eggNOG). Use when a consumer skill needs records, sequences, FASTQs, ID maps, or precomputed orthologs.
version: 1.0.0
updated: "2026-10-05"
triggers:
  - "download genome"
  - "entrez search fetch"
  - "download sra fastq"
  - "geo superarray super"
  - "map ids bulk"
  - "precomputed orthologs"
disable-model-invocation: true
---

# Access Builder (run phase)

> **v1.0.0.** The main retrieval phase. Routes each question to the right source using the decision rules below, executes via `scripts/`, and emits every artifact under the **manifest.tsv contract** (see §Contract).

## Inputs / Outputs contract

### Inputs

| Path | Source | Required? |
| --- | --- | --- |
| `contract.json` (verdict ≥ GO-WITH-WARNINGS) | `access-preflight` | yes |
| Consumer request: domain, IDs/accessions, output dir | consumer skill | yes |

### Outputs

| Path | Owner | Format | Notes |
| --- | --- | --- | --- |
| Downloaded files in `--outdir` | this skill | per-domain | FASTA/FASTQ/tabelar/JSON |
| `--outdir/manifest.tsv` | this skill | TSV | **the contract** — one row per written file |
| `run-report.md` | this skill | Markdown | per-request summary |

## The manifest.tsv contract (what consumers depend on)

Every fetch script writes/append-merges `manifest.tsv` with EXACTLY these columns:

| Column | Content |
| --- | --- |
| `accession` | input identifier used |
| `source` | actually-used endpoint (mirror recorded if rerouted) |
| `url` | exact URL fetched (`-` for CLI-mediated local dumps) |
| `path` | local file path |
| `md5` | md5 of the written file |
| `bytes` | file size |
| `retrieval_date` | ISO8601 UTC |
| `tool` | e.g. `datasets 18.38.0` / `requests 2.x` |
| `format` | `fasta`/`fastq`/`gff`/`json`/`tsv`/`txt` |
| `contract_version` | `1` — consumer preflights assert this exists and is ≥ expected |

Consumers must read ONLY the manifest and MUST NOT parse the skill's internals. If a consumer needs a transform (e.g. decompress, filter), do it downstream of the manifest row.

## Routing rules (the distillation of 15 reference topics)

### Domain 1 — `ncbi` (Entrez E-utilities + Datasets v2)

**The single most important fact:** ESearch returns *UIDs*, not records. Content comes from EFetch/ESummary (or Datasets). Forgetting this is the most common Entrez mistake.

**Datasets-vs-E-utilities rule:** genomes, gene records, and precomputed orthologs → `datasets` CLI; everything else (PubMed, SRA queries beyond accession resolution, dbSNP, ClinVar, taxonomy…) → E-utilities.

- Search: `scripts/ncbi_fetch.py search --db nucleotide --query 'Homo sapiens[ORGN] AND BRCA1[Gene Name]'`
  - Inspect `QueryTranslation` — build field-qualified queries (`[ORGN]`, `[Gene Name]`) so results are translation-stable.
  - >10K results: `usehistory=y` (WebEnv/QueryKey), fetch server-side in chunks; never loop retmax through the full UID list.
- Fetch: `scripts/ncbi_fetch.py fetch --db nucleotide --uids <ids> --rettype fasta --out <dir>`
- Link: `scripts/ncbi_fetch.py link --db-from gene --db-to pubmed --uids <ids>`
- Bulk/genome: `scripts/ncbi_datasets.py genome --accession GCA_000008985.4 --include genome,gff3,cds --out <dir>`
- Pitfalls baked into the scripts: `retmax` caps, weekly index lag (a record can exist but not be searchable for ~1 week), WebEnv TTL (forgetting history after ~2h idle), EPost 200-ID limit, XML schema brittleness in Entrez (ESummary XML changed repeatedly); prefer JSON where the API supports it.

### Domain 2 — `reads` (SRA/ENA/STRIDES)

**Mirror order: ENA first** (plain HTTPS + md5 in the API response — simplest), then SRA direct, then STRIDES/cloud mirrors.

- Resolve: `scripts/sra_fetch.py resolve --srr SRR1234567 --out <dir>` (pysradb → ENA metadata: ftp path + md5)
- Download: `scripts/sra_fetch.py download --srr SRR1234567 --out <dir>` — prefers ENA FASTQ; falls back to `prefetch`+`fasterq-dump` SRA direct; records which in `source`.
- **fasterq-dump scratch trap**: writes *uncompressed* FASTQ to scratch — plan ~3× final size; keep 10x technical reads in mind (they are IN the FASTQ; strip downstream, only if the consumer expects that).

### Domain 3 — `geo` (GEO + BioStudies/ArrayExpress)

- Fetch: `scripts/geo_fetch.py series --accession GSE12345 --out <dir>`
- **SuperSeries trap**: detect SuperSeries BEFORE processing (GEOparse exposes the relations field; sample list is empty or points to SubSeries). If SuperSeries → enumerate SubSeries, fetch per-SubSeries, record the split in the manifest (`source` = `geo-subseries`).
- Processed-vs-raw decision: raw (FASTQ) generally unavailable on GEO — if the platform is sequencing and raw needed, route to Domain 2 with the linked SRA accessions.

### Domain 4 — `id-mapping` (UniProt REST / Ensembl REST / BioMart)

**Tool-selection rule: BioMart for bulk (>5K IDs), Ensembl REST for singles, UniProt for protein-centric mappings.**

- Bulk: `scripts/idmap.py biomart --ids-file ids.txt --from ensembl_gene_id --to hgnc_symbol --out <dir>` (pybiomart; one query for thousands — NEVER a per-ID REST loop)
- UniProt async: `scripts/idmap.py uniprot --ids-file ids.txt --from Ensembl --to UniProtKB --out <dir>` — submits a job, polls the job URL until done (stream endpoint); records job id in the manifest.
- Pitfalls: UniProt REST moved endpoints + JSON schema in 2022 — old `uniprot.org/...` paths return 301/404; map IDs to *current* accessions (`UP00...` style not legacy `UniProtKB/Swiss-Prot` prose).

### Domain 5 — `orthologs-precomputed`

- One ortholog: use the NCBI Datasets ortholog report (`scripts/ncbi_datasets.py ortholog --gene-id <id>`) — fast, but no confidence score / tree-aware calls.
- High-quality tree-aware orthologs: OrthoDB (`scripts/orthologs_fetch.py orthodb --gene <id> --level <level>`), Ensembl Compara homology endpoint (high/low confidence), OMA, eggNOG, PANTHER — pick by taxonomic scope; OrthoDB/Compara default.
- **Boundary**: DE NOVO ortholog inference (OrthoFinder3/HOGs/species trees) is the separate `ortholog-inference` skill — call it when precomputed entries are absent or insufficient. This skill never computes orthologs.

### Domain 6 — `marker-references` (eDNA metabarcoding reference libraries)

UNITE v10.2+ via PlutoF DOI, BOLD REST per-record COI, Mitohelper Zenodo sets, SILVA/PR2/MIDORI2, DECIPHER pre-trained via **gdown-for-Drive**. Full runbook: see `run/markers-reference/SKILL.md` (routing table, license gating with `--i-accept-license`, gdown quota trap, MitoFish Sept-2025 re-organization). Curation (which URL/version/license) is delegated to nf-edna's `reference-db` catalog; this skill executes.

### Domain 7 — `taxonomy`

NCBI Datasets v2 taxonomy endpoints + Catalogue of Life XR via ChecklistBank API. Full runbook: see `run/taxonomy-backbone/SKILL.md`. **Key rule: GBIF Backbone is frozen (2023); COL XR is the default** (checklistKey `7ddf754f-d193-4cc9-b351-99906754a03b`). Never silently join backbones — fetch both when a consumer needs cross-source consistency.

## Staging the run

1. Confirm `contract.json` verdict ≥ GO-WITH-WARNINGS (else stop → `access-preflight`).
2. Classify the request into one domain; if uncertain, ask the consumer skill (or user) — never guess a source.
3. Execute the matching script; all scripts accept `--outdir` and write `manifest.tsv` (append-merge with de-dup on `(accession, source, path)`).
4. Verify: non-empty outputs, md5 recomputed, manifest complete (`qc/access-qc` does the full check — run it if >25 files or any empty file).
5. Write `run-report.md` (per-domain summary, warnings surfaced).

## Signature library

| Signature in stderr / log | Likely cause | Suggested fix |
| --- | --- | --- |
| `gdown failed ... quota` | Google Drive quota on DECIPHER trainingFiles | retry later; mirror per nf-edna reference-db; never curl Drive links |
| ChecklistBank 404 on pinned checklistKey | COL XR key rotated | re-resolve from GBIF migration docs; consumers must not hardcode the key |
| --- | --- | --- |
| `HTTP 429 Too Many Requests` (eutils) | Anonymous rate budget exceeded (3 req/s) | Space calls ≥ 0.4 s; configure api_key for 10 req/s |
| `DBResultError: ('id not found', ...)` | Record created recently — weekly index lag | Verify via esearch `--uid` on the known UID; document in manifest |
| `WebEnv expired` | History lost (TTL ~2h) | Re-run esearch; keep batch fetches in one session |
| `urllib3.exceptions.MaxRetryError ... ensembl.org` | Ensembl REST rate limit (≥15 req/s) or Bead outage | Back off 8 s; switch bulk work to BioMart |
| `pysradb` missing metadata for SRR | Accession too new / metadata lag | Fall through to `prefetch` SRA direct (mirror order) |
| BioMart returns empty for valid IDs | Mirror outage or wrong dataset/bio mart selected | Retry other mirror (useast.ensembl.org); verify dataset name via `pybiomart` list |

## What NOT to do

- Do not fetch records through ESearch alone (UIDs ≠ content).
- Do not loop single-ID REST calls when BioMart covers the bulk in one query.
- Do not write into a consumer's internal layout — the contract is `--outdir` + manifest only.
- Do not use retired UniProt endpoints (pre-2022 strings).
- Do not process a GEO SuperSeries as a normal series.
- Do not compute orthologs de novo here.

## Handoff

- Success → consumer skill receives `--outdir` + `manifest.tsv`; then `qc/access-qc` (mandatory for >25 files), else direct handoff.
- Failure → `debug/access-debug` with the stderr signature.