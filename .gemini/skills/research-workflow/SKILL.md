---
name: research-workflow
description: Manage resumable research runs under `research/` and coordinate the collect, review, report, import, and archive steps.
---

# Research Workflow

## Goal
Run higher-stakes topics as resumable, tiered research threads outside the curated vault until they are ready to promote.

## Use When
- The user wants a structured research run rather than an immediate vault answer.
- A topic needs source collection, contrarian review, and a final report.
- An external model report should be imported as a lead, not treated as authority.

## Core Flow
1. **Start a run**: `uv run kops research-start --topic "<text>" --tier <fast|standard|deep>`.
2. **Check status**: `uv run kops research-status [topic|all]`.
3. **Collect sources**: `uv run kops research-collect --agent <codex|claude|gemini> --topic "<topic>"` (runs collect prompt).
4. **Adversarial review**: `uv run kops research-review --agent <codex|claude|gemini> --topic "<topic>"` (runs review prompt).
5. **Draft report**: `uv run kops research-report --agent <codex|claude|gemini> --topic "<topic>"` (runs report prompt).
6. **Import external reports**: `uv run kops research-import --topic "<topic>" --path <file> --provider <provider> --origin <origin>`.
7. **Archive completed run**: `uv run kops research-archive --topic "<topic>"` (after phase shows `done`).

## Phase Guidance
The `research-collect`, `research-review`, and `research-report` CLI subcommands render their own runtime prompts (from `kops/templates/`), so no separate skill is needed. When running or reviewing a phase by hand, hold to these contracts:

- **Collect** (`research-collect`): populate the findings file with high-signal, sourced claims. Create/update source notes in `notes/Sources/` under the strict metadata schemas; prefer primary sources; mark imported model reports `authority: lead_only` + `verification_state: needs_primary_sources`. Distinguish evidence from inference; keep uncertainty explicit; append a progress log.
- **Review** (`research-review`): adversarial contrarian pass — try to break the thesis, not confirm it. Populate `## Strongest Objections`, `## Missing Evidence`, `## Claims To Soften` with genuine gaps (never fabricated counter-evidence); name missing primary sources to consult before drafting.
- **Report** (`research-report`): synthesize brief + sources + findings + contrarian review into a bounded report. Build from collected evidence only, address the strongest objections, keep conclusions bounded by evidence, cite source summaries with wikilinks, and distinguish established from provisional findings.

## Rules
- Keep active run files in `research/`, not in `notes/`.
- Treat imported model-generated reports as leads, not authority.
- Preserve the status/progress/review/report linkage across steps.
- Promote durable findings into the main vault only after verification.

## Outputs
- `research/briefs/` (brief files: `type: research-brief`)
- `research/notes/` (status: `type: research-status`, progress: `type: research-progress`, review: `type: research-review`)
- `research/findings/` (findings: `type: research-findings`)
- `research/reports/` (reports: `type: research-report`)
- `research/imports/` (manifest: `type: research-import-manifest`)
- `research/archive/` (manifest: `type: research-archive-manifest`)
