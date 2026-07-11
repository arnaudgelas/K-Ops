---
name: ingest-sources
description: Review newly ingested raw sources and draft or update source summary notes in notes/Sources/.
---

# Ingest Sources

## Goal
Turn already-fetched raw source folders into structured source summary notes that the vault compiler can use.

## Context
Mechanical fetching and normalization is handled by `scripts/ingest_sources.py` via `kb.py ingest`.
This skill covers the agent-driven step that follows: reading normalized content and writing or updating source summaries.

## Inputs
- `data/registry.json` - registry of all ingested sources
- `data/raw/<id>/normalized.md` - normalized text for each source
- `data/raw/<id>/metadata.json` - source metadata (URL, type, timestamps)
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
- `source_kind` (must map to a canonical schema value):
  `arxiv-paper` | `paper-pdf` | `github-repo-snapshot` | `github-file` | `official-doc` | `spec` | `blog` | `news` | `local-file` | `imported-model-report` | `citation-stub`
- `evidence_strength` (must map to a canonical schema value):
  `primary-doc` | `primary-doc-partial` | `official-spec` | `strong` | `code` | `maintainer-commentary` | `changelog` | `pr-issue` | `secondary` | `model-generated` | `stub` | `citation-only` | `image-only`
- `source_status` (defaults to `active`)
- `ingested_at` (ISO-8601 date, e.g. 2026-06-14T10:53:44Z)
- `tags` (must include `kb/source`)

### Kind-Specific Required Frontmatter:
- **arxiv-paper**: `authors`, `arxiv_id`, `published_date`, `abstract`
- **paper-pdf**: `page_count`
- **github-repo-snapshot**: `git_commit`, `branch`, `tracked_file_count`, `sampled_file_count`
- **github-file**: `github_url`, `git_commit`
- **official-doc**: `organization`
- **spec**: `organization`, `version`, `status`

### Strong PDF / Imported Report Constraints:
- **PDF Coverage**: Any PDF source (`paper-pdf`, `arxiv-paper`, or URL ending in `.pdf`) with strong evidence strength (`primary-doc`, `strong`, `official-spec`) MUST include `extraction_coverage` metadata in its frontmatter (e.g. `extraction_coverage: 1.0`).
- **Imported Report**: If kind is `imported-model-report`, set `authority: lead_only`, `verification_state: needs_primary_sources`, `evidence_strength: secondary`.
- **Imported Citation Stub**: If kind is `citation-stub`, set `canonical_url: "<url>"`, `authority: lead_only`, `verification_state: needs_fetch`, `evidence_strength: stub`.

Sections (in this order, all required):
- `## Summary`
- `## What this source is`
- `## Key claims`
- `## Important evidence / details`
- `## Candidate concepts`
- `## Open questions`
- `## Reliability notes` (Required by linter)
- `## Related Concepts` (Required by linter)
- `## Backlinks`

### Large source variant

When `data/raw/<source_id>/large_source_manifest.json` exists AND the normalized source content exceeds 20 KB, the agent MUST use the large-source section schema instead of the flat schema above.

Required sections in order:
1. `## Document Summary` — 1-3 paragraph synthesis of the full source (main thesis, audience, scope). Machine-owned.
2. `## Section Evidence Map` — contains `###` subsections, one per high-signal manifest node. Only render: top-level nodes (level ≤ 1) plus child nodes that have claims, contradictions, or table/figure type. Machine-owned.
   - Each `###` heading must use the manifest node's `title` field verbatim (strip any "type: " prefix).
   - Each subsection may contain a `#### Key Claims` block with inline citations anchored to the section heading.
   - Parent nodes must not restate child claim bullets verbatim — parent Key Claims are for cross-section synthesis only.
3. `## Key Claims` — top-level cross-document claims only; must not duplicate bullets from Section Evidence Map.
4. `## Candidate concepts`
5. `## Open questions`
6. `## Reliability notes` (required by linter)
7. `## Related Concepts` (required by linter)
8. `## Backlinks`

Citation anchor format for section-level citations:
`[[Sources/<subdir>/<source_id>#<heading-anchor>|<source_id>#<heading-anchor>]]`
where `<heading-anchor>` is the Obsidian anchor derivation: lowercase, spaces → hyphens, punctuation removed.

If the note would exceed 60 KB, add `source_summary_too_large: true` and `truncated_at_section: "<last section rendered>"` to frontmatter, stop rendering, and append a TODO entry in `notes/TODO.md`.

## Safe behavior
- Prefer updating an existing note over creating a duplicate.
- Keep the summary anchored in the raw capture and registry metadata.
- If the source is too thin, use `stub` or `citation-only` rather than inventing detail.
