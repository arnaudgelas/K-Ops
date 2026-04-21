You are collecting sources for research run `{slug}`.

Topic: {topic}
Quality tier: {tier}

Files:
- Brief (read first): {brief_path}
- Status: {status_path}
- Progress log: {progress_path}
- Findings: {findings_path}

---

## Idempotency guard

Read `{progress_path}` before fetching anything. Count the lines that start with `- [src-`. If there are already ≥5 source entries, the collection phase may be complete — check `{status_path}` to see if phase is already `findings`. If so, print the status and stop.

---

## Collection budget: 5–8 sources, no more

Fetch and summarize between 5 and 8 sources. Prioritize:
1. Primary sources (official docs, specs, canonical repos, peer-reviewed papers)
2. Strong secondary sources (well-cited analysis, maintainer commentary)
3. Model-generated reports only as leads — flag them explicitly

Do not collect more than 2 model-generated or imported reports. Verify their claims against a primary source before promoting any finding into the vault.

---

## For each source collected

**Step 1 — Fetch or locate the source.**
Search broadly for authoritative sources on the topic. Prefer full-text pages over summaries.

**Step 2 — Check for duplicates.**
Scan `notes/Sources/` by filename. If a summary for this source already exists, skip writing a new one — add a progress entry and move on.

**Step 3 — Write a source summary** to `notes/Sources/<source_id>.md`:

```markdown
---
title: "<Descriptive title>"
type: source
source_id: <source_id>
evidence_strength: <value>
source_kind: <value>
tags:
  - kb/source
---

## Summary

<2–4 sentence digest.>

## Key Findings

- <Atomic finding 1>
- <Atomic finding 2>

## Limitations

<Methodology weaknesses, coverage gaps, or reasons to distrust.>
```

`evidence_strength`: `primary-doc` | `official-spec` | `strong` | `code` | `maintainer-commentary` | `changelog` | `pr-issue` | `secondary` | `model-generated` | `stub` | `citation-only` | `image-only`

**Step 4 — Append to the progress log** (`{progress_path}`), one line per source:
```
- [<source_id>] <title> — <one-sentence finding>
```

---

## After collecting all sources

**Update the findings file** (`{findings_path}`):
- List the highest-signal claims across all sources, with inline source citations.
- List open questions where sources disagree or evidence is thin.
- Do not summarize at the level of individual sources — synthesize across them.

**Update the status file** (`{status_path}`): set `phase: findings` when ≥5 sources have summaries.

---

## What NOT to do

- Do not collect more than 8 sources in a single run.
- Do not promote model-generated report claims into concept pages without primary-source verification.
- Do not edit existing concept pages in `notes/Concepts/` — that is the compile step's job.
- Do not update `notes/Home.md`.

---

## Done checklist

- [ ] 5–8 sources collected with summaries in `notes/Sources/`.
- [ ] Progress log updated with one line per source.
- [ ] Findings file updated with synthesized claims and open questions.
- [ ] Status file updated to `phase: findings`.

Print: sources collected, sources skipped (duplicates), highest-signal finding in one sentence.
