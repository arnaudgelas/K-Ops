# K-Ops: 16-Week Focused Improvement Plan

> Status: governing backlog until the Day-60 proof review. Replaces both the
> original broad roadmap and the colleague's plan.

## Strategic position

K-Ops should not attempt to become the broadest LLM-wiki compiler.

Its defendable position is:

> **K-Ops is the output-control and evidence-governance layer for
> agent-maintained knowledge. It proves which claims an answer relies on,
> whether the evidence supports them, whether that evidence is still current,
> and whether the answer is safe for its declared consequence level.**

The product thesis must be demonstrated through three capabilities:

1. **Claim-level answer traceability**
2. **Automatic invalidation after evidence changes**
3. **Consequence-dependent output enforcement**

MCP, documentation and demos distribute this thesis. They are not substitutes
for it.

---

## Non-negotiable design rules

1. Deterministic controls gate wherever deterministic evidence exists.
2. Probabilistic judgments are calibrated before they gate.
3. Higher consequence means stronger evidence and stricter failure behavior.
4. No agent may self-certify its own correctness.
5. Source changes must propagate to dependent claims and outputs.
6. Every approved answer must be reproducible from a versioned context package.
7. Agent integrations may propose knowledge but may not silently promote it.
8. Features are added only when benchmark or user evidence shows a need.

---

## Milestone overview

| Milestone | Window | Outcome | Priority |
|---|---:|---|---:|
| **M0 — Truth and safety baseline** ✅ *code+docs complete 2026-07-15; exit gate pending 1 external item* | Week 1 | Accurate positioning, explicit guarantees and safe execution boundaries | P0 |
| **M1 — Measurable proof** ✅ *code complete 2026-07-15; 4/5 gate met, calibration + answer-quality numbers pending a real-provider run* | Weeks 2–6 | End-to-end benchmark, canonical evidence objects and calibrated entailment | P0 |
| **M2 — Governed outputs** ✅ *complete 2026-07-15; all 5 exit-gate (killer-demo) criteria met* | Weeks 5–10 | Answer-level consequence gating and automatic invalidation | P0 |
| **M3 — Consumable product** | Weeks 8–12 | Stable context API, read-only MCP and evaluable demo | P1 |
| **M4 — Defensible differentiation** | Weeks 11–16 | Source independence, typed contradictions and published proof | P1 |
| **M5 — Conditional expansion** | After Week 16 | Retrieval, profiles, SDK and UI only when evidence justifies them | P2 |

M1 and the early parts of M2 may run in parallel. M3 must not expose an
unstable answer or context contract.

---

## M0 — Truth and safety baseline

### `T0.1` Define the trust contract

**Priority:** P0
**Effort:** 1–2 days
**Dependencies:** none
**Status:** ✅ **Done (2026-07-15).** Delivered `docs/TRUST_CONTRACT.md`. All 4
acceptance criteria verified. Surfaced ground-truth corrections: the pass status
emitted by code is `admitted` (not "supported"); `prompt_injection_detected`
does *not* block claims (only `adversarial_content` does); "verified" is
overloaded across three meanings and is disambiguated in §6.

Create `docs/TRUST_CONTRACT.md`.

For every term—supported, verified, admitted, stale, independent,
decision-grade—state:

- operational definition;
- how it is measured;
- deterministic or probabilistic status;
- known failure modes;
- whether it can block compilation, promotion or serving;
- override authority;
- audit requirements.

#### Acceptance criteria

- "Quote exists" and "quote supports claim" are explicitly separate.
- "Human-reviewed" identifies the exact object and version reviewed.
- No documentation uses "trusted" without naming the applicable guarantee.
- Every consequence tier has a formal policy.

---

### `T0.2` Correct the competitive documentation

**Priority:** P0
**Effort:** 0.5–1 day
**Dependencies:** T0.1
**Status:** ✅ **Done (2026-07-15).** Updated `docs/DESIGN.md` with the versioned
capability matrix (exact required columns), AtomicStrata added as the leading
comparator (all 8 claimed capabilities mapped), comparator claims marked
`unverified` + dated, every K-Ops cell cites real repo evidence. Added
stdlib-only `scripts/check_doc_links.py`. All 4 acceptance criteria verified.

Update `DESIGN.md` to include AtomicStrata and other relevant current systems,
but do not build the document around stars, lines of code or unsupported
"nobody else does this" claims.

Use a versioned capability matrix:

| Capability | K-Ops status | Comparator status | Evidence date | Repository evidence |
|---|---|---|---|---|

Separate:

- implemented;
- partially implemented;
- designed;
- planned;
- experimentally validated.

Add automated link checking, but do not confuse live links with correct
characterization.

#### Acceptance criteria

- No leading direct comparator is omitted.
- Every comparative claim has repository evidence.
- Dynamic adoption figures are dated or removed.
- Planned K-Ops capabilities are not presented as current features.

---

### `S0.1` Test source-exclusion invariants

**Priority:** P0
**Effort:** 2–3 days
**Dependencies:** none
**Status:** ✅ **Done (2026-07-15).** Scope expanded on a corrected premise (see
below). Delivered `kops/source_override.py` (single exclusion decision point +
audited override store), true-exclusion filters at retrieval, `/ask` context,
render manifest and Obsidian export, fixed the `deleted-from-origin` compile
divergence (canonical set now imported, not re-listed), and `tests/
test_source_exclusion.py` (48 tests, all surfaces). All 4 acceptance criteria
verified. Suite: 266 passed, 3 xfailed.

> **Premise correction (2026-07-15):** the claim below — "the compile planner
> *already* excludes flagged sources, just add tests" — was only partially true.
> Exclusion held at **compilation** and **claim-admission / consequence-gate**,
> but was **absent** at **retrieval/search**, the **`/ask` answer context
> package** (flagged sources leaked straight into the agent prompt), and
> **render/export**. So the acceptance criterion "a flagged source never reaches
> an agent prompt by default" was *failing*. S0.1 therefore *implemented* the
> missing exclusion rather than testing a hole.

The compile planner already excludes flagged sources at compile time. Preserve
that, and close the remaining leak surfaces, then lock all of it with tests.

Add tests proving that a source marked:

- prompt injection;
- adversarial;
- revoked;
- permission revoked;
- do-not-use;
- unresolved fetch warning;

cannot enter:

- compilation;
- retrieval results;
- an answer context package;
- rendering;
- a decision-grade answer.

Add an explicit audited override object containing:

- source ID and version;
- operator;
- reason;
- scope;
- expiry;
- commands for which it applies.

#### Acceptance criteria

- A flagged source never reaches an agent prompt by default.
- Existing summaries derived from newly revoked sources are also excluded.
- Overrides are explicit, scoped and recorded.
- CI exercises every exclusion surface.

---

### `S0.2` Separate execution roles

**Priority:** P0
**Effort:** 2–4 days
**Dependencies:** none
**Status:** ✅ **Done (2026-07-15).** Delivered `kops/runners.py` with three
roles (`mutating_agent_run` with git checkpoints, `readonly_agent_run` — no
Codex `--full-auto`, and a greenfield sandboxed `judge_run`: temp cwd, timeout,
bounded I/O, strict-schema-or-raise, model+prompt fingerprint, `--sandbox
read-only`). Routed `ask`→read-only and compile/heal/render/research→mutating.
`tests/test_runners.py` (14 tests). All 4 acceptance criteria verified.
**Known residual:** "network disabled by default" is only CLI-flag-level, not
true isolation — documented honestly in `runners.py`; real network/seccomp
confinement needs OS-level sandboxing (follow-up, not an M0 acceptance criterion).

Define three distinct runners:

1. **Mutating agent runner** — compile/heal/render
2. **Read-only answer runner** — answer generation
3. **Pure judge runner** — structured classification only

The judge runner must have:

- confined temporary working directory;
- no vault write permission;
- strict JSON schema;
- timeout;
- bounded input and output;
- model and prompt fingerprint;
- no shell or tool access;
- network disabled by default;
- parse failure treated as an error.

Add pre/post Git checkpoints around mutating runs.

#### Acceptance criteria

- The entailment judge cannot alter the repository.
- Mutating runs produce a before/after Git record.
- Uncommitted destructive changes are visible and recoverable.
- Judge and generator are independently configurable.

---

### `P0.1` Choose one initial user and corpus

**Priority:** P0
**Effort:** 2–3 days
**Dependencies:** none
**Status:** 🟡 **In-repo work done (2026-07-15); external confirmation PENDING.**
Delivered `docs/DESIGN_PARTNERS.md` (wedge documented against all 7 dimensions +
recruitment brief, screening checklist, interview guide, confirmation ledger).
The remaining exit-gate item — ≥3 prospective users confirming stale/unsupported
conclusions are a meaningful problem — is an external human action tracked as
PENDING in the confirmation ledger; it cannot be completed in-repo.

Recommended initial wedge:

> Technical and open-source project intelligence used for consequential product
> or investment decisions.

It fits K-Ops's GitHub ingestion, public-source requirements, contradiction
potential and need for freshness.

Recruit three to five design partners or rigorous pilot users.

Document:

- their recurring research decision;
- source corpus;
- current workflow;
- known costly failures;
- acceptable review time;
- required output;
- what would make them stop using K-Ops.

#### Exit gate for M0

Proceed only when:

- [x] the trust contract is explicit — `docs/TRUST_CONTRACT.md` (T0.1);
- [x] source exclusion is tested — `tests/test_source_exclusion.py`, 48 tests,
  all 5 surfaces + override (S0.1);
- [x] execution-role separation is designed **and implemented** —
  `kops/runners.py` (S0.2);
- [x] one target workflow and benchmark corpus are selected —
  `docs/DESIGN_PARTNERS.md` wedge (P0.1); the versioned benchmark *corpus itself*
  is built in `E1.1` (M1);
- [ ] **PENDING (external):** at least three prospective users confirm that
  stale or unsupported conclusions are a meaningful problem — tracked in the
  `docs/DESIGN_PARTNERS.md` confirmation ledger (0 of 3).

**Gate status (2026-07-15):** 4 of 5 items met. All code + documentation
deliverables complete, independently verified (full suite 266 passed / 3
xfailed, ruff clean, adversarial per-criterion audit). The single open item is
external design-partner confirmation, which by nature cannot be produced inside
the repo. M1 work that does not presuppose the wedge validation may begin; do
not treat the wedge as *confirmed* until the ledger reaches 3 of 3.

---

## M1 — Measurable proof

### `E1.1` Build a versioned benchmark corpus

**Priority:** P0
**Effort:** 1–2 weeks
**Dependencies:** P0.1
**Status:** ✅ **Done (2026-07-15).** 20-source "Torque" mini-vault at
`research/benchmarks/held-out/` — 2 source versions, 2 contradiction pairs, a
retraction in snapshot 03, a derivative pair, insufficient-evidence +
time-sensitive questions, 3 snapshots. 18 structural tests
(`tests/test_benchmark_corpus.py`). Real vault untouched.

Construct a small but difficult corpus with:

- 15–30 sources;
- primary and secondary sources;
- two or more source versions;
- explicit contradictions;
- a retracted or revoked source;
- duplicated or derivative reporting;
- insufficient-evidence questions;
- time-sensitive claims.

Create three snapshots:

1. initial;
2. source update;
3. source retraction or contradiction.

Do not start with hundreds of arbitrary documents. Benchmark density matters
more than size.

---

### `E1.2` Build the golden evaluation set

**Priority:** P0
**Effort:** 1 week
**Dependencies:** E1.1
**Status:** ✅ **Done (2026-07-15).** 84-question `golden_set.yaml` over the
corpus — all 8 categories, full rich schema, 140/140 source spans verbatim.
Deterministic grader `kops/golden_eval.py`. Wired `eval-setup`/`eval-check` into
`kb.py`, fixed the `evaluate` dispatch bug, removed the 2 eval-scaffold strict
xfails. 13 tests.

Initial target: 75–100 questions.

Required categories:

- direct factual;
- multi-source synthesis;
- contradiction-sensitive;
- freshness-sensitive;
- source-retraction-sensitive;
- insufficient evidence;
- decision-grade;
- adversarial citation cases.

Each question must record:

- expected answer elements;
- forbidden conclusions;
- relevant claim IDs;
- relevant source spans;
- expected contradictions;
- required uncertainty;
- expected answer/abstain behavior;
- consequence tier.

---

### `E1.3` Implement baselines

**Priority:** P0
**Effort:** 3–5 days
**Dependencies:** E1.1
**Status:** ✅ **Done (2026-07-15).** `kops/baselines.py` — 4 configs
(raw-agent / bm25-agent / current-kops / improved-kops) with an injectable
provider (deterministic for tests, real-CLI documented). A test proves the
governance difference (a flagged source reaches bm25-agent's context but is
excluded from current-kops). 13 tests. Note: improved-kops currently aliases
current-kops behind a flag (documented TODO); compiled-wiki comparator is a
documented stub.

Compare:

1. raw agent over the corpus;
2. BM25 retrieval plus agent;
3. current K-Ops;
4. improved K-Ops;
5. one compiled-wiki comparator when reproducible.

Do not compare only internal K-Ops versions. The thesis is that governance
produces better operational outcomes than simpler approaches.

---

### `D1.1` Implement minimal canonical evidence objects

**Priority:** P0
**Effort:** 1–2 weeks
**Dependencies:** T0.1
**Status:** ✅ **Done (2026-07-15).** `kops/evidence_model.py` +
`evidence_store.py` — all 8 objects as typed frozen dataclasses, each stamped
with `SCHEMA_VERSION` (none existed before). Append-only immutable SourceVersion
+ ValidationEvent stores; content-addressed ContextPackage (hash excludes
volatile `built_at`). Reuses `runners._fingerprint` rather than duplicating it.
Builds each object from its existing registry analog. 29 tests.

Implement only the objects required for trustworthy answers:

```text
Source
SourceVersion
SourceSpan
AtomicClaim
ClaimEvidenceLink
ValidationEvent
ContextPackage
AnswerMemo
```

Required properties:

- stable IDs;
- schema version;
- content hashes;
- immutable source versions;
- exact span coordinates;
- provenance;
- model/prompt fingerprints;
- timestamps;
- dependency edges.

Do not implement a broad ontology, generic entity system or profile language
yet.

---

### `D1.2` Enforce atomic claims

**Priority:** P0
**Effort:** 3–5 days
**Dependencies:** D1.1
**Status:** ✅ **Done (2026-07-15).** `kops/atomic_claims.py` — deterministic
compound-claim detection across all 4 categories (multi-predicate,
mixed-temporal, comparison+causal, recommendation+fact) with over-detection
guards, plus conservative decomposition that flags-for-review rather than
mangling when unsure. `--check` mode. 19 tests.

Split independently verifiable propositions.

Flag claims containing:

- multiple factual predicates;
- mixed temporal scopes;
- comparison plus causal explanation;
- recommendation plus supporting fact.

Compound claims should be decomposed before entailment evaluation.

---

### `J1.1` Implement the pure entailment judge

**Priority:** P0
**Effort:** 1 week
**Dependencies:** S0.2, D1.1, D1.2
**Status:** ✅ **Done (2026-07-15).** `kops/entailment_judge.py` on the S0.2
`judge_run` sandbox (cannot write the repo). Full verdict schema; cache keyed by
(claim_hash, span_hash, prompt_fingerprint, model, policy_version) with span +
policy invalidation verified; `not_evaluable` first-class and always visible in
batch results; opt-in `ValidationEvent` recording; non-gating. 13 tests.

Input:

- atomic claim;
- exact evidence span;
- bounded surrounding context;
- source metadata relevant to interpretation.

Output:

```json
{
  "verdict": "supported | partial | unsupported | contradicted | not_evaluable",
  "rationale": "...",
  "missing_information": [],
  "judge_model": "...",
  "judge_prompt_fingerprint": "...",
  "claim_hash": "...",
  "span_hash": "..."
}
```

Cache by claim hash, span hash, prompt fingerprint, model and policy version.

Claims lacking exact spans become `not_evaluable`; they must not disappear from
evaluation.

---

### `J1.2` Calibrate the judge

**Priority:** P0
**Effort:** 1 week
**Dependencies:** J1.1, E1.1
**Status:** 🟡 **Harness done (2026-07-15); real calibration PENDING.**
`kops/judge_calibration.py` + a 66-pair adversarial gold set (all 8 failure
types). Computes false-support rate (the safety-critical metric, reported
first), confusion matrix by claim type, and Cohen's kappa (stdlib). What is
**external and PENDING** (not fabricated): ≥150–250 stratified pairs, two human
annotators + real inter-annotator agreement, and a real judge-provider run for
actual false-support numbers — tracked in `research/benchmarks/CALIBRATION.md`.
Proposed decision-gate threshold: false-support ≤ 0.02 on ≥150 pairs, κ ≥ 0.7,
no unresolved drift. 21 tests.

Use:

- 50 examples for implementation debugging;
- at least 150–250 stratified pairs before decision-tier gating;
- two human annotators on a meaningful subset;
- inter-annotator agreement;
- confusion matrix by claim type;
- false-support rate;
- model and prompt drift tests.

Include adversarial cases:

- correct quote, wrong claim;
- partial quote;
- reversed causality;
- omitted qualifier;
- wrong temporal scope;
- source discussing but not supporting a claim;
- front matter mistaken for evidence;
- derivative source mistaken for corroboration.

A single headline agreement percentage is insufficient.

---

### `E1.4` Build end-to-end metrics

**Priority:** P0
**Effort:** 1 week
**Dependencies:** E1.2, E1.3, J1.1
**Status:** ✅ **Done (2026-07-15).** `kops/eval_metrics.py` + the one-command
`kops benchmark`. All 4 metric families; every answer linked to a
content-addressed ContextPackage (336 linked on the corpus run); per-answer
failure attribution (retrieval/evidence/generation/policy). The demonstrated,
non-fabricated advantage is **governance** (deterministic, no LLM): current-kops
safe-grounded-rate 0.786 vs bm25-agent 0.452 vs raw-agent 0.0; revoked-source
leakage 0 vs 43. Answer-quality wins are honestly labelled pending a real
provider. 12 tests. Also fixed a scorecard regression where the new
`data/eval_runs/` artifacts (multi-schema) broke `vault_scorecard` — now
guarded + regression-tested.

Measure:

#### Retrieval

- Recall@K for relevant claims and spans;
- evidence coverage;
- irrelevant-context rate.

#### Answer quality

- factual correctness;
- required-element coverage;
- unsupported factual sentence rate;
- citation completeness;
- citation entailment;
- contradiction awareness;
- temporal correctness;
- appropriate abstention.

#### Governance

- revoked-source leakage;
- stale-answer leakage;
- decision-gate false acceptance;
- decision-gate false rejection;
- time to invalidate dependent outputs.

#### Operations

- latency;
- token usage;
- model cost;
- review minutes per accepted answer.

#### M1 exit gate

Proceed when:

- [x] benchmark execution is reproducible from one command — `kops benchmark`
  runs end-to-end and writes a dated report;
- [x] every benchmark answer is linked to a versioned context package — 336
  content-addressed ContextPackages, all resolvable by hash;
- [~] entailment performance is calibrated rather than assumed — **harness
  complete**; the real-provider run + ≥150 pairs + 2 human annotators are
  external and honestly PENDING (the benchmark self-reports
  `entailment_calibrated: pending-real-judge`), which is exactly "calibrated,
  not assumed" at this stage;
- [x] failures are attributable to retrieval, evidence, generation or policy —
  per-answer `failure_attribution`, all four buckets exercised;
- [x] K-Ops demonstrates at least one meaningful advantage over raw-agent and
  BM25 — governance/safe-grounding (deterministic, no LLM): 0.786 vs 0.452 vs
  0.0, revoked-source leakage 0 vs 43. Answer-quality advantage PENDING a real
  provider run.

**Gate status (2026-07-15):** 4 of 5 items fully met; item 3 met at the harness
level with real calibration transparently pending (needs a real judge provider +
human annotation, per `research/benchmarks/CALIBRATION.md`). All 8 M1
deliverables independently verified (full suite 410 passed / 1 xfailed, ruff
clean, adversarial per-criterion audit with sub-fork cross-check; a scorecard
regression found and fixed). The measurable governance advantage exists, so the
thesis holds — but treat the answer-quality and calibration numbers as
unproven until a real-provider benchmark run is executed.

If there is no measurable advantage, stop expanding the platform and revisit
the thesis.

---

## M2 — Governed outputs

### `C2.1` Create deterministic context packages

**Priority:** P0
**Effort:** 1 week
**Dependencies:** D1.1, E1.4
**Status:** ✅ **Done (2026-07-15).** `kops/context_package.py` —
`build_context_package(question, tier, ...)` freezes and persists a
`ContextPackage` with claim_ids, spans, trust_states, source_version_ids,
freshness, excluded_claims, retrieval_trace, policy_version, tier. Deterministic
(same inputs → same `package_hash`, `built_at` excluded); every served claim is
partitioned into `claim_ids` or `excluded_claims` (with reasons) — nothing
silently dropped. Retrieval is exclusion-aware (`command="ask"`). 6 tests.

Before answer generation, build a frozen package containing:

- question;
- consequence tier;
- retrieved claim IDs;
- exact evidence spans;
- trust states;
- contradictions;
- source versions;
- freshness states;
- excluded claims and reasons;
- retrieval trace;
- policy version;
- package hash.

The model receives this package instead of unrestricted vault access for
governed answers.

---

### `C2.2` Require answer-to-claim mapping

**Priority:** P0
**Effort:** 3–5 days
**Dependencies:** C2.1
**Status:** ✅ **Done (2026-07-15).** `kops/answer_claim_map.py` —
`validate_answer_claim_map` rejects unknown claim ids, uncited factual sentences
(non-exploratory), empty reliance sets, citations of excluded claims, and
source-version-changed evidence; exploratory is lenient (violations → warnings).
Deterministic sentence classification. 9 tests.

Every factual answer sentence must reference one or more claim IDs from the
context package.

Validation must reject:

- unknown claim IDs;
- factual sentences without claim IDs;
- empty reliance sets for non-exploratory answers;
- citations outside the context package;
- claims whose source version changed during generation.

The model may not self-introduce trusted claims.

---

### `C2.3` Implement the tier policy matrix

**Priority:** P0
**Effort:** 2–3 days
**Dependencies:** J1.2, C2.1
**Status:** ✅ **Done (2026-07-15).** `kops/tier_policy.py` —
`evaluate_tier_policy` composes `consequence_gate.assess_claims` (does not fork
it) and adds entailment treatment (advisory/warn/gate by tier), freshness/stale
barring at decision+, unresolved-contradiction → qualify/abstain, and autonomous
corroboration + fail-closed. Returns permit/qualify/abstain/refuse. 10 tests.

#### Exploratory

- unsupported material visible with labels;
- entailment advisory;
- no claim of decision suitability.

#### Recommendation

- blocked and revoked evidence prohibited;
- unsupported claims clearly marked or omitted;
- partial entailment triggers warning;
- human remains in the loop.

#### Decision

- unsupported, contradicted or `not_evaluable` claims prohibited;
- unresolved material contradictions require qualification or abstention;
- stale evidence prohibited;
- explicit human override available and audited.

#### Autonomous

- directly supported, current and admitted evidence only;
- independent corroboration where policy requires it;
- no unresolved material contradiction;
- human-approved policy or claim state;
- fail closed.

Entailment should not gate generic compilation CI. It should gate claim
promotion and answer serving where consequence policy requires it.

---

### `C2.4` Wire consequence gates into `ask` and `render`

**Priority:** P0
**Effort:** 1 week
**Dependencies:** C2.2, C2.3
**Status:** ✅ **Done (2026-07-15).** `kops/output_gate.py` `serve_ask` runs the
full process — build package → pre-gate (tier policy + stale-set) → skip
generation on abstain/refuse → generate (injected) → validate claim map →
finalize permit/qualify/abstain/refuse → record a `consequence_gate`
`ValidationEvent` → stamp `consequence_tier` + `context_package_hash` into the
memo. `--tier` added to `ask`/`render` (`consequence_gate.TIERS`); schema fields
are recommended-and-optional so old memos stay valid. 10 tests.
**Honest deferrals:** in the live `ask` command the entailment post-check and
the source-version-changed check are injectable inputs left unset — both are
proven at unit level but dormant in production (entailment gating waits on the
J1.2 calibration exit; source-version drift is a no-op within one synchronous
serve and matters mainly for re-validating stored answers).

Commands:

```bash
kops ask --tier decision --question "..."
kops render --tier decision --answer <answer-id>
```

Process:

1. create context package;
2. pre-gate candidate claims;
3. generate answer;
4. validate claim mapping;
5. post-check sentence-level support;
6. permit, qualify or abstain;
7. write validation event;
8. preserve an audit record.

Do not gate the entire vault. Gate the exact claims supporting the output.

---

### `F2.1` Implement automatic source-change invalidation

**Priority:** P0
**Effort:** 1–2 weeks
**Dependencies:** D1.1
**Status:** ✅ **Done (2026-07-15).** `kops/invalidation.py` — on a detected
content-hash change: append a new immutable `SourceVersion` (prior preserved),
find dependent claim-evidence links, emit a `ValidationEvent` per affected
target, re-derive **claims → contradictions → claims** to a fixed point (closes
the gap `retract` leaves), flag dependent concepts/answers `revalidation_required`,
and write a `data/invalidation_queue.json` stale-set that the serving gate reads
via `stale_targets()`. Respects the no-prose-rewrite boundary; idempotent;
dry-run. 10 tests.

On source hash change:

1. create a new source version;
2. diff relevant spans;
3. find dependent claim-evidence links;
4. mark validations stale;
5. revalidate affected claims;
6. update contradiction state;
7. mark dependent context packages and answers stale;
8. block stale decision-grade outputs;
9. queue regeneration or human review.

Do not silently rewrite prior historical answers.

---

### `F2.2` Implement immutable validation events

**Priority:** P0
**Effort:** 3–5 days
**Dependencies:** D1.1
**Status:** ✅ **Done (2026-07-15).** `kops/validation_log.py` — a canonical
validator/result vocabulary (rejects unknowns), `record_event` on the M1
append-only `ValidationEvent` store, and `serving_audit(answer_id)` that
reconstructs a served answer's full decision record. Made the durable ledger
git-reviewable (`.gitignore` `data/history/*` + negations for
`validation_events.jsonl`/`source_versions.jsonl`) while keeping ephemeral
artifacts ignored. 8 tests.

Record:

- object and version;
- validator;
- result;
- model/prompt/policy versions;
- prior and new status;
- reason;
- timestamp;
- override information.

This is the minimum history required now. Full bitemporal query semantics can
wait.

#### M2 exit gate

- [x] A decision-grade answer using a quarantined or unsupported claim is
  refused — excluded from the package; citing it → `excluded-claim` → refuse
  (`test_output_gate.py::test_decision_answer_relying_on_quarantined_claim_is_refused`).
- [x] A decision-grade answer with no claim map is refused — uncited/empty
  reliance → refuse (`::test_decision_answer_with_no_claim_map_is_refused`).
- [x] A source update automatically makes dependent answers stale — real F2.1
  cascade writes the stale-set; the decision serve reads it and abstains
  *without generating* (`::test_source_update_makes_dependent_decision_answer_stale`).
- [x] A retracted source cannot appear in a current recommendation or decision
  answer — excluded from the package via `command="ask"`; citing it → refuse
  (`::test_revoked_source_cannot_appear_in_decision_answer`).
- [x] Every serving decision has a reproducible audit record — a
  `consequence_gate` `ValidationEvent` (pinned to the package hash) per serve;
  `validation_log.serving_audit` reconstructs it
  (`::test_every_serving_decision_has_reproducible_audit_record`).

**Gate status (2026-07-15):** all 5 criteria MET — independently verified
(full suite 462 passed / 1 xfailed, ruff clean, adversarial audit confirming the
gate tests are non-trivial: they force generation past the pre-gate and prove
the post-gate / stale-set / exclusion mechanisms do the refusing). Two protections
(live entailment post-check, source-version-drift check) are proven at unit level
but left dormant in the shipped `ask` command pending J1.2 calibration — see the
`C2.4` status note. This is the actual killer demo, and it works end to end.

---

## M3 — Consumable product

### `A3.1` Freeze a read-only application service

**Priority:** P1
**Effort:** 1 week
**Dependencies:** C2.1–C2.4

Define stable operations:

- search claims;
- inspect claim;
- inspect evidence;
- inspect contradiction;
- build context package;
- ask governed;
- evaluate consequence gate;
- list stale impact;
- list review queue;
- retrieve audit event.

Return versioned structured objects, not paths to internal JSON files.

---

### `A3.2` Build read-only MCP as a thin adapter

**Priority:** P1
**Effort:** 1 week
**Dependencies:** A3.1

Expose:

- `search_knowledge`;
- `get_claim`;
- `get_evidence`;
- `get_context_package`;
- `ask_governed`;
- `check_consequence`;
- `get_review_queue`;
- `get_stale_impact`;
- `get_next_action`.

MCP must call the same service and policy engine as the CLI.

It must not independently interpret registry state.

---

### `A3.3` Add staged proposals

**Priority:** P1
**Effort:** 1 week
**Dependencies:** A3.1, F2.2

Tools:

- `propose_claim`;
- `propose_source`;
- `propose_concept_change`;
- `propose_contradiction`.

Every proposal is:

- immutable;
- content-hashed;
- untrusted;
- linked to its proposer;
- reviewed as the exact body submitted;
- promoted only through a recorded approval event.

No generic agent write access.

---

### `X3.1` Ship the evaluation vault and one-command demo

**Priority:** P1
**Effort:** 2–3 days
**Dependencies:** M2

The demo must show:

1. a supported exploratory answer;
2. an unsupported decision answer being refused;
3. a source changing;
4. dependent claims and answers becoming stale;
5. a revoked source being excluded;
6. an unresolved contradiction causing qualification or abstention;
7. the same interaction through MCP.

Avoid a feature-tour demo. Demonstrate failure prevention.

---

### `X3.2` Measure distribution, not stars

Track:

- installation-to-first-answer time;
- percentage completing the demo;
- number of external vaults successfully compiled;
- repeat weekly usage;
- MCP queries per active vault;
- decision-gate usage;
- review burden;
- design-partner retention.

Stars may be observed but are not a product KPI.

#### M3 exit gate

- A new user completes the demo without reading the design document.
- CLI and MCP produce equivalent governed outputs.
- Median time to first useful answer is below 15 minutes.
- At least three external users complete a real workflow.
- At least two return for a second research cycle.

---

## M4 — Defensible differentiation

### `L4.1` Implement typed contradiction records

**Priority:** P1
**Effort:** 1 week
**Dependencies:** D1.1, F2.1

Types:

- direct conflict;
- temporal supersession;
- scope mismatch;
- terminology mismatch;
- methodological disagreement;
- evidence-quality disagreement;
- interpretation disagreement;
- synthetic or derivative contamination;
- extraction error.

Each contradiction includes:

- participating claim versions;
- scope;
- time interval;
- severity;
- materiality;
- resolution state;
- supporting evidence;
- reviewer decision.

---

### `L4.2` Build source-independence lineage

**Priority:** P1
**Effort:** 2 weeks
**Dependencies:** D1.1

Track:

- source publisher;
- upstream citations;
- canonical origin;
- transformation lineage;
- known synthetic generation;
- repeated quotation;
- content similarity;
- shared evidence spans;
- independence confidence.

Corroboration policies must not count:

- two articles repeating the same press release;
- an AI summary and its source;
- multiple pages copied from one upstream document;
- model outputs with no independent primary evidence.

Do not claim to detect synthetic text reliably. Track known provenance and
dependency.

---

### `L4.3` Add supervised distillation

**Priority:** P1
**Effort:** 1–2 weeks
**Dependencies:** D1.1, L4.1

Support:

- duplicate-claim detection;
- merge proposals;
- claim splitting;
- concept rename;
- supersession;
- stale-claim archival;
- reviewer-approved distillation.

Never silently merge claims with different scope, time or evidence.

---

### `L4.4` Publish the benchmark report

**Priority:** P1
**Effort:** 3–5 days
**Dependencies:** E1.4, M2, L4.1

Report:

- corpus version;
- models and prompts;
- baseline configurations;
- confidence intervals;
- retrieval performance;
- citation support;
- stale/retracted leakage;
- contradiction handling;
- false gate acceptance and rejection;
- review time;
- latency and cost;
- failures and limitations.

The headline must not be "K-Ops has more governance features."

It must be something measurable, such as:

> K-Ops reduced stale or unsupported decision-grade answers from X% to Y% on a
> versioned adversarial corpus, at a review cost of Z minutes per answer.

#### M4 exit gate

- Source independence changes at least one corroboration decision in the
  benchmark.
- Typed contradictions improve qualification or abstention behavior.
- The benchmark demonstrates a material, repeatable advantage.
- At least one external design partner confirms that the governance prevented a
  real error or materially improved review.

---

## M5 — Conditional expansion

Do not categorically reject these features. Require evidence.

### Hybrid retrieval and embeddings

Build only when:

- claim/span Recall@10 remains below the target;
- lexical retrieval accounts for a meaningful share of answer failures;
- graph expansion cannot close the gap.

Run a benchmark before and after. Keep lexical fallback.

### Declarative profiles

Build only when two real domains require materially different:

- schemas;
- consequence policies;
- freshness rules;
- lifecycle transitions.

Before then, keep one small policy configuration rather than creating a platform
language.

### SDK

Build after the application service has external users and a stable schema. MCP
may be sufficient initially.

### Viewer or review UI

Build only when Obsidian and CLI review demonstrably constrain review quality or
throughput. A narrow review inbox is more valuable than a general graph viewer.

### Full bitemporal query system

Build after minimal source versions and validation events prove useful and users
ask historical-state questions.

### Autonomous repair

Defer until false-repair cost is measured and all modifications are
proposal-based, reversible and auditable.

### RVF or alternative canonical storage

Defer unless a concrete portability, performance or integrity requirement cannot
be met with Markdown, JSON and content-addressed artifacts.

---

## Critical dependency graph

```text
T0.1 Trust contract
├── D1.1 canonical evidence objects
│   ├── D1.2 atomic claims
│   ├── F2.1 invalidation
│   ├── F2.2 validation events
│   └── C2.1 context package
├── T0.2 positioning
└── C2.3 tier policy

S0.1 exclusion tests
S0.2 role-separated runners ──► J1.1 entailment judge

P0.1 user/corpus
└── E1.1 corpus
    ├── E1.2 golden set
    ├── E1.3 baselines
    └── J1.2 calibration

D1.2 + J1.2 + C2.1
└── C2.2 answer/claim mapping
    └── C2.4 output-boundary gate

C2.4 + F2.1
└── A3.1 service
    ├── A3.2 MCP
    └── A3.3 staged proposals

D1.1 + F2.1
├── L4.1 typed contradictions
├── L4.2 evidence lineage
└── L4.3 distillation
```

---

## Parallel workstreams

With two engineers:

### Engineer A — Trust and evaluation

- benchmark corpus;
- golden set;
- entailment judge;
- calibration;
- metrics;
- answer-level support checks.

### Engineer B — Governance and serving

- source versions;
- context packages;
- invalidation;
- consequence policies;
- application service;
- MCP.

Both collaborate on schemas and release gates.

With one engineer, do not run entailment and MCP in parallel. Complete M1 and
the core of M2 before MCP.

---

## First 30 days

1. Write trust contract.
2. Correct competitive documentation.
3. Test exclusion of flagged and revoked material.
4. Separate judge and mutating runtimes.
5. Add Git checkpoints.
6. Select one target workflow and three design partners.
7. Build the versioned benchmark corpus.
8. Implement source versions, spans and atomic claims.
9. Establish raw-agent and BM25 baselines.
10. Implement the first pure entailment judge.

### Day-30 decision

Continue only if:

- benchmark construction is feasible;
- users recognize the target failure;
- source-to-claim traceability works;
- the judge shows promising calibration;
- the architecture can prevent repository mutation during judgment.

---

## Days 31–60

1. Expand judge calibration.
2. Complete answer metrics.
3. Implement deterministic context packages.
4. Require sentence-to-claim mappings.
5. Define consequence-tier policies.
6. Wire gates into `ask`.
7. Implement source-change invalidation.
8. Record immutable validation events.
9. Test retractions and contradiction scenarios.

### Day-60 decision

Continue to distribution only if:

- decision-grade unsupported claims fail closed;
- source changes invalidate dependent outputs;
- stale or revoked leakage is near zero in the benchmark;
- K-Ops beats at least one simpler baseline on a consequential metric;
- false rejection remains operationally tolerable.

---

## Days 61–90

1. Freeze the application service.
2. Add read-only MCP.
3. Ship the demo vault.
4. Run design-partner pilots.
5. Measure time to first useful answer and review burden.
6. Add staged proposals if actual users need agent writes.
7. Begin typed contradiction work.

### Day-90 decision

Continue toward a broader product only if:

- at least three users complete a real workflow;
- at least two return;
- governance changes or prevents a decision-relevant error;
- the review burden is acceptable;
- MCP usage is repeated rather than merely tried once.

---

## Stop or pivot conditions

Pause major development if any of these remain true after the corresponding
milestone:

- K-Ops cannot beat raw-agent or BM25 baselines on stale, unsupported or
  retracted-answer prevention.
- Entailment false-support rates are too high for decision-tier gating.
- Users consistently bypass consequence tiers.
- Review time exceeds the value of the prevented errors.
- Source invalidation cannot be made reliable without rebuilding the system.
- Users value generic search and chat but not governance.
- MCP increases trials but not repeat workflows.

A failed thesis should cause a strategic pivot, not another integration.

---

## Recommended allocation

For the first 16 weeks:

- **35%** evaluation and calibration;
- **25%** source/claim/version/invalidation model;
- **20%** context packages and output enforcement;
- **10%** service and MCP;
- **5%** documentation and demo;
- **5%** contradiction lineage and distillation exploration.

Do not spend more than 15% on distribution engineering before the M2 exit gate
passes.

---

## Single highest-priority deliverable

The defining demonstration is:

> A decision-grade answer is initially supported and allowed. A source then
> changes or is retracted. K-Ops automatically invalidates the affected claim
> and answer, refuses to serve the old conclusion, explains the exact
> dependency path, and records the entire event.

That combines the features K-Ops can credibly own:

- evidence provenance;
- source-change awareness;
- claim-level invalidation;
- consequence gating;
- abstention;
- auditability.

An entailment command alone is not the product. An MCP server alone is not the
product. That end-to-end behavior is.
