# K-Ops — Design & Rationale

This document explains *why* K-Ops is shaped the way it is: how it relates to the
Karpathy-style LLM wiki pattern and its forks, the layered architecture, the
intended direction toward a governed claim graph, and — most importantly — the
trust model and its limits.

For installation and day-to-day commands, see the [README](../README.md).

---

## Why K-Ops, and not just asking an LLM?

In April 2026, Andrej Karpathy published an LLM wiki gist — a three-folder pattern (raw sources, compiled wiki pages, a schema file) where an LLM maintains a personal knowledge base without a vector database. The post went viral in the developer community and generated a wave of community implementations.

`K-Ops` was built before the gist was published, and shares the same core conviction. Where it goes further is governance: K-Ops is not just a wiki layout, it is a file-native knowledge substrate with claim tracking, typed contradiction handling, freshness controls, and a repair loop. It now also enforces a governed *serving boundary* — a tiered consequence gate that freezes a deterministic context package, checks each answer sentence against an admitted claim, and records the decision in an immutable audit ledger — plus an automatic invalidation cascade when a source's content changes.

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

The K-Ops column above lists only capabilities that ship today (each maps to a file cited in the [capability matrix](#versioned-capability-matrix)); it does not list planned surface such as MCP serving, an SDK, a viewer, or embedding retrieval. The other columns characterise the gists and community forks **as of 2026-07-15** from their public text, not from a code audit, and are not ranked by stars or lines of code.

## Compared With Mainstream Variants

> **On comparisons in this section.** Comparator feature claims are a moving
> target: the projects below ship new capabilities, and their READMEs sometimes
> describe intended surface rather than shipped code. All comparator statements
> here are **as of 2026-07-15** and are taken from each project's public
> description, *not* independently verified against its source tree. Where we have
> not read the comparator's code, its status is marked **unverified**. K-Ops-side
> claims, by contrast, are backed by repository evidence (file paths, see the
> [capability matrix](#versioned-capability-matrix)). We deliberately do **not**
> rank these systems by GitHub stars or lines of code; adoption counts are
> dynamic and are not a measure of governance.

The nearest current comparators split the problem into different bundles of tools:

- **AtomicStrata** is the closest current system in ambition: its public materials describe an atomic-claim knowledge base with lifecycle *profiles* for concepts, runtime *trust gates*, *hybrid* (lexical + embedding) retrieval, a *viewer* UI, an *MCP* server, an *SDK*, an *evaluation* suite, and *staged imports*. That is a broad, governance-flavoured surface and is the comparator referenced throughout [ROADMAP.md](ROADMAP.md). Two honesty caveats apply. First, that list is AtomicStrata's *claimed/reported* feature surface as of 2026-07-15; we have not verified it against its repository, so each item is treated as **unverified** in the matrix below. Second, several of those capabilities (a viewer, MCP serving, an SDK, embedding retrieval) are exactly the ones K-Ops has **not** shipped yet — see "Implemented vs planned" and the matrix; K-Ops's current edge is in the deterministic governance primitives, not in surface breadth. That edge is now a governed serving *boundary*, not just point checks: a tiered consequence gate that freezes a deterministic context package and enforces an answer→claim map, quote-span existence checks, source retraction with blast radius, an automatic content-hash invalidation cascade, an immutable validation-event ledger, source-independence corroboration, and typed contradictions. (The one governance primitive AtomicStrata claims that K-Ops has *not* closed is a calibrated, trusted entailment gate — K-Ops's entailment judge ships but is uncalibrated and non-gating.)
- Direct wiki forks such as [cablate/llm-atomic-wiki](https://github.com/cablate/llm-atomic-wiki) make the atom layer explicit. That is a sensible move for claim granularity, and it is closer to K-Ops than a plain note app. K-Ops uses source summaries and claim extraction for the same reason, but keeps the operational focus on provenance, contradiction handling, and repair rather than on atomic page design alone.
- Session-history tools such as [Pratiyush/llm-wiki](https://github.com/Pratiyush/llm-wiki) narrow the scope to coding-assistant transcripts and expose a production-minded MCP surface. Useful, but narrower than a research vault that must absorb arbitrary sources and keep them auditable over time.
- Memory layers such as [Mem0](https://mem0.ai/) optimize for persistent context across sessions. That is useful infrastructure, but it is not the same thing as a curated knowledge base with source summaries, claims, and contradiction tracking.
- Notebook tools such as [NotebookLM](https://notebooklm.google/) ground answers in provided sources. They are good at source-grounded answering, but they are not designed as a file-native, repairable knowledge system.

One empirical result matters for positioning: arXiv [2605.15184](https://arxiv.org/abs/2605.15184), *Is Grep All You Need? How Agent Harnesses Reshape Agentic Search*, found that the harness mattered more than the retrieval strategy and that grep often beat vector retrieval in the tested setups. That supports K-Ops's design bias: text-first, file-native, and grep-aligned. It is also why K-Ops's not-yet-shipped embedding retrieval is a considered trade-off rather than a gap it is rushing to close.

`K-Ops` is therefore not trying to be the fastest scratchpad, the most polished MCP server, or the most abstract memory API. It is trying to be the governed layer that makes knowledge durable enough to audit, repair, and reuse.

### Versioned capability matrix

This matrix is the load-bearing comparison. Each K-Ops status is backed by
repository evidence (a file, usually `file:line`); comparator statuses are dated
and marked **unverified** where we have not read the comparator's source. Status
vocabulary: **implemented** (observable by running cited code) · **partially
implemented** (some of the capability ships, the rest is designed/planned) ·
**designed** (specified in a design doc, no enforcing code) · **planned** (on the
roadmap, not built) · **experimentally validated** (a measured result exists).
The comparator column reads AtomicStrata's claimed surface unless noted.

K-Ops rows carrying a 2026-07-16 evidence date were re-audited against the code
after the M0–M4 milestones landed; rows still dated 2026-07-15 were not
re-audited. Comparator claims remain **as of 2026-07-15** and are unverified. A
live link to a comparator is not a guarantee its features still match this table.

| Capability | K-Ops status | Comparator status | Evidence date | Repository evidence |
|---|---|---|---|---|
| Deterministic consequence / trust gate at the output boundary | implemented | claimed (AtomicStrata "runtime trust gates"), unverified | 2026-07-15 | `kops/consequence_gate.py:28-91,119-122` |
| Consequence-**tier** serving policy at the answer boundary (`ask`/`render --tier {exploratory\|recommendation\|decision\|autonomous}`) | implemented (freeze a context package → pre-gate its claims by tier → generate → validate the answer→claim map → finalize permit/qualify/abstain/refuse → record a ValidationEvent) | claimed (AtomicStrata "runtime trust gates"), unverified | 2026-07-16 | `kops/output_gate.py:1-27`; `kops/tier_policy.py:1-47` |
| Deterministic, immutable context packages (freeze the exact evidence an answer may cite) | implemented | unknown, unverified | 2026-07-16 | `kops/context_package.py:1-42` |
| Answer→claim map enforcement (every factual sentence rests on an admitted claim id) | implemented | unknown, unverified | 2026-07-16 | `kops/answer_claim_map.py:1-40` |
| Immutable validation-event ledger (git-reviewable append-only audit trail) | implemented | unknown, unverified | 2026-07-16 | `kops/validation_log.py:1-41`; `kops/evidence_store.py:52-95` |
| Canonical evidence objects (Source/SourceVersion/SourceSpan/AtomicClaim/ClaimEvidenceLink/ValidationEvent/ContextPackage/AnswerMemo) | implemented | claimed (atomic-claim model), unverified | 2026-07-16 | `kops/evidence_model.py:131-719`; `kops/evidence_store.py` |
| Atomic-claim enforcement (detect + decompose compound claims) | implemented | claimed (atomic-claim model), unverified | 2026-07-16 | `kops/atomic_claims.py:1-31` |
| Source-independence lineage (corroboration counts independent origins, not derivative copies) | implemented | unknown, unverified | 2026-07-16 | `kops/source_lineage.py:1-45` |
| Typed contradictions (direct-conflict / temporal-supersession / scope-mismatch / terminology-mismatch / …) | implemented | claimed (contradiction handling), unverified | 2026-07-16 | `kops/typed_contradictions.py:1-50` |
| Supervised distillation (merge/split/supersede/rename/archive proposals; never auto-applies) | implemented (proposal-only) | unknown, unverified | 2026-07-16 | `kops/distillation.py:1-45` |
| Quote-span **existence** verification (quote is verbatim in source) | implemented | not claimed / unknown, unverified | 2026-07-15 | `kops/span_verify.py:101-135,299-306` |
| Citation **entailment** (LLM judge: quote *supports* claim) | partially implemented (pure judge ships; **uncalibrated** — 66 labelled pairs vs ≥150 needed, human agreement + real-provider run PENDING — and **non-gating**) | claimed as part of "trust gates", unverified | 2026-07-16 | `kops/entailment_judge.py:360-453` (judge); `kops/judge_calibration.py:1-38`; `research/benchmarks/CALIBRATION.md` |
| Source retraction with blast-radius cascade | implemented | not claimed / unknown, unverified | 2026-07-15 | `kops/retract_source.py:46,112-118,201-215` |
| Per-claim provenance + admission registry | implemented | claimed (atomic-claim model), unverified | 2026-07-15 | `kops/claim_registry.py:136-161,319-324` |
| Contradiction registry | implemented | not claimed / unknown, unverified | 2026-07-15 | `kops/contradiction_registry.py`; `data/contradictions.json` |
| Concept lifecycle stages (`seed/synthesized/verified/contested`) | partially implemented (schema-enforced stages; not full "profiles") | claimed ("lifecycle profiles"), unverified | 2026-07-15 | `kops/schema.yaml:70`; `kops/kb_schema.py:208-220` |
| Content-drift staleness flagging (`revalidation_required`) | implemented | claimed (freshness), unverified | 2026-07-15 | `kops/content_drift.py:1-25` |
| Automatic content-hash invalidation **cascade** (beyond flagging) | implemented (on a source content-hash change: append immutable `SourceVersion`, re-derive claims→contradictions→claims, flag dependents `revalidation_required`, write a stale-set a serving gate reads; flags/audits, never auto-rewrites) | unknown, unverified | 2026-07-16 | `kops/invalidation.py:265-436` |
| Retrieval | partially implemented — lexical only (exact lookup + BM25); no embeddings/rerank in the answer path | claimed ("hybrid" lexical + embedding), unverified | 2026-07-15 | `kops/retrieval.py:1-10,376-404` |
| Evaluation harness + published benchmark report | implemented (one-command metrics harness over four baselines + a golden set; a deterministic, git-committed report — the governance/leakage win is real, answer-quality numbers are labelled PENDING a real provider; not a continuous validated suite) | claimed ("evaluation"), unverified | 2026-07-16 | `kops/eval_metrics.py`; `kops/baselines.py`; `kops/golden_eval.py`; `kops/benchmark_report.py` → `research/benchmarks/REPORT.md` |
| Staged / resumable imports | implemented (resumable research runs; source ingest pipeline) | claimed ("staged imports"), unverified | 2026-07-15 | `kops/research_workflow.py`; `kops/ingest_sources.py` |
| Viewer / UI | planned (not implemented; CLI + Obsidian only) | claimed ("viewer"), unverified | 2026-07-15 | no code; `docs/DESIGN.md` "Implemented vs planned" |
| MCP serving | planned (not implemented) | claimed ("MCP"), unverified | 2026-07-15 | no MCP module in `kops/`; `docs/DESIGN.md` "Planned" list |
| SDK / library API | planned (not implemented; CLI-first) | claimed ("SDK"), unverified | 2026-07-15 | no SDK package in repo; CLI entry `kops/kb.py` |

Two rules govern this table. **(1)** No K-Ops cell may say "implemented" without a
file it can be observed in — if you add a row, cite the code. **(2)** Every
comparator cell is dated and, unless someone has actually read the comparator's
source, marked `unverified`; do not upgrade a comparator claim to a fact from its
marketing copy.

**Link checking.** Run `python3 scripts/check_doc_links.py` to confirm the
Markdown links in `docs/*.md` resolve (internal paths + in-page anchors) and to
list the external links for manual review. The checker deliberately does **not**
fetch external URLs, because a resolving link is not a correct characterization —
a comparator can keep its URL while changing every feature in this table. Green
output means "no broken paths", never "these comparisons are still accurate."

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

The canonical evidence objects on that path now exist —
`kops/evidence_model.py` defines Source, SourceSpan, AtomicClaim,
ClaimEvidenceLink, ValidationEvent, ContextPackage, and AnswerMemo over
append-only stores (`kops/evidence_store.py`), and the serving path already
freezes context packages and records validation events. What is still
directional is full entity/relation graph traversal and, above all, a
*calibrated* entailment judge that would let "who or what validated it?" be
answered by a trusted gate rather than an uncalibrated one. Until then, treat
concept pages as curated working surfaces and the registries as audit surfaces,
not as proof that every claim has been independently verified.

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
- canonical evidence objects (`kops/evidence_model.py`) with append-only stores
  (`kops/evidence_store.py`): Source, SourceVersion, SourceSpan, AtomicClaim,
  ClaimEvidenceLink, ValidationEvent, ContextPackage, AnswerMemo
- atomic-claim enforcement: detect and conservatively decompose compound claims
  (`kops/atomic_claims.py`)
- answer-boundary consequence gating with `--tier {exploratory|recommendation|
  decision|autonomous}` on `ask`/`render`: freeze a deterministic context
  package (`kops/context_package.py`), pre-gate its claims by the tier policy
  (`kops/tier_policy.py`), validate the answer→claim map (`kops/answer_claim_map.py`),
  finalize permit/qualify/abstain/refuse, and record the decision
  (`kops/output_gate.py`)
- immutable, git-reviewable validation-event ledger (`kops/validation_log.py`)
- automatic content-hash invalidation **cascade** on a source content change
  (`kops/invalidation.py`): append a SourceVersion, re-derive
  claims→contradictions→claims, flag dependents, and write a stale-set a serving
  gate reads
- source-independence lineage so corroboration counts genuinely independent
  origins rather than derivative copies (`kops/source_lineage.py`)
- typed contradictions distinguishing material from immaterial conflicts
  (`kops/typed_contradictions.py`)
- supervised distillation that *proposes* merge/split/supersede/rename/archive
  edits and never auto-applies them (`kops/distillation.py`)
- an end-to-end evaluation harness (`kops/eval_metrics.py`, `kops/baselines.py`,
  `kops/golden_eval.py`) and a deterministic published benchmark report
  (`kops/benchmark_report.py` → `research/benchmarks/REPORT.md`)
- an LLM entailment judge (`kops/entailment_judge.py`) that classifies whether a
  span supports an atomic claim — shipped but **uncalibrated** (66 labelled pairs
  vs ≥150 needed; human inter-annotator agreement and a real-provider run PENDING,
  see `kops/judge_calibration.py` + `research/benchmarks/CALIBRATION.md`) and
  deliberately **non-gating** (it does not gate compilation CI, and in the live
  `ask` path it is an injectable input left unset), so it is not yet a trusted gate

Planned, not implemented as a production feature:

- RVF binary capsule export
- MCP serving over a compiled RVF capsule
- persistent SQLite/FTS index
- a viewer / UI (CLI + Obsidian only today)
- embedding / hybrid retrieval and reranking in the answer path
- an SDK / library API (CLI-first today)
- a *calibrated, gating* entailment judge (the judge exists; calibration and
  wiring it in as a trusted decision-tier gate do not)

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

- quote **existence** is verified (the quote is really in the source); quote
  **entailment** (that the quote supports the claim) now has an LLM judge
  (`kops/entailment_judge.py`), but it is **uncalibrated** (66 labelled pairs vs
  the ≥150 the gate rule needs; human inter-annotator agreement and a
  real-provider run are PENDING — see `research/benchmarks/CALIBRATION.md`) and
  deliberately **non-gating**, so entailment is not yet a trusted guarantee
- claims that cite a source but carry no `quote=` anchor are checked for citation
  presence, not for support
- a source content-hash change now triggers an automatic invalidation cascade
  (`kops/invalidation.py`), but that cascade **flags and re-derives**; it never
  auto-rewrites curated prose — a human plus Git still decides what changes
- contradiction records are now typed (`kops/typed_contradictions.py`), but the
  type is a deterministic heuristic over the record's text and participating
  claims, not an adjudicated judgement
- supervised distillation (`kops/distillation.py`) now *proposes* merges,
  splits, supersessions, renames, and archivals, but never applies them, so
  concept pages can still accumulate duplicate or stale claims until a human acts
  on the proposals
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
