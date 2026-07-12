# K-Ops

<p align="center">
  <img src="logo.png" alt="K-Ops Logo" width="250">
</p>

**Your research should not live in a graveyard of browser tabs.**

`K-Ops` is a local, agent-operated research pipeline for turning links,
PDFs, repositories, notes, and files into a durable Markdown knowledge vault.

It keeps the Karpathy-style LLM wiki idea in view, but treats that as the
starting point. K-Ops is more opinionated: raw evidence is preserved, sources
are normalized, claims are extracted into machine-readable registries,
contradictions are surfaced, answers are filed back into the vault, and health
checks make epistemic debt visible.

The project is intentionally file-native. You should be able to inspect every
artifact with a text editor, review changes with Git, and open the curated
vault directly in Obsidian.

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

## Architecture

K-Ops has two cooperating layers:

```text
raw evidence -> registry -> source summaries -> concept pages
                         \-> claims / contradictions / scorecard
                         \-> retrieval seeds for Q&A
```

**Deterministic Python layer**

- ingests URLs, PDFs, repositories, and local files into `data/raw/`
- maintains `data/registry.json`
- computes content hashes and large-source manifests
- extracts claim and contradiction registries from curated notes
- builds graph/index artifacts and vault scorecards
- seeds Q&A prompts with local BM25/exact-search results
- validates answer memo frontmatter after agent runs
- performs atomic writes for shared JSON/text state

**Agent layer**

- summarizes raw evidence into `notes/Sources/`
- compiles source summaries into `notes/Concepts/`
- answers questions into `notes/Answers/`
- performs judgment-heavy healing, synthesis, and rendering

This split is deliberate. Python should own repeatable bookkeeping and
validation. Agents should own interpretation, synthesis, and prose. Recent
hardening work moves more context from Python into prompts instead of asking
agents to rediscover it by hand.

### Direction: governed claim graph

The current repo is file-native: Markdown is the human workspace and JSON files
are the machine-readable audit layer. The intended direction is stricter than
"RAG over notes":

```text
Source -> SourceSpan -> Claim -> Entity -> Relation
       -> Contradiction -> ValidationEvent -> ContextPackage -> AnswerMemo
```

That target model matters because a research system has to answer questions
that a summary vault cannot answer reliably:

- was this claim true at the time it was stated?
- which source span supports it?
- where does it apply, and where does it not apply?
- what contradicts or supersedes it?
- who or what validated it?
- what answers or decisions depend on it?
- is it allowed to support a consequential recommendation?

Until that canonical claim graph is implemented, treat concept pages as curated
working surfaces and the registries as audit surfaces, not as proof that every
claim has been independently verified.

### OKF compatibility posture

K-Ops uses OKF as an interchange and traversal layer, not as the whole
governance model.

OKF v0.1 is intentionally minimal: a knowledge bundle is a directory tree of
Markdown files with YAML frontmatter, `type` is the only required concept
frontmatter field, `index.md` and `log.md` are reserved filenames, and consumers
are expected to tolerate unknown fields, missing optional fields, and broken
links. That permissiveness is a strength for exchange.

K-Ops should therefore use OKF for:

- portable bundle layout
- standard Markdown links in generated traversal indexes
- root `okf_version` declaration
- progressive disclosure through `index.md`
- tolerance of producer-specific frontmatter

K-Ops should not use OKF as a substitute for:

- claim admission
- citation-span verification
- contradiction adjudication
- staleness propagation
- validation events
- consequence gating

In other words: OKF makes the vault easier to read and exchange. It does not
make claims true, fresh, scoped, or safe to act on.

### Implemented vs planned

Implemented today:

- Obsidian-compatible Markdown vault under `notes/`
- OKF-style progressive `index.md` files for bundle traversal
- source registry, claim registry, contradiction registry, and scorecard
- deterministic quote-span verification (`verify-spans`): checks each claim's
  cited quote actually appears in its source, fails closed on a mismatch
- concept-graph community/bridge/gap audit (`community-audit`): clusters concepts,
  flags high-betweenness bridge nodes and fragile single-connector clusters, and
  surfaces cross-cluster knowledge gaps (shared sources, no link)
- aggregated human-review worklist (`review-queue`): one prioritised list of
  failed spans, blocked/quarantined/unsupported claims, undocumented
  contradictions, sources needing verification, unreviewed probes, and gaps
- exact lookup and BM25 retrieval over sources, concepts, claims, and sections
- deterministic compile plans written to `.tmp/compile_plan.json`
- answer memo schema checks after `ask`
- GitHub repository snapshot ingestion
- resumable research-run workflow under `research/`

Planned, not implemented as a production feature:

- RVF binary capsule export
- MCP serving over a compiled RVF capsule
- persistent SQLite/FTS index
- LLM-judged citation *entailment* (whether a verified quote actually supports
  the claim, beyond merely existing in the source)
- automatic content-hash stale cascade on refresh
- bitemporal claim history and validation events
- consequence thresholds for high-impact answers
- supervised concept merge, rename, and distillation tools

---

## What You Get

- direct single-source capture with `kb.py add <source>`
- batch source ingestion for URLs, PDFs, local files, and note files
- GitHub repository ingestion with repository snapshot support
- normalized source artifacts under `data/raw/`
- a source registry in `data/registry.json`
- an Obsidian-ready vault under `notes/`
- progressive disclosure directory listings (`index.md` files) auto-generated at all folder levels
- prompt templates and role-based skills for ingestion, compilation, healing, Q&A, rendering, and research
- machine-readable claim and contradiction registries plus a vault scorecard
- a Python CLI in `kops/kb.py` that orchestrates the workflow with Codex CLI, Claude Code, or Gemini CLI
- repo-root `.obsidian/` settings so the repository can be opened directly in Obsidian

## Trust Model and Limits

K-Ops is designed to make provenance and review cheaper. It does not make
LLM-written summaries automatically true.

Current guarantees:

- raw evidence under `data/raw/` is preserved
- source metadata includes stable IDs and content hashes
- concept claims can be required to carry inline source links
- claims carrying a `quote=` anchor are verified to actually appear in their
  source (`verify-spans`); a fabricated quote fails closed and raises an error
  signal in the scorecard
- model-generated and weak sources can be quarantined at claim-registry level
- answer memos must provide valid `retrieval_path` and `fetch_required`
- lint/schema/scorecard checks expose unsupported, stale, conflicting, or weak
  areas

Current limits:

- quote **existence** is verified (the quote is really in the source) but not
  quote **entailment** (that the quote supports the claim) — entailment needs an
  LLM judge and is not yet implemented
- claims that cite a source but carry no `quote=` anchor are checked for citation
  presence, not for support
- content hash changes do not yet trigger a full automatic invalidation cascade
- contradiction records do not yet distinguish direct conflict, temporal
  supersession, scope mismatch, terminology conflict, or synthetic contamination
- concept pages can still accumulate duplicate or stale claims without a
  supervised distillation pass
- retrieval is still lexical/BM25-first; graph traversal, embeddings,
  reranking, and query routing are roadmap items
- agent runs still require human review before consequential use

Treat K-Ops as a governed research-workflow substrate, not as an autonomous
truth oracle.

## Admission Rule

Do not treat ingestion as progress by itself. A new source only becomes useful
after it has passed through admission, decomposition, linking, contradiction
review, and evaluation.

For serious use, operate with three zones:

- **Raw intake:** fetched material in `data/raw/`; preserved, but not trusted.
- **Quarantine:** weak, synthetic, ambiguous, stale, or low-authority material;
  visible to operators, but not allowed to support high-consequence answers.
- **Curated vault:** source summaries, concept pages, claims, and answers that
  have passed the current lint/schema/scorecard gates and human review.

The practical discipline is simple: curation capacity should determine
ingestion volume. If you cannot validate, link, and evaluate the material, do
not keep adding more.

---

## The Loop

```
Capture -> Normalize -> Compile -> Ask -> Render
```

1. **Capture** - add URLs, PDFs, GitHub repos, notes, or local files.
2. **Normalize** - ingest them into `data/raw/` and register them in `data/registry.json`.
3. **Compile** - agents turn raw content into source summaries, then merge them into concept pages under `notes/`, generating OKF progressive index files.
4. **Ask** - query the vault in natural language; Python seeds the prompt with local retrieval results and files grounded answers back into `notes/Answers/`.
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

There are two ways to use K-Ops: **install the `kops` CLI** and run it against
your own vault, or **clone the repo** to develop the tooling itself.

### Install `uv`

If `uv` is not already installed:

```bash
brew install uv
# or
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Option A — Install the `kops` CLI (run it against any vault)

Install the packaged CLI once, then point it at any vault. Only the tooling is
installed — your vault stays a plain folder of Markdown, and no private data ever
lives with the code.

```bash
uv tool install --from git+https://github.com/arnaudgelas/K-Ops kops
```

Run it from inside a vault (it walks up to find `config/kb_config.yaml`), or
target one explicitly with `--vault`:

```bash
cd ~/my-vault && kops compile --agent codex
kops --vault ~/my-vault validate        # from anywhere
```

`kops --help` works without a vault. Bundled assets (validation schema, prompt
templates, skills) ship inside the wheel, so no source checkout is needed.

### Option B — Develop the tooling (work on K-Ops itself)

Clone the repo and use `uv` for an editable dev environment:

```bash
uv sync                # install deps + kops in editable mode
uv run kops --help     # run the CLI from the checkout
uv run pytest          # run the test suite
```

Command examples in this README use the `uv run kops ...` (dev) form. With
Option A installed, drop the `uv run` prefix and just use `kops ...`.

### Verify an agent CLI

The workflow expects one of these commands to be available:

- `codex`
- `claude`
- `gemini`

If the command name differs on your machine, set the override variables above.

---

## Quick Start

### 1. Add a source

For daily capture, add one URL, GitHub repository, or local file directly:

```bash
uv run kops add https://example.com/article
uv run kops add https://github.com/owner/repo
uv run kops add ./papers/interesting-paper.pdf
```

For batch capture, use a newline-delimited input file:

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

### 2. Ingest a batch

```bash
uv run kops ingest --input examples/links.txt
```

The ingest flow automatically routes:

- GitHub repository URLs to the repository snapshot ingest path
- GitHub repo page URLs such as `.../tree/main` or `.../blob/main/README.md` to the underlying repository
- other URLs to the regular web/PDF ingest path
- local files to direct copy/normalization

Both `add` and `ingest` create:

- `data/raw/<source-id>/original.*`
- `data/raw/<source-id>/normalized.md`
- `data/raw/<source-id>/metadata.json`
- `data/registry.json`

If you want to force a branch for GitHub repository URLs in the input list:

```bash
uv run kops ingest --input examples/links.txt --branch main
```

### 3. Compile the vault

```bash
uv run kops compile --agent codex
```

or:

```bash
uv run kops compile --agent claude
uv run kops compile --agent gemini
```

This writes `.tmp/compile_plan.json`, uses `templates/compile_prompt.md`, and
updates:

- `notes/Sources/`
- `notes/Concepts/`
- `notes/Home.md`
- `notes/TODO.md`

### 4. Ask a question

```bash
uv run kops ask --agent codex --question "What are the main claims and open questions?"
```

This seeds the Q&A prompt with local retrieval results and writes a timestamped
answer memo to `notes/Answers/`. The runtime rejects answer memos that leave
required provenance fields such as `retrieval_path` empty.

### 5. Heal and lint

```bash
uv run kops heal --agent claude
uv run kops lint
```

`heal` surfaces contradictions, unsupported claims, and weak structure. `lint` checks vault consistency and backlink integrity.

### 6. Validate and inspect quality

```bash
uv run kops validate
uv run kops install-agent-assets --agent all --scope project
uv run kops extract-claims
uv run kops extract-contradictions
uv run kops scorecard
```

`validate` confirms the vault paths load. The registry commands rebuild the machine-readable claim and contradiction layers, and `scorecard` summarizes health drift.

`audit-kb` is an alias for the scorecard audit surface:

```bash
uv run kops audit-kb
```

### 7. Render output

```bash
uv run kops render --agent codex --format memo --prompt "Write a 1-page executive memo"
```

Supported render formats:

- `memo`
- `slides`
- `outline`
- `report`

Rendered outputs are written under `outputs/`.

### 8. Install CLI runtime assets

```bash
uv run kops install-agent-assets --agent all --scope project
```

This syncs the repo's Codex skills, Claude Code agents and commands, and Gemini CLI commands/context into the selected runtime locations.

### 9. Use agent-native entries

After installing runtime assets, you can run the same loop from Claude Code, Codex, or Gemini instead of only through `kops/kb.py`. If you are already inside one of those tools, just say what you want:

| Workflow | Just say (with Claude-code, Codex, or Gemini) | Python CLI |
|---|---|---|
| Ingest source | `ingest this source` | `uv run kops ingest --input examples/links.txt` |
| Consolidate vault | `consolidate the vault` | `uv run kops compile --agent <codex\|claude\|gemini>` |
| Ask question | `answer this question from the vault: ...` | `uv run kops ask --agent <agent> --question "..."` |
| Heal vault | `heal the vault` | `uv run kops heal --agent <agent>` |
| Render output | `render this as a memo: ...` | `uv run kops render --agent <agent> --format memo --prompt "..."` |

Use the Python CLI for mechanical fetching and registry updates. Use the agent-native entries when you are already inside Claude Code, Codex, or Gemini and want that runtime to perform the source-summary, Q&A, healing, consolidation, or rendering pass.

---

## Command Reference

### Ingest

- `add <source>`: ingest one URL, GitHub repo URL, or local file directly
- `add <source> --branch <name>`: override the branch for a GitHub repo URL
- `ingest --input <file>`: ingest URLs and local paths from a newline-separated input file
- `ingest --branch <name>`: override the branch for GitHub repository URLs
- `ingest --fail-fast`: stop at the first ingestion error
- `ingest-github --repo <url>`: ingest one GitHub repository directly
- `ingest-github --compile-agent <codex|claude|gemini>`: compile immediately after ingesting the repository
- `refresh --agent <...>`: re-fetch/re-clone every source in `data/registry.json`, then compile the vault

### Vault Work

- `compile --agent <...>`: compile source summaries into durable notes
- `compile-large --source-id <id>`: run the bottom-up summarization orchestrator for large sources (>50 nodes)
- `ask --agent <...> --question <text>`: generate an answer memo from the vault
- `heal --agent <...>`: run the healing prompt
- `render --agent <...> --format <memo|slides|outline|report> --prompt <text>`: generate an output artifact
- `uv run python -m kops.generate_indexes`: regenerate Source Atlas, Topic Atlas, and OKF directory indexes


### Maintenance

- `lint`: check registry, source notes, concept links, and backlink consistency
- `lint --strict`: fail on backlink drift
- `lint --fix-backlinks`: append missing source backlinks into concept evidence sections where possible
- `lint --check`: dry-run index generation in memory and fail if any auto-generated index files differ
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
- `audit-kb`: run the scorecard audit under an explicit audit command name
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
uv run kops ingest --input examples/links.txt
uv run kops compile --agent codex
uv run kops ask --agent codex --question "Compare the approaches and identify unresolved issues"
uv run kops heal --agent codex
uv run kops lint
```

If you are refreshing an existing vault, use this instead:

```bash
uv run kops refresh --agent codex
```

For daily or weekly production use, prefer an epistemic workflow over a
continuous collector:

1. Add sources to intake.
2. Normalize and hash sources.
3. Compile source summaries.
4. Extract candidate claims and contradictions.
5. Run lint, schema validation, and scorecard.
6. Review quarantined or weak claims before promoting them.
7. Fix stale, orphaned, duplicate, and unsupported knowledge.
8. Ask or render only after the vault is clean enough for the consequence level.

The repository is intentionally conservative here. More ingestion without
admission control creates epistemic debt.

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
│   │   └── index.md
│   ├── Attachments/
│   ├── Concepts/
│   │   └── index.md
│   ├── Indexes/
│   ├── Maintenance/
│   ├── Runbooks/
│   │   └── index.md
│   ├── Sources/
│   │   └── index.md
│   ├── _Archive/
│   ├── _Templates/
│   ├── Home.md
│   ├── TODO.md
│   └── index.md
├── outputs/
├── research/
├── kops/                  # installable tooling package (Python modules + bundled skills/, templates/, schema.yaml)
├── config/                # kb_config.yaml — vault configuration
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

- The orchestrator lives in `kops/kb.py`.
- Most synthesis work is delegated to the selected agent CLI.
- GitHub repo ingestion creates a markdown snapshot with links back to the repository and extracted key concepts, architectural decisions, and a small set of high-signal files across the repository tree.
- Open the repo root in Obsidian to browse the curated note graph directly.
- For high-stakes use, review diffs and run `validate --strict`, `lint --strict`,
  `extract-claims`, `extract-contradictions`, and `audit-kb` before relying on
  generated conclusions.
