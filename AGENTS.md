# AGENTS.md

This repo is designed for agentic CLI workflows.

## Roles

### Source Ingestor
Goal: transform new raw sources into normalized source summaries.

### Wiki Compiler
Goal: merge source summaries into durable concept pages and indexes.

### Lint + Heal
Goal: detect contradictions, weak structure, missing backlinks, and unsupported claims.

### Q&A Agent
Goal: answer using the vault, then file durable insights back into the vault.

### Render Agent
Goal: convert the current vault into memos, briefings, slide outlines, diagrams, and plot specs.

## Repo Contract
- `data/raw/` holds source evidence
- `notes/Sources/` holds per-source summaries
- `notes/Concepts/` holds durable knowledge pages
- `notes/Answers/` holds generated answer memos
- `notes/Home.md` is the Obsidian entry point
- `notes/TODO.md` tracks gaps and healing tasks
- `notes/Runbooks/Agent_Workflow_Quick_Reference.md` is the compact operator map for cross-CLI workflows

## Behavioral Guardrails
- Prefer modifying a small number of files with high signal.
- Prefer precise edits over broad rewrites.
- Preserve provenance from source summaries into concept pages.
- When uncertain, mark uncertainty explicitly.
