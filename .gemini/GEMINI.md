# GEMINI.md

This repository is an Obsidian-aligned living research vault. The same operating contract should work whether the active CLI is Gemini CLI, Claude Code, or Codex CLI.

Canonical rules: see `OPERATING_RULES.md`.

## Mission
Turn raw sources into a durable Markdown knowledge base. Every answer should either:
1. reference existing vault notes, or
2. improve the vault if durable new knowledge was produced.

## Operating rules
- Treat `data/raw/` as immutable source evidence.
- Treat `notes/` as the curated Obsidian vault.
- Treat `research/` as the active run workspace for resumable research jobs, not as a substitute for the curated vault.
- Prefer updating existing concept pages instead of creating duplicates.
- Keep always-on instructions short; move command detail into runbooks, skills, or templates.
- Every concept page should link to related pages and relevant source summaries.
- Record contradictions, uncertainties, and missing evidence explicitly.
- Do not silently invent citations.
- Treat imported model-generated reports as leads that must be verified against primary sources before they can shape concept pages.
- If a question cannot be answered from the vault, say so and propose the minimum fetch needed.

## Default workflow
1. Read relevant source summaries in `notes/Sources/`.
2. Read the linked concept pages in `notes/Concepts/`.
3. Use `notes/Runbooks/Agent_Workflow_Quick_Reference.md` when you need command syntax or command order.
4. Answer from the vault.
5. If the answer yields durable knowledge, file it back into the vault.
6. Run `lint` after structural edits.
7. Update `notes/Home.md` and `notes/TODO.md` when the vault's structure or gaps change.

## Page conventions
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

## Reference notes
- `notes/Runbooks/Agent_Workflow_Quick_Reference.md`
- `notes/Concepts/Workflow_Pattern_Inventory.md`
- `scripts/kb.py bootstrap --target <dir>`

## Obsidian conventions
- Use Obsidian-style wikilinks for internal note links when editing curated notes.
- Keep note filenames stable and human-readable.
- Prefer frontmatter on durable notes so properties remain queryable in Obsidian.
