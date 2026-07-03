---
title: "Adversarial Review: K-Ops Hybrid Architecture Design (OKF + RVF)"
type: maintenance
tags:
  - kb/maintenance
  - kb/review
created: 2026-06-18
---

# Adversarial Review: K-Ops Hybrid Architecture Design

**Document reviewed:** `design.md` — K-Ops Hybrid Architecture Design Spec (Obsidian, OKF, and RVF Integration)

**Posture:** Devil's advocate. Every claim, design decision, and implementation choice is challenged. The goal is to surface the weakest load-bearing assumptions before Phase 3 engineering begins.

---

## I. Fundamental Premise: Does the Problem Exist?

### ADV-1 — The stated bottleneck is not the actual bottleneck

The document opens: "A robust knowledge vault must serve both humans and machine runtimes without locking data into a proprietary or single-modality format." This is a valid goal. But the proposed solution (sub-millisecond binary search via a compiled capsule) solves a performance problem that does not exist at the vault's current scale or likely future scale.

The vault currently has **1 source**, **1 concept page**, and **0 answer memos**. Even at 10,000 notes — an exceptionally large personal vault — keyword search over flat markdown files via `ripgrep` completes in under 30ms on modern hardware. SQLite FTS5 over the same corpus completes in under 5ms. FAISS similarity search over 10,000 384-dim vectors completes in under 1ms with zero custom code.

The actual bottleneck in any LLM-assisted workflow is model inference, which takes 2–30 seconds. Reducing retrieval from 30ms to 0.5ms is a 3% improvement on the end-to-end latency of an operation that takes 5 seconds. This is optimizing the wrong variable by two orders of magnitude.

**Challenge:** Before committing to a custom binary format and a WASM runtime, produce a benchmark showing the current retrieval implementation is a measurable bottleneck. Without that data, the entire RVF motivation is speculative.

---

### ADV-2 — The three-layer architecture multiplies complexity without proportional gain

The design introduces three overlapping systems (Obsidian, OKF, RVF) that each require:
- Their own tooling and maintenance pipeline
- Their own failure modes and recovery procedures
- Their own mental model for the operator
- Their own sync/staleness problem with the other two

A personal knowledge vault's dominant cost is **the human time spent organizing, editing, and questioning knowledge** — not retrieval performance. Adding three interdependent format layers increases the human maintenance burden substantially. The design does not quantify this cost.

The implicit assumption is that OKF enables agent interop and RVF enables fast search, making the vault more useful. But the current vault already has agent-driven compilation, linting, and Q&A — all working directly on markdown files. The design must demonstrate a concrete workflow that is **impossible or severely degraded** without OKF and RVF, not merely faster in theory.

---

### ADV-3 — "Vendor-neutral" is a marketing claim, not a technical reality

OKF is described as "standardized, vendor-neutral structure" and "Open Knowledge Format." But:

1. It is invented here, right now, at v0.1. There is no standards body, no RFC, no community, no implementations besides this vault. Calling it "open" is aspirational, not actual.
2. OKF notes still carry K-Ops-specific frontmatter (`claim_quality`, `evidence_status`, `kb/` tags). A hypothetical third-party OKF tool would not know what `claim_quality: provisional` means. This is K-Ops format with a neutral-sounding name.
3. RVF is "RuVector Format" — also invented here. Two new formats in one design document is not a simplification strategy.

If the goal is genuine interoperability with external tools, the correct approach is to adopt an existing standard (Logseq's format, Foam's structure, Obsidian Publish's export format, or simply "markdown files with YAML frontmatter" which is already a de facto standard). Creating new named formats moves in the opposite direction.

---

## II. OKF: Open Knowledge Format

### ADV-4 — Relative links are fundamentally more brittle than wikilinks for this use case

OKF's core requirement is standard relative Markdown links: `[Label](../Concepts/Target.md)`. The design argues this enables URI-based resolution by OKF tools. But:

1. **Rename brittleness:** Move or rename `Target.md` and every inbound relative link breaks silently. Obsidian resolves wikilinks by filename search — it handles renames transparently. Relative links have no such resilience. In a vault where the CLI agents create and update files, one misspelled filename in a write propagates broken links across every file that referenced it.

2. **Depth dependency:** A relative link from `notes/Concepts/A.md` to `notes/Sources/B.md` requires `../Sources/B.md`. The same link from `notes/Answers/C.md` requires `../Sources/B.md` too — identical by accident because both are one level deep. If a file moves one level deeper, all its outbound relative links silently point to wrong files. The lint patterns (`DualLinkPattern`) already handle both formats precisely because relative links required this defensive complexity.

3. **The mitigation doesn't work.** The design says "Obsidian's native toggle off for Use [[Wikilinks]] handles this automatically during link autocomplete." This controls what Obsidian generates on new link creation, but: (a) existing wikilinks in the vault are not migrated, (b) agents (Claude, Codex, Gemini) writing via the compile/heal prompts are instructed to write wikilinks — the SKILL.md and compile_prompt.md both specify `[[wikilink]]` syntax. The agent side of "two-way symmetry" is not updated.

---

### ADV-5 — `index.md` progressive disclosure creates a third navigation layer nobody asked for

The vault already has two navigation systems:
1. `notes/Home.md` — the curated navigation entry point, already used by all agent prompts
2. `notes/Indexes/` — generated Source_Atlas, Topic_Atlas, Vault_Dashboard, Source_Registry

OKF adds a third: per-folder `index.md` files at `notes/`, `notes/Concepts/`, `notes/Sources/`, `notes/Answers/`, `notes/Runbooks/`.

Problems:

1. **Stale by design.** These indexes are generated by `generate_indexes.py` and are static markdown. Every time a source or concept is added, they go stale until manually regenerated. There is no hook that regenerates them automatically. An agent reading `notes/Concepts/index.md` may get a list of concepts that is missing the last five compilation passes.

2. **Invisible to quality tooling.** The glob monkey-patch in `utils.py` explicitly excludes `index.md` from all `*.md` processing. This means the linter, scorecard, claim registry, and contradiction registry all ignore `index.md` files. A broken link in `notes/Concepts/index.md` will never be flagged. A missing concept in `notes/index.md` will never be detected.

3. **Modern agents don't need progressive disclosure.** The premise is that agents traverse folders "efficiently" by reading index files. But Claude Code's agent model uses tool calls (`list_dir`, `read_file`). The Q&A prompt already says "Read `notes/Home.md` first." No agent in the current system uses folder `index.md` files for traversal — the codebase shows zero references to folder-level index reading in any skill or template. This feature exists for a traversal model that isn't used.

4. **OKF `index.md` conflicts with the "OKF reserved" exclusion.** If `index.md` is OKF's primary discovery mechanism, why is it excluded from all quality processing? The exclusion was added to prevent linter processing of these auto-generated files. But this means the OKF navigation layer is permanently unvalidated.

---

### ADV-6 — OKF frontmatter adds fields that conflict with existing schema and are not validated

The OKF sample frontmatter introduces two new fields:
```yaml
description: "Structured inventory of K-Ops agent workflow patterns."
timestamp: 2026-06-17T16:21:00Z
```

Issues:
1. `description` is not in `config/schema.yaml`. The schema validator will not check it. It will not be surfaced in Dataview queries because no existing query template references it. It may drift from `title`, which already serves as the human-readable identifier.
2. `timestamp` conflicts with `ingested_at` (sources) and `asked_at` (answers). Concept pages have neither field currently. Adding a third timestamp field of ambiguous semantics (`created_at`? `compiled_at`? `updated_at`?) creates confusion.
3. Neither field is enforced by any lint rule, backfill script, or schema validator. They will be absent on 100% of existing notes and optional in practice, defeating the "strict frontmatter schema" claim.

---

### ADV-7 — "Vendor-neutral agentic traversal" is solved by existing tools OKF ignores

The OKF argument is that agents need a standardized traversal format. But:

- Claude Code has native file system tools (`list_dir`, `read_file`, `grep`) that traverse any directory structure without a special index.
- The Codex CLI and Gemini CLI also have file system access.
- The Q&A agent already uses `notes/Home.md` as its index — a curated, semantically meaningful entry point that is far more informative than a mechanical `index.md` directory listing.
- If an external agent with no K-Ops knowledge needs to traverse the vault, an `index.md` file listing `src-1f2a3b4c5d.md (Agent Workflow Quick Reference Summary)` tells it almost nothing useful. The real content is in the note body and frontmatter.

OKF's traversal value proposition assumes agents are dumb directory walkers. Modern LLM agents are not.

---

## III. RVF: The Binary Capsule

### ADV-8 — This is a database. Use a database.

The RVF spec describes exactly what several mature, widely-deployed open-source tools already do:

| RVF Segment | Existing tool that does this |
|---|---|
| `VEC_SEG` + `INDEX_SEG` (HNSW vector search) | FAISS, ChromaDB, LanceDB, Qdrant, pgvector |
| `GRAPH_SEG` (typed adjacency graph) | NetworkX, DuckDB, SQLite graph tables |
| `META_SEG` (compressed metadata + full text) | SQLite FTS5, DuckDB full-text search |
| `WITNESS_SEG` (hash-chain audit log) | Git (already present) |
| Binary capsule format | LanceDB `.lance` format, SQLite `.db` |

Building a custom binary format from scratch to replicate what these tools do — tools that have years of engineering, battle-tested correctness, active communities, Python bindings, and known performance characteristics — is a high-risk, low-reward strategy.

The engineering cost of getting a custom HNSW implementation right (correct recall, correct distance metrics, proper ef/M parameter tuning, memory layout, serialization) is measured in months. Getting it production-quality (no data corruption, correct behavior at boundary conditions, proper error handling) takes longer. The spec says nothing about any of this.

---

### ADV-9 — "Sub-millisecond" is a meaningless target without a baseline

The document uses "sub-millisecond" six times. This is the core performance claim that justifies the entire RVF engineering effort. But:

1. There is no baseline measurement of current retrieval latency.
2. There is no user-facing workflow where retrieval latency is the constraint. The Q&A agent's end-to-end time is dominated by LLM inference (seconds), not file reading (milliseconds).
3. For the vault's realistic content size (hundreds to low thousands of notes), ChromaDB's Python client returns results in 10–50ms. SQLite FTS5 returns results in 1–5ms. Both are "fast enough" for any human-in-the-loop knowledge workflow.
4. The only scenario where sub-millisecond retrieval provides UX value is a high-QPS production search API serving thousands of concurrent users. That is not this project.

Without a benchmark showing current performance is unacceptable, "sub-millisecond" is a number chosen because it sounds impressive, not because it addresses a real constraint.

---

### ADV-10 — The `WITNESS_SEG` hash-chain is unjustified security theater

The WITNESS_SEG contains "a cryptographic audit hash-chain of the vault lineage based on Git commit history and `log.md` updates, verifying compilation integrity."

Questions this raises:
1. **What threat model does this address?** The vault is a local personal knowledge base in a private git repository. Who is the attacker? What tampering is being detected?
2. **Git already provides this.** A git commit is a cryptographic hash of the tree, chained to its parent commits. Git already provides an immutable, verifiable audit log of every change to every file. Adding a parallel hash-chain inside a binary format duplicates this without adding security — a corrupted `.rvf` file would simply be rebuilt from the git-verified source.
3. **`log.md` files are not defined.** The glob monkey-patch also excludes `log.md`, suggesting they exist, but no runbook or design document explains what `log.md` files are, who writes them, or what they contain. The WITNESS_SEG references them as part of the chain without defining their format.
4. **The SHAKE-256 choice is unexplained.** SHA-256 is the standard choice for file integrity. SHAKE-256 (an XOF) is a more complex algorithm appropriate for specialized use cases. The choice is not justified.

---

### ADV-11 — The "46 KB WASM Control Plane" number is not credible

The spec claims "a lightweight runtime (~46 KB) loaded in static web dashboards allowing search queries directly in-browser."

A WASM module that performs:
- Custom binary format parsing
- Vector dequantization (int8 → float32)
- HNSW nearest-neighbor search traversal
- Distance computation (cosine similarity over 384-dim vectors)
- JSON decoding of META_SEG
- Result ranking and serialization

...cannot be 46 KB. A minimal Rust WASM binary with HNSW and basic float operations compiles to 200–500 KB before compression. The `hnsw_rs` crate's WASM build is ~300 KB. The number appears to be made up or copied from a different, simpler WASM project.

This matters because the 46 KB claim may be load-bearing in a stakeholder conversation ("it's barely any overhead"). The real number would be ~10x larger.

---

### ADV-12 — No model versioning: embedding changes invalidate the entire capsule

The MANIFEST_SEG stores "model identifier, vector dimension." But:

1. If you start with `all-MiniLM-L6-v2` (384 dims) and later upgrade to `bge-small-en-v1.5` (384 dims, but different embedding space), the dimension stays the same but all vectors are incompatible. Cosine similarity between old and new embeddings is meaningless.
2. If you switch from local embeddings to API embeddings (1536 dims), the entire capsule must be rebuilt.
3. The spec has no migration strategy, no version numbering for the capsule format, and no warning that changing the embedding model invalidates all existing query results.

In practice, every meaningful improvement to embedding models over the past 3 years has invalidated prior embeddings. Building a system with no migration path means rebuilding from scratch every time the model improves.

---

### ADV-13 — The delta compile mitigation is an undesigned system within a system

The "Vector Generation Overhead" tradeoff mitigation says: "Compute content hashes for note files and only re-embed pages whose hash changed."

This requires:
- A persistent mapping of `{file_path → content_hash → embedding}` (a cache database)
- Logic to detect deleted files and remove their embeddings from the HNSW index (HNSW deletion is notoriously hard — most implementations use a mark-and-rebuild approach)
- Logic to detect renamed files and update graph edges without re-embedding
- Incremental HNSW index updates (which differ significantly from batch builds in performance characteristics)

The `content_hash` field in `data/registry.json` exists for sources but not for concept pages or answer memos. The delta compile system is described in one bullet point as a "mitigation" but is actually a substantial engineering project in its own right.

---

### ADV-14 — The `.rvf` creates a second source of truth that will inevitably diverge from the vault

The MCP server serves queries against `kops.rvf`. The agents also have direct filesystem access to `notes/`. After a compile pass:

1. Vault markdown files are updated.
2. `kops.rvf` is **not** automatically regenerated (there's no hook described).
3. An agent querying via MCP gets results from the old capsule.
4. An agent reading via filesystem gets the current vault.

The design does not address: when is `export-rvf` triggered? Manually? On every `compile`? On a schedule? Without a clear trigger, the capsule will always be stale to some degree. The staler it is, the less useful the MCP server is — but the staler it is, the larger the divergence between MCP results and filesystem truth.

This is the canonical distributed systems dual-write problem. The mitigation for this class of problem (CQRS, event sourcing, etc.) is not addressed.

---

### ADV-15 — The MCP server adds an operational dependency with no documented management

Phase 4 says "Configure the `@ruvector/rvf-mcp-server` integration." This implies an external package (`@ruvector/rvf-mcp-server`) that:
- Must be installed and running before any agent can use it
- Requires network port management (what port? what happens if it's in use?)
- Must be restarted when `kops.rvf` is rebuilt
- Must handle concurrent agent connections gracefully
- Has no documented error recovery, health checks, or logging

For a personal local tool, every session that uses the MCP path requires first verifying the server is running. This adds friction that the current filesystem-direct approach does not have. The design presents MCP serving as a capability gain; it is also an operational burden gain.

---

## IV. Dual-Compatibility Strategy

### ADV-16 — The "dual-compatibility" comparison table stacks the deck

The strategic comparison table presents "Strict Export-Only" vs "Dual-Compatibility" in a way that makes the choice obvious. But the comparison contains errors:

1. **"Low linter/parser alignment overhead" for Dual-Compatibility is false.** The `DualLinkPattern` class — copied 4 times across scripts — exists precisely because the vault must parse both wikilinks and relative markdown links. The "alignment overhead" is in the codebase right now. It's called CRIT-3 in the design review.

2. **"Two-Way: Humans and agents read/write the same files" is aspirational, not current.** Agents write wikilinks (specified in all SKILL.md and template files). Obsidian with wikilinks enabled writes wikilinks. OKF wants relative links. Today, zero files use consistent relative links. The "two-way symmetry" is a goal, not a status.

3. **"Zero duplication" for Dual-Compatibility is partially false.** The skills are triplicated across `.claude/`, `.codex/`, `.gemini/`. The `index.md` files are generated copies of information already in the source notes. Duplication exists; it's just a different kind.

4. The comparison omits a third option: **"Obsidian-first with structured exports on demand"** — keep wikilinks as the native format, export a clean relative-link snapshot via `export-vault` only when external tool compatibility is needed. This has the simplicity of wikilinks for daily use with the OKF interop benefit when required.

---

### ADV-17 — The "Obsidian native configuration" tip contradicts the existing vault's actual link format

The design tip says: "disable wikilinks → Obsidian will automatically generate relative Markdown paths."

The existing vault has wikilinks everywhere. The SKILL.md files specify wikilinks. The compile_prompt.md specifies wikilinks. The lint rules check for wikilinks. The Obsidian_Plugin_Setup.md runbook references wikilinks in Dataview examples.

If a user follows this tip and disables wikilinks, Obsidian will:
- Generate relative paths for any new links they create
- Leave all existing wikilinks as-is (it doesn't auto-convert)
- Result in a mixed-format vault where half the links are `[[wikilinks]]` and half are `[relative](paths.md)`

The DualLinkPattern handles both in lint, but templates, agent prompts, and skills are written for wikilinks. The tip causes fragmentation without providing a migration path for the existing content.

---

## V. Implementation Roadmap

### ADV-18 — Phase 1 and Phase 2 claim "Completed" status for work with known structural bugs

Phase 1: "Equipped lint_vault.py with DualLinkPattern." This is marked Completed, but as identified in CRIT-3 of the design review, `DualLinkPattern` is copy-pasted across 4 scripts with a fragile flag-inference heuristic. Calling this "completed" creates false confidence that the foundation is solid when it has a known structural defect.

Phase 2: "Created `generate_okf_progressive_indexes` in `generate_indexes.py`." The `index.md` files exist in the repo (as shown in the file listing: `notes/index.md`, `notes/Concepts/index.md`, `notes/Sources/index.md`). But they are: (a) excluded from all quality processing, (b) statically generated and immediately stale, (c) not used by any agent prompt in the current codebase. Calling this "completed" means Phase 2 built infrastructure that no current workflow uses.

Phases 1 and 2 are better described as "scaffolded" or "partially implemented." Marking them "Completed" in a roadmap anchors the reader's expectation that the foundation is production-ready.

---

### ADV-19 — Phase 3 is multiple engineering projects presented as one phase

Phase 3 "RVF Compiler" contains:
- A new binary file format with 6 segment types
- An embedding pipeline with local model management
- HNSW index construction and serialization
- Typed graph adjacency serialization
- A binary segment packer
- A WASM runtime build

Each of these is a standalone engineering effort. Packaging them as "Phase 3: Next Phase" with 4 bullet points misrepresents the scope. A more honest roadmap would break these into sub-phases with separate completion criteria, so that partial progress is visible and the decision to continue (or pivot) can be made at each sub-phase boundary.

---

### ADV-20 — Phase 4 depends on an external package with no dependency vetting

"Configure the `@ruvector/rvf-mcp-server` integration." This is an NPM package. Before committing to a dependency:
- Is this package published? Under what license?
- Who maintains it? What's its test coverage?
- Does it handle the `kops.rvf` custom format, or is it a generic MCP wrapper that would need significant extension?
- What happens when the package breaks or is abandoned?

The design references this package as a configuration step ("configure the integration") implying it's a ready-made solution. If the package requires significant adaptation to the RVF format, this is a hidden implementation task. If it doesn't exist yet, Phase 4 is blocked before Phase 3 finishes.

---

## VI. Testing, Operations, and Observability

### ADV-21 — Zero testing strategy for any of the proposed infrastructure

The design has no mention of:
- Unit tests for binary segment serialization/deserialization (a corrupt VEC_SEG could silently return wrong results)
- Recall@k benchmarks for the HNSW implementation (what precision/recall is acceptable?)
- Correctness tests for the OKF link migration (do all existing wikilinks produce valid relative paths?)
- Integration tests for the MCP server (does the agent actually get better answers via MCP than via filesystem?)
- Regression tests ensuring that OKF changes don't break Obsidian's graph view or backlink indexing
- Performance benchmarks for the embedding pipeline (how long does a full vault compile take?)
- End-to-end tests: does a question answered via MCP RAG produce a factually correct answer grounded in the right source?

A design document for infrastructure of this complexity without a testing strategy is incomplete.

---

### ADV-22 — No staleness policy for the `.rvf` capsule

The vault has a detailed staleness policy for sources (3-month threshold for Anthropic docs, 6-month for GitHub snapshots, etc.) and a `revalidation_required` flag system. None of this applies to `kops.rvf`. When should the capsule be rebuilt? The design doesn't say. The likely answer is "whenever `compile` runs" — but that's not stated, and chaining `export-rvf` to every `compile` adds compilation time for every workflow.

---

### ADV-23 — The WASM browser dashboard is a product, not a feature

The mermaid diagram includes "Static Dashboards / Browser" as a first-class output, served via the WASM Control Plane. This implies:
- A web application that loads `.rvf` files in-browser
- UI components for search, result display, and navigation
- A build pipeline for the WASM module
- Hosting or distribution for the static dashboard

None of this is discussed beyond one diagram box. Building a browser-side knowledge dashboard is a product-level effort. Including it as a bullet in a 4-phase roadmap dramatically understates the work and, more importantly, does not clarify who the user of this dashboard is (if the operator is already using Obsidian, why do they need a browser dashboard?).

---

## VII. Alternatives Not Considered

### ADV-24 — Obsidian Smart Connections plugin eliminates Phase 3 entirely

Obsidian's "Smart Connections" community plugin provides:
- Local embedding of all vault notes (runs in-process, no external server)
- Semantic similarity search via cosine distance
- In-vault UI showing "related notes" based on embedding similarity
- Zero custom code, zero binary format, zero HNSW implementation

Installation takes 2 minutes. It would deliver the semantic search value proposition of the RVF `VEC_SEG` + `INDEX_SEG` with no engineering effort. Before committing to Phase 3, this alternative must be evaluated and disqualified with a documented reason.

---

### ADV-25 — LanceDB or ChromaDB as a side-car is a one-day implementation

Both LanceDB and ChromaDB provide:
- Vector storage with HNSW indexing (HNSW construction, not custom)
- Delta indexing (add/remove individual documents without rebuilding)
- Python APIs
- MCP compatibility (Chroma has an official MCP server)
- Persistent storage in a single file (LanceDB's `.lance` format) or local directory (Chroma)

A 50-line Python script wrapping ChromaDB would store embeddings, index them, and serve similarity search. It would not require inventing a new binary format, a new WASM runtime, or a new MCP server package. It would have a community, documentation, and bug fixes maintained by someone else.

The design's silence on these alternatives is its weakest point. When evaluating a custom implementation vs. an existing solution, the burden of proof lies with the custom approach to demonstrate why existing tools are insufficient.

---

### ADV-26 — DuckDB + markdown scanning beats the RVF spec for this use case

DuckDB (embeddable, zero server, single binary) can:
- Full-text search markdown files via `read_text` + FTS
- Store `FLOAT[384]` embedding columns with cosine similarity via `list_cosine_similarity`
- Execute graph-like queries via recursive CTEs
- Export to JSON, Parquet, or CSV
- Run in Python via `import duckdb`

A `data/vault.duckdb` side-car file, regenerated on `compile`, would provide everything RVF offers without custom binary format engineering, without a WASM build, and without a separate MCP server. DuckDB has a community MCP server. Total implementation: ~100 lines of Python, ~2 days of work.

---

### ADV-27 — The `export-vault` command already solves OKF's stated goal

The vault already has `kb.py export-vault` which creates a zip archive of the vault. If the goal is providing an external agent with a traversable, neutral-format copy of the vault, a zip export with a manifest is sufficient. There is no need for per-folder `index.md` files permanently cluttering the live vault.

An on-demand export approach (OKF-format snapshot only when needed, not stored in the live vault) cleanly separates the human-editing workspace from the agent-interop export, eliminating the dual-format maintenance burden.

---

## Summary: Priority Issues

| Priority | ID | Issue |
|---|---|---|
| **Critical** | ADV-1 | No evidence the claimed bottleneck (retrieval speed) actually exists at this scale |
| **Critical** | ADV-8 | Inventing a new binary format and HNSW implementation when FAISS/ChromaDB/LanceDB exist |
| **Critical** | ADV-9 | "Sub-millisecond" target has no baseline measurement to justify the engineering investment |
| **Critical** | ADV-24 | Obsidian Smart Connections plugin delivers Phase 3's value with zero code |
| **Critical** | ADV-25 | ChromaDB/LanceDB deliver Phase 3+4 with a one-day implementation |
| **High** | ADV-4 | Relative links are more brittle than wikilinks; mitigation only covers new links, not existing or agent-written ones |
| **High** | ADV-5 | OKF `index.md` is invisible to quality tooling, stale immediately, and unused by any agent prompt |
| **High** | ADV-11 | WASM Control Plane "46 KB" is not a credible claim; real size is ~10x |
| **High** | ADV-12 | No embedding model versioning; any model upgrade invalidates the entire capsule |
| **High** | ADV-14 | `.rvf` creates a second source of truth with no documented sync trigger |
| **High** | ADV-18 | Phase 1 and Phase 2 marked "Completed" with known structural bugs in DualLinkPattern and stale index.md |
| **High** | ADV-19 | Phase 3 is 6 separate engineering projects collapsed into 4 bullet points |
| **Medium** | ADV-3 | OKF "open" and "vendor-neutral" claims are aspirational; it's a proprietary format |
| **Medium** | ADV-6 | OKF frontmatter fields (`description`, `timestamp`) conflict with existing schema and are unvalidated |
| **Medium** | ADV-10 | WITNESS_SEG hash-chain duplicates Git's existing audit log without addressing a real threat model |
| **Medium** | ADV-13 | Delta compile "mitigation" is itself a multi-week engineering project |
| **Medium** | ADV-15 | MCP server adds an operational dependency with no management documentation |
| **Medium** | ADV-16 | Dual-compatibility comparison table contains factual errors |
| **Medium** | ADV-20 | Phase 4 depends on an unvetted external NPM package |
| **Medium** | ADV-21 | Zero testing strategy for any of the proposed infrastructure |
| **Medium** | ADV-22 | No staleness policy for `kops.rvf` analogous to the vault's source staleness rules |
| **Low** | ADV-2 | Three-layer architecture multiplies maintenance burden without quantified gain |
| **Low** | ADV-17 | "Disable wikilinks" tip causes format fragmentation without migrating existing links |
| **Low** | ADV-23 | WASM browser dashboard is a product-level effort silently included in Phase 3 |
| **Low** | ADV-26 | DuckDB as a side-car covers the full RVF spec in ~100 lines |
| **Low** | ADV-27 | The existing `export-vault` command already solves OKF's traversal goal on-demand |

---

## Recommended Path Forward

Before proceeding with Phase 3 or any OKF link-format migration, resolve these in order:

1. **Benchmark first.** Measure actual Q&A agent end-to-end latency. Identify what fraction is retrieval vs. inference. If retrieval is under 5% of total time, the RVF rationale collapses.

2. **Evaluate Obsidian Smart Connections.** Install it, run it on the current vault, measure recall quality. If it meets the semantic search need, Phase 3 is unnecessary.

3. **Evaluate ChromaDB or LanceDB.** Implement a 50-line spike. Compare results with the Smart Connections plugin. Pick one.

4. **Decide the link format, once, and migrate fully.** Either (a) commit to wikilinks, update SKILL.md/templates to be consistent, and drop OKF's relative-link requirement; or (b) commit to relative links, migrate all existing files, and update all agent prompts. The current hybrid state (wikilinks everywhere, relative links required by OKF, DualLinkPattern required by the hybrid) is the most expensive option.

5. **If RVF proceeds after evaluation, split Phase 3 into 6 sub-phases** with independent completion criteria and a go/no-go decision at each gate.

6. **Drop WITNESS_SEG.** Git provides the audit capability without custom code. Use the engineering time on correctness instead.
