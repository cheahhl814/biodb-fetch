# Database Access & Retrieval for Bioinformatics

[![Version](https://img.shields.io/badge/version-1.0.1-blue)](#-installation)
[![Type](https://img.shields.io/badge/type-agent%20skill-blueviolet)](#-installation)
[![Built with](https://img.shields.io/badge/built%20with-skill--forge-orange)](https://github.com/cheahhl814/skill-forge)

[![Shape](https://img.shields.io/badge/shape-multi--tool%20pipeline-8A2BE2)](#-pipeline-overview)

Reusable dependency skill for programmatic access to NCBI, EMBL-EBI, and UniProt resources across eight retrieval domains: ncbi (Entrez E-utilities + NCBI Datasets v2 CLI with the Datasets-vs-E-utilities routing rule), reads (SRA/ENA/STRIDES with ENA as default mirror), geo (GEO + SuperSeries detection), id-mapping (UniProt REST async jobs, Ensembl REST + BioMart bulk mapping), orthologs-precomputed (OrthoDB/Compara/OMA/eggNOG/PANTHER lookup), marker-references (eDNA metabarcoding libraries: UNITE/PlutoF, BOLD API, Mitohelper/SILVA/PR2/MIDORI2, DECIPHER-via-gdown), occurrence-marine (OBIS occurrence/checklist/dataset retrieval with WKT/year filters), and taxonomy (NCBI Datasets taxonomy + Catalogue of Life XR/ChecklistBank; GBIF Backbone frozen 2023 rule). Shared preflight layer handles NCBI email/API-key, network reachability, and rate limiting; every fetch script emits a manifest.tsv (accession, source, URL, md5, retrieval date, tool version, contract_version) so consuming skills get a stable, testable contract. Compute-heavy topics (local BLAST, remote homology, interaction databases) are deliberately out of scope - they need multi-GB pixi environments and different failure modes. Built from a 15-topic prose reference corpus via skill-forge.

**Repository**: https://github.com/cheahhl814/biodb-fetch

> [!NOTE]
> Sibling disambiguation: **lit-fetch** retrieves literature (papers); **biodb-fetch** retrieves
> records/data from biological databases (NCBI, ENA, GEO, UniProt, Ensembl, OrthoDB, UNITE/BOLD/OBIS/WoRMS).
> This skill is the read-side counterpart of **ena-submit** (which uploads data back to ENA).


> [!NOTE]
> Current version: **v1.0.1** (updated 2026-11-17).

## Contents

- [Installation](#-installation)
- [Usage](#-usage)
- [Pipeline overview](#-pipeline-overview)
- [Tools](#-tools)
- [Update check](#-update-check)
- [Repository layout](#-repository-layout)
- [Hard guarantees](#-hard-guarantees)
- [Provenance](#-provenance)

## 🚀 Installation

This is an **agent skill**, not a user-facing library. The recommended install path is to let your AI agent import it.

**Option A — give your agent this prompt (recommended):**

```text
Install the biodb-fetch skill from
https://github.com/cheahhl814/biodb-fetch —
clone it into your agent's skills directory (the path your agent watches
for skills) and run `pixi install` from that directory. Then read the
skill's SKILL.md to understand its phases and the Input/Output contract
for each. Confirm when the environment is ready.
```

**Option B — manual install:**

```bash
git clone https://github.com/cheahhl814/biodb-fetch.git
cd biodb-fetch
pixi install
```

> [!TIP]
> `pixi install` resolves every pinned tool from `pixi.toml` (channels: conda-forge, bioconda) into an isolated `.pixi/` environment — no system-wide installs, no version conflicts with other skills.

## 💡 Usage

The skill is designed to be driven by an AI agent: the agent reads the master `SKILL.md`, detects the current phase from the filesystem state of your run directory, and routes to the right sub-skill.

### Natural-language prompts that trigger the skill

```text
download genome
database access
entrez search
efetch esearch
ncbi datasets
```

### Manual execution

There is no single all-in-one command. Preflight, debug and battle-test are agent-driven procedures (an agent reads the sub-skill and follows it); the fetch phase is plain scripts; only QC ships as a `pixi` task:

```bash
pixi install

# Phase 1 — preflight: follow preflight/access-preflight/SKILL.md
#   (agent-driven: checks tools, endpoints, credentials, scratch disk;
#    writes contract.json + preflight-report.md)

# Phase 2 — fetch (examples; see run/<module>/SKILL.md for the full routing)
pixi run python3 scripts/ncbi_fetch.py search --db nucleotide --query 'human[ORGN] AND BRCA1[Gene Name]'
pixi run python3 scripts/ncbi_datasets.py genome --accession GCA_000008985.4 --include genome,gff3 --out work/genome
pixi run python3 scripts/sra_fetch.py download --srr SRR1234567 --out work/reads   # ENA-first
pixi run python3 scripts/taxonomy.py --help    # other domains: marker_refs.py, occurrence_marine.py, geo_fetch.py, idmap.py, orthologs_fetch.py

# Phase 3 — QC (only scripted phase; recomputes md5s, checks formats + contract_version)
pixi run qc --outdir work/reads
```

> [!NOTE]
> `pixi run` only pins the environment. Everything else is `python3 scripts/<tool>.py` — run any script with `--help` for its flags.

> [!IMPORTANT]
> Each phase has an explicit **Inputs/Outputs contract** at the top of its sub-skill `SKILL.md`. If the upstream artifact is missing (e.g. you run `run` before `preflight` passed), the sub-skill refuses to proceed and tells you which phase to run first. Phases are gated on purpose — don't skip them.

## 🔬 Pipeline overview

The analysis follows a phased evidence chain. Each phase consumes the artifacts of the previous phase and gates progression with a Go/No-Go check.

| # | Phase | Goal | Sub-skill | Artifact produced |
|:--|:------|:-----|:----------|:------------------|
| **1** | `preflight` | Validate pixi env, network reachability, NCBI email/api_key, and scratch disk before any fetch | `preflight/` | `contract.json` + `preflight-report.md` |
| **2** | `run` | Execute the retrieval routing (ncbi / reads / geo / id-mapping / orthologs-precomputed / marker-references / occurrence-marine / taxonomy) under the manifest.tsv contract | `run/` | downloaded files + `manifest.tsv` |
| **3** | `qc` | Verify every fetched file: md5, source, contract_version, non-empty payloads before consumer handoff | `qc/` | `qc-report.md` (+ JSON verdict on stdout) |
| **4** | `debug` | Interpret fetch failures via the signature library (rate limits, WebEnv TTL, 2022 migrations, mirror outages) | `debug/` | `$RUN_DIR/debug-report.md` |
| **5** | `battle-test` | Structural smoke tests + fixtures-first contract verification + opt-in live canaries | `battle-test/` | `$RUN_DIR/battle-test-report.md` |

> [!TIP]
> Read each sub-skill's `SKILL.md` for the full procedure, its ask-user stop points, and its signature library (stderr pattern → cause → fix).

## 🧰 Tools

All tools are resolved from conda-forge/bioconda via the pinned `pixi.toml`.

| Tool | Version | Role |
|:-----|:--------|:-----|
| `python` | 3.12 | scripting runtime |
| `biopython` | 1.88 | Bio.Entrez esearch/efetch/elink client |
| `ncbi-datasets-cli` | 18.38.0 | modern bulk genome/gene/ortholog download |
| `sra-tools` | 3.4.1 | SRA prefetch/fasterq-dump |
| `pysradb` | 2.5.1 | SRA/GEO accession resolution |
| `geoparse` | 2.0.4 | GEO SOFT parsing; SuperSeries handling |
| `pybiomart` | 0.2.0 | bulk ID mapping via BioMart |
| `gdown` | 6.4.1 | Google Drive downloads (DECIPHER pre-trained trainingFiles) |
| `pyobis` | 1.6.2 | OBIS occurrence/taxa/checklist/dataset API client |
| `requests` | * | UniProt REST, Ensembl REST, ENA API, cloud mirrors |

Tool usage is grounded in the offline `docs-corpus/` snapshots (version-matched `--help`/`man` captures, upstream repo docs, and web docs as fallback) — the agent reads these instead of guessing flags.

## 🗄️ Shared store

All fetched payloads land in one shared store **inside the skill folder** (`<skill-dir>/store/`, override with `BIODB_FETCH_STORE`). Payload paths are content-addressed (`<domain>/<slug>-<sha16>.<ext>` + md5 `.sha256` sidecars, no timestamps), so a second skill or batch reusing the same data gets a `cache=hit` manifest row pointing into the store — zero re-download. Every row also lands in `<store>/manifest.tsv`, the cross-skill data inventory; grep it before dispatching a request. Because a source's data can grow (e.g. OBIS occurrence records), cache rows carry `retrieval_date`; consumers set freshness windows, and `--refresh` re-pulls.

> [!IMPORTANT]
> The store lives inside the skill folder: any `rsync --delete` update of the skill MUST exclude it — `rsync -av --delete --exclude='store/' src/ ~/.agents/skills/biodb-fetch/`. Data is gitignored (`store/`) and never committed.

## 🔄 Update check

Every skill built with [skill-forge](https://github.com/cheahhl814/skill-forge) ships a self-update check that compares the deployed git SHA against this upstream repo via `git fetch` — no GitHub API call, no extra dependencies.

```bash
pixi run update-check
```

| Verdict | Exit | Meaning |
|:--------|:-----|:--------|
| `UP-TO-DATE` | 0 | Local HEAD matches origin/HEAD |
| `LOCAL-AHEAD` | 0 | Unpushed local commits; no action needed |
| `BEHIND-BY-N` | 1 | Upstream is N commits ahead → re-pull/re-sync from this repo |
| `OFFLINE` | 2 | `git fetch` failed; informational only |
| `NO-ORIGIN` | 2 | No `origin` remote configured; informational only |

## 📁 Repository layout

```text
biodb-fetch/
├── SKILL.md                 # Master orchestrator (router — start here)
├── README.md                # This file
├── pixi.toml                # Pinned tool environment (pixi install)
├── docs-corpus/             # Offline snapshots of upstream tool docs
│   └── python/
│   └── biopython/
│   └── ncbi-datasets-cli/
│   └── sra-tools/
│   └── pysradb/
│   └── geoparse/
│   └── pybiomart/
│   └── gdown/
│   └── pyobis/
│   └── requests/
├── preflight/            # Phase sub-skill
├── run/            # Phase sub-skill
├── qc/            # Phase sub-skill
├── debug/            # Phase sub-skill
├── battle-test/            # Phase sub-skill
├── bin/
│   └── skill-update-check.py  # Self-update check (pixi run update-check)
```

## 🔒 Hard guarantees

- **Filesystem evidence chain** — every phase emits the artifact the next phase consumes; the boundary between phases is the filesystem, not agent memory.
- **Docs-grounded tool usage** — tool flags come from `docs-corpus/`, never from the agent's memory.
- **Explicit stop points** — ambiguous decisions are surfaced to you as *Evidence + Recommend + Options*, not auto-picked.
- **Reproducible environments** — every tool is pinned in `pixi.toml` and resolved via pixi.

## 🚀 Nextflow runner

This skill does not currently ship a Nextflow runner. For cohort/HPC execution, wrap the `pixi run` tasks in a workflow scheduler of your choice.

## Provenance

Built with the [skill-forge](https://github.com/cheahhl814/skill-forge) meta-skill, following the AiX-BIO skill convention (preflight → build → debug → battle-test evidence chain). Pattern adopted from:

- **BettaMt-agents** — https://github.com/cheahhl814/BettaMt-agents
- **bacterial-genome-analysis** — https://github.com/cheahhl814/bacterial-genome-analysis
- **amr-gene-screening** — https://github.com/cheahhl814/amr-gene-screening

## License

Released under the MIT License — see the license file in this repository for details.
