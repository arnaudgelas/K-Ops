---
title: "Research Workflow Runbook"
type: maintenance
tags:
  - kb/runbook
  - kb/research
---

# Research Workflow Runbook

The research workflow is a multi-phase, agent-driven pipeline for deep investigations. It produces a durable report grounded in primary sources and includes a mandatory contrarian review step.

## Phases

```
briefing → source-collection → findings → contrarian-review → report-drafting → done
```

| Phase | Command | What happens |
|---|---|---|
| `briefing` | `research-start` | Creates brief, status, and progress scaffolding |
| `source-collection` | `research-collect` | Agent fetches and summarizes primary sources |
| `findings` | (after collect) | Findings file populated by agent |
| `contrarian-review` | `research-review` | Agent challenges the emerging thesis |
| `report-drafting` | `research-report` | Agent drafts the final report |
| `done` | `research-archive` | Moves all files to `research/archive/` |
| `blocked` | (manual) | Set when research cannot proceed |

## Quality Tiers

| Tier | Description |
|---|---|
| `fast` | One-pass source scan, brief review, lightweight report |
| `standard` | Full source collection, contrarian review, structured report |
| `deep` | Multiple source-collection passes, rigorous review, comprehensive report |

## Commands

### Start a new research run

```bash
uv run python scripts/kb.py research-start --topic "Your topic" --tier standard
```

Creates files in:
- `research/briefs/<slug>-<date>.md`
- `research/notes/<slug>-status.md`
- `research/notes/<slug>-progress.md`

### Check status of all active runs

```bash
uv run python scripts/kb.py research-status
```

### Source collection phase

```bash
uv run python scripts/kb.py research-collect --agent claude --topic "Your topic"
```

Agent reads the brief and existing sources, fetches new evidence, writes to `research/findings/`.

### Contrarian review phase

```bash
uv run python scripts/kb.py research-review --agent claude --topic "Your topic"
```

Requires findings to exist. Agent challenges claims, writes to `research/notes/<slug>-contrarian-review.md`.

### Report drafting phase

```bash
uv run python scripts/kb.py research-report --agent claude --topic "Your topic"
```

Requires both findings and contrarian review. Writes to `research/reports/`.
Pass `--allow-missing-review` to skip the review requirement (not recommended).

### Import an external AI-generated report

```bash
uv run python scripts/kb.py research-import \
  --topic "Your topic" \
  --path /path/to/report.md \
  --provider gemini \
  --origin "https://canonical-url-if-any"
```

Creates a lead-only source note (`authority: lead_only`, `verification_state: needs_primary_sources`).
Extracted citations are created as stub source notes for subsequent fetching.

### Archive a completed run

```bash
uv run python scripts/kb.py research-archive --topic "Your topic"
```

Only works when phase is `done`. Moves all research files to `research/archive/<slug>/`.

## File Locations

```
research/
├── briefs/          # Research briefs (what to investigate and why)
├── findings/        # Source-collection output (claims + evidence)
├── notes/           # Status files, progress logs, contrarian reviews
├── reports/         # Final reports
├── imports/         # Imported external reports and their citation stubs
└── archive/         # Completed research runs
```

Note: `research/` is gitignored. Research files are working scratch space, not durable vault notes. Promote key findings into `notes/Concepts/` manually after archive.

## Rules

- Always start with `research-start` to get the status/progress scaffolding.
- Never skip `research-review` on `standard` or `deep` tier work.
- Treat imported AI reports as leads (`authority: lead_only`). Verify claims against primary sources before promoting into concept pages.
- After archival, import the key findings into the vault with `compile` or manually edit concept pages.
- Run `lint` after adding research-derived source notes to `notes/Sources/`.

## Related

- [[Concepts/Workflow_Pattern_Inventory|Workflow Pattern Inventory]]
- [[Agent_Workflow_Quick_Reference|Agent Workflow Quick Reference]]
