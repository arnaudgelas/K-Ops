from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
TEMPLATES_DIR = ROOT / "templates"
CLAUDE_AGENTS_DIR = ROOT / ".claude" / "agents"
CLAUDE_MEMORY = ROOT / "CLAUDE.md"
GEMINI_MEMORY = ROOT / "GEMINI.md"


@dataclass(frozen=True)
class Operation:
    kind: str
    source: Path
    target: Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def ensure_home(home: Path | None) -> Path:
    return home.expanduser() if home is not None else Path.home()


def command_name(template: Path) -> str:
    name = template.stem
    return name.removesuffix("_prompt")


def command_description(name: str) -> str:
    descriptions = {
        "ask": "Ask the vault a question",
        "compile": "Compile source summaries into concept pages",
        "heal": "Lint and heal the vault",
        "render": "Render vault content into downstream outputs",
    }
    return descriptions.get(name, name.replace("-", " ").capitalize())


def render_claude_command(template_path: Path) -> str:
    name = command_name(template_path)
    body = read_text(template_path).strip()

    if name == "ask":
        body = body.replace("{question}", "$ARGUMENTS")
        body = body.replace(
            "{answer_path}",
            "notes/Answers/<timestamped-memo>.md",
        )
    elif name == "render":
        body = body.replace("{format}", "$1")
        body = body.replace("{prompt}", "$ARGUMENTS")

    model = "haiku" if name == "heal" else "sonnet"
    frontmatter = [
        "---",
        f"description: {command_description(name)}",
    ]
    if name == "ask":
        frontmatter.append("argument-hint: [question]")
    elif name == "render":
        frontmatter.append("argument-hint: [format] [brief]")
    frontmatter.append(f"model: {model}")
    frontmatter.append("---")
    return "\n".join(frontmatter) + "\n\n" + body + "\n"


def escape_toml_multiline(text: str) -> str:
    return text.replace('"""', '\\"\\"\\"')


def render_gemini_command(template_path: Path) -> str:
    name = command_name(template_path)
    body = read_text(template_path).strip()

    if name == "ask":
        body = body.replace("{question}", "the user's question")
        body = body.replace("{answer_path}", "a timestamped file under notes/Answers/")
    elif name == "render":
        body = body.replace("{format}", "the requested output format")
        body = body.replace("{prompt}", "the requested output brief")

    description = command_description(name)
    return (
        f'description = "{description}"\n'
        f'prompt = """\n{escape_toml_multiline(body)}\n"""\n'
    )


def collect_ops(home: Path) -> list[Operation]:
    ops: list[Operation] = []

    codex_root = home / ".codex" / "skills"
    for source in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        ops.append(Operation("copy", source, codex_root / source.parent.name / "SKILL.md"))

    claude_agents_root = home / ".claude" / "agents"
    for source in sorted(CLAUDE_AGENTS_DIR.glob("*.md")):
        ops.append(Operation("copy", source, claude_agents_root / source.name))

    claude_commands_root = home / ".claude" / "commands"
    for source in sorted(TEMPLATES_DIR.glob("*.md")):
        ops.append(
            Operation(
                "claude-command",
                source,
                claude_commands_root / f"{command_name(source)}.md",
            )
        )

    gemini_root = home / ".gemini"
    if GEMINI_MEMORY.exists():
        ops.append(Operation("copy", GEMINI_MEMORY, gemini_root / "GEMINI.md"))

    gemini_commands_root = gemini_root / "commands"
    for source in sorted(TEMPLATES_DIR.glob("*.md")):
        ops.append(
            Operation(
                "gemini-command",
                source,
                gemini_commands_root / f"{command_name(source)}.toml",
            )
        )

    if CLAUDE_MEMORY.exists():
        ops.append(Operation("copy", CLAUDE_MEMORY, home / ".claude" / "CLAUDE.md"))

    return ops


def materialize(operation: Operation, *, dry_run: bool) -> str:
    if operation.kind == "copy":
        content = read_text(operation.source)
        if operation.target.exists() and operation.target.read_text(encoding="utf-8") == content:
            return "skipped"
        existed = operation.target.exists()
        write_text(operation.target, content, dry_run=dry_run)
        return "updated" if existed else "created"

    if operation.kind == "claude-command":
        content = render_claude_command(operation.source)
        if operation.target.exists() and operation.target.read_text(encoding="utf-8") == content:
            return "skipped"
        existed = operation.target.exists()
        write_text(operation.target, content, dry_run=dry_run)
        return "updated" if existed else "created"

    if operation.kind == "gemini-command":
        content = render_gemini_command(operation.source)
        if operation.target.exists() and operation.target.read_text(encoding="utf-8") == content:
            return "skipped"
        existed = operation.target.exists()
        write_text(operation.target, content, dry_run=dry_run)
        return "updated" if existed else "created"

    raise ValueError(f"Unsupported operation kind: {operation.kind}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install Codex, Claude Code, and Gemini CLI runtime assets from this repo.",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help="Override the home directory used for user-level installs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be installed without writing any files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files even if the destination already exists.",
    )
    args = parser.parse_args()

    home = ensure_home(args.home)
    ops = collect_ops(home)

    results: list[str] = []
    for op in ops:
        if op.target.exists() and not args.force:
            current = op.target.read_text(encoding="utf-8")
            expected = None
            if op.kind == "copy":
                expected = read_text(op.source)
            elif op.kind == "claude-command":
                expected = render_claude_command(op.source)
            elif op.kind == "gemini-command":
                expected = render_gemini_command(op.source)
            if expected is not None and current == expected:
                results.append(f"skipped {op.target}")
                continue
        status = materialize(op, dry_run=args.dry_run)
        results.append(f"{status} {op.target}")

    for line in results:
        print(line)

    if args.dry_run:
        print("dry-run complete")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
