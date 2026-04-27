---
name: lint-heal
description: Scan the vault for contradictions, unsupported claims, structural weaknesses, and missing pages, then repair what is safe.
---

# Lint + Heal

## Goal
Continuously improve vault quality.

## Look for
- contradictions between concept pages and source summaries
- unsupported claims
- dead-end pages with no backlinks
- duplicate concepts with inconsistent naming
- missing overview pages for dense topic clusters

## Safe actions
- tighten wording without changing meaning
- add missing backlinks
- move uncertain claims into open questions
- update `notes/TODO.md` for unresolved items

## Do not
- rewrite knowledge
- invent citations
- create new concept pages
- touch `data/raw/`

## Repair order

1. Fix broken wikilinks.
2. Add missing required sections as empty scaffolds.
3. Add missing frontmatter fields with safe defaults.
4. Record revalidation-required pages in `notes/TODO.md`.
5. On source notes, add `evidence_strength` and `source_id` before anything else.
