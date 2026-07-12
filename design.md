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

Known limit: content hashes are stored, but a complete automatic invalidation
cascade from changed raw content to stale concept claims is not implemented
yet.

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

### Evaluation Surface

Unit tests protect code behavior. They do not measure whether the knowledge
base is epistemically healthy.

The evaluation layer should become a product surface with stable metrics for:

- retrieval recall
- context precision
- citation accuracy
- claim faithfulness
- contradiction surfacing
- stale-source refusal
- coverage of important concepts
- single-source dependency risk
- unsupported answer rate

Deterministic retrieval benchmarks should run in CI. LLM-judged faithfulness
and citation-entailment checks can run as slower audits, but their outputs
should still be stored as versioned evaluation records.

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
  *entails* the claim; entailment still needs an LLM judge
- claims without a `quote=` anchor are still only presence-checked
- LLM-written summaries and concept claims still need human review
- answer memos are validated for provenance shape, not full sentence-level
  entailment

Quote-existence verification is implemented (`kops/span_verify.py`,
`verify-spans`): every claim anchor carrying a `quote=` is checked against the
resolved source text (verbatim, whitespace/punctuation-folded, or across an
ellipsis bridge). A quote absent from its source makes the claim `failed` and
raises an error-severity scorecard signal; `verify-spans --check` exits non-zero.
This is deterministic and fails closed. The next correctness step is
citation *entailment*: an LLM judge that decides whether a verified quote
actually supports the claim, stored as a versioned, lower-trust evaluation record.

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
text). Two known limits: (1) claim re-blocking is complete because it recomputes from
source frontmatter, but concept/answer revalidation-flagging is only as complete as the
graph's `cites_source`/`supported_by` edges; (2) the graph builder's link extractors
(`extract_section_links`, `INLINE_SOURCE_CITE_RE` in `vault_graph.py`) do not yet match
*aliased* wikilinks (`[[Sources/src-x|alias]]`), so evidence citations written in that
form are missed by the blast radius. Fixing the extractors would also improve
community-audit gaps and scorecard orphan metrics. Until then, retract's claim-level
blocking is the reliable backstop.

Contradictions also need typed handling. A generic conflict bucket is too weak.
The taxonomy should distinguish:

- direct contradiction
- temporal supersession
- scope mismatch
- terminology conflict
- interpretation dispute
- evidence-quality conflict
- synthetic contamination

This is especially important when model-generated reports are imported as
leads. Synthetic origin must survive extraction so repeated model output does
not become mistaken for independent corroboration.

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
  verify -> recover. Only `ask` closes it today (the answer provenance gate rejects
  malformed memos). `compile`/`heal` do not yet verify-and-recover: the agent writes
  concept pages and nothing deterministically re-checks that output and bounces
  failures back inside the same invocation. Target: generate -> verify -> repair
  before the write is accepted.
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

What remains is the *inner* loop — making `compile`/`heal` verify-and-recover before a
write is accepted. Only `ask` closes its inner loop today (the answer provenance gate);
`compile`/`heal` still write agent output with no deterministic post-write check. Its full
form (re-invoke the agent to repair) needs a live agent CLI, so it is validated differently
from the deterministic work above.

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
- Compare stored content hashes during refresh and mark dependent notes stale.
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
  `extract-contradictions`/`verify-spans`/`next-action` `--check`). Remaining loop work:
  close the *inner* loop (`compile`/`heal` verify-and-recover before a write is accepted).
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

- Define thresholds for exploratory, recommendation, decision, and autonomous
  action use.
- Prevent low-tier or quarantined claims from supporting high-consequence
  outputs.
- Require context-package manifests for important answers, including included
  claims, excluded claims, gaps, stale flags, contradictions, and source
  manifests.

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
