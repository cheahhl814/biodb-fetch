---
name: biodb-fetch
description: 'Reusable dependency skill for programmatic database retrieval across eight domains: ncbi (Entrez + Datasets v2 CLI, routed by Datasets-vs-E-utilities rule), reads (SRA/ENA/STRIDES, ENA-first), geo (SuperSeries detection), id-mapping (UniProt async, Ensembl REST, BioMart bulk), orthologs-precomputed (OrthoDB/Compara/OMA/eggNOG), marker-references (eDNA libraries: UNITE/PlutoF, BOLD API, Mitohelper/SILVA/PR2/MIDORI2, DECIPHER-via-gdown), occurrence-marine (OBIS public API w/ WKT-year filters), taxonomy (NCBI Datasets + CoL XR/ChecklistBank + WoRMS AphiaIDs). Every fetch script emits a manifest.tsv with contract_version so consumer skills get a stable testable contract; licenses (CC-BY-NC) gate in code. Compute-heavy topics (BLAST, homology, interactions) out of scope. Read-side counterpart of ena-submit; pairs with lit-fetch (papers vs records). Built via skill-forge.'
version: 1.0.1
updated: "2026-11-17"
triggers:
  - "biomart id mapping"
  - "catalogue of life"
  - "database access"
  - "download genome"
  - "download sra"
  - "edna reference database"
  - "efetch esearch"
  - "entrez search"
  - "fetch records ncbi"
  - "geo accession"
  - "map gene ids"
  - "marine occurrence data"
  - "ncbi datasets"
  - "obis occurrence"
  - "precomputed orthologs"
  - "silva download"
  - "srr to fastq"
  - "taxonomy lookup"
  - "uniprot rest"
  - "unite download"
  - "worms aphiaid"
disable-model-invocation: true
---

# Database Access & Retrieval for Bioinformatics

> Dependency skill for programmatic bioinformatics database access: NCBI Entrez E-utilities + Datasets v2 CLI, SRA/ENA/STRIDES read download, GEO with SuperSeries detection, UniProt/Ensembl/BioMart ID mapping, and pre-computed ortholog retrieval. Every fetch script emits manifest.tsv with a contract_version that consuming skills verify. Compute-heavy topics (BLAST, remote homology, interaction databases) are deliberately out of scope. Built on the AiX-BIO convention via skill-forge.

## Audience

This skill serves two purposes:

- **AI Agents**: Triggered by the phrases above. The agent must follow the strict evidence chain and run the Go/No-Go gates.
- **Human Users**: Provides a transparent audit trail.

## When to Use This Skill

Use this skill when a consumer (another skill, or a person) needs to **retrieve records or files from a biological database**, e.g.:

- Genomes, gene records, or precomputed ortholog reports from NCBI (Datasets CLI / E-utilities), or bulk ID mapping via UniProt / Ensembl / BioMart
- SRA/ENA read downloads (ENA-first mirror order) and GEO series retrieval (SuperSeries-aware)
- eDNA reference libraries (UNITE/PlutoF, BOLD, SILVA/PR2/MIDORI2, Mitohelper), OBIS marine occurrences, or taxonomy backbones (NCBI Datasets, Catalogue of Life XR / ChecklistBank, WoRMS)
- A downstream skill that needs a `manifest.tsv` (contract v1/v2) describing exactly what was downloaded, from where, md5 included

**Do NOT use this skill** if:

- You need the literature (papers, preprints) → `lit-fetch`
- You need to *submit* data to ENA → `ena-submit`
- You need de novo ortholog inference (OrthoFinder3, species trees) → `ortholog-inference`
- You need BLAST, remote homology search, or interaction databases — out of scope for this skill
- You only need to *read* the `docs-corpus/` reference material — no fetch is involved

## 0. Orchestrator — detect stage, route to the right sub-skill

This meta-skill is a **router**, not a doer. It does not duplicate logic from the sub-skills. Its job is to ask: **"what stage is the user at, and which sub-skill should they invoke next?"**

### 0.1 Locate the run directory

By convention the agent writes handoff files (see §B) to a run directory. Default: the current working directory. Override with `RUN_DIR` env var.

### 0.2 Detect the user's stage

Stage is decided by which artifacts exist in the run directory (`$RUN_DIR`, default: cwd). First match wins:

```bash
# Artifact ladder — the sub-skills write these; first match wins
if   [ -f "$RUN_DIR/qc-report.md" ]; then echo "done      — QC verdict exists"
elif [ -f "$RUN_DIR/manifest.tsv" ]; then echo "qc        — run finished, QC pending"
elif [ -f "$RUN_DIR/contract.json" ]; then echo "run       — preflight passed (check its verdict first)"
else echo "preflight — nothing staged yet"; fi
```

Ambiguous evidence (e.g. a `manifest.tsv` but no `contract.json`, or artifacts from an older run in the same directory) → ask the user one short question (see **SP0** in §0.5).

### 0.5 Master ask-user stop points

This orchestrator has **one** user-facing stop point (SP0). All other stop points live in the sub-skills. The pattern is **Evidence + Recommend + Options**.

#### SP0 — Entry-stage ambiguity

| Trigger | Ask |
|---|---|
| Artifact ladder is ambiguous (e.g. `manifest.tsv` exists but `contract.json` doesn't, or stale artifacts from an older run sit in the directory) | "Which stage are we in — preflight (re-check environment), run (fetch), or qc (verify an existing fetch)?" |

**Auto-pick when**: the ladder gives a single unambiguous answer, OR the user just invoked the skill with no other context and no artifacts exist → default to `preflight`.

#### Routing rule

Auto-pick the default when the evidence is unambiguous. Ask only when the agent genuinely cannot decide.

### 0.3 Route to the right sub-skill

| Stage / domain | Sub-skill | Produces |
| --- | --- | --- |
| `preflight` | `preflight/access-preflight` | `contract.json` + `preflight-report.md` + `preflight-evidence.txt` |
| `run` — ncbi / reads / geo / id-mapping / orthologs-precomputed | `run/access-builder` (scripts `ncbi_fetch.py`, `ncbi_datasets.py`, `sra_fetch.py`, `geo_fetch.py`, `idmap.py`, `orthologs_fetch.py`) | `manifest.tsv` + files + `run-report.md` |
| `run` — marker-references (eDNA libraries) | `run/markers-reference` (`scripts/marker_refs.py`) | `manifest.tsv` rows with license gating |
| `run` — occurrence-marine (OBIS) | `run/occurrence-marine` (`scripts/occurrence_marine.py`) | occurrence records + `manifest.tsv` |
| `run` — taxonomy (NCBI/CoL/WoRMS) | `run/taxonomy-backbone` (`scripts/taxonomy.py`) | taxonomy files + `manifest.tsv` |
| `qc` | `qc/access-qc` (`scripts/qc_check.py --outdir <dir>`) | `qc-report.md` (PASS / PASS-WITH-WARNINGS / FAIL) |
| failure anywhere | `debug/access-debug` | `debug-report.md` (RECOVERABLE / BLOCKED) |
| structural self-check | `battle-test/access-battle-test` | `battle-test-report.md` |

**Do not skip preflight.** The preflight sub-skill computes the evidence and writes `contract.json`; the run phase refuses to start without a `GO` / `GO-WITH-WARNINGS` verdict.

If the request spans multiple run sub-skills (e.g. genomes + taxonomy), run them sequentially into the same `--outdir` — the manifest is append-merged and de-duplicated on `(accession, source, path)`.

## Update Check

This skill ships with a self-update check that compares the deployed `SKILL.md` (and the rest of the skill) against the upstream `github.com/cheahhl814/biodb-fetch` repo via `git fetch` + SHA diff — no GitHub API call, no extra dependencies.

```bash
pixi run update-check
# Verdict legend (exit code in parens):
#   UP-TO-DATE       (0)  local HEAD matches origin/HEAD
#   LOCAL-AHEAD      (0)  unpushed local commits; no action needed
#   BEHIND-BY-N      (1)  upstream is N commits ahead → rsync from @skills/biodb-fetch/
#   OFFLINE          (2)  git fetch failed (no network / no credentials); informational
#   NO-ORIGIN        (2)  no `origin` remote configured; informational
```

When `BEHIND-BY-N`, the script prints the canonical fix (rsync from `@skills/biodb-fetch/` to `~/.agents/skills/biodb-fetch/` per AGENTS.md §4a, then `diff -rq` to verify). When `OFFLINE`, the script still prints `local_sha` + deployed version so the user can compare by hand. The full implementation is in `bin/skill-update-check.py` (rendered from the meta-skill's `templates/bin/skill-update-check.py.j2`).

### 0.4 How to run

There is no single all-in-one command: preflight and debug are agent-driven procedures, and the fetch phase is split by domain. The scripts are the entry points; `pixi` only provides the pinned environment.

```bash
pixi install

# Phase 1 — preflight: the agent follows preflight/access-preflight/SKILL.md
#           (writes contract.json; refuses to proceed on NO-GO)

# Phase 2 — fetch (one example per domain):
pixi run python3 scripts/ncbi_fetch.py search --db nucleotide --query 'BRCA1[Gene Name] AND human[ORGN]'
pixi run python3 scripts/ncbi_datasets.py genome --accession GCA_000008985.4 --include genome,gff3 --out work/genome
pixi run python3 scripts/sra_fetch.py download --srr SRR1234567 --out work/reads      # ENA-first
pixi run python3 scripts/geo_fetch.py series --accession GSE12345 --out work/geo
pixi run python3 scripts/idmap.py biomart --ids-file ids.txt --from ensembl_gene_id --to hgnc_symbol --out work/ids

# Phase 3 — QC (verifies md5s, formats, contract_version):
pixi run qc --outdir work/reads
# equivalent: pixi run python3 scripts/qc_check.py --outdir work/reads
```

## A. Pipeline Architecture

The analysis is divided into **three sequential phases**: Preflight → Run → QC. The agent MUST complete each phase in order and pass the associated "Go/No-Go" gate.

### Phase 1: Preflight (The Audit)

**Goal**: Validate environment, credentials, reachability and disk; write `contract.json` + `preflight-report.md`.

- **Sub-skill**: `preflight/access-preflight`
- **Must-Verify**: All endpoints for the target domains answered; NCBI credentials state known; scratch disk ≥ 3× expected FASTQ volume.
- **Exit Gate**: `contract.json` exists with verdict ≥ `GO-WITH-WARNINGS`.

### Phase 2: Run (The Workflow)

**Goal**: Execute the fetches for the requested domain(s) under the manifest contract.

- **Sub-skill**: `run/access-builder` (ncbi / reads / geo / id-mapping / orthologs-precomputed), `run/markers-reference`, `run/occurrence-marine`, `run/taxonomy-backbone`
- **Must-Verify**: Preflight verdict ≥ `GO-WITH-WARNINGS`; correct domain module chosen.
- **Exit Gate**: `manifest.tsv` written in `--outdir`, files non-empty, paths recorded.

### Phase 3: QC (The Report)

**Goal**: Verify everything the run produced before a consumer trusts it.

- **Sub-skill**: `qc/access-qc` (`scripts/qc_check.py --outdir <dir>`)
- **Must-Verify**: Run output present; `manifest.tsv` complete.
- **Exit Gate**: `qc-report.md` exists with verdict PASS or PASS-WITH-WARNINGS.

## B. The Evidence Chain & Handoff Contract

| From → To | Artifact | Owner | Consumer |
| --- | --- | --- | --- |
| Consumer → Preflight | Consumer request (domain, IDs, outdir) | upstream | `preflight/access-preflight` |
| Preflight → Run | `contract.json` + `preflight-report.md` | `preflight/access-preflight` | `run/*` |
| Run → QC | `manifest.tsv` + fetched files in `--outdir` | `run/*` | `qc/access-qc` |
| QC → User | `qc-report.md` | `qc/access-qc` | User / consumer skill |

## C. Output contract — no artifact

This orchestrator skill produces **no file of its own**. All artifacts are produced by the sub-skills.

## D. Go/No-Go Gates

The agent must stop and warn the user if:

- **Preflight NO-GO**: `contract.json` shows verdict `NO-GO`.
- **QC FAIL**: `qc-report.md` shows `FAIL` (md5 mismatch, empty payload, unparseable file) — the consumer must not receive the outdir.

## E. Common follow-ups

| User says | What to do |
| --- | --- |
| "Show me my last QC report" | `cat $RUN_DIR/qc-report.md` |
| "What did the fetch produce?" | `column -t -s$'\t' $RUN_DIR/manifest.tsv` or `cat $RUN_DIR/run-report.md` |
| "Can I publish this?" | Point to `contract.json` + `manifest.tsv` + `qc-report.md` as the audit trail. |

## Verification

- [ ] Preflight was performed; `contract.json` verdict ≥ `GO-WITH-WARNINGS`.
- [ ] Run completed; `manifest.tsv` exists in `--outdir` and covers every requested accession.
- [ ] QC was performed; `qc-report.md` exists with verdict PASS or PASS-WITH-WARNINGS.

## Handoff pointers

After this orchestrator routes the user to a phase, the agent should explicitly state which sub-skill was invoked and what file it produces.

## Provenance

Built with the [skill-forge](https://github.com/cheahhl814/skill-forge) meta-skill. Pattern adopted from [BettaMt-agents](https://github.com/cheahhl814/BettaMt-agents).