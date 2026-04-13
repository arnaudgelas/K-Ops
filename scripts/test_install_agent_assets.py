from __future__ import annotations

import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    sys.path.append(str(ROOT / "scripts"))
    from install_agent_assets import install_agent_assets  # noqa: WPS433

    with tempfile.TemporaryDirectory(prefix="kb-install-assets-") as tmp:
        project_root = Path(tmp) / "project"
        home_root = Path(tmp) / "home"
        project_root.mkdir()
        home_root.mkdir()

        (project_root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
        (project_root / "CLAUDE.md").write_text("# CLAUDE\n", encoding="utf-8")
        notes_dir = project_root / "notes" / "Runbooks"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "Agent_Workflow_Quick_Reference.md").write_text("# Runbook\n", encoding="utf-8")

        created = install_agent_assets(
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
            project_root / ".codex" / "prompts" / "heal.md",
            project_root / "GEMINI.md",
            home_root / ".claude" / "skills" / "qa-agent" / "references" / "workflow-prompt.md",
            home_root / ".gemini" / "commands" / "compile.toml",
            home_root / ".codex" / "skills" / "render-output" / "SKILL.md",
        ]

        for path in expected_files:
            if not path.exists():
                raise AssertionError(f"Expected runtime asset to exist: {path}")

        gemini_text = (project_root / "GEMINI.md").read_text(encoding="utf-8")
        if "@./AGENTS.md" not in gemini_text or "@./CLAUDE.md" not in gemini_text:
            raise AssertionError(f"GEMINI.md did not import the repo contract:\n{gemini_text}")

        ask_command = (project_root / ".claude" / "commands" / "ask.md").read_text(encoding="utf-8")
        if "$ARGUMENTS" not in ask_command:
            raise AssertionError(f"Claude ask command did not include argument substitution:\n{ask_command}")

        render_command = (project_root / ".gemini" / "commands" / "render.toml").read_text(encoding="utf-8")
        if "Treat the first argument as the output format" not in render_command:
            raise AssertionError(f"Gemini render command did not adapt the render prompt:\n{render_command}")

        codex_prompt = (project_root / ".codex" / "prompts" / "ask.md").read_text(encoding="utf-8")
        if "notes/Answers/" not in codex_prompt:
            raise AssertionError(f"Codex prompt did not preserve the answer memo workflow:\n{codex_prompt}")

        compile_skill = (project_root / ".claude" / "skills" / "compile-wiki" / "SKILL.md").read_text(encoding="utf-8")
        if "Runtime Prompt" not in compile_skill:
            raise AssertionError(f"Skill bundle did not get the runtime prompt note:\n{compile_skill}")

        if not created:
            raise AssertionError("Installer reported no created assets")

        print("install_agent_assets regression passed")


if __name__ == "__main__":
    main()
