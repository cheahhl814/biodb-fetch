---
name: taxbackdrop-occurrence-marine
description: Retrieval runbook for marine biodiversity occurrence data — OBIS via its public REST API (pyobis client) with scientificname/taxonid/datasetid/nodeid/year/depth/WKT-geometry filters and no credentials for the public tier. Covers occurrences, species checklists, and dataset metadata; pairs with GBIF occurrence data (marine↔terrestrial duality) for consumers like occurrence-crosscheck and edna-gbif-publish. Use when a pipeline needs marine species occurrence records.
version: 1.0.0
updated: "2026-10-05"
triggers:
  - "obis occurrence"
  - "marine occurrence data"
  - "species distribution marine"
  - "obis checklist"
disable-model-invocation: true
---

# Occurrence Marine — OBIS (run module)

> **v1.0.0.** Fetch-only module for OBIS (Ocean Biodiversity Information System), the world's marine species-occurrence integration harvested from thousands of datasets. Delivers occurrence records, species checklists, and dataset metadata under the manifest v1 contract. Public tier needs NO credentials.

## Contract

| Field | Value |
| --- | --- |
| `source` | `obis-api-occurrence` / `obis-api-checklist` / `obis-api-dataset` |
| Row `url` | the exact executed API URL (pyobis exposes it as `api_url`) — reproducible |
| Credentials | **none for public search/download**; keep the row's date window + geometry in the manifest for reproducibility |
| Records' ID spine | `AphiaID` (WoRMS) — resolve names via the `taxonomy` domain's `worms` source when cross-joining |

## Source selection (marine occurrence questions)

| Need | Command |
| --- | --- |
| Occurrence points for a species (+ WKT region, year window) | `scripts/occurrence_marine.py occurrence --name "Chelonia mydas" --wkt "POLYGON((...))" --from-year 2010 --to-year 2024` |
| Species checklist under a taxon | `scripts/occurrence_marine.py checklist --name "Perciformes"` |
| Dataset metadata (coverage, institutions, record counts) | `scripts/occurrence_marine.py datasets --name "Chelonia mydas"` |
| Name → AphiaID (+synonyms, vernaculars) | `scripts/taxonomy.py worms --name "Thunnus thynnus" --synonyms --vernacular` |

## Pitfalls (baked into the module + runbook)

1. **WKT is a filter, not a projection** — geometry filters run server-side; verify the polygon in the consumer's map layer, not here.
2. **Year windows**: single-year values work as ranges (`1990,1991`-style); a one-digit year means AD 98 — always pass 4-digit years.
3. **Limit discipline**: occurrence queries can hit thousands of records; the script pages via `--limit` (default 1000). For region-scale pulls, split by WKT tiles or year windows instead of one giant query.
4. **OBIS ≠ GBIF record IDs**: cross-check consumers must join via scientific name (+ AphiaID ↔ GBIF taxonKey) — the two systems issue different identifiers for the same concept.
5. **Dropped/flagged-quality records**: OBIS carries QC flags and `dropped` statuses; consumers decide whether to keep flagged records — this module returns what the API returns, flagged fields included.
6. **Name-to-Aphia drift**: taxonomy edits propagate; pin the AphiaID once resolved and record it in the consumer's manifest.

## Signature library

| Signature | Likely cause | Fix |
| --- | --- | --- |
| `pyobis` import error in scripts | ran outside the pixi env | `pixi run python3 scripts/occurrence_marine.py …` (pyobis 1.6.2 in pixi.toml) |
| Empty occurrence response for a marine species | name variant / too-restrictive WKT | drop the geometry filter first; fuzzy-resolve the name via `taxonomy.py worms --fuzzy` |
| `HTTP 429/5xx` from api.obis.org | burst limit during batch pulls | the script pages via `--limit`; raise spacing for CSV-list loops |
| Records lack coordinates | absence-only records or eDNA-detection extension rows | check `Dropped`/`flags` fields and the DNADerivedData extension; document consumer choice |
| `POLYGON((...))` rejected server-side | malformed WKT (ring order, unclosed ring) | validate the WKT text (`geocoding` skill or shapely) before re-submitting |

## Handoff

Pass `--outdir` + `manifest.tsv` to the consumer. Occurrence interpretation, mapping, and GBIF-joining stay downstream (`occurrence-crosscheck`, `geocoding`, `data-visualization`).