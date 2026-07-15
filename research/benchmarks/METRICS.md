# METRICS — end-to-end M1 benchmark metrics (roadmap task E1.4)

This document is the honesty layer for the M1 metrics harness
(`kops/eval_metrics.py`). It states what each metric means, which numbers are
**real today** (deterministic, no LLM) versus **demo-plumbing pending a real
LLM run**, the one-command invocation, and the M1 exit-gate status.

Companion docs: [`BASELINES.md`](BASELINES.md) (the four E1.3 baselines) and
[`CALIBRATION.md`](CALIBRATION.md) (the J1.2 entailment calibration set).

## One command

```bash
# Deterministic, offline, reproducible. Overlays the 03-retraction snapshot so
# the governance advantage is demonstrated. Writes data/eval_runs/benchmark-<date>.json (+ .jsonl).
kops benchmark
# equivalently:
python -m kops.eval_metrics
```

Useful flags: `--no-snapshot` (plain base corpus), `--snapshot <dir>`,
`--provider agent-cli:<agent>` (REAL numbers — see below), `--entailment`
(run the J1.1 judge), `--top-k`, `--out-dir`, `--corpus`, `--golden-set`.

The run is deterministic: injected provider, deterministic BM25, no RNG. Two runs
produce byte-identical metrics under `eval_metrics.deterministic_view()` (which
strips volatile fields: timestamps, wall-clock latency, temp paths).

## The pipeline

1. Materialise the working vault = base E1.1 corpus **+** snapshot `Sources/`
   overlay (`overlay_corpus`). The default `03-retraction` overlay marks
   `src-5ec0000016` (the "5M events/sec" blog) `source_status: revoked`.
2. For each golden question × each of the four baselines
   (`raw-agent`, `bm25-agent`, `current-kops`, `improved-kops`): run the baseline
   (E1.3), **build + persist a versioned `ContextPackage`** (D1.1) for the
   answer, **grade** the answer against the golden set (E1.2), and **attribute**
   any failure.
3. Compute the four metric families, the comparison table, and (optionally) the
   entailment metrics.
4. Write the dated report + per-answer JSONL.

## Every answer is linked to a versioned ContextPackage

Exit-gate requirement. For each `(baseline, question)` answer the harness builds
a content-addressed `ContextPackage` carrying: the question, the consequence
tier, retrieved claim ids, retrieved evidence spans, **each retrieved source's
immutable `SourceVersion` id**, per-source trust + freshness state, the flagged
sources governance **excluded** (with reasons), the retrieval trace, the policy
version, and the `package_hash`. It is persisted via `EvidenceStore` and the
per-answer report record carries its `context_package_hash`, resolvable with
`store.load_context_package(hash)`.

## The four metric families

### Retrieval — REAL today (deterministic)

Measured from which sources reach each baseline's context, per baseline.

- **recall_at_k** — mean over questions of `|retrieved ∩ relevant| / |relevant|`
  (relevant = golden `relevant_source_spans` source ids).
- **evidence_coverage** — fraction of questions with ≥1 relevant source retrieved.
- **irrelevant_context_rate** — mean fraction of retrieved sources not relevant.

### Answer quality — DEMO / plumbing PENDING a real LLM

Graded from the **provider's answer text**. With the offline
`DeterministicProvider` the "answers" are canned templates, so these are
plumbing numbers that prove the grader is wired end-to-end — **not** answer
accuracy. Labelled `_status: demo-plumbing-pending-real-llm` in the report.

- factual_correctness (golden pass rate), required_element_coverage,
  contradiction_awareness, temporal_correctness (freshness category),
  appropriate_abstention, catastrophic_answers.
- unsupported_factual_sentence_rate, citation_completeness → `null` (need a
  claim-mapped, citing answer; the offline provider does not cite).
- citation_entailment → see the entailment section (judge-gated).

Real numbers require `--provider agent-cli:<agent>` (a real generator).

### Governance — REAL today (deterministic) — the demonstrated advantage

Measured purely from retrieved-context membership; no LLM.

- **revoked_source_leakage** — questions where a revoked/blocked source reached
  the context. `current-kops` / `improved-kops` = **0**; `bm25-agent` > 0.
- **flagged_source_leakage** — same for any flag reason.
- **decision_gate_false_accept** — high-consequence (recommendation/decision/
  autonomous) questions where a flagged source leaked in.
- **decision_gate_false_reject** — questions where a **clean, relevant** source
  the ungoverned baseline retrieved was dropped (over-exclusion). K-Ops = 0
  (governance only drops flagged sources).
- **stale_answer_leakage** — 0 in a single-state run; exercised by cross-snapshot
  timelines (documented, not fabricated).
- **time_to_invalidate** — `immediate`: exclusion is synchronous on a status
  change (0 retrieval cycles).

### Operations

- **latency_ms** — measured wall-clock (volatile; excluded from the determinism
  view).
- **token_usage** — `N/A`: the provider does not report tokens.
- **model_cost_usd** — `0.0` with the offline provider.
- **review_minutes_per_accepted_answer** — deterministic formula over per-tier
  review minutes (exploratory 1 / recommendation 3 / decision 8 / autonomous 15)
  divided by accepted (non-catastrophic) answers.

## Failure attribution (exit-gate requirement)

Every graded answer carries a `failure_attribution` in a fixed taxonomy, assigned
by deterministic priority:

1. **policy** — a flagged/revoked source leaked into context, or the answer broke
   a tier/abstention/citation policy (forbidden conclusion, fabricated citation,
   wrong abstention).
2. **retrieval** — the question had relevant sources but none were retrieved.
3. **evidence** — relevant sources retrieved but the required
   contradiction/uncertainty the evidence should carry is absent.
4. **generation** — context was adequate but the produced answer fell short
   (missing required elements).
5. **none** — a passing answer.

## The demonstrated advantage: `safe_grounded_rate`

The single honest metric where K-Ops beats **both** other retrieval baselines,
available WITHOUT a real LLM. Defined as the fraction of questions where a
baseline retrieves ≥1 relevant **clean** source **and** leaks 0 flagged sources.

Reference numbers (default run, 84 golden questions, `03-retraction` snapshot,
deterministic provider):

| baseline       | safe_grounded_rate | revoked_source_leakage |
| -------------- | ------------------ | ---------------------- |
| raw-agent      | 0.000 (no grounding) | 0 |
| bm25-agent     | 0.452 (leaks flagged) | 43 |
| current-kops   | **0.786** | **0** |
| improved-kops  | **0.786** | **0** |

`raw-agent` has an empty context (0 grounding); `bm25-agent` grounds answers but
leaks the revoked source on 43/84 questions; governed K-Ops is the only baseline
that is **both** well-grounded **and** non-leaking. This is a
governance/retrieval property, **not** an answer-accuracy claim. Answer-accuracy
advantages are reported as `PENDING` a real-provider run and are never
fabricated.

## M1 exit-gate status

| Criterion | Status |
| --------- | ------ |
| Benchmark reproducible from one command | **Met** — `kops benchmark`. |
| Every benchmark answer linked to a versioned context package | **Met** — a persisted, resolvable `ContextPackage` per answer. |
| Entailment calibrated rather than assumed | **Pending a real judge** — with `--entailment` + a configured judge (`KB_JUDGE_AGENT`/`KB_JUDGE_CMD`) the harness scores the judge against the J1.2 GOLD calibration fixtures (`accuracy_vs_gold`). Deterministic tests use a stub judge; real calibration needs a real judge (and the CALIBRATION.md expansion to ≥150–250 pairs before decision-tier gating). |
| Failures attributable to retrieval / evidence / generation / policy | **Met** — `failure_attribution` per graded answer. |
| K-Ops beats raw-agent AND BM25 on ≥1 meaningful metric | **Met (governance)** — `safe_grounded_rate` above. Answer-quality wins **pending** a real-provider run. |

## Running with a real provider (for real numbers)

```bash
# Real generator (answer quality becomes real, not demo):
kops benchmark --provider agent-cli:codex          # or claude / gemini

# Real entailment judge (citation entailment + calibration become real):
export KB_JUDGE_AGENT=codex                          # or claude / gemini
kops benchmark --entailment
```

Governance and retrieval numbers are identical with or without a real provider —
they never depend on the LLM. Only answer quality and entailment change.
