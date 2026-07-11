---
title: "K-Ops / OKF-RVF Design Review 2026-06-17"
type: maintenance
tags:
  - kb/maintenance
  - kb/review
created: 2026-06-17
---

# K-Ops / OKF-RVF Design Review

**Scope reviewed:** OPERATING_RULES.md, all SKILL.md files, templates, agent definitions, scripts (kb.py, lint_vault.py, claim_registry.py, contradiction_registry.py, vault_graph.py, scorecard, kb_runtime, utils), schema.yaml, kb_config.yaml, all runbooks, all index pages, the .claude/.codex/.gemini triplication, and the live vault state (scorecard, TODO, Contradictions, sources).

---

## I. Architecture & Structural Integrity

### CRIT-1 — Three levels of instructions for the same roles, with no canonical authority

There are three overlapping specifications for each agent role: (a) `.claude/agents/*.md` (4 agents, ~3 bullets each, extremely thin), (b) `.claude/skills/*/SKILL.md` (detailed behavior rules), and (c) `templates/*_prompt.md` (the most complete spec, with schemas, checklists, and step-by-step protocols). These frequently diverge.

Example: the compile task in `SKILL.md` requires a "Compile Log Requirement" section, while `templates/compile_prompt.md` has a more detailed Step 4 with identical but differently worded requirements. Any developer updating one doesn't know they must update the other two.

**Recommendation:** Collapse to two tiers. Delete `.claude/agents/*.md` as redundant. Elevate `SKILL.md` to be the single canonical spec; `templates/*_prompt.md` becomes the runtime-rendered prompt that can reference `SKILL.md` content. Establish a clear rule: OPERATING_RULES.md = invariants; SKILL.md = per-role behavior; template = injected context for the prompt.

---

### CRIT-2 — Triplication of skills across `.claude/`, `.codex/`, `.gemini/` makes drift inevitable

Every skill exists three times. OPERATING_RULES.md is the single-source contract, but skills are copy-pasted into three directories. The `install-agent-assets` command presumably syncs them, but `kops/install_agent_assets.py` is not documented and it's unclear which direction the sync flows (skills/ → runtime dirs, or runtime dirs → skills/). Any edit to ingest-sources SKILL.md requires 3 identical changes.

**Recommendation:** Maintain skills in one canonical location (e.g., `skills/` at root). `install-agent-assets` should be the authoritative sync script and its behavior must be documented in the runbook. Add a lint check that all three runtime skill files are byte-identical to the canonical source.

---

### CRIT-3 — `DualLinkPattern` is copy-pasted across 4 scripts

`lint_vault.py`, `claim_registry.py`, `contradiction_registry.py`, and `vault_graph.py` each define an identical `DualLinkPattern` class with the same `findall`/`finditer` interface. If a bug is found in the regex or interface, it must be fixed in 4 places. The flag-selection logic (`re.MULTILINE` iff `"::"` is in the pattern string) is a silent heuristic that works by accident.

**Recommendation:** Move `DualLinkPattern` to `utils.py` and import it everywhere. Explicitly pass the `flags` argument instead of inferring it from the pattern string.

---

### HIGH-4 — `OKF` is undefined; `index.md` silent exclusion is a hidden footgun

`utils.py` monkey-patches `Path.glob` and `Path.rglob` at import time to silently exclude `index.md` and `log.md` from all `*.md` globs. The only explanation is "OKF reserved index files" — but "OKF" is never defined anywhere in the documentation, and no runbook explains why these files are excluded or what they're for. If a user creates a concept page called `index.md`, it silently disappears from all processing with no error.

**Recommendation:** (a) Define OKF in OPERATING_RULES.md. (b) Document the exclusion rule in both the runbook and in OPERATING_RULES.md. (c) Add a lint check that warns if any excluded-filename note contains non-trivial content that looks like a concept or source page.

---

### HIGH-5 — Compile log written to gitignored `research/scratch/`

`templates/compile_prompt.md` (Step 4, Done Checklist) requires writing a compile log to `research/scratch/compile-YYYYMMDD.md`. But `research/` is gitignored ("research files are working scratch space"). Compile logs provide critical traceability — which sources were processed, which pages created, which contradictions flagged — but they silently vanish. This directly contradicts the vault's provenance mission.

**Recommendation:** Move the compile log to `data/compile_log/` (committed, alongside `claims.json` and `contradictions.json`) or to `notes/Maintenance/`. Alternatively, add a `compile-log` subcommand that aggregates compile summaries into a committed ledger file.

---

## II. Schema & Validation Gaps

### CRIT-6 — Source summary template (`_Templates/Source_Summary.md`) contradicts the SKILL.md spec

The template in `notes/_Templates/Source_Summary.md` defines sections: Summary, Key Claims, Evidence Notes, Related Concepts, Backlinks.

The ingest-sources SKILL.md requires: Summary, What this source is, Key claims, Important evidence / details, Candidate concepts, Open questions, **Reliability notes**, **Related Concepts**, Backlinks.

A user creating a note from the template will produce a file that fails lint (missing 4 required sections). The template also lacks all the required frontmatter fields (`source_id`, `source_url`, `source_kind`, `evidence_strength`, `source_status`, `ingested_at`).

**Recommendation:** Regenerate `_Templates/Source_Summary.md` directly from the ingest-sources SKILL.md section schema, including all required frontmatter fields with `{{placeholder}}` tokens. Add a CI step or lint check that verifies template completeness against the SKILL schema.

---

### CRIT-7 — Concept page template missing `evidence_status` (required by schema.yaml)

`notes/_Templates/Concept_Note.md` frontmatter has `title`, `type`, `tags`, `claim_quality` — but `schema.yaml` lists `evidence_status` as a required field for concept pages. A note created from the template will immediately fail schema validation. The template also uses Templater-style `{{placeholder}}` syntax but Templater is only "recommended" (optional), not confirmed as installed.

**Recommendation:** Add `evidence_status: seed` to the template (the safe default). Add a note in Obsidian_Plugin_Setup.md clarifying that Templater is required if using templates, not optional.

---

### HIGH-8 — Obsidian Plugin Setup runbook lists outdated `evidence_strength` values

The Dataview Property Reference table in `Obsidian_Plugin_Setup.md` lists only 5 evidence strength values: `primary-doc, secondary, strong, stub, image-only`. The actual schema has 11 valid values including `primary-doc-partial`, `official-spec`, `code`, `maintainer-commentary`, `changelog`, `pr-issue`, `model-generated`, `citation-only`. The runbook is misleading — a user would apply an incorrect strength value thinking it's valid.

**Recommendation:** Auto-generate the property reference table from `config/schema.yaml` as part of the `generate_indexes.py` run. Alternatively, add a one-liner comment above the table: "See `config/schema.yaml` for the authoritative list."

---

### MED-9 — `schema.yaml`, OPERATING_RULES.md, and SKILL.md are three disconnected sources of truth for field validation

A change to `schema.yaml` does not cascade to OPERATING_RULES.md's promotion rules or to SKILL.md agent behavior. A new `source_kind` added to `schema.yaml` won't be recognized by the agent during compilation unless SKILL.md and `compile_prompt.md` are also updated. There's no mechanical enforcement of schema-skill alignment.

**Recommendation:** Add a `validate` step to the lint pass that cross-checks: (a) every `source_kind` value in `schema.yaml` is listed in `SKILL.md` for ingest-sources, and (b) every valid `evidence_strength` in `schema.yaml` is mentioned in OPERATING_RULES.md's taxonomy table. Fail lint if any discrepancy is found.

---

## III. Workflow & Process Design

### CRIT-10 — `compile` does not chain `extract-claims` or `extract-contradictions`

OPERATING_RULES.md mandates "Run `extract-claims` after any compile pass to keep `data/claims.json` current." But `cmd_compile` in `kb_runtime.py` just dispatches to the agent CLI — it does not call `run_extract_claims()` or `run_extract_contradictions()` afterward. The user must remember to run these manually. If they don't, the scorecard, lint, and contradiction checks operate on stale data silently.

`maintenance` does chain them, but `compile` (the most-used single command) does not.

**Recommendation:** After `cmd_compile` returns, automatically call `run_extract_claims()` and `run_extract_contradictions()`. Print a notice so the user can see it happened. Add these as a post-compile hook rather than a separate step, matching the stated contract.

---

### HIGH-11 — Research → vault promotion is manual, unguided, and uncheckpointed

After `research-archive`, the runbook says "import the key findings into the vault with `compile` or manually edit concept pages." But:
- There's no `research-promote` command
- There's no diff between report claims and current concept pages
- The research report stays in `research/archive/` forever unless the user manually transplants it
- There's `research-import` for external AI reports, but no equivalent for first-party research findings

This is the most likely place where knowledge never escapes the research workspace.

**Recommendation:** Add a `research-promote` command (or `compile --from-research`) that reads an archived research report, identifies candidate concept page updates, and launches the compile agent with the report as additional context. The agent's task should be to diff report claims against existing concept pages and propose targeted updates rather than a cold compile.

---

### HIGH-12 — `ask → promote to Concepts/` pattern is contradicted by the Q&A skill

The Workflow_Pattern_Inventory describes an `ask → (manual review) → promote to Concepts/` pattern. But the Q&A SKILL.md and `ask_prompt.md` both explicitly say "Do not create new concept pages from a Q&A session. Add to existing ones only." This is an outright contradiction — the workflow pattern document describes a capability that the Q&A skill forbids.

The open question on `Workflow_Pattern_Inventory` ("Should the `ask → promote` step be automated or always require human gating?") treats this as an open design choice, but it's already decided: the skill says no. The pattern document needs to be updated, or the skill needs a separate `promote` mechanism.

**Recommendation:** Either (a) remove `→ promote to Concepts/` from the `Ask → Promote` workflow pattern and document that Q&A never creates concept pages, or (b) add a distinct `kb.py promote-answer --answer <id>` command that specifically lifts durable Q&A findings into concept pages, keeping Q&A and promotion as separate steps with an explicit human gate.

---

### HIGH-13 — Probe review system is defined in scorecard but has no runbook

The scorecard reports an unreviewed probe for `Workflow_Pattern_Inventory` and warns to "run the Probe Review checklist." But there is no "Probe Review checklist" in any runbook. The `research/evals/dev-probes.jsonl` file lives in the gitignored `research/` directory, so probes cannot be committed. The `generate-probes` and `evaluate` commands exist, but the human review step is entirely undocumented.

**Recommendation:** (a) Move `dev-probes.jsonl` to `data/evals/` so it's committed and version-controlled. (b) Write a Probe Review Runbook that covers: how to generate probes, how to review them, what "approved" means, and how approval affects scorecard metrics. (c) Add `probe-review` to the Quick Reference runbook's Quality & Evaluation section.

---

### HIGH-14 — Eval harness is scaffolded but non-operational

`data/scorecard.json` shows `eval_pass_rate: null`, `latest_run: null`, `approved: 0`. There are no golden tests and no eval runs. The commands `eval-setup`, `eval-check`, and `evaluate` exist but are unused. Without any approved eval baseline, there is no way to detect regressions in vault answer quality as it grows.

**Recommendation:** Prioritize running `eval-setup` to create `tests/qa_golden.yaml`, seeding it with at least 5 representative questions (one per query_class type). Run `evaluate` against them and commit the results to `data/eval_runs/`. Add a CI check that runs `eval-check` on every commit to keep the golden file valid.

---

### MED-15 — Stale propagation not triggered on manual source note edits

The staleness policy says `refresh` auto-flags `revalidation_required: true` on concepts citing changed sources. But if a user manually edits a source note or the underlying `data/raw/` content changes (e.g., a re-fetch that doesn't use `refresh`), no staleness flag is set. The `content_hash` field in source metadata exists for this purpose but is listed as only "recommended" in `schema.yaml`, meaning it's often absent.

**Recommendation:** (a) Promote `content_hash` from `recommended` to `required` in `schema.yaml`. (b) Add a pre-commit hook or lint check that computes the hash of `data/raw/<id>/normalized.md` and compares it to the registered hash — flagging a mismatch as a stale source needing `refresh`.

---

### MED-16 — `maintenance` and individual step ordering are underdocumented

The Quick Reference runbook lists both a "safe execution order" (8 steps) and a `maintenance` command that "runs: refresh → compile → normalize → backfill → graph → lint." But:
- The `maintenance` command skips `extract-claims`, `extract-contradictions`, `ask`, and `scorecard` — which the "safe execution order" includes
- The runbook doesn't explain when to use `maintenance` vs the individual steps
- Users running `maintenance` will not get an updated scorecard or claims registry

**Recommendation:** Add a brief decision table to the runbook: "Use `maintenance` for routine weekly upkeep (data normalization, backfills, graph). Use the individual safe execution order for post-compile quality gates. Always run `extract-claims`, `extract-contradictions`, and `scorecard` after any compile or maintenance run."

---

## IV. Obsidian Integration Gaps

### HIGH-17 — Static index pages vs live Dataview is a design tension without resolution

`generate_indexes.py` produces static markdown indexes (Source_Atlas, Topic_Atlas, Vault_Dashboard). These must be regenerated each time sources or concepts change. Meanwhile, `Obsidian_Plugin_Setup.md` documents Dataview queries that would give live results.

The current state is neither: the static indexes require manual regeneration (easy to forget), and the live Dataview queries are only examples in a runbook, not embedded in the actual vault pages. The Vault_Dashboard freshness alerts table will show stale data the moment a source is added.

**Recommendation:** Commit to one approach. The pragmatic path: keep static generation for the source and topic atlases (they require cross-cutting computation), but embed Dataview live queries in `notes/Home.md` and `notes/Indexes/Vault_Dashboard.md` for the freshness alerts and concept quality tables. Document in the Quick Reference that `generate_indexes.py` must be run before exporting or sharing the vault.

---

### MED-18 — No `.obsidian/` configuration committed; new users start from scratch

The vault has no committed `.obsidian/` directory. A user who clones the repo and opens it in Obsidian gets default settings with no pre-configured plugins, graph layout, or hotkeys. The setup runbook requires manually installing 4 plugins and configuring Templater's template folder. `kb.py bootstrap` creates the directory structure but not the Obsidian configuration.

**Recommendation:** Commit a `.obsidian/` directory with: `community-plugins.json` (plugin list), `plugins/dataview/data.json` (enabled: true), and `app.json` (core settings like `newFileLocation: "notes/_Templates"`). This is a one-time setup that massively improves onboarding.

---

### MED-19 — Wikilink format created by Obsidian UI differs from the required path-prefixed format

Obsidian's UI creates links in the format `[[filename]]` or `[[filename|alias]]`. The vault requires `[[Concepts/ConceptName|label]]` with an explicit path prefix. Any note linked via Obsidian's native UI or graph will fail lint because the path prefix is missing. This creates constant friction for human editors working in Obsidian.

**Recommendation:** (a) Configure Obsidian to use "Shortest path that is unambiguous" in Settings → Files & Links → New link format. Since filenames appear to be unique across the vault, this would produce `[[ConceptName|label]]` without the path prefix — and the lint patterns would need to accept bare wikilinks. (b) Alternatively, document explicitly that all links must be created via the CLI compile step, not Obsidian's UI. Pick one and enforce it.

---

### MED-20 — Gemini's native Google grounding contradicts `allow_web_fetch_during_qa: false`

`kb_config.yaml` sets `allow_web_fetch_during_qa: false`, which the ask_prompt template respects ("If web fetch policy is disabled, do not browse the web"). But `GEMINI.md` says "Grounding via Google Search is available — prefer vault-first answers, use web grounding only for missing evidence." This is a direct contradiction: the config says no web fetch, the CLI-specific guidance permits it. A Gemini Q&A session run via `kb.py ask` will have `allow_web_fetch_during_qa: false` injected into the prompt, but Gemini can ground independently of that instruction.

**Recommendation:** Add a `allow_web_grounding_during_qa` flag to `kb_config.yaml` with separate semantics from `allow_web_fetch_during_qa`. Document the distinction: `web_fetch` = explicit tool call to fetch a URL; `web_grounding` = Gemini's implicit search grounding. Set appropriate defaults and emit the right policy flag per CLI.

---

## V. Quality & Reliability

### MED-21 — `claim_quality: stale` degradation pathway is undefined

`stale` is a valid `claim_quality` value, but OPERATING_RULES.md never explains how a concept reaches this state. The staleness policy explains source-level staleness and sets `revalidation_required: true`, but there's no described path from that flag to `claim_quality: stale`. Backfill scripts set quality from evidence strength, not from stale flags.

**Recommendation:** Define explicitly in OPERATING_RULES.md: "A concept page is set to `claim_quality: stale` when (a) `revalidation_required: true` is present AND (b) the stale-impact review has not been completed within 30 days of the flag being set." Add this transition logic to `backfill_concept_quality.py` or as a new command `mark-stale-concepts`.

---

### LOW-22 — No semantic / embedding search; retrieval relies entirely on LLM heuristics

The `search` command is keyword-only (BM25-style). The Q&A prompt instructs the agent to "scan notes/Concepts/ filenames. Pick the 3-5 most relevant to the question by title alone." This is a brittle heuristic — a concept page titled `PKM_As_Agent_Memory` will not be surfaced by a question about "personal knowledge management" unless the agent already knows to connect those terms.

**Recommendation:** Add an optional embedding index. The simplest path: `kb.py embed` generates embeddings for all concept and source pages and stores them in `data/embeddings/`. `kb.py search --semantic` uses cosine similarity to return the top-N candidates. The Q&A prompt can then start with a semantic lookup instead of filename scanning.

---

### LOW-23 — No concept page merge/rename command

If two concept pages cover overlapping territory, there's no `kb.py merge-concepts --source A --target B` command. The user must manually transfer Key Claims, update backlinks in all source summaries, delete the old page, and update Home.md. This is high-friction and error-prone.

**Recommendation:** Add `kb.py merge-concepts --source <stem> --target <stem>` that: (a) appends source's Key Claims to target, (b) updates `## Evidence / Source Basis` links, (c) adds a `superseded_by::` entry on the source page, (d) adds a `supersedes::` entry on the target page, (e) updates all backlinks in `notes/Sources/`, and (f) appends a merge record to `notes/TODO.md`.

---

## Summary Priority Matrix

| Priority | ID | Issue |
|---|---|---|
| **Critical** | CRIT-1 | Three instruction levels with no canonical authority |
| **Critical** | CRIT-2 | Skills triplicated across `.claude/.codex/.gemini`, drift inevitable |
| **Critical** | CRIT-3 | `DualLinkPattern` copy-pasted across 4 scripts |
| **Critical** | CRIT-6 | Source summary template contradicts SKILL spec (4 missing sections) |
| **Critical** | CRIT-7 | Concept template missing required `evidence_status` field |
| **Critical** | CRIT-10 | `compile` does not auto-run `extract-claims`/`extract-contradictions` |
| **High** | HIGH-4 | `index.md` silent exclusion undocumented; "OKF" undefined |
| **High** | HIGH-5 | Compile log written to gitignored path; traceability lost |
| **High** | HIGH-8 | Evidence strength table in runbook is outdated (5 of 11 values) |
| **High** | HIGH-11 | Research → vault promotion is manual, unguided, uncheckpointed |
| **High** | HIGH-12 | `ask → promote` contradicted by Q&A skill |
| **High** | HIGH-13 | Probe review system has no runbook; probes are gitignored |
| **High** | HIGH-14 | Eval harness non-operational (`eval_pass_rate: null`) |
| **Medium** | MED-9 | `schema.yaml`, OPERATING_RULES.md, SKILL.md not cross-validated |
| **Medium** | MED-15 | Manual source edits do not trigger stale propagation |
| **Medium** | MED-16 | `maintenance` vs individual steps ordering underdocumented |
| **Medium** | MED-17 | Static indexes vs live Dataview unresolved tension |
| **Medium** | MED-18 | No `.obsidian/` config committed; new user onboarding friction |
| **Medium** | MED-19 | Obsidian UI wikilink format fails lint |
| **Medium** | MED-20 | Gemini grounding contradicts `allow_web_fetch_during_qa: false` |
| **Medium** | MED-21 | `claim_quality: stale` degradation pathway undefined |
| **Low** | LOW-22 | No semantic/embedding search; retrieval depends on LLM title heuristics |
| **Low** | LOW-23 | No `merge-concepts` command; manual merging is high-friction |

---

## Where to Start

The three Critical schema/template issues (CRIT-6, CRIT-7, CRIT-10) will immediately yield lint failures on every new note, so they have the highest return on the smallest investment. CRIT-1 and CRIT-2 are architectural and should be addressed before adding more skills or CLIs — otherwise each new CLI multiplies the drift surface. HIGH-5 (compile log disappearing into gitignored scratch) undermines the entire provenance model and is a two-line config change to fix.
