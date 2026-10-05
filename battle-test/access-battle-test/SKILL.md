---
name: access-battle-test
description: Quality gate for the biodb-fetch skill — structural smoke tests (frontmatter coherence, contract wiring, signature libraries, docs-corpus freshness, pixi parse, git hygiene, self-update check, fixtures determinism) plus fixtures-first contract verification against scripts/ (offline) and opt-in live canaries per endpoint (fixtures first — live API tests are nondeterministic). Verdict PASS / PASS-WITH-WARNINGS.
version: 1.0.0
updated: "2026-10-05"
triggers:
  - "battle-test database access"
  - "verify skill structure"
---

# Access Battle-Test

> **v1.0.0.** 14 structural checks + fixtures-first script verification. Contract: consume `skill-built.md` (from build) + `params.json`; emit `battle-test-report.md` (verdict ≥ PASS-WITH-WARNINGS required for ship). All scripts py_compile or py-import first, never blind-execute fetches.

## Inputs / Outputs contract

### Inputs

| Path | Source |
| --- | --- |
| `params.json` (tracked), `skill-built.md` (run artifact) | preflight / build |
| SKILL.md, README.md, pixi.toml, sub-skill dirs, docs-corpus/, scripts/, test-data/ | build |

### Outputs

| Path | Owner |
| --- | --- |
| `$RUN_DIR/battle-test-report.md` | this skill |
| `$RUN_DIR/battle-test_evidence.txt` (raw) | this skill |

## Checks

1. **Frontmatter coherence** — SKILL.md + all sub-skill SKILL.mds have name/description/version/updated/triggers; versions match.
2. **Description length** — every frontmatter description ≤ 1024 chars (Pi hard limit; herdr-lab incident 2026-10-02).
3. **Contract wiring** — preflight/run/qc/debug artifact names referenced by the next phase's Inputs table all match.
4. **Signature-library completeness** — ≥ 3 entries in each sub-skill's §Signature library.
5. **Scripts parse** — `python3 -m py_compile scripts/*.py` all green (offline-safe, no fetch executed).
6. **Docs-corpus freshness** — every tool in pixi.toml has `docs-corpus/<tool>/README.md` with ≥1 populated source; `.fingerprints` matches current md5 of corpus files.
7. **Pixi parse** — `pixi lock --dry-run` solves (no isolated envs in this skill: joint solve at preflight).
8. **Git hygiene** — `.gitignore` covers run artifacts (skill-built.md, battle-test-report.md, preflight.md, *_evidence.txt); `git ls-files -ci --exclude-standard` empty; `params.json` tracked.
9. **Self-update check** — `bin/skill-update-check.py` exists, py_compiles, referenced by README.md + pixi.toml.
10. **Fixtures determinism** — two runs of `test-data/make_fixtures.py` produce identical MANIFEST.tsv.
11. **README hygiene** — no unfilled slots, no machine-specific paths, no personal info (§2a rules).
12. **Contract columns** — `dbaccess_common.py` MANIFEST_COLUMNS == the contract v2 set the sub-skills document (incl. the `cache` column).
13. **Out-of-scope honesty** — README + run sub-skill state that local-blast/remote-homology/interaction-databases are NOT included; ortholog boundary vs `ortholog-inference` present; marker-reference license gates (CC-BY-NC refuse-without-flag) live in code, not prose only.
14. **Fixtures-first script verification (opt-in `--execution`, offline fixtures only)** — run each fetch script with a `--help`-only smoke (argparse wiring works without network).

### Live canaries (opt-in, scheduled; NEVER part of default verdict)

One cheap read-only GET per endpoint family, run on a schedule (weekly or per-release), recorded but advisory-only:

- eutils `einfo.fcgi` (200), datasets API (200), ENA portal (200), UniProt `rest.uniprot.org/` (200), Ensembl REST ping (200), OrthoDB (200)
- Rationale: recorded FIXTURE captures can pass while a real endpoint migrated (UniProt-2022 precedent) — the canary detects that drift between releases. Rate-limit friendly (≤ 2 req/endpoint, spaced).

## Signature library

| Signature in evidence / log | Likely cause | Suggested fix |
| --- | --- | --- |
| `verdict: BEHIND-BY-N` from `pixi run update-check` | upstream `github.com/cheahhl814/biodb-fetch` is ahead of the deployed copy | re-deploy via `rsync` from the skills checkout, then `diff -rq` to verify |
| `verdict: OFFLINE` / `NO-ORIGIN` from update-check | no network or no `origin` remote — informational, exit 2 | re-run when online, or `git remote add origin https://github.com/cheahhl814/biodb-fetch.git` |
| `yaml ScannerError: mapping values are not allowed` | frontmatter description contains an unquoted `: ` | wrap the description in single quotes (2026-10-05 master SKILL.md incident) |
| `FAIL: run artifacts are TRACKED` | `.gitignore` rendered after a `git add -A` | `git rm --cached <artifact>` — files stay on disk; never force-commit run artifacts |
| `test-data fixtures differ between two runs` | non-deterministic write (time/seed/gzip mtime) in the generator | fix the params/template and re-render `make_fixtures.py`, never the rendered copy |

## Verdict

- `PASS` / `PASS-WITH-WARNINGS` (≤1 WARN) → ship-ready: commit + push + deploy per meta-skill Phase 4 exit gates.
- Any `FAIL` → stop; route to `debug/access-debug`.

## What NOT to do

- Do not execute network fetches as part of the default gate (fixtures/canaries only).
- Do not accept an empty docs-corpus entry without routed SP1 evidence.
- Do not push/deploy from this skill — that is the user's gated step.