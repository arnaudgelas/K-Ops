# K-Ops — Design & Rationale

This document explains *why* K-Ops is shaped the way it is: how it relates to the
Karpathy-style LLM wiki pattern and its forks, the layered architecture, the
intended direction toward a governed claim graph, and — most importantly — the
trust model and its limits.

For installation and day-to-day commands, see the [README](../README.md).

---

## Why K-Ops, and not just asking an LLM?

In April 2026, Andrej Karpathy published an LLM wiki gist — a three-folder pattern (raw sources, compiled wiki pages, a schema file) where an LLM maintains a personal knowledge base without a vector database. The post went viral in the developer community and generated a wave of community implementations.

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
| **Bootstrap new vault** | No | No | No | `kops bootstrap --target <dir>` |

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
- source retraction (`retract`): revoke a bad source, map its blast radius over
  the graph, flag dependent concepts/answers for revalidation, and re-block
  dependent claims — flags and reports, never silently rewrites claims
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
