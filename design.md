# K-Ops Design Notes

## Purpose

K-Ops is a local, file-native research intelligence system. Its job is to turn
raw sources into a curated Markdown vault that humans can inspect and agents
can reuse without losing provenance.

The design goal is not "ask an LLM over a folder." The design goal is a
governed loop:

```text
capture -> normalize -> compile -> audit -> ask -> render -> repair
```

Python owns deterministic bookkeeping. Agents own interpretation and prose.
The two layers must exchange structured context instead of asking agents to
rediscover machine-computable facts by hand.

## Current Architecture

```text
data/raw/                 immutable-ish fetched evidence
data/registry.json        source inventory and ingest metadata
notes/Sources/            human-readable source summaries
notes/Concepts/           durable concept pages
notes/Answers/            answer memos with provenance
data/claims.json          derived claim registry
data/contradictions.json  derived contradiction registry
data/scorecard.json       derived quality/audit surface
```

The curated vault remains Markdown-first so it can be opened directly in
Obsidian and reviewed with normal Git tooling. Machine-readable JSON files are
derived audit surfaces unless explicitly documented otherwise.

## Target Canonical Model

The long-term design should not make the Obsidian vault the silent source of
truth. Markdown should be the human-readable projection of a governed claim
model.

Target object chain:

```text
Source
SourceSpan
Claim
Entity
Relation
Contradiction
ValidationEvent
ContextPackage
AnswerMemo
```

Minimum production-grade claim fields:

- stable claim ID
- normalized statement
- claim type
- source span or quote anchor
- acquisition mode
- provenance chain
- epistemic tier
- governance regime
- scope
- valid time
- system time
- contradiction status
- decay class
- dependency edges
- validation events

The current extracted claim registry is a useful audit surface, but it is not
yet this canonical model. The design should evolve toward evented claim state:
created, promoted, demoted, contradicted, superseded, merged, deprecated,
validated, and retired.

## OKF Interop Position

OKF v0.1 is a deliberately small interchange format. Its useful core is:

- a bundle is a directory tree of Markdown files
- concept documents carry YAML frontmatter
- `type` is the only required concept frontmatter field
- `index.md` and `log.md` are reserved filenames
- generated `index.md` files support progressive disclosure
- standard Markdown links express cross-concept relationships
- consumers tolerate unknown fields, missing optional fields, and broken links

That is the right portability layer for K-Ops, because it keeps the vault
readable by humans, Git, Obsidian, static renderers, and agents without custom
SDKs.

The pushback is equally important: OKF is intentionally not a governed
intelligence schema. It does not define claim objects, source spans,
validation events, contradiction states, decay policies, access controls,
evaluation metrics, or action thresholds. Those have to remain K-Ops
extensions or move into a stricter canonical claim graph.

Design rule:

- generated traversal files should stay close to OKF and avoid K-Ops-only
  syntax where portability matters
- curated K-Ops notes may carry richer frontmatter and sections as
  producer-defined extensions
- consumers must preserve unknown K-Ops fields when round-tripping
- OKF conformance must not be treated as evidence validation

## Implemented Control Points

### Source Intake

Source intake supports URLs, PDFs, local files, note files, and GitHub
repositories.

- `kb.py add <source>` captures one source directly.
- `kb.py ingest --input <file>` captures a batch.
- GitHub repository URLs route to repository snapshot ingestion.
- Raw artifacts, normalized text, metadata, and content hashes are written
  under `data/raw/<source-id>/`.

Content-hash drift is now detected (`check-content-drift`, `kops/content_drift.py`): it
compares the `content_hash` baseline recorded on a source note against the current raw
hash under `data/raw/<id>/metadata.json` and, with `--flag`, marks the source note and
every derived page `revalidation_required` (the content-hash analog of the git-commit
`check-drift`). Seed baselines with `backfill-content-hash`; re-baseline after re-curating
with `backfill-content-hash --force`. Like `check-drift` it only *flags* — it never
rewrites prose, and it is opt-in (not auto-run on refresh), so a stale baseline does not
produce persistent false positives.

### Compile Planning

Before a compile prompt is rendered, Python writes `.tmp/compile_plan.json`.
The plan contains:

- `to_summarize`: registry IDs without source notes
- `skip`: registry IDs that already have source notes
- `flag_for_review`: sources with blocking review hints such as prompt
  injection flags or revoked source status

This removes a previous failure mode where the prompt referred to a plan file
that no code produced.

### Retrieval-Seeded Q&A

`ask` now builds a local retrieval context before handing off to the selected
agent. It uses the existing `VaultIndex` exact/BM25 index over:

- source summaries
- concept pages
- claims
- large-source sections when manifests exist

The prompt receives result IDs, kinds, scores, paths, snippets, and a suggested
`retrieval_path` entry. The agent still has to open evidence before making
substantive claims.

### Answer Provenance Gate

After an agent writes an answer memo, the runtime validates answer frontmatter
with `kb_schema.Validator`.

The runtime rejects answers that:

- leave the scaffold placeholder in place
- fail answer memo schema validation
- leave `retrieval_path` empty
- omit `fetch_required`

This turns answer provenance from prompt prose into a runtime contract.

### Claim Admission

`extract-claims` derives claim records from concept-page `## Key Claims`
bullets. Claim records now carry source admission metadata:

- `admission_status`
- `admission_reasons`
- `synthetic_origin`

This lets weak, synthetic, deprecated, revoked, missing, or adversarial sources
surface in `data/claims.json` and `data/scorecard.json`, not only in lint
messages.

### Governance Surfaces

Four deterministic commands turn scattered signals into acted-upon governance:

- `verify-spans` (`kops/span_verify.py`) — checks that each claim's `quote=`
  anchor exists in its source; fails closed. See Trust Model below.
- `community-audit` (`kops/graph_community.py`) — clusters the concept graph
  (deterministic greedy-modularity), reports high-betweenness bridge nodes, fragile
  single-connector clusters, and cross-cluster knowledge gaps.
- `review-queue` (`kops/review_queue.py`) — aggregates everything needing human
  judgment (failed spans, blocked/quarantined/unsupported claims, undocumented
  contradictions, sources needing verification, unreviewed probes, gaps) into one
  prioritised, read-only worklist.
- `retract` (`kops/retract_source.py`) — revokes a source and unwinds its blast
  radius. See Staleness and Contradictions below.

### Canonical Evidence Objects

The governed claim model (see Target Canonical Model) now has a concrete,
typed representation. `kops/evidence_model.py` defines the canonical, versioned
evidence objects (Source, SourceVersion, SourceSpan, AtomicClaim,
ClaimEvidenceLink, ValidationEvent, ContextPackage, AnswerMemo) as typed views
over the existing registries plus a few greenfield objects, each stamped with a
schema version and content-addressable hashes. `kops/evidence_store.py`
persists them: SourceVersion and ValidationEvent as append-only JSONL, and
ContextPackage as content-addressed JSON. `kops/atomic_claims.py` enforces the
one-proposition-per-claim rule with deterministic heuristics — a prerequisite
for entailment judging — and conservatively flags compound claims for review
rather than silently splitting them.

### Consequence-Gated Answer Serving

The output boundary is now governed, not only advisory. `kops/output_gate.py`
composes the serving path the roadmap prescribes: it builds and freezes an
immutable, content-addressed context package (`kops/context_package.py`) of the
exact evidence an answer may rely on; pre-gates the admitted claims with the
consequence-tier policy (`kops/tier_policy.py`), which layers freshness,
material contradictions, and (for autonomous) independent corroboration on top
of the deterministic admission gate in `kops/consequence_gate.py`; generates the
answer through an injected generator; validates the answer-claim map
(`kops/answer_claim_map.py`) so every factual sentence rests on an admitted
claim id and nothing excluded or uncited is smuggled in; finalizes a
`permit | qualify | abstain | refuse` decision; and records an immutable
validation event. `ask` and `render` take `--tier`, so an answer or render is
governed by its declared consequence tier at the output boundary rather than
only by the standalone `consequence-gate` command.

### Automatic Source-Change Invalidation

Source-change staleness now propagates as a deterministic cascade, not just a
manual flag. `kops/invalidation.py` composes content-drift detection, the
dependency-graph walk, the immutable evidence store, and the claim/contradiction
registries: on a detected content-hash change it appends a new immutable
`SourceVersion`, marks the affected validations stale by appending a
`ValidationEvent` per dependent claim/answer/context package, re-derives the
claim registry then the contradiction registry then the claim registry again
(fixed point — closing the gap `retract` leaves), flags dependent
concepts/answers/the source note `revalidation_required`, and writes a
deterministic stale-set to `data/invalidation_queue.json` that a serving gate
reads to refuse stale evidence as current at the decision or autonomous tier.
Like `retract`, it flags, re-derives, and audits only — it never rewrites
curated prose and never deletes.

### Immutable Validation-Event Ledger

Every governance decision — an entailment verdict, a consequence-gate ruling, a
source invalidation, a human review — leaves a durable, tamper-evident record.
`kops/validation_log.py` is the canonical record/read layer over the M1
primitives: `ValidationEvent` records are appended to
`data/history/validation_events.jsonl` via `kops/evidence_store.py` (append-only,
and deliberately git-tracked so every appended decision shows up in a reviewable
diff). It adds a small validated vocabulary of validator names and their allowed
results, and a `serving_audit` API that reconstructs the full decision record
behind one served answer. Git commit history remains the tamper backstop.

### Source-Independence Corroboration

Corroboration now counts genuinely independent origins, not derivative copies.
`kops/source_lineage.py` resolves declared source lineage — `derived_from`
chains, declared `tier`/`publisher`, and synthetic markers — and collapses
derivative copies so two blogs quoting one vendor benchmark, or an AI summary
paired with its source, count as a single witness. It relies only on declared
provenance; it deliberately does not attempt to detect undeclared AI text or
infer hidden shared sources. The autonomous tier consults this so manufactured
corroboration cannot clear the bar.

### Typed Contradictions

Contradictions are now typed and carry materiality, not a single generic
conflict bucket. `kops/typed_contradictions.py` classifies each contradiction
record deterministically from its `open_question` text plus its participating
claims and sources into one of the taxonomy types (see Staleness and
Contradictions), stamps it with governance fields, and exposes
`material_contradiction_ids` — the claim ids in an unresolved *material*
contradiction — which the tier policy consults so an immaterial terminology
mismatch does not gate a decision while a material direct conflict does.

### Supervised Distillation (Proposal-Only)

`kops/distillation.py` looks at the claim graph as a whole and proposes where it
could be distilled: merging near-duplicate claims whose scope/time/evidence
match, superseding when they diverge in time only, splitting compound claims,
and flagging divergent near-duplicates for review. Following the `review_queue`
/ `retract_source` idiom it is a pure, read-only detector: it writes
`data/distillation_proposals.json` and surfaces worklist items but never merges,
splits, renames, or deletes any claim or concept prose. A human plus Git decides
what actually changes.

### Entailment Judge (Advisory, Uncalibrated)

`kops/entailment_judge.py` is a pure classifier that judges whether an exact
evidence span *supports* an atomic claim, returning a structured verdict
(`supported | partial | unsupported | contradicted | not_evaluable`) with
rationale, content-addressed and cached. It is deliberately **non-gating**: it
produces verdicts for evaluation and calibration only and is not wired into any
compile/heal gate. `kops/judge_calibration.py` answers the separate question of
whether the judge is trustworthy enough to gate decision-tier outputs; its
false-support rate and human inter-annotator agreement are **PENDING** real
annotators and a real provider run, so the judge stays advisory until calibrated
(see Trust Model).

### Evaluation Surface

Unit tests protect code behavior. They do not measure whether the knowledge
base is epistemically healthy.

The evaluation layer is now a product surface. `kops/eval_metrics.py`
(`kops benchmark`) runs the baselines over the benchmark corpus, grades answers
against the golden set, links each answer to a versioned context package, and
reports four metric families — retrieval, answer quality, governance, and
operations — covering:

- retrieval recall
- context precision
- citation accuracy
- claim faithfulness
- contradiction surfacing
- stale-source refusal
- coverage of important concepts
- single-source dependency risk
- unsupported answer rate

`kops/benchmark_report.py` (`benchmark-report`) publishes a stable, committed
`research/benchmarks/REPORT.md`. The honesty contract is explicit in both: the
retrieval and governance numbers are REAL and deterministic (a property of which
sources reach each baseline's context, computed with no LLM); the answer-quality
numbers are labelled PENDING a real-provider run; and citation-entailment runs
the (uncalibrated) J1.1 judge only when a judge is configured, otherwise
reported PENDING and never fabricated. Deterministic retrieval/governance
benchmarks run in CI; LLM-judged faithfulness and citation-entailment stay
slower, advisory audits stored as versioned evaluation records.

### Atomic State Writes

Shared utility writes use temp files plus `os.replace()` for JSON and text
state written through `save_json()` and `write_text()`. This reduces the risk
of corrupting registry and derived state during crashes or interrupted runs.

### CI and Test Discovery

CI runs pytest rather than `unittest discover`, and useful regression scripts
have been moved under `tests/`. Ruff style and format checks run in CI.

## Trust Model

K-Ops makes source use auditable. It does not prove that every LLM-written
claim is entailed by its citation.

Current checks are strong for structure:

- required frontmatter
- schema-conformant answer memos
- direct citation coverage thresholds
- revoked/model-generated/adversarial source gates
- contradiction registry extraction
- stale/revalidation flags when present

Current checks are weaker for truth:

- citation presence is not the same as citation support
- quote-span verification checks a quote *exists* in the source, not that it
  *entails* the claim; an entailment judge is now implemented but remains
  uncalibrated and non-gating, so quote *support* is still not guaranteed
- claims without a `quote=` anchor are still only presence-checked
- LLM-written summaries and concept claims still need human review
- answer memos are validated for provenance shape, not full sentence-level
  entailment

Quote-existence verification is implemented (`kops/span_verify.py`,
`verify-spans`): every claim anchor carrying a `quote=` is checked against the
resolved source text (verbatim, whitespace/punctuation-folded, or across an
ellipsis bridge). A quote absent from its source makes the claim `failed` and
raises an error-severity scorecard signal; `verify-spans --check` exits non-zero.
This is deterministic and fails closed.

Citation *entailment* — whether a verified quote actually *supports* the claim —
is the next correctness layer and is now **implemented but uncalibrated and
non-gating**. `kops/entailment_judge.py` produces a structured
`supported | partial | unsupported | contradicted | not_evaluable` verdict per
(atomic claim, span) pair, content-addressed and cached, stored as a versioned,
lower-trust evaluation record. It is deliberately not wired into any compile,
heal, or serving gate: `kops/judge_calibration.py` still reports its
false-support rate and human inter-annotator agreement as PENDING, so the judge
is an advisory audit layer, not a deterministic gate and not a guarantee of
support or truth. Quote *existence* stays deterministic; quote *support* stays
advisory until the judge is calibrated.

## Staleness and Contradictions

Staleness is source-specific:

- a GitHub repository changes by commit
- a regulation changes by amendment
- a paper changes by version
- a blog post or vendor doc may change silently
- a benchmark result can expire when models, datasets, or tooling change

The desired behavior is not only "mark source stale." It is dependency impact:
which source summaries, claims, concepts, answer memos, and rendered outputs
depend on the changed source?

The `retract` command implements this for the revocation case: it revokes a source,
computes the blast radius over the vault graph, flags dependent concepts/answers for
revalidation, and re-blocks dependent claims (flagging only — it never rewrites claim
text). Claim re-blocking is complete because it recomputes from source frontmatter;
concept/answer revalidation-flagging is as complete as the graph's `cites_source`/
`supported_by` edges. The graph builder's link extractors (`extract_section_links`,
`INLINE_SOURCE_CITE_RE`, `SOURCE_LINK_RE` in `vault_graph.py`) now match *aliased*
wikilinks (`[[Sources/src-x|alias]]`) as well as bare and sub-foldered forms, so evidence
citations written in the vault's aliased convention are captured — improving retract's
blast radius, community-audit gaps, and scorecard orphan metrics alike.

The content-change case is now implemented as an automatic cascade rather than a
manual flag. `kops/invalidation.py` (run `python -m kops.invalidation`) composes
content-drift detection, the retract blast-radius walk, the immutable evidence
store, and the registries: on a detected content-hash change it appends a new
immutable `SourceVersion`, appends a `ValidationEvent` per dependent
claim/answer/context package, re-derives the claim registry then the
contradiction registry then the claim registry again (fixed point), flags
dependents `revalidation_required`, and writes `data/invalidation_queue.json` so
a serving gate refuses stale evidence as current at the decision or autonomous
tier. Like `retract` it flags, re-derives, and audits only; it never rewrites
prose. See Implemented Control Points.

Contradictions now get typed handling; a generic conflict bucket is too weak.
`kops/typed_contradictions.py` classifies each contradiction record
deterministically into the taxonomy:

- direct contradiction
- temporal supersession
- scope mismatch
- terminology conflict
- interpretation dispute
- evidence-quality conflict
- synthetic contamination

Each record also carries a materiality assessment, and
`material_contradiction_ids` exposes the claim ids in an unresolved *material*
contradiction so the tier policy can force *qualify*/*abstain* on those while an
immaterial terminology mismatch does not gate a decision.

This is especially important when model-generated reports are imported as
leads. Synthetic origin must survive extraction so repeated model output does
not become mistaken for independent corroboration — which `kops/source_lineage.py`
now enforces by counting only declared-independent origins (see Implemented
Control Points).

## Security Model

Raw web pages, PDFs, and repositories are untrusted input. Ingestion detects
some prompt-injection patterns and compile plans can flag suspect sources for
review. That is not a full sandbox.

Current risk:

- agent CLIs may run with broad local permissions
- raw content can contain instructions aimed at the agent
- detection is advisory unless a workflow treats `flag_for_review` as blocking

Desired direction:

- command-specific permission profiles
- no full-auto execution for ingestion-adjacent compile/ask paths
- blocked compile for flagged sources until human review
- separate raw-evidence read scope from curated-vault write scope

## Loop Engineering

K-Ops is described here as a "governed loop," but it is currently an *open* loop: a
human runs each command, reads the output, and decides the next step. It has sensors
(scorecard, review-queue, span verification) and actuators (compile, heal, retract)
but no controller, no feedback comparison, and no convergence criteria. Closing that
gap is loop engineering: designing the system that runs the cycle — observe, act,
verify, recover — with an explicit goal and stopping condition, instead of prompting
each step by hand.

The engineering progression is prompt -> context -> harness -> loop. K-Ops has done
the first three: prompt templates; context engineering (retrieval-seeded `ask`,
`compile_plan.json`); harness engineering (deterministic Python bookkeeping, the
agent hand-off, the answer provenance gate). The loop layer is the least engineered
and is the current frontier.

### Two loops, engineered differently

- **Inner loop** — one agent invocation (`compile`, `ask`, `heal`): observe -> act ->
  verify -> recover. `ask` closes it via the answer provenance gate. `compile`/`heal` now
  close the **verify** half (`kops/inner_loop.py`): they snapshot the deterministic signal
  vector before the agent runs, rebuild the registries the write invalidated, and report
  loudly if the write regressed the vector (a new failed span / blocked claim, or a
  vanished artifact). The **recover** half — re-invoking the agent to repair — is
  deliberately deferred: it needs a live agent and stays human-gated; a regression is
  surfaced for a human or a follow-up pass to fix or revert.
- **Outer loop** — the vault lifecycle across invocations: sense (scorecard /
  review-queue / span verification) -> prioritise -> act -> re-sense. This is fully
  open. No measured feedback shows whether the vault is converging toward health or
  drifting.

### Constraints unique to a governance system

Loop engineering usually optimises for autonomy. Here it must not. Four hard rules,
in tension with "let the loop run":

1. **Human-gated actuation.** The loop proposes; a human plus Git approves. Design
   principle 7 and the security model (no full-auto compile/ask) forbid an autonomous
   repair loop over a knowledge base. Loop engineering here means an *instrumented,
   proposal-generating* loop, not an autonomous one.
2. **Only non-gameable signals may close the loop.** A loop driven by a soft metric
   gets gamed: told to cut "unsupported claims," an agent downgrades or deletes
   claims; told to raise citation coverage, it adds citations it never read (the
   documented tool-call-hacking failure mode). K-Ops is unusually well-placed here —
   its deterministic checks (quote existence via `verify-spans`, claim admission,
   lint, contradiction extraction) are hard to game and are the trustworthy control
   signals. LLM-judged metrics (faithfulness, citation *entailment*) stay strictly
   **advisory** and must never gate the loop.
3. **Regression detection across the full signal vector.** A repair that fixes one
   signal can break another (resolving a contradiction edits a claim and breaks its
   quote span). Each iteration must compare the whole deterministic signal vector
   before and after and reject a net-negative step. Without this, the loop thrashes.
4. **Explicit convergence / stop criteria.** No new error-severity items; signal delta
   below a threshold; a token/iteration budget. An open-ended loop over a vault
   over-edits, and over-editing curated knowledge is destructive, not neutral.

### What is missing (and the order that matters)

The commands `verify-spans`, `review-queue`, `community-audit`, and `retract` are the
loop's **sensors and actuators**. Progress on closing the feedback:

1. **Measurement over time — done.** `signal-log` records a deterministic 6-signal
   vector to `data/history/signals.jsonl` each run and reports deltas, so convergence,
   regression, and steady-state error are now visible across iterations. Signals are
   plain counts off committed artifacts; a deleted artifact is itself flagged (present
   -> absent is a hard regression), so the control signal cannot be gamed by deletion.
2. **A regression gate — done.** `signal-log --check` fails closed when an error-class
   signal rises or a required artifact disappears. `maintenance` records a datapoint
   and warns on regression without hard-exiting; the fail-closed gate is the standalone
   `--check` (for CI).
3. **A controller — done.** `next-action` maps the current deterministic signals to the
   single highest-leverage next repair (the top-severity `review-queue` item, with a
   concrete command hint) and a convergence verdict. It recommends; it never acts.
4. **Documented stop criteria — done.** `next-action` emits one of three states, from
   deterministic signals only:
   - `blocking` — an error-severity review item, an error-class signal (`failed_quote_spans`
     / `blocked_claims`) > 0, or a missing derived artifact. The loop MUST continue.
   - `cleanup` — no blocking condition, but warning/info items remain. Safe to stop the
     mandatory loop ("converged enough"); optional cleanup is left.
   - `converged` — nothing open. Stop.
   The mandatory loop stops when the verdict is not `blocking`; an agent-run loop should
   also stop on its own token/iteration budget (the runner's concern, not the vault's).

The loop is now measurable, gated, and controlled: K-Ops can tell whether an iteration
helped (`signal-log`), refuse a regression (`signal-log --check`), name the next move, and
decide when to stop (`next-action`).

CI enforces the deterministic gates: `extract-claims --check` and
`extract-contradictions --check` (registries in sync), `verify-spans --check` (no
fabricated quotes), and `next-action --check` (fail on any blocking state). Note the two
gate kinds differ by statefulness: `next-action --check` is an **absolute** gate (blocking
state now → fail) and is stateless, so it is the right CI gate; `signal-log --check` is a
**regression** gate that needs a persisted baseline, so it belongs to the local/persisted
cadence, not stateless CI. The outer loop is done.

The *inner* loop is now closed on its **verify** half too: `compile`/`heal` run a
deterministic post-write check (`kops/inner_loop.py`) that rebuilds derived state and flags
a regressing agent write. What remains is the **recover** half — automatically re-invoking
the agent to repair a flagged write — which needs a live agent CLI and stays human-gated;
today the regression is reported for a human or a follow-up pass to act on. With that, the
loop is measured, gated, controlled, CI-enforced, and inner-verified; only agent-driven
auto-repair is left, and it is intentionally not automated.

## Design Principles

1. Keep raw evidence recoverable.
2. Treat Markdown as the human interface, not a magic truth layer.
3. Prefer deterministic Python for indexing, validation, and planning.
4. Use agents for bounded synthesis tasks with explicit inputs.
5. Fail loudly when provenance fields are missing.
6. Keep generated audit artifacts reproducible.
7. Preserve Git review as the final safety rail.
8. Gate high-consequence answers behind stronger evidence thresholds.

## Near-Term Roadmap

### P0: Trust and Safety

- ~~Add quote-span verification for claims.~~ **Done** — deterministic quote
  *existence* verification (`verify-spans`). Remaining: LLM-judged citation
  *entailment* over verified quotes.
- ~~Compare stored content hashes during refresh and mark dependent notes stale.~~
  **Done** — `check-content-drift` compares a source note's `content_hash` baseline
  against the current raw hash and flags the note + derived pages; `backfill-content-hash`
  seeds/re-baselines. Opt-in (not auto-run on refresh) to avoid stale-baseline false
  positives. Remaining: an optional auto-run hook and baseline-on-compile.
- Make source review flags blocking in compile workflows.
- Add pre/post agent-run Git checkpoints or branches.
- **Loop enablement (see Loop Engineering).** ~~Append each run's deterministic signal
  summary to `data/history/*.jsonl` and report deltas; add a regression gate.~~
  **Done** — `signal-log` records a deterministic 6-signal vector to
  `data/history/signals.jsonl` (gitignored, append-only), reports deltas, and
  `signal-log --check` fails closed on a hard regression (an error-class signal rising,
  or a derived artifact disappearing — the anti-gaming guard). `maintenance` records a
  datapoint each run and warns (does not hard-exit) on regression. The *controller*
  (`next-action`, recommend the single next repair + convergence verdict) and *stop
  criteria* are done. CI now enforces the deterministic gates (`extract-claims`/
  `extract-contradictions`/`verify-spans`/`next-action` `--check`). The *inner* loop's
  **verify** half is done too (`compile`/`heal` run a deterministic post-write regression
  check via `kops/inner_loop.py`). Remaining: the **recover** half (auto agent re-invoke),
  intentionally deferred as it needs a live agent and stays human-gated.
- ~~Add an epistemic audit command that reports unsupported claims, stale claims,
  orphan concepts, duplicate sources, weak high-centrality claims, and
  contradiction backlog as fixable work items.~~ **Largely done** — `review-queue`
  reports unsupported/blocked/quarantined claims, undocumented contradictions, and
  flagged sources; `community-audit` reports weak high-centrality (bridge) nodes,
  fragile clusters, and knowledge gaps. Remaining: duplicate-source detection and a
  single combined report.

### P1: Daily Collection

- Turn `data/fetch_queue.json` into a real queue, not only a blocked-source
  report.
- Add RSS/bookmark import adapters.
- Connect unanswered questions and missing topics to source suggestions.
- Add source-specific freshness policies for GitHub, papers, regulations,
  official docs, vendor docs, and benchmarks.

### P2: Knowledge Maintenance

- Add supervised `distill` for concept pages.
- Add `rename-concept` and `merge-concepts` with link rewrites and redirect
  stubs.
- Add claim-level deduplication and multi-source claim merging.
- Add validation commands for promote, demote, challenge, merge, supersede, and
  retire.

### P3: Scale

- Persist retrieval indexes instead of rebuilding them per query.
- Consider SQLite + FTS5 behind the current retrieval API.
- Record scorecard history as JSONL and report deltas. (Note: this is the closed-loop
  measurement prerequisite from Loop Engineering; treat as P0, not P3.)
- Add hybrid retrieval: exact lookup, BM25, embeddings, graph traversal,
  reranking, and query routing.

### P4: Consequence Gating

- ~~Define thresholds for exploratory, recommendation, decision, and autonomous
  action use. Prevent low-tier or quarantined claims from supporting high-consequence
  outputs.~~ **Done (deterministic core)** — `consequence-gate --tier` checks a set of
  claims against an escalating evidence bar (`kops/consequence_gate.py`): recommendation
  bars blocked sources; decision additionally bars quarantined/unknown/unsupported/weak/
  conflicting/stale/synthetic; autonomous requires admitted + direct + supported.
  `--check` fails closed. The gate is now wired into the output boundary:
  `kops/output_gate.py` pre-gates a frozen context package's admitted claims,
  validates the answer-claim map, and finalizes `permit | qualify | abstain |
  refuse`; `ask`/`render` take `--tier` so answers/renders carry a per-output
  tier declaration. Remaining: entailment-aware gating at decision tier depends
  on judge calibration (still PENDING).
- ~~Require context-package manifests for important answers, including included
  claims, excluded claims, gaps, stale flags, contradictions, and source
  manifests.~~ **Done** — `kops/context_package.py` freezes an immutable,
  content-addressed context package recording admitted claim ids, excluded
  claims with reasons, per-source freshness/stale flags, source version ids, and
  the retrieval trace; persisted via `kops/evidence_store.py`.

## RVF and MCP Status

RVF export and MCP serving remain architectural directions, not implemented
production features in this repo today.

If added, they should compile from the same governed source of truth:

- raw/source metadata
- curated Markdown notes
- claims and contradictions
- vault graph edges
- scorecard and validation metadata

They should not become a second canonical store.
