---
name: research-review
description: Perform a contrarian review of research findings, challenging assumptions and identifying weak or missing evidence.
---

# Research Review

## Goal
Stress-test the emerging thesis before report drafting by actively seeking counter-evidence and logical weaknesses.

## Inputs
- Research brief (`research/briefs/<slug>-<date>.md`)
- Findings file (`research/findings/<slug>-<date>.md`)
- Contrarian review file (`research/notes/<slug>-contrarian-review.md`)

## Output contract
- Write a substantive contrarian review focused on weak evidence, hidden assumptions, and missing primary sources.
- Identify which claims should be softened, qualified, or removed.
- Write/update `{review_path}` preserving the frontmatter.
- Populate `## Strongest Objections`, `## Missing Evidence`, and `## Claims To Soften`.
- Update `{progress_path}` with a review log.

## Rules
- Adversarial mode: the goal is to break the thesis, not confirm it.
- Do not fabricate counter-evidence - identify genuine gaps.
- Keep the review grounded in what the evidence actually supports.
- Suggest missing primary sources or specs that must be consulted before report drafting.
