# Hyper-Extract Integration Plan

Status: **Proposal / not started**
Owner: Arnaud Gelas
Last updated: 2026-07-04
Related: [design.md](design.md), `scripts/claim_registry.py`, `scripts/contradiction_registry.py`, `scripts/vault_graph.py`, `research/evals/`

---

## 1. Objective

Evaluate and (conditionally) integrate [Hyper-Extract](https://github.com/yifanfeng97/hyper-extract) as an **optional, out-of-process, quarantined extraction backend** for K-Ops — used **only** for the capabilities K-Ops cannot trivially replicate: **n-ary (hyperedge) claims** and **temporal/spatio-temporal claims**.

It must **not** become K-Ops's knowledge layer, dependency core, retrieval layer, or vault schema. Every extracted node/edge enters as an **unverified candidate** and must earn admission through K-Ops's existing governance (source-span grounding, claim registry, contradiction registry).

## 2. Guiding constraints (non-negotiable)

- **C1 — Trust boundary.** Extractor output is untrusted "model-generated leads." It lands in staging, never directly in `notes/Concepts/`.
- **C2 — Process isolation.** Hyper-Extract runs as an external CLI in its **own** virtualenv. K-Ops exchanges JSON files with it and gains **zero** transitive dependencies (no LangChain/FAISS/embedding deps in K-Ops's tree).
- **C3 — Scope discipline.** Use Hyper-Extract only for hyperedges + temporal graphs. Flat entities/binary relations are built natively.
- **C4 — Grounding gate.** No candidate is promoted without a defensible source span in `normalized.md`. Ungroundable candidates stay quarantined.
- **C5 — Falsify before building.** The span-groundability probe (Phase 0) can kill the entire effort before any adapter code is written.

## 3. Kill criteria (stop the project if any trip)

- **K1.** On the Phase 0 probe, a large fraction of abstractive edges cannot be span-grounded without adding another LLM in the loop → the integration is just "one unverified LLM layer swapped for another." **Stop.**
- **K2.** Phase 1 pilot shows hyperedge/temporal extraction quality (precision) below the native DIY baseline from Phase 2. **Stop** — build native only.
- **K3.** Process isolation (C2) proves impractical and the only path is importing the dependency tree. **Stop** — reassess.

---

## 4. Phased task list

Priority: **P0** = do first / gating · **P1** = core · **P2** = valuable · **P3** = hardening/nice-to-have.

### Phase 0 — Falsification probe (P0, gating)

Cheapest possible test of the riskiest assumption. **No adapter code.** Manual/scripted only.

| ID | Task | Priority | Depends on | Acceptance criteria |
|----|------|----------|-----------|---------------------|
| T0.1 | Select 3 **already-curated** sources from `notes/Sources/` (so curated concept pages are the reference oracle). Prefer variety: one paper, one repo/tech doc, one policy/regulatory-style doc. | P0 | — | 3 source IDs chosen; each has an existing concept page + `normalized.md`. |
| T0.2 | Install Hyper-Extract in an **isolated** venv (`.venv-hyperextract/` or a separate dir). Confirm it runs and never touches K-Ops's `.venv`. | P0 | — | `he --version` runs from isolated env; K-Ops `uv.lock` unchanged. |
| T0.3 | Manually run `he parse` on the 3 sources with a hypergraph template and a temporal template. Capture raw JSON output. | P0 | T0.1, T0.2 | Raw extraction JSON saved for each source × template. |
| T0.4 | **Span-groundability probe.** For each extracted hyperedge/temporal edge, attempt to locate a supporting span in `normalized.md` by (a) exact/substring match, then (b) manual human check. Record: groundable-exact / groundable-by-human / ungroundable. | P0 | T0.3 | A table of groundability rates per source; explicit % ungroundable. |
| T0.5 | **Go/No-Go decision.** Evaluate against K1. Write a one-page verdict. | P0 | T0.4 | Documented decision: proceed / stop / narrow scope. |

> **Gate:** Phases 1+ do not start until T0.5 = proceed.

### Phase 1 — Pilot & measurement (P0)

Broaden the probe into a measured pilot with an oracle.

| ID | Task | Priority | Depends on | Acceptance criteria |
|----|------|----------|-----------|---------------------|
| T1.1 | Expand to ~10 representative sources, mixing **already-curated** (oracle available) and fresh. | P0 | T0.5 | 10 sources selected and normalized. |
| T1.2 | Run 2–3 Hyper-Extract templates per source; capture raw JSON + runtime + token cost. | P0 | T1.1 | Raw outputs + cost/runtime log per run. |
| T1.3 | Against curated sources, measure: (a) edges matching curated knowledge (recall signal), (b) edges **contradicting** curated knowledge (contradiction-surfacing value), (c) ungroundable/hallucinated edges (kill metric). | P0 | T1.2 | Scored spreadsheet with the three counts per source. |
| T1.4 | Assess dedup/duplicate-entity rate and hyperedge/temporal usefulness qualitatively. | P1 | T1.2 | Short written assessment. |
| T1.5 | **Pilot verdict** against K1/K2. Decide final scope (hyperedge-only, temporal-only, both, or stop). | P0 | T1.3, T1.4 | Documented scope decision feeding Phase 3. |

### Phase 2 — Native typed extraction (P1, parallelizable)

Build the cheap capability in-house; **no Hyper-Extract dependency**. Can proceed in parallel with Phase 0/1 because it is independent.

| ID | Task | Priority | Depends on | Acceptance criteria |
|----|------|----------|-----------|---------------------|
| T2.1 | Define Pydantic schemas for `EntityCandidate` and `RelationCandidate` (binary). | P1 | — | Schemas in `scripts/` with tests. |
| T2.2 | Implement a native typed-extraction pass using K-Ops's existing provider layer + structured-output mode. ~100 LOC target. | P1 | T2.1 | `scripts/kb.py extract-structure --backend native` emits entity/relation candidates. |
| T2.3 | Establish this native output as the **baseline** for K2 comparison. | P1 | T2.2, T1.3 | Baseline precision/recall recorded in eval set. |

### Phase 3 — Out-of-process Hyper-Extract oracle (P1)

Only build if Phase 1 verdict = proceed. Scope limited by C3.

| ID | Task | Priority | Depends on | Acceptance criteria |
|----|------|----------|-----------|---------------------|
| T3.1 | Wrap the isolated Hyper-Extract CLI behind a subprocess call that writes to `data/extractions/hyperextract/<source-id>/raw.json`. No in-process import. | P1 | T1.5 | Subprocess invocation from K-Ops; JSON files produced; K-Ops deps unchanged. |
| T3.2 | Restrict invocation to hyperedge + temporal templates only. | P1 | T3.1 | CLI rejects/omits flat-entity-only templates by config. |
| T3.3 | Add `scripts/kb.py extract-structure --backend hyperextract --template ...` dispatching to T3.1. | P1 | T3.1 | Command runs end-to-end producing raw JSON. |

### Phase 4 — Adapter & candidate governance (P1)

Map raw extractions into governed K-Ops candidate objects behind the grounding gate.

| ID | Task | Priority | Depends on | Acceptance criteria |
|----|------|----------|-----------|---------------------|
| T4.1 | Define candidate object schema with required fields: `candidate_id, source_id, source_hash, extractor, extractor_version, template, entity_or_claim, source_span, quote, confidence, admission_status=candidate, validation_state=unverified`. | P1 | T1.5 | Schema + validation in `scripts/`. |
| T4.2 | Implement adapter mapping: node→`EntityCandidate`, edge→`RelationCandidate`, temporal edge→`TemporalClaimCandidate`, hyperedge→`MultiEntityClaimCandidate`, template metadata→`extraction_profile`. | P1 | T4.1, T3.3 | `candidates.json`, `entities.json`, `relations.json` written per source. |
| T4.3 | Implement the **grounding pass**: attempt exact-span match against `normalized.md`; on failure, flag for the escalation policy (see T4.4). Ungroundable → stays quarantined. | P1 | T4.2 | Each candidate has span/quote or quarantine reason. |
| T4.4 | Decide + document the abstractive-grounding escalation policy (exact-only vs. bounded fuzzy vs. human-in-loop). This directly answers Challenge 1; must not silently reintroduce an unverified LLM. | P1 | T0.4, T4.3 | Written policy; if any LLM step is used, it is logged as a distinct low-trust event. |
| T4.5 | Promotion path: groundable candidates flow into `claim_registry.py` as unadmitted claims; nothing auto-promotes to concept pages. | P1 | T4.3 | Candidates appear in claim registry with `admission_status=candidate`. |

### Phase 5 — Contradiction surfacing (P2)

Treat extraction as an adversarial audit of the existing graph, not just additive growth.

| ID | Task | Priority | Depends on | Acceptance criteria |
|----|------|----------|-----------|---------------------|
| T5.1 | Detect when a groundable candidate edge contradicts an already-admitted claim; route to `contradiction_registry.py` as a first-class output. | P2 | T4.5 | Contradictions logged with both claim IDs + source spans. |
| T5.2 | Surface contradiction-surfacing yield in the vault scorecard (`vault_scorecard.py`). | P2 | T5.1 | New scorecard signal for extractor-surfaced contradictions. |

### Phase 6 — Testing, eval & hardening (P2/P3)

| ID | Task | Priority | Depends on | Acceptance criteria |
|----|------|----------|-----------|---------------------|
| T6.1 | **Golden-fixture tests for the adapter only** (deterministic JSON→candidate mapping). | P2 | T4.2 | Fixtures in `tests/fixtures/`; deterministic pass. |
| T6.2 | **Scored eval-harness track for extraction quality** (precision/recall over time), reusing `research/evals/`. Not golden fixtures. | P2 | T2.3, T4.5 | Extraction quality metrics tracked across runs. |
| T6.3 | Document the whole flow in a runbook (`notes/Runbooks/`) and update `design.md` + README interop/trust-boundary section. | P2 | T4.5 | Runbook + docs merged; `lint` clean. |
| T6.4 | Pin `extractor_version`; add CI guard that the isolated venv install does not leak into K-Ops's `uv.lock`. | P3 | T3.1 | CI check present and passing. |
| T6.5 | Optional local-model path (vLLM) evaluation for offline extraction. | P3 | T3.3 | Written feasibility note. |

---

## 5. Dependency graph (critical path)

```
T0.1 ┐
T0.2 ┼─> T0.3 ─> T0.4 ─> T0.5(GATE) ─> T1.1 ─> T1.2 ─> T1.3 ┐
     │                                              T1.4 ┼─> T1.5(SCOPE GATE) ─> T3.1 ─> T3.2 ─> T3.3 ─> T4.2
                                                                                                  │
Phase 2 (independent): T2.1 ─> T2.2 ─> T2.3 ───────────────────────────────────────┐             │
                                                                                    └─(K2 compare)│
                                                             T4.1 ───────────────────────────────>┤
                                                                                                  v
                                                    T4.2 ─> T4.3 ─> T4.4 ─> T4.5 ─> T5.1 ─> T5.2
                                                                              │
                                                                              └─> T6.1 / T6.2 / T6.3 / T6.4 / T6.5
```

**Critical path:** T0.* → T1.* → T3.* → T4.* → T5.*. Phase 2 runs in parallel and is the K2 comparison baseline. Two hard gates: **T0.5** (does grounding work at all) and **T1.5** (does scoped extraction beat native baseline).

## 6. Immediate next actions

1. **T0.1** — pick the 3 curated sources.
2. **T0.2** — stand up the isolated Hyper-Extract venv.
3. **T0.3 / T0.4** — run the span-groundability probe.

Everything downstream is contingent on **T0.5**. Do not write adapter code before the gate.

## 7. Explicitly out of scope

- Hyper-Extract's Obsidian export (schema drift vs. K-Ops vault contract).
- Hyper-Extract's MCP server as a K-Ops retrieval layer.
- Its incremental-merge (K-Ops's contradiction registry owns conflict resolution).
- Its 80+ domain templates as wholesale imports (design references only).
- Any required (non-optional) dependency on `hyperextract` in K-Ops's core.
