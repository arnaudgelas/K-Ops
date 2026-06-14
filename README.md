# K-Ops

**Your research should not live in a graveyard of browser tabs.**

`K-Ops` is a local, agent-first research pipeline for turning links, PDFs, notes, and files into a durable Markdown knowledge vault for Obsidian.

It keeps the Karpathy-style LLM wiki idea in view, but treats that as the starting point. K-Ops is more opinionated: sources are normalized, claims are tracked, contradictions are surfaced, and the vault stays honest about what it knows and what it does not.

---

## Why K-Ops, and not just asking an LLM?

In April 2026, Andrej Karpathy published an LLM wiki gist — a three-folder pattern (raw sources, compiled wiki pages, a schema file) where an LLM maintains a personal knowledge base without a vector database. The post reached 16 million views and generated a wave of community implementations.

`K-Ops` was built before the gist was published, and shares the same core conviction. Where it goes further is governance: K-Ops is not just a wiki layout, it is a file-native knowledge substrate with claim tracking, contradiction handling, freshness controls, and a repair loop.

| | Karpathy original gist | v2 gist (rohitg00) | Community implementations | K-Ops |
|---|---|---|---|---|
| **Status** | Pattern / idea doc | Spec doc | Working code, narrow scope | Working system with Python CLI |
| **Source types** | Any (unspecified) | Any (unspecified) | Session transcripts or posts | URLs, PDFs, GitHub repos, local files |
| **Pipeline structure** | raw → wiki | raw → wiki | raw → atoms → wiki | raw → source summary → concept page |
| **Provenance** | Not specified | Proposed | Partial | Every claim tied to source summaries |
| **Contradictions** | Not addressed | Proposed | Lint check only | Contradiction registry (`data/contradictions.json`) |
| **Claim registry** | No | Proposed | No | Machine-readable `data/claims.json` |
| **Quality scorecard** | No | No | No | `data/scorecard.json` with health drift |
| **Staleness** | No | Confidence decay / forgetting curves | Lifecycle states | Freshness thresholds and revalidation flags |
| **Multi-agent** | Single model | Proposed mesh | Multiple adapters | Claude Code, Codex CLI, Gemini CLI |
| **Obsidian integration** | Not specified | Not specified | Symlink overlay | Native: `.obsidian/` at repo root |
| **Research runs** | None | None | None | Resumable: brief → collect → review → report → archive |
| **Bootstrap new vault** | No | No | No | `kb.py bootstrap --target <dir>` |

The point of the comparison is not that one gist is right and the other is wrong. The point is that K-Ops turns the gist shape into an operating system: source summaries, concept pages, machine-readable claims, contradiction tracking, scorecards, and a CLI that runs the whole loop.

## Compared With Mainstream Variants

The Karpathy-style fork space is useful to look at, but it still splits the problem into partial tools:

- Direct wiki forks such as [cablate/llm-atomic-wiki](https://github.com/cablate/llm-atomic-wiki) make the atom layer explicit. That is a sensible move for claim granularity, and it is closer to K-Ops than a plain note app. K-Ops uses source summaries and claim extraction for the same reason, but keeps the operational focus on provenance, contradiction handling, and repair rather than on atomic page design alone.
- Session-history tools such as [Pratiyush/llm-wiki](https://github.com/Pratiyush/llm-wiki) narrow the scope to coding-assistant transcripts and expose a production-minded MCP surface. Useful, but narrower than a research vault that must absorb arbitrary sources and keep them auditable over time.
- Memory layers such as [Mem0](https://mem0.ai/) optimize for persistent context across sessions. That is useful infrastructure, but it is not the same thing as a curated knowledge base with source summaries, claims, and contradiction tracking.
- Notebook tools such as [NotebookLM](https://notebooklm.google/) ground answers in provided sources. They are good at source-grounded answering, but they are not designed as a file-native, repairable knowledge system.

One empirical result matters for positioning: arXiv [2605.15184](https://arxiv.org/abs/2605.15184), *Is Grep All You Need? How Agent Harnesses Reshape Agentic Search*, found that the harness mattered more than the retrieval strategy and that grep often beat vector retrieval in the tested setups. That supports K-Ops's design bias: text-first, file-native, and grep-aligned.

`K-Ops` is therefore not trying to be the fastest scratchpad, the most polished MCP server, or the most abstract memory API. It is trying to be the governed layer that makes knowledge durable enough to audit, repair, and reuse.

---

## What You Get

- source ingestion for URLs, PDFs, local files, and note files
- GitHub repository ingestion with repository snapshot support
- normalized source artifacts under `data/raw/`
- a source registry in `data/registry.json`
- an Obsidian-ready vault under `notes/`
- prompt templates and role-based skills for ingestion, compilation, healing, Q&A, rendering, and research
- atomic claim and contradiction registries plus a vault scorecard for quality tracking
- a Python CLI in `scripts/kb.py` that orchestrates the workflow with Codex CLI, Claude Code, or Gemini CLI
- repo-root `.obsidian/` settings so the repository can be opened directly in Obsidian

---

## The Loop

```
Capture -> Normalize -> Compile -> Ask -> Render
```

1. **Capture** - drop in URLs, PDFs, GitHub repos, notes, or local files.
2. **Normalize** - ingest them into `data/raw/` and register them in `data/registry.json`.
3. **Compile** - agents turn raw content into source summaries, then merge them into concept pages under `notes/`.
4. **Ask** - query the vault in natural language and file grounded answers back into `notes/Answers/`.
5. **Render** - convert the current knowledge base into memos, outlines, slides, or reports.

---

## Requirements

- Python 3.11+
- `uv`
- one supported agent CLI on your `PATH`
  - `codex`
  - `claude`
  - `gemini`

Common fallback executable names are detected automatically:

- `codex-cli`
- `claude-code`
- `gemini-cli`

You can override the detected command with environment variables:

```bash
export KB_CODEX_CMD="codex"
export KB_CLAUDE_CMD="claude"
export KB_GEMINI_CMD="gemini"
```

---

## Setup

### 1. Install `uv`

If `uv` is not already installed:

```bash
brew install uv
```

or:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Sync the environment

```bash
uv sync
```

This project uses `uv` for dependency management. Use `uv sync` and `uv run`; do not use `pip install`.

### 3. Verify an agent CLI

The workflow expects one of these commands to be available:

- `codex`
- `claude`
- `gemini`

If the command name differs on your machine, set the override variables above.

---

## Quick Start

### 1. Add sources

Use one of the example input files:

- `examples/links.txt`
- `examples/kb-seed-sources.txt`
- `examples/project-on-fire-sources.txt`

Each line can point to a URL, local file, or note path:

```text
https://example.com/article
https://arxiv.org/abs/1706.03762
https://github.com/owner/repo
./examples/sample-note.md
./papers/interesting-paper.pdf
```

### 2. Ingest sources

```bash
uv run python scripts/kb.py ingest --input examples/links.txt
```

The ingest flow automatically routes:

- GitHub repository URLs to the repository snapshot ingest path
- GitHub repo page URLs such as `.../tree/main` or `.../blob/main/README.md` to the underlying repository
- other URLs to the regular web/PDF ingest path
- local files to direct copy/normalization

This creates:

- `data/raw/<source-id>/original.*`
- `data/raw/<source-id>/normalized.md`
- `data/raw/<source-id>/metadata.json`
- `data/registry.json`

If you want to force a branch for GitHub repository URLs in the input list:

```bash
uv run python scripts/kb.py ingest --input examples/links.txt --branch main
```

### 3. Compile the vault

```bash
uv run python scripts/kb.py compile --agent codex
```

or:

```bash
uv run python scripts/kb.py compile --agent claude
uv run python scripts/kb.py compile --agent gemini
```

This uses `templates/compile_prompt.md` and updates:

- `notes/Sources/`
- `notes/Concepts/`
- `notes/Home.md`
- `notes/TODO.md`

### 4. Ask a question

```bash
uv run python scripts/kb.py ask --agent codex --question "What are the main claims and open questions?"
```

This writes a timestamped answer memo to `notes/Answers/`.

### 5. Heal and lint

```bash
uv run python scripts/kb.py heal --agent claude
uv run python scripts/kb.py lint
```

`heal` surfaces contradictions, unsupported claims, and weak structure. `lint` checks vault consistency and backlink integrity.

### 6. Validate and inspect quality

```bash
uv run python scripts/kb.py validate
uv run python scripts/kb.py install-agent-assets --agent all --scope project
uv run python scripts/kb.py extract-claims
uv run python scripts/kb.py extract-contradictions
uv run python scripts/kb.py scorecard
```

`validate` confirms the vault paths load. The registry commands rebuild the machine-readable claim and contradiction layers, and `scorecard` summarizes health drift.

### 7. Render output

```bash
uv run python scripts/kb.py render --agent codex --format memo --prompt "Write a 1-page executive memo"
```

Supported render formats:

- `memo`
- `slides`
- `outline`
- `report`

Rendered outputs are written under `outputs/`.

### 8. Install CLI runtime assets

```bash
uv run python scripts/kb.py install-agent-assets --agent all --scope project
```

This syncs the repo's Codex skills, Claude Code agents and commands, and Gemini CLI commands/context into the selected runtime locations.

---

## Command Reference

### Ingest

- `ingest --input <file>`: ingest URLs and local paths from a newline-separated input file
- `ingest --branch <name>`: override the branch for GitHub repository URLs
- `ingest --fail-fast`: stop at the first ingestion error
- `ingest-github --repo <url>`: ingest one GitHub repository directly
- `ingest-github --compile-agent <codex|claude|gemini>`: compile immediately after ingesting the repository
- `refresh --agent <...>`: re-fetch/re-clone every source in `data/registry.json`, then compile the vault

### Vault Work

- `compile --agent <...>`: compile source summaries into durable notes
- `ask --agent <...> --question <text>`: generate an answer memo from the vault
- `heal --agent <...>`: run the healing prompt
- `render --agent <...> --format <memo|slides|outline|report> --prompt <text>`: generate an output artifact

### Maintenance

- `lint`: check registry, source notes, concept links, and backlink consistency
- `lint --strict`: fail on backlink drift
- `lint --fix-backlinks`: append missing source backlinks into concept evidence sections where possible
- `normalize-github-sources`: align GitHub-backed metadata fields
- `normalize-github-sources --dry-run`: preview GitHub metadata changes
- `backfill-source-notes`: create or repair missing source-summary notes
- `backfill-source-metadata`: backfill registry and raw metadata fields
- `backfill-concept-quality`: backfill concept claim-quality metadata
- `backfill-answer-quality`: backfill answer memo quality metadata
- `install-agent-assets`: sync skills and prompt templates into agent runtime locations
- `extract-claims`: rebuild `data/claims.json`
- `claim-search --query <text>`: search the claim registry
- `extract-contradictions`: rebuild `data/contradictions.json`
- `contradiction-search --query <text>`: search contradiction records
- `scorecard`: compute `data/scorecard.json`
- `stale-impact`: list notes flagged for revalidation
- `clear-stale-flags`: remove `revalidation_required` flags
- `validate`: confirm the vault config and required paths load
- `maintenance`: run the full mechanical maintenance pass
- `bootstrap --target <dir>`: create a new blank starter knowledge base with the same scripts, templates, and note structure
- `bootstrap --target <dir> --force`: overwrite the starter scaffold even if the target already exists
- `bootstrap --target <dir> --with-examples`: add a tiny example input folder to the starter vault

`maintenance --agent <...>` optionally refreshes and recompiles before the maintenance passes run.

### Graph and Export

- `export-vault`: write a zip archive containing `.obsidian/` and `notes/`
- `export-index`: export a structured vault manifest
- `export-index --format csv`: write the manifest as CSV
- `build-graph`: build the vault graph and retention report
- `search --query <text>`: search the graph
- `graph-traverse --start <id>`: traverse the graph from a node
- `retention-report`: write the retention report on its own

### Research Runs

The repo supports a resumable research-run workflow in `research/` for higher-stakes topics. Active run files live outside the curated vault so they can be resumed without polluting concept pages.

Core commands:

- `research-start --topic <text> --tier <fast|standard|deep>`
- `research-status [topic|all]`
- `research-collect --agent <codex|claude|gemini> --topic <text> --tier <...>`
- `research-review --agent <...> --topic <text> --tier <...>`
- `research-report --agent <...> --topic <text> --tier <...>`
- `research-import --topic <text> --path <file> --provider <gemini|openai|claude|perplexity|other> [--origin <label>]`
- `research-archive --topic <text>`

Imported model-generated reports are treated as leads, not authority. They are copied into the active run workspace and summarized into `notes/Sources/` with explicit provenance and a `lead_only` posture.

---

## Recommended Workflow

```bash
uv sync
uv run python scripts/kb.py ingest --input examples/links.txt
uv run python scripts/kb.py compile --agent codex
uv run python scripts/kb.py ask --agent codex --question "Compare the approaches and identify unresolved issues"
uv run python scripts/kb.py heal --agent codex
uv run python scripts/kb.py lint
```

If you are refreshing an existing vault, use this instead:

```bash
uv run python scripts/kb.py refresh --agent codex
```

---

## Repository Layout

```text
K-Ops/
├── data/
│   ├── claims.json
│   ├── contradictions.json
│   ├── fetch_queue.json
│   ├── raw/
│   ├── registry.json
│   └── scorecard.json
├── examples/
├── notes/
│   ├── Answers/
│   ├── Attachments/
│   ├── Concepts/
│   ├── Indexes/
│   ├── Maintenance/
│   ├── Runbooks/
│   ├── Sources/
│   ├── _Archive/
│   ├── _Templates/
│   ├── Home.md
│   └── TODO.md
├── outputs/
├── research/
├── scripts/
├── skills/
├── templates/
├── .obsidian/
├── AGENTS.md
├── CLAUDE.md
├── GEMINI.md
├── OPERATING_RULES.md
├── pyproject.toml
└── uv.lock
```

---

## Notes

- The orchestrator lives in `scripts/kb.py`.
- Most synthesis work is delegated to the selected agent CLI.
- GitHub repo ingestion creates a markdown snapshot with links back to the repository and extracted key concepts, architectural decisions, and a small set of high-signal files across the repository tree.
- Open the repo root in Obsidian to browse the curated note graph directly.
