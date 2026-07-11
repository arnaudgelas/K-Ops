---
name: render-output
description: Convert vault content into downstream outputs like memos, reports, slide outlines, diagrams, and plot specifications.
---

# Render Output

## Goal
Transform the current vault into human-facing deliverables.

## Common outputs
- executive memo
- research brief
- slide outline (structured markdown outline, not a binary file)
- architecture note
- comparison table
- Mermaid diagram spec

## Rules
- Deliverables must be strictly grounded in the vault. Do not introduce outside information.
- Include a "Source Map" section at the end of the rendered document, detailing which Concept pages and Source summaries (with Obsidian wikilinks) informed the content.
- Save all rendered outputs under the `outputs/` directory with a clean, lowercase, hyphenated filename (e.g. `outputs/multi-agent-orchestration-slides.md`).
- Print the file paths of all generated files when done.
