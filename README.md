# K-Ops

**Your research shouldn't live in a graveyard of browser tabs.**

Most knowledge work ends the same way: a folder full of half-read PDFs, a Notion page you haven't opened in months, and a vague memory that you researched this topic before — somewhere. K-Ops is the system that breaks that cycle.

It's an agent-first knowledge base that turns raw sources into a living vault: structured, interlinked, queryable, and honest about what it doesn't know. You feed it evidence. It compounds into knowledge.

---

## Why K-Ops, and not just asking an LLM?

There's a beautiful idea floating around — popularized by Andrej Karpathy's LLM Wiki concept — that you can just let a language model edit and maintain a personal wiki for you. Drop your notes in, ask the model to update them, repeat.

K-Ops respects that idea and takes it further:

| | Karpathy-style LLM Wiki | K-Ops |
|---|---|---|
| **How knowledge is built** | LLM edits a flat document in place | Structured pipeline: raw source → summary → concept page |
| **Provenance** | Easy to lose — edits accumulate without trace | Every claim links back to a source summary; citations are enforced |
| **Contradictions** | Silent — the model picks a winner | Explicit — conflicts are flagged, recorded, and surfaced |
| **Quality signals** | None | Claim registry, contradiction registry, vault scorecard |
| **Link structure** | Manual | Auto-suggested from co-citation, PMI, Jaccard, semantic gravity, and more |
| **Multi-agent** | Typically one model | Claude Code, Codex CLI, Gemini CLI — same vault, any model |
| **Staleness** | No tracking | Per-source-type freshness thresholds; `revalidation_required` flag |
| **Schema enforcement** | None | `config/schema.yaml` validates every note type at lint time |
| **Research runs** | Ad hoc | Resumable: brief → collect → review → report → archive |

The short version: a Karpathy-style wiki is a great scratchpad. K-Ops is the system you use when you need to *trust* the knowledge — when it needs to be traceable, auditable, and honest about its own gaps.

---

## The loop that makes knowledge compound

```
Capture → Compile → Heal → Ask → Render
```

1. **Capture** — drop in URLs, files, GitHub repos. Don't overthink the format.
2. **Compile** — agents turn raw content into source summaries, then merge them into interlinked concept pages with inline citations.
3. **Heal** — fix broken links, add missing sections, flag stale claims. The vault stays navigable as it grows.
4. **Ask** — query the vault in natural language. Every answer is grounded in your sources and filed back as a reusable memo.
5. **Render** — convert knowledge into real outputs: briefs, slide outlines, memos, diagrams.

Each pass makes the vault sharper. Over time, asking a question you've already answered becomes instant — the memo is already there, with its sources.

---

## Five minutes to your first insight

```bash
# 1. Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Set up the project
uv sync

# 3. Ingest your first sources
uv run python scripts/kb.py ingest --input path/to/urls.txt

# 4. Compile summaries and concept pages
uv run python scripts/kb.py compile --agent claude

# 5. Ask something
uv run python scripts/kb.py ask --agent claude --question "What are the key themes across my sources?"

# 6. Render a memo
uv run python scripts/kb.py render --agent claude --format memo --prompt "Summarize findings for a stakeholder briefing"
```

Or install the `k-ops` console script and drop the `uv run python`:

```bash
uv tool install .
k-ops ingest --input path/to/urls.txt
```

---

## What's inside

| Layer | Location | What it does |
|---|---|---|
| Raw evidence | `data/raw/` | Immutable source files — never touched after ingest |
| Source summaries | `notes/Sources/` | Normalized per-source digests with reliability notes |
| Concept pages | `notes/Concepts/` | Durable, interlinked knowledge with inline citations |
| Answer memos | `notes/Answers/` | Grounded Q&A filed back into the vault |
| Indexes | `notes/Indexes/` | Source registry, topic atlas, vault dashboard |
| Maintenance | `notes/Maintenance/` | Contradictions log, missing topics, completed work |
| Research runs | `research/` | Resumable workspace: brief → findings → review → report |
| Claim registry | `data/claims.json` | Atomic claims, searchable by keyword |
| Contradiction registry | `data/contradictions.json` | Structured conflict records — one entry per disputed claim |
| Vault scorecard | `data/scorecard.json` | Quality metrics and health signals |
| Fetch queue | `data/fetch_queue.json` | Blocked URLs with failure modes and workarounds tracked |
| Templates | `notes/_Templates/` | Consistent scaffolds for every note type |
| Runbooks | `notes/Runbooks/` | Step-by-step workflow guides |

---

## Full command reference

```bash
# ── Core workflow ────────────────────────────────────────────────
uv run python scripts/kb.py ingest --input urls.txt
uv run python scripts/kb.py ingest-github --repo owner/repo --compile-agent claude
uv run python scripts/kb.py compile --agent claude
uv run python scripts/kb.py compile --dry-run          # preview prompt only
uv run python scripts/kb.py heal --agent claude
uv run python scripts/kb.py heal --dry-run
uv run python scripts/kb.py ask --agent claude --question "..."
uv run python scripts/kb.py render --agent claude --format memo --prompt "..."

# ── Quality & claims ─────────────────────────────────────────────
uv run python scripts/kb.py extract-claims
uv run python scripts/kb.py extract-contradictions
uv run python scripts/kb.py scorecard
uv run python scripts/kb.py claim-search --query "topic"
uv run python scripts/kb.py contradiction-search --query "disputed point"
uv run python scripts/kb.py claim-map --concept ConceptName   # Mermaid argument map

# ── Link intelligence ────────────────────────────────────────────
uv run python scripts/kb.py suggest-links --approach co-citation
uv run python scripts/kb.py suggest-links --approach embedding
uv run python scripts/kb.py suggest-links --approach conceptual-gravity

# ── Schema & normalization ───────────────────────────────────────
uv run python scripts/kb.py validate
uv run python scripts/kb.py validate --strict          # schema-validated via config/schema.yaml
uv run python scripts/kb.py normalize-frontmatter      # fix tags, enums, timestamps
uv run python scripts/kb.py lint

# ── Indexes & registry ───────────────────────────────────────────
uv run python scripts/kb.py generate-source-registry
uv run python scripts/kb.py fetch-queue                # list blocked / paywalled URLs

# ── Maintenance ──────────────────────────────────────────────────
uv run python scripts/kb.py maintenance --clean-tmp    # prune .tmp files older than 7 days
uv run python scripts/kb.py migrate-source-fields      # backfill source_kind / ingested_at

# ── Setup ────────────────────────────────────────────────────────
uv run python scripts/kb.py install-agent-assets --agent all --scope project
```

---

## Link intelligence — beyond manual wikilinks

One of the hardest parts of any knowledge base is discovering *which notes should link to each other*. K-Ops does this automatically, with nine approaches you can mix and match:

- **Co-citation** — pages cited together often should probably be linked
- **Shared sources** — concepts built from the same evidence may be related
- **Embedding similarity** — semantic proximity without shared keywords
- **Conceptual gravity** — high-degree nodes that many concepts orbit
- **Analogical mapping** — structural parallels across different domains
- **Triadic closure** — if A→B and B→C, A→C is a candidate
- **Eigenvector centrality** — pages that are important to important pages
- **Friction** — links that *should* exist but don't, creating dead ends
- **Contradiction mapping** — contradicting concepts should reference each other

Run `suggest-links` after a compile pass. Review the candidates. Accept the ones that feel right.

---

## Works with any agent

K-Ops is not locked to one AI provider. Your vault structure stays identical regardless of which CLI you use:

| Agent | Flag |
|---|---|
| Claude Code | `--agent claude` |
| OpenAI Codex CLI | `--agent codex` |
| Google Gemini CLI | `--agent gemini` |

Swap mid-workflow. Use the cheapest model for healing, the strongest for synthesis. The skills and prompts are identical across all three.

---

## The principles it runs on

- **Provenance over convenience.** Every claim traces back to a source summary. No silent invention.
- **Honest about gaps.** Thin evidence gets marked `provisional`. Conflicts go into `## Open Questions`, not the trash.
- **Schema as a contract.** `config/schema.yaml` defines what a valid source summary or concept page looks like. `validate --strict` catches drift before it spreads.
- **Staleness is a first-class citizen.** Sources have freshness thresholds. Stale claims get flagged — not silently stale, explicitly flagged.
- **Small edits, high signal.** Prefer one precise change over a broad rewrite. The vault grows by accretion, not replacement.

---

## Start here

Open `notes/Home.md` — that's the vault's front door.  
Check `notes/TODO.md` for what needs attention.  
Reach for `notes/Runbooks/Agent_Workflow_Quick_Reference.md` when you need the compact operator map.  
Open `notes/Runbooks/Obsidian_Plugin_Setup.md` when you want Dataview dashboards over your vault metadata.

The first pass doesn't need to be perfect. **It just needs to be real.**
