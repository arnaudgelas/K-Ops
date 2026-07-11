---
name: compile-wiki
description: Merge source summaries into durable concept pages with backlinks, index entries, and explicit open questions.
---

# Compile Wiki

## Goal
Turn source summaries into durable concept pages and keep the navigation layer coherent.

## Rules
- Prefer fewer, stronger concept pages over many overlapping pages.
- Merge duplicates instead of proliferating similar pages.
- Keep backlinks reciprocal when possible.
- Preserve uncertainty and provenance.

## Desired outcomes
- `notes/Concepts/*.md` becomes the main knowledge layer.
- `notes/Home.md` becomes the best navigation entry point.
- `notes/TODO.md` captures unresolved gaps and follow-up fetches.

## Required concept shape
Every compiled concept page must strictly contain the following sections in order:
1. `# <Concept Name>`
2. `## What It Is`
3. `## Why It Matters`
4. `## Key Claims`
5. `## Related Concepts`
6. `## Evidence / Source Basis`
7. `## Open Questions` (required on every concept page; write at least one question or state `_No open questions identified._`)
8. `## Backlinks`

## Citation requirement
Every bullet in `## Key Claims` that makes a factual assertion **must** end with at least one inline source wikilink: `([[Sources/<source_id>|<source_id>]])` or `([[Concepts/<name>|<name>]])`.
- `supported` concept pages require ≥ 90% direct inline citation coverage on claims.
- `provisional` concept pages require ≥ 70% direct inline citation coverage.
- If a claim cannot be sourced, mark it `(unverified)` and set `claim_quality: provisional`.

## Contradiction alerts
Before writing or updating a concept page, check `data/contradictions.json` for entries where `concept` matches the page stem. If any exist:
1. Set `claim_quality: conflicting` and `evidence_status: contested` in the frontmatter.
2. Inject this warning callout **immediately after the frontmatter block** (before the title and `## What It Is`):
   ```markdown
   > [!warning] Contradiction
   > This concept has documented conflicting evidence. See `## Open Questions` for details.
   ```
3. In `## Open Questions`, list each contradiction's `open_question` text as a bullet.

## evidence_status & claim_quality
Set `evidence_status` in frontmatter based on the evidence in `## Evidence / Source Basis`:
- `seed` — 0 or 1 sources cited
- `synthesized` — 2+ sources, no contradiction entries in `data/contradictions.json`
- `contested` — any entries exist in `data/contradictions.json` for this concept
- `verified` — leave as-is if already set by a human reviewer

Set `claim_quality` in frontmatter based on citation coverage and conflicts:
- `supported` — ≥ 90% citation coverage, no revoked or model-generated backing sources, no conflicts
- `provisional` — citation coverage < 90% but ≥ 70%, or has unverified claims
- `weak` — citation coverage < 70% or sparse evidence
- `conflicting` — contradiction exists in `data/contradictions.json`
- `stale` — flagged stale

## Large source note contract

See `notes/Runbooks/Large_Source_Hierarchy.md` for the normative spec. The following rules are binding during compile:

1. **Human-owned sections in large source notes.** `## Document Summary` and `## Section Evidence Map` written by the ingest-sources skill (or by a human) are treated as human-owned. Compile must not rewrite their prose. Compile may append new `###` subsections to `## Section Evidence Map` when new nodes appear in the manifest, but must not alter existing subsection prose.

2. **Append-only for new manifest nodes.** If the manifest gains new nodes since the last ingest, compile may append new `### <section_title>` blocks to `## Section Evidence Map`. Existing blocks are read-only (same rule as `## Open Questions`).

3. **60 KB warning.** Before writing a large source note, check the projected output size. If it would exceed 60 KB (61 440 bytes), emit a compile log entry:
   ```
   [source-note-too-large] <source_id>: <size> bytes
   ```
   Add `source_summary_too_large: true` to the note's frontmatter. Do not truncate silently.

## Compile Log Requirement
Every compilation run must produce a compile log entry before the skill is considered complete.
Write or append a brief log to `research/scratch/compile-YYYYMMDD.md` (use today's date) containing:
- Sources processed (list of source IDs read)
- Pages updated (concept pages that were modified)
- Pages created (new concept pages)
- Contradictions flagged (any new conflicts detected)
- Claims added (new Key Claims entries)

If the file already exists for today, append to it with a timestamp header.
