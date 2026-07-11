# GEMINI.md

This repository is an Obsidian-aligned living research vault for agentic coding knowledge.

Canonical rules: see `OPERATING_RULES.md`. This file adds only Gemini-specific overrides.

## Gemini-Specific Notes
- Use `uv run kops compile --agent gemini` for wiki compilation passes.
- Use `uv run kops heal --agent gemini` for structural repair.
- Use `uv run kops validate` to confirm config before running workflows.
- Use `uv run kops install-agent-assets --agent gemini` to sync skills to the Gemini runtime directory.
- Grounding via Google Search is available — prefer vault-first answers, use web grounding only for missing evidence.

## Reference Notes
- `notes/Runbooks/Agent_Workflow_Quick_Reference.md` — all commands and safe execution order
- `OPERATING_RULES.md` — canonical operating rules (full contract)
