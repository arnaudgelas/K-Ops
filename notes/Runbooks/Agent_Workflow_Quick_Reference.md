---
title: "Agent Workflow Quick Reference"
type: maintenance
tags:
  - kb/maintenance
  - kb/runbook
---

# Agent Workflow Quick Reference

Compact command map for the K-Ops vault.

## Core Workflow Commands

| Command | Use When | Notes |
|---|---|---|
| `ingest` | You have a newline-delimited list of URLs or file paths | Writes raw evidence into `data/raw/` and updates `data/registry.json` |
| `ingest-github` | You want a single GitHub repository snapshot | Captures repo docs and writes a raw snapshot |
| `compile` | You want source summaries and concept pages | Uses the active agent CLI |
| `ask` | You want a durable answer memo | Writes to `notes/Answers/` and may file insights back into the vault |
| `heal` | You need structural cleanup | Runs lint-and-repair behavior |
| `lint` | You want consistency checks | Verifies registry, backlinks, and note structure |
| `refresh` | You want to re-check known sources | Re-fetches registered sources before compiling |
| `maintenance` | You want a full automated cycle | refresh + compile + normalize + backfill + graph + lint |

## Research Workflow Commands

| Command | Use When | Notes |
|---|---|---|
| `research-start` | Beginning a new deep investigation | Creates brief, status, progress scaffolding in `research/` |
| `research-status` | Checking phase of one or all active runs | Shows phase, tier, and file paths |
| `research-collect` | Source-collection phase | Agent fetches sources, updates findings |
| `research-review` | Contrarian review phase | Agent challenges the thesis; requires findings to exist |
| `research-report` | Final report drafting | Requires both findings and review |
| `research-import` | Importing an external AI-generated report | Creates lead-only source stubs |
| `research-archive` | Archiving a completed run | Only works when phase is `done` |

## Claim & Freshness Commands

| Command | Use When | Notes |
|---|---|---|
| `extract-claims` | After compile — rebuild `data/claims.json` | Extracts Key Claims bullets with stable IDs |
| `claim-search` | Looking for atomic claims by keyword | Accepts `--query`, `--limit`, `--format` |
| `stale-impact` | After refresh — seeing what changed | Lists concepts + answers with `revalidation_required: true` |
| `clear-stale-flags` | After reviewing stale concepts/answers | Removes `revalidation_required` flags; use `--dry-run` first |

## Contradiction Commands

| Command | Use When | Notes |
|---|---|---|
| `extract-contradictions` | After compile — rebuild `data/contradictions.json` | One record per Open Questions bullet; undocumented if section missing |
| `contradiction-search` | Looking for conflict records by keyword | Accepts `--query`, `--limit`, `--format` |

## Quality & Evaluation Commands

| Command | Use When | Notes |
|---|---|---|
| `scorecard` | Checking overall vault health | Writes `data/scorecard.json`; prints human-readable summary |
| `eval-setup` | Setting up the golden Q&A harness (once) | Creates `tests/qa_golden.yaml` if absent |
| `eval-check` | Validating the golden Q&A file structure | Parses and checks required fields |

## Analysis and Export Commands

| Command | Use When | Notes |
|---|---|---|
| `build-graph` | Building the vault graph + retention report | Writes to `data/graph/` |
| `search` | Keyword search across vault nodes | Accepts `--query`, `--limit`, `--scope` |
| `graph-traverse` | Walking the link graph from a starting note | Accepts `--start`, `--depth`, `--relation` |
| `retention-report` | Reviewing note freshness / stale content | Writes to `data/graph/retention_report.json` |
| `export-vault` | Exporting the vault as a zip archive | Writes to `outputs/` |
| `export-index` | Exporting a JSON/CSV index of all notes | Writes to `outputs/` |

## Maintenance and Repair Commands

| Command | Use When | Notes |
|---|---|---|
| `backfill-source-notes` | Missing source summaries need creating | Uses registry + raw artifacts |
| `backfill-source-metadata` | Source content hashes or timestamps missing | Updates registry and raw metadata |
| `backfill-concept-quality` | Concept pages missing `claim_quality` | Infers quality from evidence strength |
| `backfill-answer-quality` | Answer memos missing `answer_quality` | Infers from Vault Updates section |
| `normalize-github-sources` | GitHub source canonical URLs inconsistent | Adds canonical_repository + github_home |
| `render` | Producing a downstream deliverable | Accepts `--format` (memo, slides, outline, report) |

## Setup Commands

| Command | Use When | Notes |
|---|---|---|
| `install-agent-assets` | Syncing skills and prompts to agent runtimes | Run after editing `skills/` or `templates/` |
| `bootstrap` | Creating a fresh blank starter vault | Creates another copy of this file structure |

## Safe Execution Order

1. `ingest` or `refresh` (refresh auto-flags stale concepts/answers)
2. `compile`
3. `extract-claims`
4. `extract-contradictions`
5. `ask` (optional)
6. `heal`
7. `lint`
8. `scorecard` (optional — review health signals)

For deep research: see [[Research_Workflow|Research Workflow Runbook]].

## Rules

- Keep `data/raw/` immutable — never edit files there by hand.
- Keep `notes/Home.md` as the main navigation entry point.
- Use `notes/_Templates/` for note templates.
- Run `lint` after any structural edits (backlinks, frontmatter, note structure).
- Run `install-agent-assets` after editing `skills/` or `templates/`.

## Related

- [[Research_Workflow|Research Workflow Runbook]]
- [[Concepts/Workflow_Pattern_Inventory|Workflow Pattern Inventory]]
