---
name: lint-heal
description: Scan the vault for contradictions, unsupported claims, structural weaknesses, and missing pages, then repair what is safe.
---

# Lint + Heal

## Goal
Continuously improve vault quality and ensure structural integrity.

## Look for
- Contradictions between concept pages and source summaries (check `data/contradictions.json`).
- Unsupported claims (Key Claims lacking direct inline citations `[[Sources/src-<id>|src-<id>]]`).
- Dead-end pages with no backlinks or missing reciprocal Related Concepts/semantic predicate links.
- Duplicate concepts with inconsistent naming or missing from `notes/Indexes/Topic_Atlas.md`.
- Missing required sections in concept pages or source summaries.
- Missing required metadata fields or bad values in frontmatter.
- Mismatched answer memo scope/quality (durable must be shared with non-empty updates; memo-only must be private with no updates).
- PDF sources with strong evidence strength missing `extraction_coverage`.
- Imported report metadata mismatches.
- Mismatched or missing reciprocal semantic edge predicates (`supersedes::` ↔ `superseded_by::`, symmetric `contrasts_with::`, reverse links for `part_of::`).

## Safe actions
- Fix broken wikilinks (e.g. resolve spaces to underscores, fix file paths).
- Add missing required sections as empty scaffolds.
- Add missing frontmatter fields with safe defaults (e.g. `claim_quality: provisional`, `type: concept`, `source_status: active`, etc.).
- Fix missing or mismatched reciprocal semantic edge predicates.
- Move uncertain or unverified claims into Open Questions.
- Update `notes/TODO.md` for unresolved items or pages needing human revalidation.
- Re-link orphan concept pages in `notes/Home.md`.

## Do not
- Rewrite established knowledge or claims.
- Invent citations or add unsupported claims.
- Create new concept pages.
- Touch `data/raw/` - those files are immutable.
- Remove the `revalidation_required: true` flag (record it in `notes/TODO.md` instead).
