---
name: research-workflow
description: Manage resumable research runs under `research/` and coordinate the collect, review, report, import, and archive steps.
---

# Research Workflow

## Goal
Run higher-stakes topics as resumable, tiered research threads outside the curated vault until they are ready to promote.

## Use When
- the user wants a structured research run rather than an immediate vault answer
- a topic needs source collection, contrarian review, and a final report
- an external model report should be imported as a lead, not treated as authority

## Core Flow
1. Start a run with `uv run python scripts/kb.py research-start --topic "<text>" --tier <fast|standard|deep>`.
2. Check or resume with `research-status`.
3. Collect sources with `research-collect`.
4. Run a contrarian review with `research-review`.
5. Draft the report with `research-report`.
6. Import external reports with `research-import` only when you want to preserve provenance and treat them as leads.
7. Archive the run with `research-archive` after completion.

## Companion Skills
- `research-collect`
- `research-review`
- `research-report`

## Rules
- Keep active run files in `research/`, not in `notes/`.
- Treat imported model-generated reports as leads, not authority.
- Preserve the status/progress/review/report linkage across steps.
- Promote durable findings into the main vault only after verification.

## Outputs
- `research/briefs/`
- `research/notes/`
- `research/findings/`
- `research/reports/`
- `research/imports/`
- `research/archive/`
