# Held-out Benchmark Corpus — MANIFEST (task E1.1)

A small, dense, versioned benchmark corpus for K-Ops M1. It is an **isolated
mini-vault** about a **fictional-but-plausible** open-source project, **Torque**
(a Rust stream-processing engine by Torque Labs). Content is authored fixtures —
that is expected and correct for a benchmark. It is internally consistent so the
contradictions and the retraction are deliberate, not accidental. No external
fetches; everything is deterministic.

Domain matches the P0.1 wedge: *technical / open-source project intelligence for
consequential product or investment decisions*.

## Layout

```
research/benchmarks/held-out/
  corpus/                          # loadable mini-vault (== snapshot 01 state)
    config/kb_config.yaml          # so KB_HOME / --vault can point here
    notes/Sources/src-*.md         # 20 source notes (schema.yaml frontmatter)
    notes/Concepts/*.md            # 5 concept pages (## Key Claims, ## Evidence / Source Basis)
    notes/Home.md
    data/registry.json             # registry list of all 20 sources
  snapshots/
    01-initial/                    # baseline state (state.json + SNAPSHOT.md)
    02-source-update/              # versioned source content_hash changes (state.json + overriding note)
    03-retraction/                 # a source revoked + contradiction crystallized
  questions.jsonl                  # 16 benchmark questions (+ 1 leading _comment line)
  MANIFEST.md                      # this file
```

`corpus/` is the initial (snapshot 01) state. Each snapshot under `snapshots/`
is a **diff from `corpus/`**: `state.json` is the authoritative logical state
(every source id → `content_hash` + `source_status`), and any `notes/Sources/*.md`
files in a snapshot directory are the note versions that **override** the
matching files in `corpus/`. Snapshots are cumulative: 02 carries forward into
03.

## How to run against it

The corpus is a self-contained vault. Point the retrieval tooling at it:

```
KB_HOME=research/benchmarks/held-out/corpus uv run python -m kops.search_vault "exactly-once"
```

`kops/run_full_benchmark.py` and `kops/eval_set_disjoint.py` already expect
`research/benchmarks/held-out/questions.jsonl`. See **Divergence** below for how
the question schema aligns and where it does not.

## Source inventory (id → tier → kind → role / what it says)

Primary sources (prefix `fac`):

| id | kind | evidence | what it says |
|----|------|----------|--------------|
| src-fac0000001 | official-doc | changelog | v2.0.0 GA on 2026-01-15; introduces exactly-once; Apache-2.0; exactly-once enabled by `processing.guarantee = exactly_once` in `torque.toml`. |
| src-fac0000002 | official-doc | changelog | **VERSIONED source.** Latest release notes. Snapshot 01 = v2.1.0 with memory leak #812 OPEN. Snapshot 02/03 = v2.1.1 with leak FIXED + RCE patched. |
| src-fac0000003 | github-file | pr-issue | Issue #812: memory leak in windowed aggregation; OPEN on v2.1.0 in snapshot 01. |
| src-fac0000004 | official-doc | primary-doc | Security advisory TQ-SA-2026-001: deserialization RCE (CVSS 9.1), affects 2.0.0–2.1.0, fixed in v2.1.1. |
| src-fac0000005 | blog | primary-doc | Series A: $18M led by Northwind Ventures, 2026-02-20. **Origin of derived news src-5ec0000011.** |
| src-fac0000006 | github-file | maintainer-commentary | Roadmap: v3.0 adds distributed multi-node mode, targeted Q4 2026. |
| src-fac0000007 | blog | maintainer-commentary | **Vendor benchmark:** 1.2M events/sec on an 8-core node. **Origin of the derivative pair (012, 013).** |
| src-fac0000008 | github-file | pr-issue | PR #905: proposes relicensing v3.0 from Apache-2.0 to BSL 1.1 (not merged). |
| src-fac0000009 | github-repo-snapshot | code | Repo snapshot 2026-04-01: 14,200 stars, 187 contributors, `main`@9f3c2a1. **Time-sensitive.** |
| src-fac0000010 | official-doc | primary-doc | GOVERNANCE.md: only Torque Labs employees can merge → single-vendor control. **Contradiction anchor.** |

Secondary sources (prefix `5ec`):

| id | kind | evidence | role / what it says |
|----|------|----------|---------------------|
| src-5ec0000011 | news | secondary | Trade-press: repeats the $18M Northwind Series A. **Derived from src-fac0000005.** |
| src-5ec0000012 | blog | secondary | StreamWeekly: repeats 1.2M events/sec. **Derivative pair #1, derived from src-fac0000007.** |
| src-5ec0000013 | blog | secondary | DataEng Digest: repeats 1.2M events/sec. **Derivative pair #2, derived from src-fac0000007.** |
| src-5ec0000014 | blog | secondary | Community thread: argues exactly-once is really at-least-once + dedup. **Contradicts src-fac0000001.** |
| src-5ec0000015 | imported-model-report | model-generated | Analyst memo: calls Torque community-driven / vendor-neutral (UNVERIFIED). **Contradicts src-fac0000010.** |
| src-5ec0000016 | blog | secondary | Blog: "Torque hits 5M events/sec." **RETRACTED in snapshot 03** (revoked). Also contradicts vendor 1.2M. |
| src-5ec0000017 | blog | secondary | Torque vs Fluxion comparison (opinion). |
| src-5ec0000018 | blog | secondary | Founder podcast interview summary. |
| src-5ec0000019 | blog | secondary | Community 1.x→2.x migration guide. |
| src-5ec0000020 | blog | stub | "Awesome Stream Processing" listing entry (low signal). |

20 sources total (10 primary, 10 secondary) — within the 15–30 range.

## How each acceptance-criteria element is realized

- **Two source versions (content_hash changes):** `src-fac0000002` is the
  versioned source. Snapshot 01 documents v2.1.0 (`content_hash` A); snapshot 02
  replaces it with the v2.1.1 release notes (`content_hash` B ≠ A). The
  supporting claim flips: the memory leak goes from *unresolved* to *fixed*. Both
  `state.json` files and the overriding note in `snapshots/02-source-update/`
  record this.
- **Explicit contradictions (≥1 pair):**
  1. *Exactly-once:* src-fac0000001 (vendor claims exactly-once) vs
     src-5ec0000014 (community says at-least-once + dedup).
  2. *Governance:* src-fac0000010 (single-vendor control) vs src-5ec0000015
     (analyst calls it community-driven).
  Surfaced in `Torque_Processing_Semantics.md` and `Torque_Governance_And_Funding.md`.
- **Retracted / revoked source:** src-5ec0000016 (the 5M events/sec blog). In
  `snapshots/03-retraction/` it becomes `source_status: revoked` with
  `retracted_at` and `retraction_reason`; the overriding note carries the
  retraction frontmatter.
- **Duplicated / derivative reporting:** src-5ec0000012 and src-5ec0000013 both
  repeat the 1.2M figure, and both trace to the single vendor benchmark
  src-fac0000007 (`derived_from`). Two secondaries, one primary origin → **not**
  independent corroboration. (Separately, src-5ec0000011 is derived from the
  funding announcement src-fac0000005.)
- **Insufficient-evidence questions (abstention):** `q-trap-01` (2027 revenue)
  and `q-trap-02` (managed-service cloud provider) — the corpus genuinely holds
  no such data; the correct behavior is to abstain.
- **Time-sensitive claims:** `q-freshness-01` (latest stable release),
  `q-freshness-02` (stars/contributors, `as_of` 2026-04-01), and
  `q-freshness-03` (is leak #812 fixed) — answers depend on date/snapshot.

## Questions schema (`questions.jsonl`)

One JSON object per line. The first line is a `{"_comment": ...}` header, which
`run_full_benchmark.py` and `eval_set_disjoint.py` both skip.

Fields consumed by `kops/run_full_benchmark.py`:

- `id` — unique question id (`q-<class>-NN`).
- `question` — the question text.
- `class` — one of `lookup | synthesis | freshness | code | trap`.
- `expected_answer_facts` — list of fact strings checked by keyword overlap.
- `required_source_ids` — source ids that must back the answer (empty for
  insufficient-evidence traps).

Extra fields (ignored by the runner, used by later M1 tasks / documented here):

- `insufficient_evidence` (bool) — the corpus cannot answer; abstention is correct.
- `time_sensitive` (bool) + `as_of` (date) — answer depends on date.
- `contradiction` (bool) — answer must surface a source conflict.
- `derivative_trap` (bool) — answer must not treat derived reports as independent.
- `catastrophic` (bool) — a confidently wrong answer is a catastrophic failure
  (mirrors the runner's catastrophic result categories: fabricated-citation,
  wrong-source, contradicted-by-source).
- `snapshot_variance` — for questions whose correct answer differs by snapshot,
  the expected answer per snapshot.

Coverage: 16 questions — lookup ×4, synthesis ×4, freshness ×3, code ×1, trap ×4;
2 insufficient-evidence, 3 time-sensitive, 2 contradiction, 1 derivative, 4
catastrophic.

## Divergence from `run_full_benchmark.py` (documented)

- `run_full_benchmark.py` reads `questions.jsonl` from this directory but
  retrieves against the **real** vault (`notes/`), which does not contain
  Torque. This corpus is deliberately isolated to keep the real research vault
  clean. To evaluate against the corpus, a harness must set
  `KB_HOME=research/benchmarks/held-out/corpus` (or pass `--vault`) so
  `VaultIndex` / `search_vault` index the mini-vault. The `config/kb_config.yaml`
  in `corpus/` makes it auto-detectable as a vault root.
- The runner's `evaluate_mode_b` reads `expected_answer_facts` and
  `required_source_ids`, which are present. Trap questions with empty
  `required_source_ids` are intentional (abstention).

## Snapshot summary

| snapshot | change from previous | net state |
|----------|----------------------|-----------|
| 01-initial | — | v2.1.0 latest; leak #812 open; 5M blog active; all contradictions live |
| 02-source-update | src-fac0000002 → v2.1.1 (content_hash changes) | leak fixed; RCE patched; latest = v2.1.1 |
| 03-retraction | src-5ec0000016 → revoked (retraction frontmatter) | 5M claim retracted; only vendor 1.2M survives |

The invariants above are enforced by `tests/test_benchmark_corpus.py`.
