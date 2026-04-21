# K-Ops

**Stop collecting. Start knowing.**

Most research ends up as a graveyard of browser tabs, half-read PDFs, and notes you'll never find again. K-Ops is the antidote: an agent-first knowledge base that turns raw evidence into durable, compounding knowledge — automatically.

Drop in a URL or a file. Walk away with a structured, interlinked vault you can query, heal, and render into real outputs. No friction. No lost context.

---

## What Makes K-Ops Different

Traditional note-taking tools make *you* do the work. K-Ops delegates it.

- **Agents do the heavy lifting.** Ingestion, summarization, link repair, Q&A — all driven by `claude-code`, `codex-cli`, or `gemini-cli`. You pick the model; the workflow stays the same.
- **The vault compounds over time.** Every source summary feeds concept pages. Every answer memo becomes reusable knowledge. Nothing is siloed.
- **Obsidian-native.** The `notes/` directory is a first-class Obsidian vault — backlinks, templates, and navigation work out of the box.
- **One script to rule them all.** `scripts/kb.py` is your single interface for every operation: ingest, compile, heal, ask, render.

---

## The Loop That Changes How You Research

```
Capture → Compile → Heal → Ask → Render
```

1. **Capture** raw evidence without overthinking the format — URLs, files, repos.
2. **Compile** that evidence into normalized summaries and durable concept pages.
3. **Heal** structure and backlinks so the vault stays navigable as it grows.
4. **Ask** questions against the vault; get answers grounded in your own sources.
5. **Render** the current knowledge into briefs, reports, slide outlines, or memos.

Each pass makes the vault smarter. That is the promise: less scattered information, more knowledge that earns its place.

---

## Five Minutes to Your First Insight

```bash
# 1. Install uv if you haven't
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Set up the project
uv sync

# 3. Ingest your first sources
uv run python scripts/kb.py ingest --input path/to/urls.txt

# 4. Compile summaries and concept pages
uv run python scripts/kb.py compile --agent claude

# 5. Ask a question
uv run python scripts/kb.py ask --agent claude --question "What are the key themes across my sources?"

# 6. Render a memo
uv run python scripts/kb.py render --agent claude --format memo --prompt "Summarize findings for a stakeholder briefing"
```

---

## Full Command Reference

```bash
# Ingest a GitHub repository and compile it immediately
uv run python scripts/kb.py ingest-github --repo owner/repo --compile-agent claude

# Heal structure after edits (fix backlinks, metadata, orphaned pages)
uv run python scripts/kb.py heal --agent claude

# Dry-run to preview what compile or heal would do
uv run python scripts/kb.py compile --dry-run
uv run python scripts/kb.py heal --dry-run

# Extract atomic claims from every concept page
uv run python scripts/kb.py extract-claims

# Extract structured contradiction records from conflicting concepts
uv run python scripts/kb.py extract-contradictions

# Check vault health — quality metrics, stale backlog, coverage signals
uv run python scripts/kb.py scorecard

# Search claims or contradictions by keyword
uv run python scripts/kb.py claim-search --query "your topic"
uv run python scripts/kb.py contradiction-search --query "disputed point"

# Validate your config before running any workflow
uv run python scripts/kb.py validate

# Sync skills and prompt templates into agent runtime locations
uv run python scripts/kb.py install-agent-assets --agent all --scope project
```

---

## What You Get

| Layer | Location | Purpose |
|---|---|---|
| Raw evidence | `data/raw/` | Immutable source files |
| Source summaries | `notes/Sources/` | Normalized per-source digests |
| Concept pages | `notes/Concepts/` | Durable, interlinked knowledge |
| Answer memos | `notes/Answers/` | Grounded Q&A, filed back into the vault |
| Claim registry | `data/claims.json` | Atomic claims extracted from concept pages, searchable by keyword |
| Contradiction registry | `data/contradictions.json` | Structured conflict records — one entry per Open Questions bullet |
| Vault scorecard | `data/scorecard.json` | Quality metrics across all domains; health signals for early warnings |
| Templates | `notes/_Templates/` | Consistent note structure |
| Runbooks | `notes/Runbooks/` | Step-by-step workflow guides |

## Operational Aids

- `notes/Runbooks/Obsidian_Plugin_Setup.md`: recommended Obsidian plugins for querying and maintaining frontmatter-driven vaults
- `skills/research-workflow/SKILL.md`: resumable research-run workflow for source collection, review, reporting, and archiving

---

## Multi-Agent by Design

K-Ops is not locked to a single AI provider. Swap agents mid-workflow without changing your vault structure:

| Agent | Flag |
|---|---|
| Claude Code | `--agent claude` |
| OpenAI Codex CLI | `--agent codex` |
| Google Gemini CLI | `--agent gemini` |

---

## Guiding Principles

- Keep durable knowledge in `notes/`, not buried in raw source files.
- Prefer small, high-signal edits over broad rewrites.
- Preserve provenance: trace every claim back to a source summary; use `extract-claims` to make that graph machine-readable.
- Mark uncertainty explicitly when evidence is thin; document conflicts in `## Open Questions` so `extract-contradictions` can surface them.
- Run `heal` after any change that touches backlinks, structure, or metadata.
- Run `scorecard` to catch quality drift before it compounds.

---

## Start Here

Open `notes/Home.md` — that is the vault entry point.  
Check `notes/TODO.md` for pending follow-up work.  
Reach for `notes/Runbooks/Agent_Workflow_Quick_Reference.md` when you need the compact workflow map.
Use `notes/Runbooks/Obsidian_Plugin_Setup.md` when you want to turn the vault's metadata into Obsidian dashboards.

The first pass does not need to be perfect. **It just needs to be real.**
