---
title: "Agent Workflow Quick Reference Summary"
type: source-summary
source_id: src-1f2a3b4c5d
source_url: "notes/Runbooks/Agent_Workflow_Quick_Reference.md"
source_kind: local-file
evidence_strength: strong
source_status: active
ingested_at: "2026-06-14"
tags:
  - kb/source
---

# Source Summary: src-1f2a3b4c5d

## Summary

This source summary captures the repo's workflow command map and the canonical command order described in the quick reference and reflected in `scripts/kb.py`.

## Key Claims

- The baseline repository workflow is `ingest` or `refresh`, then `compile`, then `extract-claims`, `extract-contradictions`, `heal`, `lint`, and `scorecard`.
- The maintenance cycle combines `refresh`, `compile`, `normalize`, `backfill`, `graph`, and `lint`.

## Evidence Notes

- Derived from `notes/Runbooks/Agent_Workflow_Quick_Reference.md` and `scripts/kb.py`.

## Related Concepts

- [[Concepts/Workflow_Pattern_Inventory|Workflow Pattern Inventory]]

## Backlinks

- [[Home]]
