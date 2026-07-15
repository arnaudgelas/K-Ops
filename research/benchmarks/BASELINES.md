# M1 Comparison Baselines (`E1.3`)

Runners that put the SAME benchmark questions through several distinct
configurations so the M1 thesis — that K-Ops **governance** beats simpler
approaches — can be measured, not asserted. Implemented in `kops/baselines.py`;
tests in `tests/test_baselines.py`.

## The four baselines

| Baseline | Retrieval | Governance | What it isolates |
|---|---|---|---|
| `raw-agent` | none (empty context) | off | Bare LLM with no grounding in the corpus. |
| `bm25-agent` | `VaultIndex.bm25(command="search", include_flagged=True)` | **off** | "Just BM25 + an LLM" strawman. Flagged/revoked/adversarial sources are NOT excluded. |
| `current-kops` | `VaultIndex.search(command="ask")` | **on** | The real governed `ask` path; flagged sources excluded before the provider sees them. |
| `improved-kops` | `search(command="ask")` (+ M1 hook) | on | Same as current-kops today, behind the `improved` flag. Hook for M1 evidence-model / atomic-claim / entailment wiring — see `TODO(E1.2)` in `_retrieve_governed`. |

`raw-agent` uses an **empty** context (not a whole-corpus dump) so the
"no retrieval" condition is unambiguous and cheap; the whole-corpus variant is a
possible future addition.

The governance axis is the point: `bm25-agent` passes `include_flagged=True` so
it deliberately gets none of K-Ops's exclusion filtering, while `current-kops`
uses `command="ask"` with exclusion on by default. The test
`test_governance_difference_is_demonstrated` asserts a flagged source present in
`bm25-agent`'s context is absent from `current-kops`'s.

### Optional: `compiled-wiki`
A reproducible compiled-wiki comparator is **not** available yet. The slot
exists as a documented stub (`baselines.compiled_wiki_stub`) that raises
`NotImplementedError` rather than fabricating a comparator. Wire a real
implementation there when the artifact is reproducible.

## Injectable provider

The LLM is the only place a baseline could touch a model, so it is injected as a
`Provider` (name + `fingerprint` + `generate(question, context) -> str`). This
keeps the whole harness deterministic and offline. There is no RNG.

- `DeterministicProvider` — offline, canned answers. Used by every test and by
  the default CLI provider. Fingerprint reflects its canned config.
- `AgentCliProvider(agent)` — REAL provider. Invokes the provider CLI
  (`codex`/`claude`/`gemini`) read-only and captures stdout. Never exercised by
  the test suite; used only for real benchmark runs.

## Running

Offline dry run (deterministic provider — no LLM, no network):

```
uv run python -m kops.baselines \
  --vault research/benchmarks/held-out/corpus \
  --provider deterministic
```

Writes `<vault>/data/baseline_runs/<date>.jsonl` (override with `--out`).
`--vault` must contain `config/kb_config.yaml`; questions default to
`<vault>/../questions.jsonl` (the E1.1 held-out set). Restrict baselines with
repeatable `--baseline`, e.g. `--baseline bm25-agent --baseline current-kops`.

Real run (requires a provider CLI, or a `KB_*_CMD` stub, on PATH):

```
uv run python -m kops.baselines \
  --vault research/benchmarks/held-out/corpus \
  --provider agent-cli:codex \
  --out data/baseline_runs/$(date +%F).jsonl
```

**Do not fabricate benchmark numbers.** A real run must use `agent-cli:*`; the
deterministic provider produces canned text only, for harness reproducibility.

## Output record schema (JSON Lines)

One object per (baseline, question), consumed by the E1.4 metrics harness:

| Field | Meaning |
|---|---|
| `baseline` | `raw-agent` \| `bm25-agent` \| `current-kops` \| `improved-kops` |
| `question`, `question_id` | the query and its id (from `questions.jsonl`) |
| `retrieval_method` | `none` \| `bm25-lexical` \| `governed-ask` |
| `governance` | bool — whether K-Ops exclusion/governance was applied |
| `improved` | bool — whether the M1 improvements hook is active |
| `retrieved` | list of `{id, kind, retrieval_method, score, snippet, source_id, anchor}` |
| `retrieved_ids` | convenience list of retrieved ids |
| `context` | exact context string handed to the provider (empty for `raw-agent`) |
| `answer` | provider answer text |
| `provider`, `provider_fingerprint` | provider provenance |
| `top_k`, `generated_at` | run parameters |
