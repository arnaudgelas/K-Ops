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

The next correctness step is quote-anchored claim verification: require claims
to carry a source span or short quote and verify that the quote exists in raw
or normalized evidence before promotion.

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

## Near-Term Roadmap

### P0: Trust and Safety

- Add quote-span verification for claims.
- Compare stored content hashes during refresh and mark dependent notes stale.
- Make source review flags blocking in compile workflows.
- Add pre/post agent-run Git checkpoints or branches.

### P1: Daily Collection

- Turn `data/fetch_queue.json` into a real queue, not only a blocked-source
  report.
- Add RSS/bookmark import adapters.
- Connect unanswered questions and missing topics to source suggestions.

### P2: Knowledge Maintenance

- Add supervised `distill` for concept pages.
- Add `rename-concept` and `merge-concepts` with link rewrites and redirect
  stubs.
- Add claim-level deduplication and multi-source claim merging.

### P3: Scale

- Persist retrieval indexes instead of rebuilding them per query.
- Consider SQLite + FTS5 behind the current retrieval API.
- Record scorecard history as JSONL and report deltas.

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
