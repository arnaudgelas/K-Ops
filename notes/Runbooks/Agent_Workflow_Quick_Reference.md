---
title: "Agent Workflow Quick Reference"
type: maintenance
tags:
  - kb/maintenance
  - kb/runbook
---
# Agent Workflow Quick Reference

Compact command map for the starter vault.

## Commands

| Command | Use When | Notes |
|---|---|---|
| `ingest` | You have a newline-delimited list of URLs or file paths | Writes raw evidence into `data/raw/` and updates `data/registry.json` |
| `ingest-github` | You want a single GitHub repository snapshot | Captures repo docs and writes a raw snapshot |
| `compile` | You want source summaries and concept pages | Uses the active agent CLI |
| `ask` | You want a durable answer memo | Writes to `notes/Answers/` and may file insights back into the vault |
| `heal` | You need structural cleanup | Runs lint-and-repair behavior |
| `lint` | You want consistency checks | Verifies registry, backlinks, and note structure |
| `refresh` | You want to re-check known sources | Re-fetches registered sources before compiling |
| `backfill-source-notes` | You need missing source summaries created | Uses registry and raw artifacts |
| `bootstrap` | You want a fresh blank starter vault | Creates another copy of this file structure |

## Safe Order

1. `ingest`
2. `compile`
3. `ask`
4. `heal`
5. `lint`

## Rules

- Keep `data/raw/` empty until you actually ingest something.
- Keep `notes/Home.md` as the main navigation entry point.
- Use `notes/_Templates/` for note templates, not for source evidence.
