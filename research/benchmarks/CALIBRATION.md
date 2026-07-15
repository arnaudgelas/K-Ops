# Entailment Judge Calibration (roadmap J1.2)

Status of calibrating the J1.1 entailment judge (`kops/entailment_judge.py`)
for the question that gates M2: **is the judge trustworthy enough to gate
decision-tier outputs?** A single headline agreement percentage is explicitly
insufficient (roadmap J1.2), so this harness reports a confusion matrix by
claim type, per-adversarial-category agreement, a safety-critical false-support
rate, drift signals, and inter-annotator agreement.

## What is built (in-session, deterministic, no LLM)

- **Labeled calibration set** — `held-out/entailment_calibration.jsonl`.
  66 hand-authored `(claim, span, context, GOLD verdict)` pairs. GOLD labels are
  human-authored ground truth (that is the point of a fixture). Quotes are
  verbatim from the E1.1 Torque corpus (`held-out/corpus/notes/Sources/`).
  - Stratified by claim type: version-release, licensing, funding, security,
    governance, performance-throughput, quantitative-metric,
    processing-semantics, causal, temporal.
  - Straightforward pairs: 10 supported, 6 unsupported, 6 contradicted,
    6 not_evaluable (compound claims + missing/empty spans, which the judge's
    own guards must return as not_evaluable without a provider).
  - All eight roadmap adversarial failure types, each tagged with its
    `adversarial_type`:
    correct-quote-wrong-claim (6), partial-quote (5), reversed-causality (4),
    omitted-qualifier (5), wrong-temporal-scope (5), discussing-not-supporting (5),
    front-matter-as-evidence (4), derivative-as-corroboration (4).
  - Gold distribution: 27 unsupported, 13 contradicted, 10 supported,
    10 partial, 6 not_evaluable → **40 gold-negative cases** that a trustworthy
    judge must not call supported/partial (the denominator of false-support).

- **Calibration harness** — `kops/judge_calibration.py`
  (`python -m kops.judge_calibration`; deliberately not a `kb.py` subcommand).
  Computes:
  - **false-support rate** (the safety metric, reported first): the fraction of
    gold `unsupported`/`contradicted`/`not_evaluable` cases the judge called
    `supported`/`partial`;
  - **confusion matrix** overall and **by claim type** (predicted vs gold);
  - **agreement vs gold** overall and **per adversarial category**;
  - **model/prompt drift**: records the judge fingerprint + policy version with
    every run and flags any change between runs (`detect_drift`), embedded in
    the report vs the previous run;
  - **inter-annotator agreement (Cohen's kappa)**: implemented in stdlib,
    ingests two annotator label files; with fewer than two it returns a PENDING
    status rather than inventing labels.
  - Output: a dated `data/eval_runs/entailment-calibration-<YYYYMMDD>.jsonl`
    artifact plus a human-readable `.md` summary.

- **Tests** — `tests/test_judge_calibration.py`. Exact confusion-matrix cells
  and a known false-support rate on a synthetic set; hand-checked Cohen's kappa;
  PENDING when annotators are absent; drift flagged across runs; end-to-end via
  the sandboxed `KB_JUDGE_CMD` stub. No real LLM; no fabricated numbers.

## What is PENDING (and why)

These parts require human or real-model work that cannot be done in-session, and
are deliberately NOT faked (mirroring the M0 design-partner ledger convention):

1. **Expand to ≥150–250 stratified pairs.** The shipped 66 is the debug/seed
   tier (roadmap: "50 examples for implementation debugging"). Decision-tier
   gating needs ≥150–250. Remaining: author ≥84 more pairs (target 150) to ≥184
   (target 250), keeping the claim-type and adversarial-type stratification.
   `validate_coverage(...).meets_decision_gate_size` is `False` until then.
2. **Two human annotators + real inter-annotator agreement.** No human labels
   exist yet. `inter_annotator_agreement(None)` reports
   `PENDING: 2 human annotations required`. Deliverable: two independent human
   annotators label a meaningful subset; feed their files with `--annotator`.
3. **A real judge-provider run for actual false-support numbers.** Every
   in-session run uses an injected/stub predictor, so no false-support number
   here reflects a calibrated model. Deliverable: run
   `KB_JUDGE_AGENT=... python -m kops.judge_calibration` against the real
   provider and record the resulting artifact.

## Proposed decision-tier gate rule (PROPOSED — not yet ratified)

> Entailment may **not** gate decision-tier outputs until, on a run against the
> real provider:
> - **false-support rate ≤ 0.02** (≤ 2% of gold-negative cases called
>   supported/partial), on
> - **≥ 150 stratified pairs** covering all eight adversarial types, with
> - **≥ 2 human annotators** on a meaningful subset and
> - **Cohen's kappa ≥ 0.7** between them, and
> - **no unresolved drift** (judge fingerprint + policy version stable across
>   the calibration run and the gated run).

Rationale for the thresholds (all PROPOSED, tune against real data):

- **false-support ≤ 0.02** — fabricated support is the catastrophic failure for
  a decision gate (a confidently-wrong "supported" is worse than an abstention),
  so the bar is strict and is the primary gate.
- **≥ 150 pairs** — the roadmap floor; below it the rate estimate is too noisy
  to gate on.
- **kappa ≥ 0.7** — substantial human agreement; if humans cannot agree on the
  gold labels, the judge cannot be held to them.
- **drift-free** — a changed fingerprint/policy invalidates prior calibration,
  so a stale-but-passing number must not carry across the boundary.

Until the gate passes, entailment stays **advisory** for exploratory/recommendation
tiers (labels visible, not gating) per the tier policy matrix (C2.3).

## How to run

```bash
# Coverage of the labeled set (no judge invoked):
python -m kops.judge_calibration --coverage-only

# Full calibration against the real provider (writes a dated artifact):
KB_JUDGE_AGENT=codex python -m kops.judge_calibration \
  --annotator annotators/alice.jsonl --annotator annotators/bob.jsonl
```

Annotator files are JSONL of `{"pair_id": "...", "verdict": "..."}`.
