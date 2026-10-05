---
name: taxbackdrop-taxonomy-backbone
description: Retrieval runbook for the taxonomy domain — NCBI Datasets v2 taxonomy endpoints (summary/names/children via the pinned datasets CLI) and Catalogue of Life Extended Release via ChecklistBank API. Includes the frozen GBIF-Backbone → COL XR migration rule every consumer must know since rgbif 3.9. Use when resolving names to canonical IDs, synonyms, or children lists.
version: 1.0.0
updated: "2026-10-05"
triggers:
  - "taxonomy lookup"
  - "ncbi taxonomy"
  - "catalogue of life"
  - "name resolution"
---

# Taxonomy Backbone (run module)

> **v1.0.0.** Two sources, fetch-only, no new heavy dependencies. This module does NOT parse or compare taxonomies — it retrieves backbone evidence files under the manifest contract.

## The 2025+ backbone rule (state this to every consumer)

**GBIF's Backbone Taxonomy is frozen (last updated 2023) and Catalogue of Life Extended Release (COL XR) is GBIF's new default taxonomy.** Consumers using occurrence APIs must migrate their `checklistKey` to GBIF's COL XR key `7ddf754f-d193-4cc9-b351-99906754a03b` (alpha-numeric taxon keys, not legacy numeric ones). The `rgbif 3.9.0` breaking-change note documents the same migration. Biodb-fetch's colxr source defaults to that key.

## Source selection

| Need | Source | Why |
| --- | --- | --- |
| NCBI-centric lineage, species children, synonyms along GenBank records | `scripts/taxonomy.py ncbi` (Datasets v2 taxonomy endpoints) | Same binary already pinned; taxonomy is now a first-class Datasets dataset |
| Name → canonical ID across checklists, synonym flattening, GBIF-facing work | `scripts/taxonomy.py colxr` (ChecklistBank REST) | COL XR is the live authoritative backbone |
| Marine taxa: AphiaIDs for OBIS joins, fuzzy matching, synonym/vernacular flattening | `scripts/taxonomy.py worms` (WoRMS REST, marinespecies.org) | OBIS keys on AphiaID; WoRMS is the marine backbone — fuzzy `AphiaRecordsByMatchNames`, synonyms, common names |

## Contract

Every call appends to `--outdir/manifest.tsv` (contract v1). `source` values: `ncbi-datasets-taxonomy`, `checklistbank-colxr`. Children packages come as Datasets zips (record under `format=json`, path the zip).

## Procedure

```bash
pixi run python3 scripts/taxonomy.py ncbi --query "Mytilus galloprovincialis" --out ./work/database-access/
pixi run python3 scripts/taxonomy.py ncbi --taxid 292547 --children
pixi run python3 scripts/taxonomy.py colxr --name "Mediterranean mussel"
pixi run python3 scripts/taxonomy.py worms --name "Thunnus thynnus" --fuzzy --synonyms --vernacular --out ./work/database-access/
```

## Pitfalls (baked into the module)

1. **Name-first, taxid-second**: NCBI accepts both; species-rank queries change with taxonomy edits — pin the taxid in the consumer once resolved.
2. **Taxonomy propagation lag**: changes take days to flow from NCBI Taxonomy into GenBank/RefSeq/Datasets views — a mismatch is not an error; record it in the manifest notes.
3. **COL XR ≠ NCBI Taxonomy**: they disagree at ranks and synonym sets; never silently join across backbones — fetch both and let the consumer decide.
4. **Ambiguous vernacular names**: common names resolve to many usages; prefer scientific names + explicit `dataset`.

## Signature library

| Signature | Likely cause | Fix |
| --- | --- | --- |
| `datasets summary taxonomy` empty for a valid name | propagation lag or name variant | retry with taxid; check the taxonomy updates page |
| `ChecklistBank 404 on dataset key` | the pinned `checklistKey` rotated | re-resolve COL XR key from GBIF migration docs; never hardcode in consumers |
| `HTTP 429` on api.checklistbank.org | burst above fair use | the script's RateLimiter handles it; raise spacing for batch loops |
| WoRMS returns empty for a real marine name | name variant, non-marine placement, or lag | retry with `--fuzzy` (`AphiaRecordsByMatchNames`); check `marine_only` semantics |
| WoRMS name-usage `status` is unaccepted | synonym of the current concept | follow `valid_AphiaID`/accepted name in the response; never silently treat synonyms as accepted |
| `Zip-only children package` | expected — `--children` returns a data-package zip | unzip downstream; manifest row records the zip |

## Handoff

Pass `--outdir` + `manifest.tsv` to the consumer; name→ID joins live downstream of this module.