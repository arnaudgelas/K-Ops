# K-Ops Benchmark Report

## Headline

**On a versioned adversarial corpus of 84 governed questions, K-Ops served 0 stale/revoked-source decision answers versus BM25's 43 leaks, at ~4.7 review-minutes per accepted answer.** These governance/leakage numbers are REAL and deterministic (a property of retrieval/exclusion, no LLM). Answer-*quality* wins remain PENDING a real-provider run and are NOT claimed here.

## Corpus version and snapshot

| Field | Value |
| --- | --- |
| Corpus | corpus |
| Snapshot | 03-retraction |
| Questions graded | 84 |
| Schema version | 1.0.0 |
| Harness policy version | 1.0.0 |
| Retrieval top-k | 8 |

The default snapshot is `03-retraction`, in which one source (`src-5ec0000016`, a 5M-events/sec blog) is revoked. That is the state in which the governance advantage is demonstrable: an ungoverned lexical baseline retrieves the revoked source; governed K-Ops excludes it.

## Models, prompts, and provider

| Field | Value |
| --- | --- |
| Provider | deterministic (offline) |
| Provider fingerprint | n/a |
| Baselines | raw-agent, bm25-agent, current-kops, improved-kops |

The committed report is generated with the offline **deterministic provider**: it emits canned answer templates, so every *answer-quality* number below is demo/plumbing (clearly labelled). Governance, retrieval, and the M4 differentiation are independent of the provider and are real today.

## Baseline configurations

Four baselines run over identical questions and corpus state:

- **raw-agent** — no retrieval grounding; answers from the model prior only.
- **bm25-agent** — ungoverned lexical (BM25) retrieval; no exclusion filter.
- **current-kops** — governed retrieval: flagged/revoked sources excluded, consequence-tier evidence bar applied.
- **improved-kops** — current-kops plus the M2/M4 policy refinements.

## Retrieval performance

Deterministic (measured from retrieved-context membership; no LLM).

| Baseline | recall@k | evidence_coverage | irrelevant_context_rate |
| --- | --- | --- | --- |
| raw-agent | 0.000 | 0.000 | 0.000 |
| bm25-agent | 0.837 | 0.893 | 0.770 |
| current-kops | 0.724 | 0.786 | 0.791 |
| improved-kops | 0.724 | 0.786 | 0.791 |

## Citation support

Cited-span entailment (J1.1 judge): **pending-real-judge**.

No judge was configured for this run, so citation entailment is reported as PENDING rather than fabricated. Set `KB_JUDGE_AGENT`/`KB_JUDGE_CMD` and pass `--entailment` to score it and calibrate against the human GOLD fixtures.

## Stale and retracted source leakage

The headline result. A *leak* is a flagged/revoked source reaching a baseline's answer context. REAL and deterministic — no LLM involved.

| Baseline | revoked leaks | revoked-leak rate | flagged leaks | stale leaks | time-to-invalidate |
| --- | --- | --- | --- | --- | --- |
| raw-agent | 0 | 0.000 (95% CI [0.000, 0.044]; 0/84) | 0 | 0 | immediate |
| bm25-agent | 43 | 0.512 (95% CI [0.407, 0.616]; 43/84) | 43 | 0 | immediate |
| current-kops | 0 | 0.000 (95% CI [0.000, 0.044]; 0/84) | 0 | 0 | immediate |
| improved-kops | 0 | 0.000 (95% CI [0.000, 0.044]; 0/84) | 0 | 0 | immediate |

Governed K-Ops leaks **0** revoked sources; the ungoverned BM25 baseline leaks **43** out of 84 questions. Exclusion is synchronous on status change (0 retrieval cycles to invalidate).

## Safe-grounded rate (composite advantage)

Fraction of questions where the baseline retrieves ≥1 relevant CLEAN source AND leaks 0 flagged/revoked sources — the single metric where K-Ops beats BOTH raw-agent (no grounding) and bm25-agent (leaks). Rates carry a Wilson 95% CI.

| Baseline | safe_grounded_rate |
| --- | --- |
| raw-agent | 0.000 (95% CI [0.000, 0.044]; 0/84) |
| bm25-agent | 0.452 (95% CI [0.350, 0.559]; 38/84) |
| current-kops | 0.786 (95% CI [0.686, 0.860]; 66/84) |
| improved-kops | 0.786 (95% CI [0.686, 0.860]; 66/84) |

## Contradiction handling

K-Ops records contradictions as *typed* records (L4.1) and treats them by materiality: a material contradiction gates a decision; an immaterial one (terminology / extraction / scope) is downgraded to an advisory warning. The measured effect on the decision tier is:

| Contradiction | Classified type | Materiality | Decision-tier outcome |
| --- | --- | --- | --- |
| Vendor vs community semantics | direct-conflict | material | qualify |
| Terminology difference | terminology-mismatch | immaterial | permit |

See the **M4 differentiation** section for the full measured delta.

## Decision-gate accuracy (false accept / false reject)

A *false accept* is a flagged source admitted to a high-tier (recommendation/decision/autonomous) answer; a *false reject* is a clean, relevant source the baseline dropped that the ungoverned baseline kept.

| Baseline | decision_gate_false_accept | decision_gate_false_reject |
| --- | --- | --- |
| raw-agent | 0 | 66 |
| bm25-agent | 39 | 0 |
| current-kops | 0 | 0 |
| improved-kops | 0 | 0 |

## Review burden

Deterministic review-cost model: minutes of human review per accepted answer, weighted by consequence tier.

| Baseline | review_minutes_per_accepted_answer |
| --- | --- |
| raw-agent | 4.695 |
| bm25-agent | 4.695 |
| current-kops | 4.695 |
| improved-kops | 4.695 |

## Latency and cost

Wall-clock latency is volatile and is therefore excluded from this committed body (it lives in the per-run JSON under `data/eval_runs/`). Token usage and model cost are 0 / N/A with the offline deterministic provider.

| Baseline | model_cost_usd | token_usage |
| --- | --- | --- |
| raw-agent | 0.0 | N/A |
| bm25-agent | 0.0 | N/A |
| current-kops | 0.0 | N/A |
| improved-kops | 0.0 | N/A |

## M4 differentiation

The two defensible M4 capabilities, each shown as a **measured decision delta** over the benchmark corpus. Both are deterministic (no LLM) and computed live from the M4 modules at render time, not written as prose.

### (a) Source independence changes a corroboration decision

A claim cites the corpus derivative pair `src-5ec0000012` and `src-5ec0000013` — two secondary blogs that both `derived_from` the single vendor benchmark `src-fac0000007`. Evaluated at the **autonomous** tier:

| Lineage consulted? | Independent origins | Corroborated? | Autonomous decision |
| --- | --- | --- | --- |
| No (naive distinct-source count) | src-5ec0000012, src-5ec0000013 (2) | True | **permit** |
| Yes (declared `derived_from`) | src-5ec0000012 (1) | False | **refuse** |

**Decision flip: `permit` → `refuse`** (barred for: needs-corroboration). Consulting declared lineage collapses two apparent witnesses to one independent origin, so the autonomous corroboration requirement is no longer met.

### (b) Typed contradictions improve qualify/abstain

The same claim participates in a contradiction. The typed classifier decides materiality; the tier policy decides the outcome at the **decision** tier:

| Contradiction record | Classified type | Materiality | Decision |
| --- | --- | --- | --- |
| Direct conflict (vendor vs community) | direct-conflict | material | **qualify** |
| Terminology mismatch | terminology-mismatch | immaterial | **permit** |

**Decision delta: `qualify` → `permit`.** A material (direct-conflict) contradiction forces the decision to qualify; distinguishing an immaterial (terminology-mismatch) contradiction lets the same claim permit, instead of over-gating every disagreement.

## Failures and limitations

- **Answer quality is PENDING a real provider.** Every number in the `answer_quality` family is marked `demo-plumbing-pending-real-llm`: it is graded from the offline provider's canned answers and must not be read as a proven accuracy win. A real-provider run is required before any answer-quality headline.
- **Citation entailment** is only scored when a judge is configured; otherwise it is reported as PENDING (never fabricated).
- **Latency** is volatile and excluded from this committed body.
- **The corpus is authored fixtures** (fictional project *Torque*). The governance and M4 deltas are real *given the corpus*; external validity requires re-running on additional corpora.
- **Stale-answer leakage is 0 in a single-state run** and is exercised by cross-snapshot timelines, not by this single overlay.
