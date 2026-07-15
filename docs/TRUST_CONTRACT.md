# K-Ops — Trust Contract

This document defines K-Ops's trust vocabulary precisely and grounds every term
in what the code does **today**. It is the reference for what each status word
is allowed to mean, how it is produced, whether it is deterministic, and whether
it can stop a compile, a promotion, or a served answer.

Companion documents: [DESIGN.md](DESIGN.md) (trust model and limits) and
[ROADMAP.md](ROADMAP.md) task `T0.1` (the acceptance criteria this document
satisfies).

## How to read this document

- **IMPLEMENTED TODAY** — behaviour you can observe by running the cited code.
  Every such claim names a source file and line range as evidence.
- **PLANNED — NOT IMPLEMENTED** — described in the roadmap or design notes but
  with no enforcing code. These are marked explicitly and must never be
  presented as a live guarantee.

There is no unqualified word "trusted" in this contract. Wherever trust is
asserted, the specific guarantee is named (e.g. "the cited quote exists in the
source", not "the source is trusted"). If you extend this document, keep that
rule.

---

## 1. Object identity and version (what "human-reviewed" pins)

A review, a verdict, or an admission is only meaningful against a **named object
at a named version**. K-Ops has three identity handles, all deterministic:

- **Source version — `content_hash`.** A source note records `content_hash`, the
  SHA-256 of the raw content the summary was built from (`schema.yaml:14-15`;
  `content_drift.py` docstring). "This source was reviewed" therefore means
  "the raw content whose SHA-256 is `content_hash` was reviewed." When the raw
  content changes, its hash changes, and `check-content-drift` flags the source
  note and every derived page `revalidation_required` because the reviewed
  version no longer matches on-disk reality (`content_drift.py:1-25`). For
  GitHub-repo sources the analogous version handle is the recorded `git_commit`
  (`check_source_drift.py`).
- **Source identity — `source_id`.** The canonical `src-[0-9a-f]{10}` id,
  format-validated in `kb_schema.py:25,110-119`.
- **Claim identity — `claim_id`.** Content-addressable: `clm-` plus the first 10
  hex of `sha256(concept_stem + ":" + normalized_claim_text)`
  (`claim_registry.py:164-167`). The id changes if the claim text changes, so a
  review recorded against a `claim_id` is implicitly a review of that exact
  wording.

**Rule:** any statement that an object was human-reviewed MUST cite the object's
identity handle (`source_id` / `claim_id`) **and** its version handle
(`content_hash` or `git_commit`). A review with no version handle is a review of
nothing checkable, because drift cannot be detected against it.

> Object-versioned review *records* (a first-class validation-event log binding
> reviewer, timestamp, `claim_id`, and `content_hash`) are **PLANNED — NOT
> IMPLEMENTED**. Today the version handles exist and drift is detectable, but the
> review event itself lives in Git history and note frontmatter, not in a
> dedicated audit log.

---

## 2. The two separate questions: "quote exists" vs "quote supports claim"

These are different guarantees with different implementations and different
trust levels. Conflating them is the single most important error this contract
exists to prevent.

| Question | Term | Status | Mechanism |
|---|---|---|---|
| Does the cited quote literally appear in the source? | **quote existence** | IMPLEMENTED, deterministic | `span_verify.py` / `verify-spans` |
| Does that quote actually *support* the claim it is cited for? | **entailment** | **PLANNED — NOT IMPLEMENTED** | needs an LLM judge; a separate, lower-trust layer |

- **Quote existence (IMPLEMENTED).** For every claim anchor carrying a
  `quote=…`, `span_verify.py` resolves the source text and checks the quote is
  present verbatim, modulo whitespace/Unicode-punctuation folding, or across an
  ellipsis bridge (`span_verify.py:101-135`). Per-claim verdicts are `verified`,
  `failed`, `unverifiable`, or `absent` (`span_verify.py:25-34, 143-188`). This
  is purely deterministic string matching; no model is involved.
- **Entailment (NOT IMPLEMENTED).** The module's own scope boundary states it
  plainly: it verifies "**existence** (the quote is in the source), not
  **entailment** (the quote supports the claim). Entailment needs an LLM judge
  and is a separate, lower-trust layer" (`span_verify.py:16-24`). A `verified`
  span "does not certify that the source *substantiates* the claim." Nothing in
  K-Ops today judges whether a quote entails its claim. Do not describe K-Ops as
  checking citation support.

---

## 3. Field-level status vocabulary (what the code actually stores)

These are the concrete frontmatter/registry fields the code reads and writes.
The roadmap-named terms in Section 4 are built on top of them.

For each term: **(1)** definition · **(2)** measurement · **(3)** deterministic
vs probabilistic · **(4)** failure modes · **(5)** can it block
compile/promotion/serving · **(6)** override authority · **(7)** audit.

### 3.1 `evidence_status` (two distinct namespaces — do not conflate)

There are **two** fields named `evidence_status`. They share a name only.

**(a) Claim-level `evidence_status` ∈ {`direct`, `inherited`, `unsupported`}**
1. How well a specific claim is anchored to its sources: `direct` = the claim
   bullet carries an inline source link; `inherited` = no inline link but the
   concept's Evidence section cites sources; `unsupported` = neither
   (`claim_registry.py:319-324`).
2. Measured deterministically from link presence during claim extraction.
3. Deterministic.
4. `inherited` overstates support (the page cites sources but this bullet does
   not); a claim can be `direct` yet cite an irrelevant source (existence, not
   entailment).
5. **Blocks promotion/serving via the consequence gate:** `unsupported` fails
   `decision` and `autonomous`; anything other than `direct` fails `autonomous`
   (`consequence_gate.py:51-52, 63-64`). Does not block compilation.
6. Machine-derived; override by editing the concept page's links, then
   re-running `extract-claims`. Never hand-edited in `data/claims.json`.
7. Recorded per claim in `data/claims.json`.

**(b) Concept-page `evidence_status` ∈ {`seed`, `synthesized`, `verified`,
`contested`}**
1. Lifecycle stage of a concept page, machine-derived and set by `compile-wiki`
   (`schema.yaml:70`).
2. Set by the compile step.
3. Deterministic (rule-based), but the underlying judgement it summarises can be
   probabilistic upstream.
4. The value `verified` here is **page-lifecycle "verified", not
   quote-verified and not entailment-verified** — see Section 6 on overloaded
   terms.
5. **Blocks compilation:** it is schema-enforced. `validate_concept_page`
   rejects any value outside the enum (`kb_schema.py:208-220`), so a bad value
   fails strict validation.
6. Machine-derived by compile; a human overrides by re-compiling, not by hand.
7. Schema-validated on every concept page.

### 3.2 `admission_status` ∈ {`admitted`, `quarantine`, `blocked`, `unknown`, `unsupported`}

1. Whether the evidence *behind a claim* is allowed to carry weight. Derived by
   taking the worst status across the claim's sources
   (`claim_registry.py:136-161`). Per-source classification
   (`_classify_source`, `claim_registry.py:102-133`): `blocked` if
   `source_status` is a blocked value or `adversarial_content: true`;
   `quarantine` if deprecated / weak evidence strength / model-report kind /
   verification pending; `unknown` if the source note is missing; otherwise
   `admitted`. A claim with no sources at all is `unsupported`.
2. Measured deterministically from source frontmatter at extraction time.
3. Deterministic.
4. `admitted` means "not disqualified", not "correct" — it is a floor, not a
   proof. `unknown` (missing source note) is a data-integrity gap, not a safe
   state.
5. **Blocks promotion/serving via the consequence gate:** `blocked` fails every
   tier from `recommendation` up; `quarantine` / `unknown` / `unsupported` fail
   `decision` and `autonomous`; only `admitted` clears `autonomous`
   (`consequence_gate.py:43-62`). Does not block compilation.
6. Machine-derived; override by fixing the source's status/metadata and
   re-running `extract-claims`.
7. Recorded per claim with `admission_reasons` in `data/claims.json`.

> Note: the passing value emitted by the code is `admitted`
> (`claim_registry.py:133,161`). Earlier prose sometimes wrote "supported" for
> this slot; the ground-truth token is **`admitted`**. `supported` is a
> *`claim_quality`* value (Section 4.1), a different field.

### 3.3 `source_status` ∈ {`active`, `deprecated`, `revoked`, `permission-revoked`, `deleted-from-origin`, `do-not-use`}

1. The lifecycle/authority state of a source note. `active` = usable;
   `deprecated` = superseded (→ quarantine); the four **blocked** values
   (`revoked`, `permission-revoked`, `deleted-from-origin`, `do-not-use`) mean
   the source must not back any admitted claim (`claim_registry.py:77-79`;
   `retract_source.py:46`).
2. Set by hand or by `retract` (`retract_source.py:112-118`).
3. Deterministic in effect (its downstream classification is rule-based).
4. **Schema does not enforce the enum.** `schema.yaml:12` documents
   `active | deprecated | revoked` in a comment, but `validate_source_note`
   only checks *required-field presence*, not the value
   (`kb_schema.py:106-190`). So the four extended blocked values are honoured by
   `claim_registry`/`retract` but a typo'd `source_status` will not be caught by
   validation — contrast `evidence_status` on concept pages, which **is** enum-
   validated (`kb_schema.py:208-220`). This asymmetry is a known gap.
5. **Blocks promotion/serving indirectly:** a blocked value flips dependent
   claims to `admission_status: blocked`, which the consequence gate bars
   (Section 3.2). Does not block compilation, but flags the source in the
   compile plan (`kb_runtime.py:258-259`).
6. Human-authored, or set by `retract`. Reversing a retraction is a human Git
   edit.
7. `retract` stamps `retracted_at` and `retraction_reason` and records the blast
   radius (`retract_source.py:112-118, 201-215`).

### 3.4 `adversarial_content` (boolean)

1. `true` when a fetch detected prompt-injection attempts or manipulative
   instructions inside the source text (`kb_schema.py:149-152`).
2. Set at ingest; schema-validated to be a boolean (`kb_schema.py:152-161`).
3. Deterministic in effect (a boolean flag), though the upstream *detection* is
   heuristic/probabilistic.
4. False negatives: undetected injection leaves the flag `false`. The flag marks
   the *source*, not the individual sentence.
5. **Blocks promotion/serving:** `true` classifies the source `blocked`
   (`claim_registry.py:117-118`), barring its claims at `recommendation`+; it
   also flags the source in the compile plan (`kb_runtime.py:252-253`).
6. Human/ingest-set; override by human review + edit.
7. Surfaces in the compile plan and, transitively, in `review-queue`.

### 3.5 `prompt_injection_detected` (boolean)

1. `true` when the runtime registry entry recorded a detected injection attempt
   (`kb_runtime.py:254-255`).
2. Set at ingest/fetch.
3. Deterministic flag; probabilistic detection upstream.
4. **Important boundary:** unlike `adversarial_content`, this flag is **not**
   wired into `claim_registry._classify_source`, so on its own it does **not**
   change a claim's `admission_status` and the consequence gate does **not** bar
   a claim for it. It is a **review flag**, not an admission blocker. To block
   claims, the source must also carry `adversarial_content: true` or a blocked
   `source_status`.
5. **Blocks compilation surface only as a flag:** it adds the source to the
   compile plan's flagged list (`kb_runtime.py:254-255`) and thus to
   `review-queue`; it does not by itself stop serving.
6. Human review decides whether to escalate it to `adversarial_content`/
   `source_status`.
7. Recorded on the registry entry; surfaced in the compile plan.

---

## 4. Roadmap trust vocabulary

The `T0.1` terms, mapped to the fields above.

### 4.1 supported

1. A value of `claim_quality` (`schema.yaml:68`, enum
   `supported | provisional | weak | conflicting | stale`), declared in concept-
   page frontmatter, asserting the claim is backed by its evidence.
2. **Human-authored** in frontmatter; the registry copies it onto each claim
   (`claim_registry.py:305, 351-352`). It is *not* machine-derived and *not*
   quote- or entailment-checked.
3. **Probabilistic / editorial** — it reflects a human judgement, not a
   deterministic check.
4. Its biggest failure mode: `supported` can be asserted on a claim whose quote
   was never verified or does not entail it. `supported` ≠ `verified` ≠
   `admitted`.
5. **Blocks promotion/serving:** `autonomous` requires `claim_quality ==
   supported` (`consequence_gate.py:65-66`); `weak`/`conflicting`/`stale` fail
   `decision` (`consequence_gate.py:53-54`). Does not block compilation.
6. Author-set; changeable by a human editing the page.
7. Lives in page frontmatter and `data/claims.json`.

### 4.2 verified

**Overloaded — always name which "verified" you mean** (see Section 6):

- **quote-verified** — `span_verify` verdict `verified`: every quote anchor was
  found in its source. Deterministic (`span_verify.py:27, 143-188`).
  Existence only, never entailment.
- **page-verified** — concept `evidence_status: verified`: a compile lifecycle
  stage (Section 3.1b), schema-validated but unrelated to quote checking.

1. See the two senses above.
2. quote-verified is measured by `verify-spans`; page-verified is set by
   `compile-wiki`.
3. quote-verified: deterministic. page-verified: rule-based label over
   possibly-probabilistic inputs.
4. Neither sense implies entailment. Neither implies the claim is true.
5. quote-verified **blocks serving via `--check`**: `verify-spans --check` exits
   non-zero when any claim is `failed` (`span_verify.py:299-306`). page-verified
   **blocks compilation** via schema enum (`kb_schema.py:208-220`).
6. Both machine-derived; overridden by fixing the underlying object and
   re-running the respective command, not by hand-editing the artifact.
7. quote-verified is written to `data/span_verification.json`
   (`span_verify.py:278-297`).

### 4.3 admitted

1. The passing value of `admission_status` (Section 3.2): the evidence behind a
   claim is not disqualified by source status, adversarial content, quarantine,
   missing note, or absent sourcing.
2. Deterministically derived from source frontmatter (`claim_registry.py:102-161`).
3. Deterministic.
4. `admitted` is a floor ("nothing disqualifying"), not proof of correctness or
   relevance.
5. **Blocks promotion/serving:** the `autonomous` tier requires `admitted`
   (`consequence_gate.py:61-62`). Does not block compilation.
6. Machine-derived; override by correcting source metadata + re-running
   `extract-claims`.
7. `data/claims.json` with `admission_reasons`.

### 4.4 stale

1. Evidence or a claim that is out of date. Two mechanisms: (a) `claim_quality:
   stale`, an editorial frontmatter value; (b) drift-driven staleness —
   `check-content-drift` sets `revalidation_required: true` on a source note and
   its derived pages when `content_hash` diverges from the current raw content
   (`content_drift.py:1-25`), and `retract` sets the same flag across a revoked
   source's blast radius (`retract_source.py:121-128, 185-194`).
2. (a) human-set; (b) deterministic hash comparison (no re-fetch).
3. (a) editorial/probabilistic; (b) deterministic.
4. `claim_quality: stale` is a human judgement that can lag reality; the drift
   check only fires if a baseline `content_hash` was recorded
   (`backfill-content-hash` seeds it).
5. **Blocks promotion/serving:** `claim_quality: stale` fails `decision`
   (`consequence_gate.py:53-54`). `revalidation_required` surfaces in
   `stale-impact`/`review-queue` but does **not** by itself hard-block serving.
6. Human review clears `revalidation_required` after re-curation; `claim_quality`
   is author-set.
7. Drift flags carry `revalidation_reason`; the automatic full invalidation
   cascade beyond flagging is **PLANNED — NOT IMPLEMENTED** (`DESIGN.md:203`).

### 4.5 independent

1. Two or more sources being genuinely independent lines of evidence (not
   copies, re-hosts, or a model summarising the same origin).
2. **PLANNED — NOT IMPLEMENTED.** No code computes or enforces source
   independence today. Source-independence typing is scheduled for milestone M4
   (`ROADMAP.md:49`). The only related code is link-suggestion heuristics
   (`graph_link_candidates.py`, `kb_suggest_links.py`), which do not establish
   evidential independence.
3. n/a (not implemented).
4. Because it is unenforced, no K-Ops output today may claim that two sources are
   "independent corroboration."
5. Cannot block anything today.
6. n/a.
7. n/a until implemented.

### 4.6 decision-grade

1. Not a stored field: a *derived* property meaning "this evidence clears the
   `decision` consequence tier." Evidence is decision-grade iff
   `consequence-gate --tier decision` reports it clears the bar
   (`consequence_gate.py:48-58`).
2. Computed deterministically by the consequence gate over the claim registry.
3. Deterministic.
4. It certifies the evidence bar (admitted, supported/not-weak, non-stale,
   non-synthetic, sourced) — it does **not** certify entailment or truth. A
   decision-grade claim can still cite a quote that does not entail it.
5. **Blocks promotion/serving:** `consequence-gate --tier decision --check`
   exits non-zero when the bar is not cleared (`consequence_gate.py:119-122`).
6. Machine-derived; the bar itself is fixed policy in `consequence_gate.py`.
7. Gate result is printable as JSON (`consequence_gate.py:107-110`).

---

## 5. Consequence tiers — formal policy for each

Source of truth: `consequence_gate.py:28-91`. The gate reads the claim registry
only, applies no LLM judgement, and **reports and gates but never rewrites
claims** (`consequence_gate.py:17-18`). `--check` exits non-zero when the tier's
bar is not cleared (`consequence_gate.py:119-122`). Tiers are strictly nested:
each higher tier adds bars, never removes them.

### Tier: exploratory

- **Intent:** brainstorming / orientation. No bar.
- **Policy:** every claim clears; no admission or quality requirement
  (`consequence_gate.py:33-34`).
- **Deterministic:** yes (trivially).
- **Blocks?** Never blocks.
- **Override authority:** none needed.
- **Audit:** gate output optional.

### Tier: recommendation

- **Intent:** advice a human will weigh before acting.
- **Policy:** bars any claim whose `admission_status == blocked` — i.e. resting
  on a revoked / do-not-use / adversarial source (`consequence_gate.py:42-46`).
  Nothing else is barred at this tier.
- **Deterministic:** yes.
- **Failure mode:** a merely-`quarantine`/`unsupported` claim still passes here;
  quarantined evidence can inform a recommendation.
- **Blocks?** Blocks serving/promotion of the answer under `--check` if any claim
  is `blocked`.
- **Override authority:** a human must clear the source's blocked status
  (unblock/re-admit) via edit or reverse-`retract`.
- **Audit:** violations list each blocked `claim_id` and reason.

### Tier: decision

- **Intent:** a choice will be made on this evidence.
- **Policy:** all `recommendation` bars, **plus** bars
  `admission_status ∈ {quarantine, unknown, unsupported}`,
  `evidence_status == unsupported`,
  `claim_quality ∈ {weak, conflicting, stale}`, and any `synthetic_origin`
  claim (`consequence_gate.py:48-58`).
- **Deterministic:** yes.
- **Failure mode:** it enforces the *evidence bar*, not entailment or truth — a
  decision-grade claim may still cite a non-entailing quote.
- **Blocks?** Blocks serving/promotion under `--check`.
- **Override authority:** human must upgrade the underlying evidence (re-source,
  re-quality, re-admit) and re-run; the bar is not tunable per answer.
- **Audit:** per-claim `reasons` (e.g. `admission:quarantine`,
  `claim-quality:stale`, `synthetic-origin`).

### Tier: autonomous

- **Intent:** an agent may act without human review — the strongest bar.
- **Policy:** every claim must be **exactly** `admission_status == admitted`,
  `evidence_status == direct` (inline-cited, no inherited support), and
  `claim_quality == supported` (`consequence_gate.py:60-67`).
- **Deterministic:** yes.
- **Failure mode:** even a fully-passing set is only "cleared the strongest
  *deterministic* bar." It still does **not** prove entailment or truth, and
  entailment checking does not exist (Section 2). Autonomous action on K-Ops
  evidence is therefore not endorsed by this contract today; `DESIGN.md:210`
  states agent runs still require human review before consequential use.
- **Blocks?** Blocks serving/promotion under `--check`.
- **Override authority:** none intended — this tier is meant to be un-overridable
  short of fixing every claim.
- **Audit:** per-claim `reasons` (`not-admitted:*`, `evidence-not-direct:*`,
  `quality-not-supported:*`).

---

## 6. Overloaded terms and the "trusted" audit

Three trap-words carry different guarantees in different places. Always qualify
them.

- **"verified"** — could mean quote-existence (`span_verify`), or concept
  page-lifecycle (`evidence_status: verified`). Neither means entailment. Say
  which.
- **"supported"** — the `claim_quality` editorial value (human-set), *not* the
  `admission_status` pass value (that is `admitted`, machine-derived). Different
  fields, different producers.
- **"admitted" vs "supported" vs "verified" vs "decision-grade"** — four
  distinct bars. A claim can be `admitted` (source not disqualified) yet not
  `supported` (weak), or `supported` yet not quote-`verified`, or
  quote-`verified` yet not entailing.

**"trusted" audit of this document:** the word "trusted" is not used as a
standalone guarantee anywhere above. Each guarantee names its mechanism (quote
exists / source not blocked / evidence bar cleared / schema-valid). If you add
text, do not write "trusted source", "trusted claim", or "trusted answer" —
write the specific guarantee.

---

## 7. Planned — not implemented (do not present as live guarantees)

- **Citation entailment (LLM judge)** — whether a verified quote actually
  supports its claim (`span_verify.py:16-24`, `DESIGN.md:169-170`).
- **Automatic content-hash invalidation cascade** — beyond flagging
  `revalidation_required`, a full automatic cascade is not implemented
  (`DESIGN.md:203`).
- **Source independence typing** — Section 4.5; milestone M4 (`ROADMAP.md:49`).
- **Object-versioned validation-event log** — a first-class record binding
  reviewer + timestamp + `claim_id` + `content_hash` (Section 1); today reviews
  live in Git history and frontmatter.
- **Context packages / stable context API** — milestone M3 (`ROADMAP.md:48`).
- **`source_status` enum validation** — the extended blocked values are honoured
  by the registry but not schema-enforced (Section 3.3).

---

## Related

- [DESIGN.md](DESIGN.md) — Trust Model and Limits; Admission Rule; Implemented
  vs planned.
- [ROADMAP.md](ROADMAP.md) — `T0.1` acceptance criteria and milestone map.
- Enforcing code: `kops/consequence_gate.py`, `kops/claim_registry.py`,
  `kops/span_verify.py`, `kops/retract_source.py`, `kops/content_drift.py`,
  `kops/kb_schema.py`, `kops/schema.yaml`.
