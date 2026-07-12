# AGENTS.md

This repo is designed for agentic CLI workflows.

Canonical rules: see `OPERATING_RULES.md`.

## Roles

### Source Ingestor
Goal: transform new raw sources into normalized source summaries.

### Wiki Compiler
Goal: merge source summaries into durable concept pages and indexes.

### Lint + Heal
Goal: detect contradictions, weak structure, missing backlinks, and unsupported claims.

### Q&A Agent
Goal: answer using the vault, then file durable insights back into the vault.

### Render Agent
Goal: convert the current vault into memos, briefings, slide outlines, diagrams, and plot specs.

## Repo Contract
- `data/raw/` holds source evidence
- `notes/Sources/` holds per-source summaries
- `notes/Concepts/` holds durable knowledge pages
- `notes/Answers/` holds generated answer memos
- `notes/Home.md` is the Obsidian entry point
- `notes/TODO.md` tracks gaps and healing tasks
- `notes/Runbooks/Agent_Workflow_Quick_Reference.md` is the compact operator map for cross-CLI workflows
- `research/` holds resumable research-run artifacts and stays separate from curated vault notes
- `kops bootstrap --target <dir>` creates a new blank starter vault with the same file structure and tooling

## Behavioral Guardrails
- Prefer modifying a small number of files with high signal.
- Prefer precise edits over broad rewrites.
- Preserve provenance from source summaries into concept pages.
- When uncertain, mark uncertainty explicitly.

## Codex-Specific Notes
- Use `uv run kops install-agent-assets` to sync canonical skills/templates to the Codex runtime directory.
- Use `uv run kops validate` to confirm config loads before running workflows.
- Prefer `uv run kops compile --agent codex` when you want Codex to do the compilation pass.
- Use `uv run kops extract-claims`, `extract-contradictions`, and `scorecard` to keep the machine-readable quality layer current.
- After `extract-claims`, run `uv run kops verify-spans` to confirm claim quote anchors exist in their sources, and `uv run kops review-queue` to surface everything awaiting human review.
