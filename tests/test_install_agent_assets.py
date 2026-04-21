"""Tests for install_agent_assets.py."""
from __future__ import annotations

import tempfile
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_install_agent_assets_round_trip():
    from install_agent_assets import install_agent_assets

    with tempfile.TemporaryDirectory(prefix="kb-install-assets-") as tmp:
        project_root = Path(tmp) / "project"
        home_root = Path(tmp) / "home"
        project_root.mkdir()
        home_root.mkdir()

        (project_root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
        (project_root / "CLAUDE.md").write_text("# CLAUDE\n", encoding="utf-8")
        (project_root / "GEMINI.md").write_text("# GEMINI\n", encoding="utf-8")
        notes_dir = project_root / "notes" / "Runbooks"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "Agent_Workflow_Quick_Reference.md").write_text("# Runbook\n", encoding="utf-8")

        results = install_agent_assets(
            agent="all",
            scope="both",
            project_root=project_root,
            home_root=home_root,
            overwrite=True,
        )

        expected_files = [
            project_root / ".claude" / "skills" / "compile-wiki" / "SKILL.md",
            project_root / ".claude" / "commands" / "ask.md",
            project_root / ".gemini" / "commands" / "render.toml",
            project_root / ".codex" / "commands" / "heal.md",
            home_root / ".claude" / "CLAUDE.md",
            home_root / ".codex" / "AGENTS.md",
            home_root / ".gemini" / "GEMINI.md",
            home_root / ".claude" / "skills" / "qa-agent" / "references" / "workflow-prompt.md",
            home_root / ".gemini" / "commands" / "compile.toml",
            home_root / ".codex" / "skills" / "render-output" / "SKILL.md",
            home_root / ".codex" / "commands" / "ask.md",
        ]
        for path in expected_files:
            assert path.exists(), f"Expected runtime asset to exist: {path}"

        gemini_text = (home_root / ".gemini" / "GEMINI.md").read_text(encoding="utf-8")
        assert "OPERATING_RULES.md" in gemini_text

        codex_text = (home_root / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
        assert "Codex-Specific Notes" in codex_text

        ask_command = (project_root / ".claude" / "commands" / "ask.md").read_text(encoding="utf-8")
        assert "$ARGUMENTS" in ask_command

        render_command = (project_root / ".gemini" / "commands" / "render.toml").read_text(encoding="utf-8")
        assert "the requested output format" in render_command

        codex_prompt = (project_root / ".codex" / "commands" / "ask.md").read_text(encoding="utf-8")
        assert "notes/Answers/" in codex_prompt

        compile_skill = (project_root / ".claude" / "skills" / "compile-wiki" / "SKILL.md").read_text(encoding="utf-8")
        assert "Runtime Prompt" in compile_skill

        assert results
        assert any(line.startswith("created") for line in results)
