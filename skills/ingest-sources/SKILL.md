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

## Steps
1. Identify source folders in `data/raw/` that are missing or have stale `notes/Sources/<id>.md` files.
2. For each source, determine its type, topic, and likely importance.
3. Draft or update `notes/Sources/<id>.md` with the required output shape below.
4. Extract candidate concepts, entities, claims, and open questions.
5. Flag sources with weak extraction quality or missing content for manual repair.

## Output shape for each source summary
- Title and source ID
- What the source is and where it came from
- Key claims with evidence quotes or references
- Candidate concepts to promote into `notes/Concepts/`
- Open questions and reliability notes
- `evidence_strength` frontmatter (`primary-doc`, `secondary`, `strong`, `stub`, `image-only`)
