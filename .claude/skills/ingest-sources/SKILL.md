---
name: ingest-sources
description: Turn raw links, PDFs, local files, and notes into normalized source entries and source summary candidates.
---

# Ingest Sources

## Goal
Convert a mixed list of URLs and local files into normalized source material that the vault compiler can use.

## Inputs
- `data/registry.json`
- `data/raw/*/normalized.md`
- `data/raw/*/metadata.json`

## Steps
1. Review newly ingested source folders.
2. Identify source type, topic, and likely importance.
3. Draft or update `notes/Sources/<id>.md`.
4. Extract candidate concepts, entities, claims, and open questions.
5. Flag weak extraction quality or missing content for manual repair.

## Output shape for each source summary
- Title
- Source ID and source path/url
- What the source is
- Key claims
- Important evidence/details
- Candidate concepts
- Open questions
- Reliability notes
