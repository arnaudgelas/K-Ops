from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = Path(__file__).resolve().parent
SKILLS_DIR = PKG_DIR / "skills"
TEMPLATES_DIR = PKG_DIR / "templates"
CLAUDE_AGENTS_DIR = ROOT / ".claude" / "agents"
CLAUDE_MEMORY = ROOT / "CLAUDE.md"
AGENTS_MEMORY = ROOT / "AGENTS.md"
GEMINI_MEMORY = ROOT / "GEMINI.md"
SUPPORTED_AGENTS = ("claude", "gemini", "codex")
AGENT_RUNTIME_DIRS = {
    "claude": ".claude",
    "gemini": ".gemini",
    "codex": ".codex",
}


@dataclass(frozen=True)
class Operation:
    kind: str
    source: Path
    target: Path
    content: str = ""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def ensure_home(home: Path | None) -> Path:
    return home.expanduser() if home is not None else Path.home()


def normalize_agents(agent: str) -> tuple[str, ...]:
    if agent == "all":
        return SUPPORTED_AGENTS
    if agent not in SUPPORTED_AGENTS:
        raise ValueError(f"Unsupported agent: {agent}")
    return (agent,)


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


def _substitute_runtime_placeholders(body: str, name: str, *, arg_var: str = "$ARGUMENTS") -> str:
    """Replace Python format-string placeholders with CLI runtime variables or safe defaults."""
    if name == "ask":
        body = body.replace("{question}", arg_var)
        body = body.replace("{answer_path}", "notes/Answers/<timestamped-memo>.md")
        body = body.replace("{web_fetch_policy}", "disabled")
        body = body.replace(
            "{retrieval_context}",
            'Not precomputed in generated slash-command mode. Run `uv run python -m kops.search_vault "$ARGUMENTS" --top 10` before answering.',
        )
    elif name == "render":
        body = body.replace("{format}", "$1")
        body = body.replace("{prompt}", arg_var)
    elif name == "compile":
        body = body.replace(
            "{plan_summary}",
            "Not provided — derive the compile plan yourself as described in Step 1 above.",
        )
    elif name == "research_collect":
        body = body.replace("{brief_path}", "research/briefs/<topic-slug>-<date>.md")
        body = body.replace("{status_path}", "research/notes/<topic-slug>-status.md")
        body = body.replace("{progress_path}", "research/notes/<topic-slug>-progress.md")
        body = body.replace("{findings_path}", "research/findings/<topic-slug>-<date>.md")
    elif name == "research_review":
        body = body.replace("{brief_path}", "research/briefs/<topic-slug>-<date>.md")
        body = body.replace("{findings_path}", "research/findings/<topic-slug>-<date>.md")
        body = body.replace("{review_path}", "research/notes/<topic-slug>-contrarian-review.md")
    elif name == "research_report":
        body = body.replace("{brief_path}", "research/briefs/<topic-slug>-<date>.md")
        body = body.replace("{findings_path}", "research/findings/<topic-slug>-<date>.md")
        body = body.replace("{review_path}", "research/notes/<topic-slug>-contrarian-review.md")
        body = body.replace("{report_path}", "research/reports/<topic-slug>-<date>.md")
    return body


def render_claude_command(template_path: Path) -> str:
    name = command_name(template_path)
    body = _substitute_runtime_placeholders(read_text(template_path).strip(), name)

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
    body = _substitute_runtime_placeholders(read_text(template_path).strip(), name)
    description = command_description(name)
    return f'description = "{description}"\nprompt = """\n{escape_toml_multiline(body)}\n"""\n'


def render_codex_command(template_path: Path) -> str:
    name = command_name(template_path)
    body = _substitute_runtime_placeholders(read_text(template_path).strip(), name)

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


def collect_skill_ops(base_root: Path, agents: tuple[str, ...]) -> list[Operation]:
    ops: list[Operation] = []
    runtime_dirs = {agent: base_root / AGENT_RUNTIME_DIRS[agent] for agent in agents}

    for source in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        for agent, runtime_dir in runtime_dirs.items():
            ops.append(
                Operation("copy", source, runtime_dir / "skills" / source.parent.name / "SKILL.md")
            )

    return ops


def collect_command_ops(base_root: Path, agents: tuple[str, ...]) -> list[Operation]:
    ops: list[Operation] = []
    for source in sorted(TEMPLATES_DIR.glob("*.md")):
        name = command_name(source)
        for agent in agents:
            runtime_dir = base_root / AGENT_RUNTIME_DIRS[agent] / "commands"
            if agent == "claude":
                ops.append(Operation("claude-command", source, runtime_dir / f"{name}.md"))
            elif agent == "gemini":
                ops.append(Operation("gemini-command", source, runtime_dir / f"{name}.toml"))
            elif agent == "codex":
                ops.append(Operation("codex-command", source, runtime_dir / f"{name}.md"))
    return ops


def collect_ops(base_root: Path, agents: tuple[str, ...]) -> list[Operation]:
    ops: list[Operation] = []
    if "claude" in agents:
        for source in sorted(CLAUDE_AGENTS_DIR.glob("*.md")):
            ops.append(Operation("copy", source, base_root / ".claude" / "agents" / source.name))
        if CLAUDE_MEMORY.exists():
            ops.append(Operation("copy", CLAUDE_MEMORY, base_root / ".claude" / "CLAUDE.md"))
    if "gemini" in agents and GEMINI_MEMORY.exists():
        ops.append(Operation("copy", GEMINI_MEMORY, base_root / ".gemini" / "GEMINI.md"))
    if "codex" in agents and AGENTS_MEMORY.exists():
        ops.append(Operation("copy", AGENTS_MEMORY, base_root / ".codex" / "AGENTS.md"))
    ops.extend(collect_skill_ops(base_root, agents))
    ops.extend(collect_command_ops(base_root, agents))
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

    if operation.kind == "codex-command":
        content = render_codex_command(operation.source)
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
        "--agent",
        choices=["all", "claude", "gemini", "codex"],
        default="all",
        help="Limit installation to a single agent runtime.",
    )
    parser.add_argument(
        "--scope",
        choices=["project", "home", "both"],
        default="both",
        help="Install into the repository runtime, the user home runtime, or both.",
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
    agents = normalize_agents(args.agent)
    ops: list[Operation] = []
    if args.scope in {"project", "both"}:
        ops.extend(collect_ops(ROOT, agents))
    if args.scope in {"home", "both"}:
        ops.extend(collect_ops(home, agents))

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
            elif op.kind == "codex-command":
                expected = render_codex_command(op.source)
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
