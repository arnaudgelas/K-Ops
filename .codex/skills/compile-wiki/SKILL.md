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
- `## What It Is`
- `## Why It Matters`
- `## Key Claims`
- `## Evidence / Source Basis`
- `## Related Concepts`
- `## Open Questions` (required on every concept page; write at least one question or state `_No open questions identified._`)
- `## Backlinks`

## Citation requirement
Every bullet in `## Key Claims` that makes a factual assertion **must** end with at least one inline source wikilink: `([[Sources/<source_id>|<source_id>]])`. If the claim cannot be sourced, mark it `(unverified)` and set `claim_quality: provisional`. Target: ≥ 50% of Key Claims bullets carry inline citations per compile pass.

## Contradiction alerts
Before writing or updating a concept page, check `data/contradictions.json` for entries where `concept` matches the page stem. If any exist:
1. Add `claim_quality: conflicting` to the frontmatter.
2. Inject this callout **immediately after the frontmatter block** (before `## What It Is`):
   ```
   > [!warning] Contradiction
   > This concept has documented conflicting evidence. See `## Open Questions` for details.
   ```
3. In `## Open Questions`, list each contradiction's `open_question` text as a bullet.

## evidence_status
Set `evidence_status` in frontmatter based on the evidence in `## Evidence / Source Basis`:
- `seed` — 0 or 1 sources cited
- `synthesized` — 2+ sources, no contradiction entries in `data/contradictions.json`
- `contested` — any entries exist in `data/contradictions.json` for this concept
- `verified` — leave as-is if already set by a human reviewer

## claim_quality valid values
`supported` | `provisional` | `weak` | `conflicting` | `stale`

## Compile Log Requirement

Every compilation run must produce a compile log entry before the skill is considered complete.

Write a brief log to `research/scratch/compile-YYYYMMDD.md` (use today's date) containing:
- Sources processed (list of source IDs read)
- Pages updated (concept pages that were modified)
- Pages created (new concept pages)
- Contradictions flagged (any new conflicts detected)
- Claims added (new Key Claims entries)

If the file already exists for today, append to it with a timestamp header. The compile log is the audit trail for the compilation step — without it, the pass is not reproducible.
