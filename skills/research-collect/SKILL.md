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

## Output contract
- Create or update source notes in `notes/Sources/` following the strict metadata schemas (valid kinds, strengths, kind-specific required fields, and PDF extraction coverage where applicable).
- Treat imported model-generated reports as leads only. Ensure their source notes declare `authority: lead_only`, `verification_state: needs_primary_sources` / `needs_fetch`, and secondary/stub evidence strength.
- Update `{findings_path}`. Maintain all frontmatter. Populate claims in `## Key Claims` directly citing the source notes.
- Distinguish evidence from inference explicitly.
- Keep the findings file bounded, sourced, and reviewable.

## Rules
- Prefer primary sources over commentary.
- Do not create duplicate source notes - update existing ones.
- Treat imported model-generated reports as leads until verified.
- Keep uncertainty explicit; do not inflate claim confidence.
- Append a progress update to `{progress_path}` after completing collection.
