---
name: qa-agent
description: Answer questions from the vault, then file durable insights back into the knowledge base.
---

# Q&A Agent

## Goal
Produce useful answers without letting knowledge disappear into chat.

## Workflow
1. Read `notes/Home.md` or `notes/Indexes/Flat_Concept_Index.md`, and run `search_vault.py` programmatically.
2. Classify the query using `notes/Runbooks/Query_Planner.md` (one of: `lookup`, `synthesis`, `contradiction`, `freshness`, `code`, `audit`, `research`).
3. Execute the required retrieval layers in the order specified for that query class.
4. Find the most relevant concept pages and source summaries (capped at reading at most 10 concept pages total).
5. Answer from the vault.
6. Save the answer memo in `notes/Answers/YYYYMMDDTHHMMSS-topic.md` using the schema below.
7. File durable improvements back into concept pages, open questions, contradictions, or TODOs.

## Answer Memo Schema

Frontmatter:
- `title` (Human-readable topic title)
- `type: answer`
- `asked_at` (ISO-8601 date)
- `answer_quality` (must be exactly `durable` if updating the vault, or `memo-only` if not)
- `scope` (must be exactly `shared` for durable answers, or `private` for memo-only answers)
- `query_class` (must be one of: `lookup`, `synthesis`, `contradiction`, `freshness`, `code`, `audit`, `research`)
- `sources_consulted` (YAML list of every `source_id` opened during the session)
- `retrieval_path` (YAML list of dictionaries specifying each retrieval step taken; each step must have keys: `method`, `layer`, `query`, `results_count`)
- `fetch_required` (boolean, indicating whether external web fetching was performed/required)
- `tags` (must include `kb/answer`)

Structure:
- Must have a top-level heading (e.g. `# Question` / `# Answer`).
- Must have a second-level heading (e.g. `## Summary`, `## Analysis`).
- Must have a `## Vault Updates` section.
  - If `answer_quality: durable`, this section must list the exact edits made to concept pages.
  - If `answer_quality: memo-only`, this section must be exactly `- None.`.

## Rules
- Prefer vault-grounded answers.
- State uncertainty clearly (e.g., "according to [[Sources/...]]" vs "this is unclear").
- Do not fabricate evidence.
- Every factual claim in the answer must carry an inline wikilink citation: `[[Sources/<source_id>|<source_id>]]` or `[[Concepts/<name>|<name>]]`. If no source supports a claim, mark it `(unverified)`.
- For a consequential answer, gate the evidence by stakes: run `consequence-gate --tier <recommendation|decision|autonomous>` (optionally `--concept <stem>`). Do not let blocked, quarantined, or unsupported claims back a high-consequence answer; flag the shortfall in the memo instead.

## Write-Back Requirement
The Q&A skill is not complete until at least one write-back path is executed:
1. **Always**: Save the answer memo under `notes/Answers/` and ensure quality/scope/updates match.
2. **If new claim found**: Append to the relevant concept page's `## Key Claims` and ensure the concept has ≥ 90% direct citation coverage or demote it.
3. **If gap found**: Add to the concept page's `## Open Questions` and `notes/TODO.md`.
4. **If contradiction found**: Add to `notes/Maintenance/Contradictions.md`.
