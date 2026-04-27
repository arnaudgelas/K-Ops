---
name: ingest-sources
description: Review newly ingested raw sources and draft or update source summary notes in notes/Sources/.
---

# Ingest Sources

## Goal
Turn already-fetched raw source folders into structured source summary notes that the vault compiler can use.

## Context
Mechanical fetching and normalization is handled automatically by `scripts/ingest_sources.py` (run via `kb.py ingest`).
This skill covers the **agent-driven** step that follows: reading the normalized content and writing or updating source summary notes.

## Inputs
- `data/registry.json` — registry of all ingested sources
- `data/raw/<id>/normalized.md` — normalized text for each source
- `data/raw/<id>/metadata.json` — source metadata (URL, type, timestamps)
- Existing `notes/Sources/<id>.md` if a prior summary exists

## Output contract
- Update only the source notes that need to change.
- Preserve provenance and uncertainty explicitly.
- Flag weak or incomplete captures instead of smoothing them over.

## Required note shape

Frontmatter (all fields mandatory per `config/schema.yaml`):
- `source_id` (canonical `src-[0-9a-f]{10}`)
- `title`
- `source_url`
- `source_kind` (`web-page` | `github-repo` | `pdf` | `imported_model_report` | `imported_model_report_citation` | `other`)
- `evidence_strength`
- `ingested_at` (ISO-8601 date)
- `tags` (include `kb/source`)

Sections (in this order, all required):
- `## Summary`
- `## What this source is`
- `## Key claims`
- `## Important evidence / details`
- `## Candidate concepts`
- `## Open questions`
- `## Reliability notes`
- `## Related Concepts`
- `## Backlinks`

## Safe behavior
- Prefer updating an existing note over creating a duplicate.
- Keep the summary anchored in the raw capture and registry metadata.
- If the source is too thin, use `stub` or `citation-only` rather than inventing detail.
