from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
TEMPLATES_DIR = ROOT / "templates"
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

# Mapping from skill directory name -> the template that provides its runtime prompt.
# Skills not listed here have no template counterpart (e.g. ingest-sources is Python-only).
SKILL_TEMPLATE_MAP: dict[str, str] = {
    "compile-wiki": "compile_prompt.md",
    "lint-heal": "heal_prompt.md",
    "qa-agent": "ask_prompt.md",
    "render-output": "render_prompt.md",
}

SKILL_RUNTIME_PROMPT_FOOTER = (
    "\n## Runtime Prompt\n\n"
    "See `references/workflow-prompt.md` for the expanded workflow prompt.\n"
)

# Only these templates should be installed as interactive CLI commands.
# Research prompt templates use named Python format vars ({slug}, {topic}, ...)
# and are invoked exclusively through kb.py — not as slash commands.
COMMAND_TEMPLATES = {"ask_prompt.md", "compile_prompt.md", "heal_prompt.md", "render_prompt.md"}


@dataclass(frozen=True)
class Operation:
    kind: str
    source: Path
    target: Path
    content: str = ""  # pre-rendered content for kind="content" operations


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


def escape_toml_multiline(text: str) -> str:
    return text.replace('"""', '\\"\\"\\"')


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


def render_codex_command(template_path: Path) -> str:
    name = command_name(template_path)
    body = read_text(template_path).strip()

    if name == "ask":
        body = body.replace("{question}", "the user's question")
        body = body.replace("{answer_path}", "a timestamped file under notes/Answers/")
    elif name == "render":
        body = body.replace("{format}", "the requested output format")
        body = body.replace("{prompt}", "the requested output brief")

    return body + "\n"


def render_skill_runtime_prompt(template_path: Path, skill_name: str) -> str:
    """Produce the runtime-prompt text for a skill's ``references/workflow-prompt.md``.

    Applies the same variable substitutions as :func:`render_claude_command` but
    returns only the prompt body (no frontmatter), because skill reference files
    are plain Markdown consumed directly by the agent.
    """
    body = read_text(template_path).strip()
    if skill_name == "qa-agent":
        body = body.replace("{question}", "$ARGUMENTS")
        body = body.replace("{answer_path}", "notes/Answers/<timestamp>_<slug>.md")
    elif skill_name == "render-output":
        body = body.replace("{format}", "$1")
        body = body.replace("{prompt}", "$ARGUMENTS")
        if "Treat the first argument" not in body:
            body += "\n\nTreat the first argument as the output format and the remaining text as the brief."
    return body + "\n"


def collect_skill_ops(project_root: Path, agents: tuple[str, ...]) -> list[Operation]:
    ops: list[Operation] = []
    runtime_dirs = {agent: project_root / AGENT_RUNTIME_DIRS[agent] for agent in agents}

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        source_skill = skill_dir / "SKILL.md"
        if not source_skill.exists():
            continue
        base_content = read_text(source_skill).rstrip()
        template_name = SKILL_TEMPLATE_MAP.get(skill_name)
        has_ref = template_name is not None
        skill_content = base_content + (SKILL_RUNTIME_PROMPT_FOOTER if has_ref else "\n")

        for agent, runtime_dir in runtime_dirs.items():
            target_skill = runtime_dir / "skills" / skill_name / "SKILL.md"
            ops.append(Operation("content", source_skill, target_skill, content=skill_content))
            if has_ref:
                template_path = TEMPLATES_DIR / template_name
                ref_content = render_skill_runtime_prompt(template_path, skill_name)
                target_ref = runtime_dir / "skills" / skill_name / "references" / "workflow-prompt.md"
                ops.append(Operation("content", template_path, target_ref, content=ref_content))
    return ops


def collect_command_ops(project_root: Path, agents: tuple[str, ...]) -> list[Operation]:
    ops: list[Operation] = []
    for source in sorted(TEMPLATES_DIR.glob("*.md")):
        if source.name not in COMMAND_TEMPLATES:
            continue
        name = command_name(source)
        for agent in agents:
            runtime_dir = project_root / AGENT_RUNTIME_DIRS[agent] / "commands"
            if agent == "claude":
                ops.append(Operation("claude-command", source, runtime_dir / f"{name}.md"))
            elif agent == "gemini":
                ops.append(Operation("gemini-command", source, runtime_dir / f"{name}.toml"))
            elif agent == "codex":
                ops.append(Operation("codex-command", source, runtime_dir / f"{name}.md"))
    return ops


def collect_project_ops(project_root: Path, agents: str = "all") -> list[Operation]:
    """Return operations to sync project-level runtime assets.

    The runtime directories are generated from ``skills/`` + ``templates/`` and
    should never be edited by hand. Running this in CI catches prompt drift
    before it reaches runtime.
    """
    selected_agents = normalize_agents(agents)
    ops = collect_skill_ops(project_root, selected_agents)
    ops.extend(collect_command_ops(project_root, selected_agents))
    return ops


def collect_home_ops(home_root: Path, agents: str = "all") -> list[Operation]:
    selected_agents = normalize_agents(agents)
    ops: list[Operation] = []

    if "claude" in selected_agents:
        for source in sorted(CLAUDE_AGENTS_DIR.glob("*.md")):
            ops.append(Operation("copy", source, home_root / ".claude" / "agents" / source.name))
        if CLAUDE_MEMORY.exists():
            ops.append(Operation("copy", CLAUDE_MEMORY, home_root / ".claude" / "CLAUDE.md"))

    if "gemini" in selected_agents and GEMINI_MEMORY.exists():
        ops.append(Operation("copy", GEMINI_MEMORY, home_root / ".gemini" / "GEMINI.md"))

    if "codex" in selected_agents and AGENTS_MEMORY.exists():
        ops.append(Operation("copy", AGENTS_MEMORY, home_root / ".codex" / "AGENTS.md"))

    ops.extend(collect_skill_ops(home_root, tuple(selected_agents)))
    ops.extend(collect_command_ops(home_root, tuple(selected_agents)))
    return ops


def render_operation(operation: Operation) -> str:
    if operation.kind == "copy":
        return read_text(operation.source)
    if operation.kind == "claude-command":
        return render_claude_command(operation.source)
    if operation.kind == "gemini-command":
        return render_gemini_command(operation.source)
    if operation.kind == "codex-command":
        return render_codex_command(operation.source)
    if operation.kind == "content":
        return operation.content
    raise ValueError(f"Unsupported operation kind: {operation.kind}")


def materialize(operation: Operation, *, dry_run: bool) -> str:
    content = render_operation(operation)
    existed = operation.target.exists()
    if existed and operation.target.read_text(encoding="utf-8") == content:
        return "skipped"
    write_text(operation.target, content, dry_run=dry_run)
    return "updated" if existed else "created"


def install_agent_assets(
    *,
    agent: str = "all",
    scope: str = "both",
    project_root: Path | None = None,
    home_root: Path | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> list[str]:
    if scope not in {"project", "home", "both"}:
        raise ValueError(f"Unsupported scope: {scope}")

    project_root = project_root.expanduser() if project_root is not None else ROOT
    home_root = ensure_home(home_root)

    ops: list[Operation] = []
    if scope in {"project", "both"}:
        ops.extend(collect_project_ops(project_root, agent))
    if scope in {"home", "both"}:
        ops.extend(collect_home_ops(home_root, agent))

    results: list[str] = []
    for op in ops:
        expected = render_operation(op)
        if op.target.exists() and not overwrite:
            current = op.target.read_text(encoding="utf-8")
            if current == expected:
                results.append(f"skipped {op.target}")
                continue
        status = materialize(op, dry_run=dry_run)
        results.append(f"{status} {op.target}")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install Codex, Claude Code, and Gemini CLI runtime assets from this repo.",
    )
    parser.add_argument(
        "--agent",
        choices=["all", "claude", "gemini", "codex"],
        default="all",
        help="Which agent runtime(s) to sync.",
    )
    parser.add_argument(
        "--scope",
        choices=["project", "home", "both"],
        default="both",
        help="Install runtime assets into the repo copy, your home directory, or both.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Override the project root used for project-level installs.",
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

    results = install_agent_assets(
        agent=args.agent,
        scope=args.scope,
        project_root=args.project_root,
        home_root=args.home,
        dry_run=args.dry_run,
        overwrite=args.force,
    )
    for line in results:
        print(line)

    would_change = [line for line in results if not line.startswith("skipped")]
    if args.dry_run:
        if would_change:
            print(
                f"dry-run: {len(would_change)} asset(s) would be created/updated "
                "— run install_agent_assets.py (without --dry-run) to sync."
            )
            return 1
        print("dry-run: all assets are up to date.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
