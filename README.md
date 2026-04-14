# K-Ops

`K-Ops` is an agent-first Markdown knowledge base starter for turning raw
evidence into durable, reusable knowledge.

It gives you the workflow scaffold for ingesting sources, compiling notes,
answering questions, and rendering outputs. The vault starts intentionally
empty so you can shape it around your own research, operations, or
documentation practice.

## What This Gives You

- A clean `notes/` vault structure for Obsidian
- A source layer in `data/raw/` for imported evidence
- Normalized summaries in `notes/Sources/`
- Durable concept pages in `notes/Concepts/`
- Answer memos in `notes/Answers/`
- Shared templates and workflow scripts for repeatable agent runs

## Why It Exists

This repo is built for a simple loop:

1. Capture evidence without overthinking the format.
2. Compile that evidence into notes you can trust and reuse.
3. Heal structure and backlinks so the vault stays navigable.
4. Ask questions against the vault and promote useful answers back into durable
   notes.
5. Render the current knowledge into briefs, outlines, slide specs, or reports.

That is the core promise: less scattered information, more compounding knowledge.

## Agent Support

The workflow is designed to work with these CLI agents:

- `claude-code`
- `codex-cli`
- `gemini-cli`

The vault contract stays the same across agents. Only the `--agent` value
changes when you run `scripts/kb.py`.

To sync repo skills and workflow prompts into the agent runtime locations, run:

```bash
uv run python scripts/kb.py install-agent-assets --agent all --scope project
```

## Recommended Flow

1. Install `uv`.
2. Run `uv sync`.
3. Add your first URLs or files to an input list.
4. Ingest the raw sources.
5. Compile summaries and concept pages.
6. Run lint or heal after structural edits.
7. Ask questions and file durable answers back into the vault.
8. Render outputs when you need a memo, outline, slide deck, or briefing.

Example commands:

```bash
# Ingest raw URLs or file paths
uv run python scripts/kb.py ingest --input path/to/input.txt

# Ingest a GitHub repository and compile it immediately
uv run python scripts/kb.py ingest-github --repo owner/repo --compile-agent codex

# Compile with a chosen agent
uv run python scripts/kb.py compile --agent codex

# Heal structure after edits
uv run python scripts/kb.py heal --agent codex

# Ask a question against the vault
uv run python scripts/kb.py ask --agent claude --question "Which notes define the ingestion contract?"

# Render a memo from the current vault state
uv run python scripts/kb.py render --agent gemini --format memo --prompt "Summarize the current intake workflow"
```

## Project Structure

- `scripts/` for ingestion, compilation, healing, linting, and rendering
- `templates/` for agent prompts
- `skills/` for reusable skill definitions
- `notes/` for the Obsidian vault structure
- `config/kb_config.yaml` for repo-local path settings

Starter references:

- `notes/Home.md` is the vault entry point
- `notes/TODO.md` tracks follow-up work
- `notes/Runbooks/Agent_Workflow_Quick_Reference.md` is the compact workflow map
- `notes/_Templates/` contains note templates for source summaries and concept pages

## Working Rules

- Keep durable knowledge in `notes/`, not in raw source files.
- Prefer small, high-signal edits over broad rewrites.
- Preserve provenance from source summaries into concept pages.
- Mark uncertainty explicitly when the evidence is thin.
- Run `lint` after changes that affect backlinks, note structure, or metadata.

## Next Step

Start with one source list, ingest it, and let the vault grow from there. The
first pass does not need to be perfect. It just needs to be real.
