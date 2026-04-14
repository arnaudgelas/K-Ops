# GEMINI.md

This repository is a starter Obsidian-aligned living research vault. The same operating contract applies whether the active CLI is Gemini CLI, Claude Code, or Codex CLI.

**Canonical rules: see `OPERATING_RULES.md`.** This file contains the complete mission, workflow, page conventions, and Obsidian conventions. The sections below summarize key points and add Gemini-specific notes.

## Summary

- Raw evidence lives in `data/raw/` (immutable).
- Curated knowledge lives in `notes/` (Obsidian vault).
- Use `scripts/kb.py` commands for ingestion, compilation, Q&A, healing, and rendering.
- Run `lint` after any structural edits.
- File durable answers back into the vault.

## Reference Notes

- `notes/Runbooks/Agent_Workflow_Quick_Reference.md` — all commands and safe execution order
- `notes/Runbooks/Research_Workflow.md` — multi-phase research pipeline
- `notes/Concepts/Workflow_Pattern_Inventory.md` — workflow pattern catalogue
- `OPERATING_RULES.md` — canonical operating rules (edit here to update all agent contexts)

## Gemini-Specific Notes

- Gemini commands in `.gemini/commands/` use TOML format with `{{args}}` variable syntax.
- Use `uv run python scripts/install_agent_assets.py` to sync canonical skills/templates to the Gemini runtime directory.
- Use `uv run python scripts/kb.py validate` to confirm config loads before running workflows.
