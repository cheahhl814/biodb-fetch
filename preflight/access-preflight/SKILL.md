---
name: access-preflight
description: Validate the environment before any database retrieval — pixi env + tools, network reachability per endpoint, NCBI email/api_key readiness, scratch disk (the fasterq-dump ~3× FASTQ space trap), and rate-limit budget. Writes contract.json (machine) + report. Refuses to proceed on GO/NO-GO failures. Use when starting retrieval work, after long pauses, or when a consumer skill delegates its data-download step.
version: 1.0.0
updated: "2026-10-05"
triggers:
  - "preflight database access"
  - "check ncbi api key"
  - "before downloading data"
---

# Access Preflight (biodb-fetch)

> **v1.0.0.** Environment + credential + reachability audit for all five retrieval domains (ncbi, reads, geo, id-mapping, orthologs-precomputed). Writes `contract.json` + `preflight-report.md`; the run phase refuses to start without `GO` / `GO-WITH-WARNINGS`.

## Audience

This sub-skill serves two purposes:

- **AI Agents**: Triggered by the phrases above. Must run all evidence collection steps, then write the artifacts.
- **Human Users**: Provides a transparent audit trail for the fetch phase.

## When to Use This Skill

Use this skill if:

- A consumer skill delegated its data-download step to `biodb-fetch` and you are about to run `run/` for the first time in a session.
- A fetch phase previously failed and you suspect environment/credential drift since the last preflight.

Do NOT use this skill if:

- You are only reading `docs-corpus/` (reference material needs no environment).
- You are auditing the skill's own structure (that is `battle-test/access-battle-test`).

## 0. Inputs / Outputs contract

### Inputs (consumed)

| Path | Source | Required? |
| --- | --- | --- |
| `params.json` | preflight (meta-skill) | yes |
| `pixi.toml` | build | yes |
| Consumer request (skill name, target domain, IDs/accessions) | consumer skill | yes |

### Outputs (produced)

| Path | Owner | Format | Notes |
| --- | --- | --- | --- |
| `contract.json` | this skill | JSON | Machine contract: verdict, endpoint reachability, credential state, rate budget, contract_version |
| `preflight-report.md` | this skill | Markdown | Human audit trail |
| `preflight-evidence.txt` | this skill | text | Raw evidence output |

### Verdict gate

The `run/access-builder` phase **refuses to run** unless `contract.json` verdict is `GO` or `GO-WITH-WARNINGS` with at least the target domain's class passing. A `NO-GO` verdict stops the pipeline.

## 0.5 Ask-User Stop Points

This sub-skill has **4 stop points** (SP1–SP3a, SP3). Each fires only when the evidence is ambiguous.

### SP1 — NCBI email / api_key missing

| Trigger | Evidence check | Action |
| --- | --- | --- |
| `NCBI_EMAIL` / `NCBI_API_KEY` env unset and no key file found | Biopython requires email; 3 req/s anonymous vs 10 with key | Ask: "No NCBI credentials configured. (A) proceed anonymous at 3 req/s (slow bulk, fine for <1K records), (B) configure `NCBI_EMAIL` + `NCBI_API_KEY` now (recommended for batches; get a key at ncbi.nlm.nih.gov/account/settings/), (C) abort" |

**Auto-pick when**: the request is a single-record demo. Default: proceed anonymous with a 3 req/s budget.

### SP2 — An endpoint unreachable

| Trigger | Evidence check | Action |
| --- | --- | --- |
| Any target-endpoint HEAD/GET times out twice (eutils, datasets API, ENA, UniProt, Ensembl, OrthoDB) per the domain map below | Network/firewall/mirror problem, not a code problem | Ask: "Endpoint `<url>` unreachable. (A) reroute to the documented mirror (e.g. ENA ↔ SRA ↔ STRIDES), (B) retry in N minutes (transient outage), (C) abort this domain" |

**Auto-pick when**: a documented mirror exists and the user has not restricted sources. Default: reroute to the mirror and record it in the manifest (`source` column shows the mirror actually used).

### SP3a — GBIF / BOLD credentials absent (marker-references / occurrence consumers)

| Trigger | Evidence check | Action |
| --- | --- | --- |
| Consumer needs GBIF headless downloads or BOLD bulk package, but no GBIF_USERNAME/PASSWORD or BOLD token is configured | Account-gated sources | Ask: "`<source>` needs an account. (A) configure credentials now via env vars (recommended, never echoed), (B) use the public tier only (BOLD per-record API is public; GBIF occurrence search is public but bulk download is not), (C) abort" |

**Auto-pick when**: the consumer request stays within the public tier. Default: proceed public, note the boundary.

### SP3 — Scratch disk below the SRA floor

| Trigger | Evidence check | Action |
| --- | --- | --- |
| Free disk on the target scratch dir < 3 × expected FASTQ size | fasterq-dump writes uncompressed FASTQ to scratch — needs ~3× final size | Ask: "Scratch space low (`X` free, need `Y`). (A) point `--outdir`/`TMPDIR` at a bigger disk, (B) stream via ENA directly to compressed output (recommended when ENA is reachable), (C) abort" |

**Auto-pick when**: disk is ample. Default: proceed.

### Operating rule

> Auto-pick when the evidence is unambiguous; ask when the agent genuinely cannot decide. Present evidence → recommendation → options.

## Procedure

The procedure has **three phases**: (1) gather inputs, (2) compute evidence, (3) write outputs.

### 1. Gather inputs from the consumer request

| Input | Required? | Default if absent |
| --- | --- | --- |
| Target domain(s) (ncbi / reads / geo / id-mapping / orthologs-precomputed) | yes | error |
| Output dir for fetched files + manifest.tsv | yes | `./work/biodb-fetch/` |
| Scratch dir (for fasterq-dump etc.) | no | system TMPDIR |
| Expected data volume (records/runs) | no | `small` (budgets 3 req/s) |

### 2. Compute evidence (always run; never skip)

```bash
# 2a. Pixi env sanity: tool versions match pixi.toml pins
pixi run python3 -c "import Bio, pysradb, GEOparse, pybiomart, requests; print('python clients OK')"
pixi run datasets version 2>/dev/null || echo "datasets CLI MISSING"
pixi run prefetch --version 2>/dev/null || echo "prefetch MISSING"

# 2b. Network reachability — HTTP 200/403-expected for each endpoint of the target domain
#   ncbi:      https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi
#             https://api.ncbi.nlm.nih.gov/datasets/v2
#   reads:     https://www.ebi.ac.uk/ena/portal/api/  (ENA — DEFAULT first-choice mirror)
#             https://sra-pub.s3.amazonaws.com/       (SRA mirror)
#   geo:       https://ftp.ncbi.nlm.nih.gov/geo/
#   id-mapping: https://rest.uniprot.org/  https://rest.ensembl.org/ (check https://www.ensembl.org for BioMart)
#   orthologs: https://orthodb.org/ https://www.ensembl.org/biomart/martservice
#   markers:   https://plutof.ut.ee/ (UNITE DOI)  https://boldsystems.org/ (BOLD API)
#   marine:    https://api.obis.org/v3 (OBIS public — no creds)  https://marinespecies.org/rest (WoRMS)
#             https://zenodo.org/ (Mitohelper/MIDORI2/region refs)  https://drive.google.com/ (DECIPHER)
#   taxonomy:  https://api.checklistbank.org/ (COL XR)
curl -sI --max-time 15 "<url>" -o /dev/null -w "%{http_code}\n"   # per endpoint; record all codes

# 2c. Credentials
printf 'NCBI_EMAIL=%s\n' "${NCBI_EMAIL:-<unset>}"
printf 'NCBI_API_KEY=%s\n' "${NCBI_API_KEY:+<set — never print the value>}"
printf 'NCBI_API_KEY=%s\n' "${NCBI_API_KEY:-<unset>}"

# 2d. Scratch disk vs SRA floor (fasterq-dump trap)
df -h "$TMPDIR" | tail -1

# 2d2. Shared store: resolve + writable check (sub-folder inside the skill folder,
#      or $BIODB_FETCH_STORE override); multi-GB payload domains need headroom here
echo "store=${BIODB_FETCH_STORE:-<skill_dir>/store}"
test -w "${BIODB_FETCH_STORE:-<skill_dir>/store}" 2>/dev/null && echo 'OK: store writable' || mkdir -p "${BIODB_FETCH_STORE:-<skill_dir>/store}"

# 2d3. Store inventory peek — data already in the store, reusable before any download:
cut -f1,2,10,11 "${BIODB_FETCH_STORE:-<skill_dir>/store}/manifest.tsv" 2>/dev/null | head -20

# 2e. Rate budget: anonymous = 3 req/s with 1/s burst; keyed = 10 req/s. Record the chosen budget in contract.json.
```

### 3. Write outputs

#### 3a) `contract.json` schema

```json
{
  "contract_version": "1",
  "verdict": "GO",
  "domains_checked": ["ncbi", "reads"],
  "endpoints": {"ncbi_eut": "200", "datasets_v2": "200", "ena_portal": "200"},
  "ncbi_credentials": {"email": "<set|unset>", "api_key": true, "rate_budget_rps": 10},
  "scratch_free_gb": 92,
  "warnings": []
}
```

#### 3b) Report template

```markdown
# Access Preflight report

Verdict: GO ✅ / GO-WITH-WARNINGS ⚠️ / NO-GO ❌

| Check | Verdict | Value | Threshold |
|---|---|---|---|
| Pixi env tools | ✅ | 8/8 import/run | all |
| Endpoints | ✅ | 200 on all target domain endpoints | reachable |
| NCBI credentials | ⚠️ | anonymous | keyed for bulk |
| Scratch disk | ✅ | 92 GB | ≥ 3× expected FASTQ |
| Rate budget | ✅ | 10 req/s (keyed) | — |
```

## Signature library

| Signature in stderr / log | Likely cause | Suggested fix |
| --- | --- | --- |
| `ModuleNotFoundError: pkg_resources` | Python ≥ 3.12 + setuptools ≥ 81 | `pixi add 'setuptools<81'` |
| `HTTP 429` / `502` from eutils on first call | Anonymous burst above 3 req/s | Add spacing ≥ 0.34 s between calls; re-run with api_key for 10 req/s |
| `datasets version` prints nothing / segfault | glibc mismatch in the binary build | Pin a different `ncbi-datasets-cli` build, or route through E-utilities |
| `prefetch: network failure` | SRA direct blocked; ENA fine | Reroute: resolve SRR → ENA FASTQ via `pysradb` and skip sra-tools (SP2) |

## Verification

- [ ] `contract.json` exists and is valid JSON with `contract_version`.
- [ ] Every target-domain endpoint got a recorded HTTP code.
- [ ] Credentials state recorded (value never echoed).
- [ ] Verdict is NOT `NO-GO` before `run/` starts.

## Handoff

- `GO` / `GO-WITH-WARNINGS` → `run/access-builder` with the consumer's domain request.
- `NO-GO` → stop; list failing checks; fix or reroute per SP2.