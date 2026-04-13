# K-Ops

`K-Ops` is a blank, agent-first Markdown knowledge base starter.

It includes the workflow machinery needed to ingest sources, compile notes, answer questions, and render outputs, but it starts without any imported source corpus.

## What Is Included

- `scripts/` for ingestion, compilation, healing, linting, and rendering
- `templates/` for agent prompts
- `skills/` for reusable skill definitions
- `notes/` for the Obsidian vault structure
- `config/kb_config.yaml` for repo-local path settings

## First Steps

1. Install `uv`.
2. Run `uv sync`.
3. Add your first URLs or files to an input list.
4. Run `uv run python scripts/kb.py ingest --input <file>`.
5. Run `uv run python scripts/kb.py compile --agent codex`.
6. Use `uv run python scripts/kb.py lint` after structural edits.

## Starter Notes

- `notes/Home.md` is the Obsidian entry point.
- `notes/TODO.md` tracks follow-up work.
- `notes/Runbooks/Agent_Workflow_Quick_Reference.md` summarizes the repo commands.
- `notes/_Templates/` contains note templates for source summaries and concept pages.
