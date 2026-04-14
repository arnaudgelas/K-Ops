---
title: "Workflow Pattern Inventory"
type: concept
claim_quality: supported
tags:
  - kb/concept
  - kb/workflow
---

# Workflow Pattern Inventory

## What It Is

A structured inventory of the recurring agent workflow patterns used in K-Ops to turn raw sources into durable knowledge.

## Why It Matters

K-Ops uses multiple agents (Claude, Codex, Gemini) each capable of running different workflow patterns. Understanding which pattern to apply and in what order prevents wasted agent runs and ensures vault quality.

## Key Patterns

### 1. Ingest → Compile → Lint (Baseline)

The minimal complete cycle. Suitable for a new batch of sources.

```
ingest → compile → lint
```

- `ingest`: fetch raw sources into `data/raw/`, update registry
- `compile`: agent reads registry + raw, writes source summaries and concept pages
- `lint`: mechanical check for structural consistency

### 2. Refresh → Compile (Source Update)

Re-fetches all registered sources to pick up changes, then recompiles.

```
refresh → compile
```

Use when sources are expected to have changed (living documents, ongoing projects).

### 3. Heal → Lint (Vault Repair)

Focuses on fixing existing notes without adding new sources.

```
heal → lint
```

Use when you notice broken backlinks, missing metadata, or structural drift.

### 4. Ask → Promote (Knowledge Extraction)

Pose a focused question against the vault; the answer memo may promote durable insights back into concept pages.

```
ask → (manual review) → promote to Concepts/
```

### 5. Research Workflow (Multi-Phase Investigation)

The full multi-phase research pipeline for deep topics requiring rigorous sourcing.

```
research-start
  → research-collect (source-collection phase)
  → research-review (contrarian-review phase)
  → research-report (report-drafting phase)
  → research-archive (archival)
```

See [[Runbooks/Research_Workflow|Research Workflow Runbook]] for details.

### 6. Maintenance (Full Cycle)

One command that runs: refresh → compile → normalize → backfill → graph → lint.

```
maintenance [--agent <name>]
```

Use weekly or before a major vault export.

### 7. Render (Output Generation)

Produce a downstream artifact from the current vault state.

```
render --agent <name> --format <memo|outline|slides|report> --prompt "<text>"
```

## Evidence / Source Basis

- Derived from `scripts/kb.py` command inventory and the `notes/Runbooks/Agent_Workflow_Quick_Reference.md` runbook.
- Confirmed by agent prompt templates in `templates/`.

## Related Concepts

- [[Runbooks/Agent_Workflow_Quick_Reference|Agent Workflow Quick Reference]]
- [[Runbooks/Research_Workflow|Research Workflow]]

## Open Questions

- Should the `ask → promote` step be automated or always require human gating?
- Is there a natural order for running multiple compile passes with different agents?

## Backlinks

- [[Home]]
