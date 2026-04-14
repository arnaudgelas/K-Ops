---
name: research-collect
description: Collect and evaluate sources for an active research run, then distill initial findings.
---

# Research Collect

## Goal
Populate the findings file for a research run with high-signal, well-sourced claims.

## Inputs
- Research brief (`research/briefs/<slug>-<date>.md`)
- Research status (`research/notes/<slug>-status.md`)
- Research progress log (`research/notes/<slug>-progress.md`)
- Findings file (`research/findings/<slug>-<date>.md`)
- Existing source notes in `notes/Sources/`

## Steps
1. Read the research brief to understand the working question, scope, and assumptions.
2. Search broadly first, then narrow to authoritative primary sources.
3. For each key source, create or update a source note in `notes/Sources/`.
4. Distinguish evidence from inference explicitly in source notes.
5. Update the findings file with high-signal claims and open questions.
6. Treat any imported model-generated reports as leads — verify their claims against primary sources before promoting them into findings.
7. Append a short progress update to the progress log when done.

## Rules
- Prefer primary sources over commentary.
- Do not create duplicate source notes — update existing ones.
- Keep uncertainty explicit; do not inflate claim confidence.
