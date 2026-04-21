You are drafting the final report for research run `{slug}`.

Topic: {topic}
Quality tier: {tier}

Files:
- Brief (read first): {brief_path}
- Findings: {findings_path}
- Contrarian review: {review_path}
- Report output (write here): {report_path}

---

## Idempotency guard

Read `{report_path}`. If it already contains a completed report (not just a scaffold), print "Report already written" and stop. Do not overwrite a completed report.

---

## Read before writing — strict order

1. Read `{brief_path}` — understand the original question and success criteria.
2. Read `{review_path}` — the contrarian review may have invalidated findings or flagged missing sources. If the review says "major gaps", note what to omit or caveat.
3. Read `{findings_path}` — the synthesized evidence base.
4. Read the source summaries cited in the findings (`notes/Sources/<source_id>.md`). Read at most 8.
5. For any claim the review specifically challenged as unsupported: read the raw source file to verify before including it in the report.

Do not rely on memory or reasoning alone for factual claims. Read the sources.

---

## Report protocol

Build the report from evidence upward, not from the thesis downward.

- Start with what the sources clearly establish (high-confidence claims).
- Then cover areas where evidence is mixed or sources disagree.
- Then identify genuine open questions that remain unresolved.
- Do not promote model-generated report claims unless a primary source corroborates them.

---

## Report output format

Write `{report_path}` using this structure:

```markdown
# Research Report: {topic}

*Generated: <date>*
*Quality tier: {tier}*
*Sources consulted: <N>*

## Executive Summary

<3–5 sentence synthesis of the most important, well-supported findings. State the confidence level.>

## Key Findings

### <Finding category 1>

<Finding text. Cite supporting sources inline: ([[Sources/<source_id>|<source_id>]]).>

### <Finding category 2>

<Finding text with citations.>

## Contested or Uncertain Areas

<Claims where sources disagree, evidence is thin, or the contrarian review raised valid objections. Be explicit about what is uncertain and why.>

## Open Questions

- <Specific unanswered question that further research could address>
- <What primary source is missing>

## Sources

| source_id | title | evidence_strength |
|---|---|---|
| <source_id> | <title> | <strength> |
```

---

## What NOT to do

- Do not include claims the contrarian review recommended removing unless you have found corroborating evidence.
- Do not cite model-generated sources as authoritative.
- Do not present uncertain findings as established facts.
- Do not create or edit concept pages — that is the compile step.

---

## Done checklist

- [ ] Report covers: executive summary, key findings, contested areas, open questions, source table.
- [ ] Every factual claim in Key Findings cites at least one source inline.
- [ ] Claims challenged in the contrarian review are either corroborated or placed in "Contested" section.
- [ ] Status file `{status_path}` updated to `phase: done`.

Print: report path, source count, count of claims placed in Contested vs Key Findings.
