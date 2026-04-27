# Operating Rules

This file is the canonical source for K-Ops vault operating rules.
`CLAUDE.md`, `AGENTS.md`, and `GEMINI.md` all reference this file. Edit here, not there.

## Mission

Turn raw sources into a durable Markdown knowledge base. Every answer should either:
1. Reference existing vault notes, or
2. Improve the vault if durable new knowledge was produced.

## Operating Rules

- Treat `data/raw/` as immutable source evidence. Each `data/raw/src-*/` directory contains `metadata.json` (the per-source manifest: `id`, `source`, `ingested_at`, `kind`, `original_path`, `normalized_path`, `title_guess`, `content_hash`) and is the authoritative record for that source even if `data/registry.json` is lost.
- Treat `notes/` as the curated Obsidian vault.
- Treat `research/` as the active run workspace for resumable research jobs, not as a substitute for the curated vault.
- Prefer updating existing concept pages instead of creating duplicates.
- Keep always-on instructions short; move command detail into runbooks, skills, or templates.
- Every concept page should link to related pages and relevant source summaries.
- Record contradictions, uncertainties, and missing evidence explicitly.
- Do not silently invent citations.
- If a question cannot be answered from the vault, say so and propose the minimum fetch needed.

## Default Workflow

1. Read relevant source summaries in `notes/Sources/`.
2. Read the linked concept pages in `notes/Concepts/`.
3. Use `notes/Runbooks/Agent_Workflow_Quick_Reference.md` when you need command syntax or command order.
4. Answer from the vault.
5. If the answer yields durable knowledge, file it back into the vault.
6. Run `lint` after structural edits.
7. Update `notes/Home.md` and `notes/TODO.md` when the vault's structure or gaps change.

## Page Conventions

Each concept page should usually contain:
- What it is
- Why it matters
- Key claims
- Evidence / source basis
- Related concepts
- Open questions
- Backlinks

## Skills

Use the skills in `skills/` when relevant:
- `ingest-sources`
- `compile-wiki`
- `lint-heal`
- `qa-agent`
- `render-output`

## Research Runs

When a topic needs a full research run, use the resumable workflow in `research/`:
- create a brief, status checkpoint, and progress log
- record the `quality_tier` as `fast`, `standard`, or `deep`
- collect sources into `notes/Sources/`
- write findings, run a contrarian review, then draft the final report
- archive completed runs with a manifest that lists every moved artifact

## Claim & Freshness Rules

- Run `extract-claims` after any compile pass to keep `data/claims.json` current.
- `refresh` automatically sets `revalidation_required: true` on concept pages that cite changed sources. Run `stale-impact` to review the impact list, update the affected pages, then run `clear-stale-flags` to dismiss.
- Concept pages with `claim_quality: conflicting` **must** have an `## Open Questions` section that names the conflicting sources and why they disagree. Lint warns if the section is absent.
- Answer memos include a `sources_consulted` frontmatter list. Populate it with the source IDs and concept filenames read during the Q&A session.

## Evidence Strength Taxonomy

Use the most precise value for `evidence_strength` on source notes:

| Value | Meaning |
|---|---|
| `primary-doc` | Canonical primary source documentation |
| `official-spec` | Official specification or standard |
| `strong` | High-confidence non-primary evidence |
| `code` | Source code or implementation artifact |
| `maintainer-commentary` | From the repo maintainer or original author |
| `changelog` | Release notes or changelog |
| `pr-issue` | Pull request or issue thread |
| `secondary` | Secondary analysis, commentary, or survey |
| `model-generated` | AI/model-generated content (treat as secondary) |
| `stub` | Minimal or placeholder capture |
| `citation-only` | Citation stub not yet fetched |
| `image-only` | Screenshot or image with no extractable text |

## Source-to-Concept Promotion Rules

These rules make the compilation step deterministic: given the same sources, different agents should make the same promotion decisions.

### Promote source summary → concept page when ALL of these hold

- **Evidence threshold:** ≥2 sources with `evidence_strength: primary-doc`, `strong`, or `official-spec` support the same core claim; OR 1 `official-spec` source alone.
- **Non-overlap:** the concept has a clear boundary that does not overlap with an existing concept page. Check existing pages before creating a new one.
- **Generalizability:** the claim is not tool-specific or version-specific — it holds across tools or contexts.
- **Minimum claim_quality:** the page can reach `supported` or at least `provisional` based on available evidence.

### Keep as source note (do not promote) when ANY of these hold

- Only 1 source with `evidence_strength: secondary` or weaker supports the core claim.
- The claim is tool-specific, version-pinned, or not generalizable beyond the source context.
- The claim contradicts an existing concept page claim without resolution — flag as a contradiction instead (see `Contradictions.md`).

### Flag as open question instead of promoting when

- The gap is load-bearing for an existing concept page but evidence is absent or insufficient.
- Add to the relevant concept page's `## Open Questions` section AND to `notes/TODO.md`.

### claim_quality thresholds

| Value | Evidence required |
|---|---|
| `supported` | ≥2 `primary-doc` / `strong` sources, OR 1 `official-spec` |
| `provisional` | 1 `strong` or `secondary` source; single corroborating source only |
| `conflicting` | Sources exist but actively disagree; both sides must be named in `## Open Questions` |
| `speculative` | 0 primary sources; inferred or model-generated only; no direct source evidence |

### Before creating any new concept page

1. Does a page already cover this concept? (Check `notes/Concepts/` and `notes/Home.md`)
2. Is the concept boundary clear and non-overlapping with existing pages?
3. Is there enough evidence to reach at least `claim_quality: provisional`?
4. Is the concept generalizable beyond a single tool or source?
5. Can you name at least 2 related concept pages to link from the new page?

If any answer is No, keep it as a source note or open question, not a concept page.

## Semantic Edge Predicates

Use typed edge predicates in the `## Related Concepts` section of concept pages to make relationships semantically explicit. Generic `[[wikilinks]]` remain appropriate for loose associations. Typed predicates should be used for meaningful directional relationships.

### Canonical Predicate Vocabulary

| Predicate | Direction | Meaning | Example use |
|---|---|---|---|
| `conforms_to::` | this page → target | This page is an application or instance of the target pattern | `PKM_As_Agent_Memory conforms_to:: LLM_Wiki_Pattern` |
| `extends::` | this page → target | This page adds capabilities or scope beyond the target | `Pedsidian_Six_Layer_Architecture extends:: LLM_Wiki_Pattern` |
| `derived_from::` | this page → source | The page's core claim originates in this source or prior work | `Knowledge_Base_Operating_Model derived_from:: src-b0114804c8` |
| `contrasts_with::` | this page ↔ target | Explicit conceptual contrast; symmetric | `Vibe_Coding contrasts_with:: Augmented_Coding` |
| `supersedes::` | this page → target | This page replaces or absorbs the target; requires `superseded_by::` on target | `NewPage supersedes:: OldPage` |
| `superseded_by::` | this page → target | This page is replaced by target; reciprocal of `supersedes::` | `OldPage superseded_by:: NewPage` |
| `part_of::` | this page → target | This page is a subpage or focused section of the target hub | `Pedsidian_Six_Layer_Architecture part_of:: Agent_Session_Continuity` |

### Usage in Related Concepts

Prefix the wikilink with the predicate and a space:

```
## Related Concepts

- `conforms_to::` [[Concepts/LLM_Wiki_Pattern|LLM Wiki Pattern]] — this vault's implementation of the pattern
- `extends::` [[Concepts/Knowledge_Base_Operating_Model|Knowledge Base Operating Model]]
- [[Concepts/Compilation_Workflow|Compilation Workflow]] — (generic link; no directional claim)
```

### Reciprocity Rules

- `supersedes::` on page A **requires** `superseded_by::` on page B. Lint warns if the reciprocal is absent.
- `part_of::` on page A **should** have a reverse link on page B (the hub page should list the subpage).
- `contrasts_with::` is symmetric — both pages should carry the predicate pointing to each other.
- `conforms_to::`, `extends::`, `derived_from::` are directional and do not require a reverse predicate.

## Source Staleness Policy

Source notes and the claims they support degrade over time. Apply these thresholds to decide when revalidation is required:

| Source type | Staleness threshold | Why |
|---|---|---|
| Anthropic / Claude docs | 3 months | Model capabilities and CLI features change frequently |
| GitHub repository snapshots | 6 months | Repos evolve; READMEs and APIs change |
| ArXiv preprints | 12 months | Superseded by published versions or follow-up work |
| Industry reports (DORA, GitHub, etc.) | 12 months | Annual cadence; new editions replace prior data |
| Blog / practitioner posts | 6 months | Tool recommendations become stale quickly |
| Product homepages / pricing pages | 3 months | Pricing, features, and URLs change without notice |

**Workflow:**
1. Run `uv run python scripts/kb.py stale-impact` monthly to surface concept pages citing sources older than their threshold.
2. For each flagged page, re-fetch the source (`ingest`), update the source summary, and recompile the concept page.
3. Run `clear-stale-flags` once the page is updated.

**Enforcement:** The `extract-claims` command populates `last_updated` on each claim. The `scorecard` command counts pages with `revalidation_required: true`. Both should be checked after any `refresh` pass.

## Reference Notes

- `notes/Runbooks/Agent_Workflow_Quick_Reference.md`
- `notes/Concepts/Workflow_Pattern_Inventory.md`
- `scripts/kb.py bootstrap --target <dir>`

## Obsidian Conventions

- Use Obsidian-style wikilinks for internal note links when editing curated notes.
- Keep note filenames stable and human-readable.
- Prefer frontmatter on durable notes so properties remain queryable in Obsidian.
