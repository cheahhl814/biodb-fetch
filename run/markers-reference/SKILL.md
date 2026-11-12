---
name: taxbackdrop-marker-references
description: Retrieval runbook for eDNA metabarcoding marker-reference libraries — UNITE (PlutoF DOI, v10.2+), BOLD REST API per-record COI, Mitohelper Zenodo datasets (12S/COI), SILVA/PR2/MIDORI2/DECIPHER execution with gdown-for-Drive handling, and explicit CC-BY-NC license gating. Centralizes nf-edna reference-db's catalog into executable fetches under the manifest contract. Use when a pipeline needs 16S/18S/12S/COI/ITS reference sequences.
version: 1.0.0
updated: "2026-10-05"
triggers:
  - "edna reference database"
  - "silva download"
  - "pr2 download"
  - "unite download"
  - "midori"
  - "bold coi"
  - "12S reference"
  - "ITS reference"
disable-model-invocation: true
---

# eDNA Marker References (run module)

> **v1.0.0.** Executes marker-reference library downloads under the manifest v1 contract. **Curation stays with nf-edna's `reference-db` sub-skill** (catalog of URLs, licenses, DECIPHER pre-trained matrix); this module is the retrieval layer that delivers files + md5 + manifest to any consumer — and fixes the nf-edna audit gap (no automated retriever with manifest semantics).

## Division of responsibilities

| Concern | Owns |
| --- | --- |
| Which URL / which version / which license | `nf-edna reference-db` catalog (curated) |
| Download execution, md5, retries, manifest rows, gdown-for-Drive | this module (`scripts/marker_refs.py`) |
| DECIPHER idtaxa training (when a pre-trained model doesn't exist) | `nf-edna idtaxa-training` (never here) |

## Sources & routing

| Key | Source | Mechanics | License |
| --- | --- | --- | --- |
| `unite` | UNITE v10.2 (DOI 10.15156/BIO/2483911) | pinned file URL from the repository page via PlutoF; QIIME `get-unite-data` uses the same PlutoF REST API | CC-BY-SH terms |
| `bold` | BOLD REST API (`boldsystems.org/index.php/API_Public/combined`) | per-record COI pulls by taxon — API-first; the bulk Public Data Package needs an account (out of contract scope) | BOLD terms |
| `mitohelper` | Mitohelper Zenodo reference datasets (v42 Nov2025 — dedup vs MitoFish Sept-30 update) | pinned `--doi-id` + `--file-url` from the Zenodo record | open |
| `silva` / `pr2` / `midori2` | as curated in nf-edna reference-db | direct https / GitHub raw / Zenodo; MIDORI2 is **CC-BY-NC** | surfaced below |
| `decipher` | DECIPHER pre-trained trainingFiles | **Google Drive — gdown only** (curl returns quota-exceeded HTML); `--drive-id` | per reference |
| `zenodo` / `url` | any pinned reference record (CanFish, INBO 12S, region-specific sets) | generic fetch | check the record |

## License gating (script-level, mirrors nf-edna preflight SP5)

`MIDORI2` (CC-BY-NC) and `bold` (data terms) refuse to run without `--i-accept-license` — the script prints the license note and stops. CC-BY / open entries auto-proceed. This keeps the non-commercial trap honest at execution time, not just in prose.

## Procedure

```bash
# UNITE (ITS): pin version + group + variant, URL from the repository page
pixi run python3 scripts/marker_refs.py unite --version 10.2 --taxon_group fungi --type static \
    --file-url <UNITE-static-fasta-url>
# BOLD COI by taxon
pixi run python3 scripts/marker_refs.py bold --taxon Thunnus
# Mitohelper 12S QIIME-compatible set
pixi run python3 scripts/marker_refs.py mitohelper --doi-id 17602902 --file-url <record-file-url>
# DECIPHER pre-trained (Google Drive)
pixi run python3 scripts/marker_refs.py decipher --drive-id <file-id>
# Any curated URL from nf-edna reference-db
pixi run python3 scripts/marker_refs.py url --url <curated-url> --source silva-nr99
```

## Pitfalls (baked into the module)

1. **UNITE paginates per (version, taxon_group, cluster)** — the script demands an explicit `--file-url` instead of scraping the DOI landing; that URL is versioned and reproducible.
2. **gdown quota errors are transient** — retry later or use the nf-edna mirror; never shell out to curl for Drive links.
3. **BOLD public API has limits and no SLA** — space ≥1 s (RateLimiter), chunk taxon queries, avoid bulk-package thinking (that's the account path).
4. **MitoFish was re-organized Sept 30 2025** (duplicates merged) — prefer the Mitohelper Zenodo datasets over raw MitoFish pulls; record which in the manifest `source`.
5. **Region-specific references (CanFish, INBO) are complements, not substitutes** — they cover narrower faunas than MIDORI2/SILVA; document the coverage choice in the consumer's report.
6. **Pre-trained R model files are binary RDS** — format checks live in nf-edna (Biostrings/DECIPHER load), not here; this module only verifies non-empty + checksum.

## Signature library

| Signature | Likely cause | Fix |
| --- | --- | --- |
| `gdown failed ... quota` | Google Drive daily quota for the file | retry later; alternate mirror; never curl a Drive link |
| `BOLD API returns HTML or error body` | taxon too broad / API hiccup | narrow `--taxon`; retry with spacing; check boldsystems.org status |
| `UNITE DOI page not resolvable to file` | repository re-layout | use the repository page's pinned URL; never scrape the landing |
| `--i-accept-license missing` | license gate on MIDORI2/BOLD | read terms, re-run with the flag — never bypass by hand-downloading inside the skill |
| Zenodo 404 on a record file | record versioned (v1..v42) | pin the exact version in `--file-url` from the record page |

## Handoff

Pass `--outdir` + `manifest.tsv` to the consumer (nf-edna or any metabarcoding pipeline). Reference-library choice + coverage rationale stays with the consumer's report.