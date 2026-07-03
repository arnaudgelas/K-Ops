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
- quote-span verification against raw evidence is not implemented
- LLM-written summaries and concept claims still need human review
- answer memos are validated for provenance shape, not full sentence-level
  entailment

The next correctness step is quote-anchored claim verification: require claims
to carry a source span or short quote and verify that the quote exists in raw
or normalized evidence before promotion.

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

- Add quote-span verification for claims.
- Compare stored content hashes during refresh and mark dependent notes stale.
- Make source review flags blocking in compile workflows.
- Add pre/post agent-run Git checkpoints or branches.
- Add an epistemic audit command that reports unsupported claims, stale claims,
  orphan concepts, duplicate sources, weak high-centrality claims, and
  contradiction backlog as fixable work items.

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
- Record scorecard history as JSONL and report deltas.
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
