# K-Ops

`K-Ops` is a blank, agent-first Markdown knowledge base starter.

It includes the workflow machinery needed to ingest sources, compile notes, answer questions, and render outputs, but it starts without any imported source corpus.

## What Is Included

- `scripts/` for ingestion, compilation, healing, linting, and rendering
- `templates/` for agent prompts
- `skills/` for reusable skill definitions
- `notes/` for the Obsidian vault structure
- `config/kb_config.yaml` for repo-local path settings

## Agent CLIs

The repo is built to work with these command-line agents:

- `claude-code`
- `codex-cli`
- `gemini-cli`

The vault structure stays the same regardless of which agent you use. The only thing that changes is the `--agent` value passed to `scripts/kb.py`.

### Agent Selection

Use the agent that matches the work you want to do:

- `claude` for source ingestion, consolidation, and longer synthesis passes
- `codex` for fast editing, mechanical refactors, and structured maintenance
- `gemini` for alternate synthesis runs, cross-checking, or a second pass on a prompt

The core workflow commands all accept `--agent`:

```bash
uv run python scripts/kb.py compile --agent claude
uv run python scripts/kb.py compile --agent codex
uv run python scripts/kb.py compile --agent gemini
uv run python scripts/kb.py heal --agent codex
uv run python scripts/kb.py ask --agent claude --question "What sources mention the ingestion contract?"
uv run python scripts/kb.py render --agent gemini --format outline --prompt "Turn the current vault into a project brief"
```

The same pattern applies to `refresh`, `maintenance`, and any other agent-backed workflow in `scripts/kb.py`.

### Environment Overrides

Command resolution also supports env var overrides when the binary name differs from the default:

- `KB_CLAUDE_CMD`
- `KB_CODEX_CMD`
- `KB_GEMINI_CMD`

Each variable can point to the exact command you want the repo to use, including any wrapper flags your local install needs.

### Typical Workflow

1. Ingest raw evidence.
2. Compile the evidence into source summaries and concept pages.
3. Heal structural issues.
4. Ask questions against the vault and promote durable answers back into notes.
5. Render outputs when you need memos, outlines, slides, or reports.

Examples:

```bash
# Ingest raw URLs or file paths
uv run python scripts/kb.py ingest --input path/to/input.txt

# Ingest a GitHub repository and immediately compile it with a chosen agent
uv run python scripts/kb.py ingest-github --repo owner/repo --compile-agent claude

# Refresh registered sources and recompile with another agent
uv run python scripts/kb.py refresh --agent codex

# Run the mechanical cleanup pass after agent edits
uv run python scripts/kb.py heal --agent codex

# Write a durable answer memo and file the insight back into the vault
uv run python scripts/kb.py ask --agent claude --question "Which notes define the ingestion contract?"

# Produce a render artifact from the current vault state
uv run python scripts/kb.py render --agent gemini --format memo --prompt "Summarize the current intake workflow"
```

### Working Inside Agent Sessions

When you are already inside a `claude-code`, `codex-cli`, or `gemini-cli` session, keep the same repo contract:

- Use the repo commands above rather than editing generated files by hand.
- Prefer `ingest` for raw evidence, `compile` for consolidation, `heal` for cleanup, and `ask` for vault-backed Q&A.
- Keep durable changes in `notes/`, not in `data/raw/`.
- Run `lint` after edits that affect backlinks, note structure, or metadata.

## First Steps

1. Install `uv`.
2. Run `uv sync`.
3. Add your first URLs or files to an input list.
4. Run `uv run python scripts/kb.py ingest --input <file>`.
5. Run `uv run python scripts/kb.py compile --agent codex` or swap in `claude` or `gemini`.
6. Use `uv run python scripts/kb.py lint` after structural edits.

## Starter Notes

- `notes/Home.md` is the Obsidian entry point.
- `notes/TODO.md` tracks follow-up work.
- `notes/Runbooks/Agent_Workflow_Quick_Reference.md` summarizes the repo commands.
- `notes/_Templates/` contains note templates for source summaries and concept pages.

## Working Notes

- Use `claude`, `codex`, or `gemini` consistently within a session so the agent can follow the same operating contract.
- Keep durable changes in `notes/`, not in raw source files.
- Run `lint` after edits that affect structure, backlinks, or note organization.
