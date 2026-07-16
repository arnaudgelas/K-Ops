# K-Ops

<p align="center">
  <img src="logo.png" alt="K-Ops Logo" width="250">
</p>

**Your research should not live in a graveyard of browser tabs.**

`K-Ops` is a local, agent-operated research pipeline for turning links,
PDFs, repositories, notes, and files into a durable Markdown knowledge vault.
Raw evidence is preserved, sources are normalized, claims are extracted into
machine-readable registries, contradictions are surfaced, answers are governed by
a consequence-tier gate and filed back into the vault, and health checks make
epistemic debt visible.

The project is intentionally file-native. You should be able to inspect every
artifact with a text editor, review changes with Git, and open the curated
vault directly in Obsidian.

> **Why it's built this way, how it compares to the Karpathy-style LLM wiki
> pattern, the architecture, and — importantly — its trust model and limits:
> see [`docs/DESIGN.md`](docs/DESIGN.md).** K-Ops is a governed research-workflow
> substrate, not an autonomous truth oracle.

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

## What You Get

- direct single-source capture with `kops add <source>`
- batch source ingestion for URLs, PDFs, local files, and note files
- GitHub repository ingestion with repository snapshot support
- normalized source artifacts under `data/raw/` and a source registry in `data/registry.json`
- an Obsidian-ready vault under `notes/` with auto-generated `index.md` progressive-disclosure listings
- prompt templates and role-based skills for ingestion, compilation, healing, Q&A, rendering, and research
- machine-readable claim and contradiction registries plus a vault scorecard
- a Python CLI in `kops/kb.py` that orchestrates the workflow with Codex CLI, Claude Code, or Gemini CLI
- repo-root `.obsidian/` settings so the repository can be opened directly in Obsidian

### Governance and evidence layer

Answers and renders are governed, not free-form:

- **consequence-tier gating** of `ask` and `render`: the output gate freezes a
  **context package**, enforces an **answer-to-claim map**, and refuses,
  qualifies, or abstains when the evidence does not clear the requested stakes
  level (`output_gate.py`, `context_package.py`, `answer_claim_map.py`,
  `tier_policy.py`)
- **canonical evidence objects** plus an append-only, git-reviewable
  **validation-event audit ledger** (`evidence_model.py`, `evidence_store.py`,
  `validation_log.py`)
- **automatic source-change invalidation** that cascades to dependent notes and
  claims (`invalidation.py`)
- **source-independence lineage** for corroboration (`source_lineage.py`),
  **typed contradictions** (`typed_contradictions.py`), and **supervised
  distillation proposals** (`distillation.py`, proposal-only)
- a versioned **evaluation harness** and a published **benchmark report** at
  `research/benchmarks/REPORT.md` (`eval_metrics.py`, `benchmark_report.py`)
- a **pure entailment judge** (`entailment_judge.py`) that runs as an *advisory*
  audit only — it is **uncalibrated and non-gating**, is not wired into any
  compile/heal/answer gate, and must not be treated as a trust guarantee
  (calibration pending, see `research/benchmarks/CALIBRATION.md`)

Still **not** shipped: MCP serving, an SDK, a viewer/UI, and
embedding/hybrid retrieval.

---

## Requirements

- Python 3.11+
- `uv`
- one supported agent CLI on your `PATH`: `codex`, `claude`, or `gemini`

Common fallback executable names (`codex-cli`, `claude-code`, `gemini-cli`) are
detected automatically. Override the detected command with environment
variables if needed:

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

Command examples below use the `uv run kops ...` (dev) form. With Option A
installed, drop the `uv run` prefix and just use `kops ...`.

---

## Quick Start

### 1. Add a source

For daily capture, add one URL, GitHub repository, or local file directly:

```bash
uv run kops add https://example.com/article
uv run kops add https://github.com/owner/repo
uv run kops add ./papers/interesting-paper.pdf
```

For batch capture, use a newline-delimited input file (see `examples/links.txt`,
`examples/kb-seed-sources.txt`, `examples/project-on-fire-sources.txt`). Each
line can point to a URL, local file, or note path:

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

Both `add` and `ingest` create `data/raw/<source-id>/{original.*,normalized.md,metadata.json}`
and update `data/registry.json`. Force a branch for GitHub repository URLs with
`--branch main`.

### 3. Compile the vault

```bash
uv run kops compile --agent codex   # or: claude, gemini
```

This writes `.tmp/compile_plan.json`, uses `templates/compile_prompt.md`, and
updates `notes/Sources/`, `notes/Concepts/`, `notes/Home.md`, and `notes/TODO.md`.

### 4. Ask a question

```bash
uv run kops ask --agent codex --question "What are the main claims and open questions?"
uv run kops ask --agent codex --question "..." --tier decision
```

This seeds the Q&A prompt with local retrieval results and writes a timestamped
answer memo to `notes/Answers/`. The runtime rejects answer memos that leave
required provenance fields such as `retrieval_path` empty.

`ask` (and `render`) accept `--tier {exploratory|recommendation|decision|autonomous}`,
the consequence tier that governs the evidence bar. The default is `exploratory`
(lowest stakes); higher tiers make the output gate refuse, qualify, or abstain
when the supporting evidence is too weak to act at that stakes level.

### 5. Heal and lint

```bash
uv run kops heal --agent claude
uv run kops lint
```

`heal` surfaces contradictions, unsupported claims, and weak structure. `lint`
checks vault consistency and backlink integrity.

### 6. Validate and inspect quality

```bash
uv run kops validate
uv run kops extract-claims
uv run kops extract-contradictions
uv run kops scorecard      # or: audit-kb
```

`validate` confirms the vault paths load. The registry commands rebuild the
machine-readable claim and contradiction layers, and `scorecard` summarizes
health drift.

### 7. Render output

```bash
uv run kops render --agent codex --format memo --prompt "Write a 1-page executive memo"
```

Supported formats: `memo`, `slides`, `outline`, `report`. Rendered outputs are
written under `outputs/`.

### 8. Install CLI runtime assets

```bash
uv run kops install-agent-assets --agent all --scope project
```

This syncs the repo's Codex skills, Claude Code agents and commands, and Gemini
CLI commands/context into the selected runtime locations.

### 9. Use agent-native entries

After installing runtime assets, you can run the same loop from Claude Code,
Codex, or Gemini instead of only through `kops/kb.py`. If you are already inside
one of those tools, just say what you want:

| Workflow | Just say (with Claude Code, Codex, or Gemini) | Python CLI |
|---|---|---|
| Ingest source | `ingest this source` | `uv run kops ingest --input examples/links.txt` |
| Consolidate vault | `consolidate the vault` | `uv run kops compile --agent <codex\|claude\|gemini>` |
| Ask question | `answer this question from the vault: ...` | `uv run kops ask --agent <agent> --question "..."` |
| Heal vault | `heal the vault` | `uv run kops heal --agent <agent>` |
| Render output | `render this as a memo: ...` | `uv run kops render --agent <agent> --format memo --prompt "..."` |

Use the Python CLI for mechanical fetching and registry updates. Use the
agent-native entries when you are already inside Claude Code, Codex, or Gemini
and want that runtime to perform the synthesis-heavy pass.

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

- `compile --agent <...>`: compile source summaries into durable notes (runs an inner-loop verify after the agent write — rebuilds registries and flags a regressing write; `--no-verify` to skip)
- `compile-large --source-id <id>`: run the bottom-up summarization orchestrator for large sources (>50 nodes)
- `ask --agent <...> --question <text>`: generate an answer memo from the vault; `--tier <exploratory|recommendation|decision|autonomous>` sets the consequence tier (default `exploratory`)
- `heal --agent <...>`: run the healing prompt (also runs the inner-loop verify; `--no-verify` to skip)
- `render --agent <...> --format <memo|slides|outline|report> --prompt <text>`: generate an output artifact; `--tier <...>` sets the consequence tier (default `exploratory`)
- `uv run python -m kops.generate_indexes`: regenerate Source Atlas, Topic Atlas, and OKF directory indexes

### Maintenance

- `lint`: check registry, source notes, concept links, and backlink consistency
- `lint --strict`: fail on backlink drift
- `lint --fix-backlinks`: append missing source backlinks into concept evidence sections where possible
- `lint --check`: dry-run index generation in memory and fail if any auto-generated index files differ
- `normalize-github-sources`: align GitHub-backed metadata fields (`--dry-run` to preview)
- `backfill-source-notes`: create or repair missing source-summary notes
- `backfill-source-metadata`: backfill registry and raw metadata fields
- `backfill-concept-quality`: backfill concept claim-quality metadata
- `backfill-answer-quality`: backfill answer memo quality metadata
- `install-agent-assets`: sync skills and prompt templates into agent runtime locations
- `extract-claims`: rebuild `data/claims.json`
- `claim-search --query <text>`: search the claim registry
- `extract-contradictions`: rebuild `data/contradictions.json`
- `contradiction-search --query <text>`: search contradiction records
- `verify-spans`: check each claim's `quote=` anchor actually appears in its source; writes `data/span_verification.json`; `--check` fails closed on a mismatch
- `scorecard`: compute `data/scorecard.json`
- `audit-kb`: run the scorecard audit under an explicit audit command name
- `review-queue`: one prioritised list of everything needing human review (failed spans, blocked/quarantined/unsupported claims, undocumented contradictions, flagged sources, unreviewed probes, gaps); `--severity`, `--format`
- `signal-log`: record/report the deterministic quality-signal vector over time (`data/history/signals.jsonl`, gitignored) and gate on it — `--record` appends a datapoint, `--check` exits non-zero on a hard regression
- `next-action`: the loop controller — recommend the single highest-leverage next repair and a convergence verdict (`blocking` / `cleanup` / `converged`) from the deterministic signals; `--format`, `--check` (exit non-zero on a blocking state)
- `consequence-gate --tier <exploratory|recommendation|decision|autonomous>`: check whether the evidence clears the bar to act at a given stakes level; `--concept`, `--check`
- `stale-impact`: list notes flagged for revalidation
- `clear-stale-flags`: remove `revalidation_required` flags
- `retract <source-id> --reason <text>`: revoke a bad source, map its blast radius, flag dependents for revalidation, and re-block dependent claims; `--dry-run`, `--status`, `--format` (flags/reports only — never rewrites claims)
- `validate`: confirm the vault config and required paths load
- `maintenance`: run the full mechanical maintenance pass (`--agent <...>` optionally refreshes and recompiles first)
- `bootstrap --target <dir>`: create a new blank starter knowledge base with the same scripts, templates, and note structure (`--force` to overwrite, `--with-examples` to add a tiny example input folder)

### Governance and Evaluation

Answers and renders pass through a consequence-tier output gate; these commands
inspect the evidence bar and measure the pipeline end to end. See also the
related governance commands listed under Maintenance and Graph and Export:
`consequence-gate`, `retract`, `review-queue`, `stale-impact`,
`clear-stale-flags`, and `check-content-drift`.

- `consequence-gate --tier <exploratory|recommendation|decision|autonomous>`: check whether the evidence clears the bar to act at a given stakes level; `--concept`, `--format <text|json>`, `--check`
- `benchmark`: run the end-to-end evaluation metrics harness over the held-out corpus; `--snapshot`/`--no-snapshot`, `--provider <deterministic|agent-cli:<agent>>`, `--entailment` (advisory judge), `--top-k`, `--corpus`, `--golden-set`, `--out-dir`
- `benchmark-report`: render `research/benchmarks/REPORT.md` from the benchmark metrics; `--run` to re-run the harness first, `--out`, `--eval-runs-dir`, `--corpus`, `--golden-set`
- `eval-setup`: create the golden Q&A evaluation scaffold if it does not exist
- `eval-check`: validate the golden Q&A scaffold and golden-set schema

### Graph and Export

- `export-vault`: write a zip archive containing `.obsidian/` and `notes/`
- `export-index`: export a structured vault manifest (`--format csv` for CSV)
- `check-content-drift [--flag]`: detect raw-content drift (content-hash) for any source and flag the source note + derived pages `revalidation_required`
- `backfill-content-hash [--force]`: seed (or re-baseline) the `content_hash` drift baseline on source notes
- `build-graph`: build the vault graph and retention report
- `community-audit`: cluster the concept graph and report communities, bridge nodes, fragile clusters, and cross-cluster knowledge gaps; writes `data/graph/community_audit.json`; `--format`, `--min-shared`
- `search --query <text>`: search the graph
- `graph-traverse --start <id>`: traverse the graph from a node
- `retention-report`: write the retention report on its own

### Research Runs

The repo supports a resumable research-run workflow in `research/` for
higher-stakes topics. Active run files live outside the curated vault so they can
be resumed without polluting concept pages.

- `research-start --topic <text> --tier <fast|standard|deep>`
- `research-status [topic|all]`
- `research-collect --agent <codex|claude|gemini> --topic <text> --tier <...>`
- `research-review --agent <...> --topic <text> --tier <...>`
- `research-report --agent <...> --topic <text> --tier <...>`
- `research-import --topic <text> --path <file> --provider <gemini|openai|claude|perplexity|other> [--origin <label>]`
- `research-archive --topic <text>`

Imported model-generated reports are treated as leads, not authority. They are
copied into the active run workspace and summarized into `notes/Sources/` with
explicit provenance and a `lead_only` posture.

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

If you are refreshing an existing vault, use `uv run kops refresh --agent codex`
instead of the ingest/compile steps.

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

The repository is intentionally conservative here: more ingestion without
admission control creates epistemic debt. See
[`docs/DESIGN.md`](docs/DESIGN.md) for the full trust model and admission rule.

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
│   ├── scorecard.json
│   └── span_verification.json
├── docs/
│   └── DESIGN.md
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

- The orchestrator lives in `kops/kb.py`; most synthesis work is delegated to the selected agent CLI.
- GitHub repo ingestion creates a markdown snapshot with links back to the repository and extracted key concepts, architectural decisions, and a small set of high-signal files across the repository tree.
- Open the repo root in Obsidian to browse the curated note graph directly.
- For high-stakes use, review diffs and run `validate --strict`, `lint --strict`,
  `extract-claims`, `extract-contradictions`, and `audit-kb` before relying on
  generated conclusions.
