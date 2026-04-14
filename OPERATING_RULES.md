# Operating Rules

This file is the canonical source for K-Ops vault operating rules.
`CLAUDE.md`, `AGENTS.md`, and `GEMINI.md` all reference this file. Edit here, not there.

## Mission

Turn raw sources into a durable Markdown knowledge base. Every answer should either:
1. Reference existing vault notes, or
2. Improve the vault if durable new knowledge was produced.

## Operating Rules

- Treat `data/raw/` as immutable source evidence.
- Treat `notes/` as the curated Obsidian vault.
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

## Reference Notes

- `notes/Runbooks/Agent_Workflow_Quick_Reference.md`
- `notes/Concepts/Workflow_Pattern_Inventory.md`
- `scripts/kb.py bootstrap --target <dir>`

## Obsidian Conventions

- Use Obsidian-style wikilinks for internal note links when editing curated notes.
- Keep note filenames stable and human-readable.
- Prefer frontmatter on durable notes so properties remain queryable in Obsidian.
