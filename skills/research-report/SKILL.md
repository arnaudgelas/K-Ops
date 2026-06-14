---
name: research-report
description: Draft the final research report from collected evidence and the contrarian review.
---

# Research Report

## Goal
Synthesize the brief, source notes, findings, and contrarian review into a bounded, evidence-grounded final report.

## Inputs
- Research brief (`research/briefs/<slug>-<date>.md`)
- Findings file (`research/findings/<slug>-<date>.md`)
- Contrarian review (`research/notes/<slug>-contrarian-review.md`)
- Report scaffold (`research/reports/<slug>-<date>.md`)
- Source notes in `notes/Sources/`

## Output contract
- Build the report from collected evidence, not background memory.
- Keep conclusions bounded by the evidence and name what remains uncertain.
- Address the strongest objections and missing evidence raised in the contrarian review.
- Write/update `{report_path}` preserving frontmatter.
- Populate `## Executive Summary`, `## Methodology`, `## Evidence and Analysis`, and `## Contradictory or Missing Evidence`.
- Cite source summaries using Obsidian wikilinks.
- Save the completed report to the report file and update `{progress_path}`.

## Rules
- Do not add claims not grounded in the collected sources.
- Distinguish established findings from provisional claims.
- Treat imported model-generated report claims as leads until verified against primary sources.
- Cite the relevant source notes with wikilinks where appropriate.
