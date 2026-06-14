from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path

from utils import (
    CONFIG,
    ROOT,
    detect_agent_command,
    ensure_dir,
    now_stamp,
    parse_frontmatter,
    shell_join,
    slugify,
    write_text,
)

ANSWER_PLACEHOLDER = "__ANSWER_PENDING__"
VAULT_UPDATES_RE = re.compile(r"## Vault Updates\s+(.*?)(?:\n## |\Z)", re.DOTALL)


def build_prompt(template_name: str, **kwargs: str) -> Path:
    template = (ROOT / "templates" / template_name).read_text(encoding="utf-8")
    rendered = template.format(**kwargs)
    prompt_path = ROOT / ".tmp" / f"{template_name}.{now_stamp()}.md"
    ensure_dir(prompt_path.parent)
    write_text(prompt_path, rendered)
    return prompt_path


def build_runtime_prompt(name: str, text: str) -> Path:
    prompt_path = ROOT / ".tmp" / f"{name}.{now_stamp()}.md"
    ensure_dir(prompt_path.parent)
    write_text(prompt_path, text.rstrip() + "\n")
    return prompt_path


def agent_run(agent: str, prompt_path: Path) -> None:
    base_cmd = detect_agent_command(agent)
    prompt_text = prompt_path.read_text(encoding="utf-8")

    if agent == "codex":
        cmd = base_cmd + ["exec", "--skip-git-repo-check", "--full-auto", prompt_text]
    elif agent == "claude":
        cmd = base_cmd + ["-p", str(prompt_path)]
    elif agent == "gemini":
        cmd = base_cmd + ["-p", prompt_text]
    else:
        raise ValueError(agent)

    print(f"\nRunning: {shell_join(cmd)}\n")
    subprocess.run(cmd, check=True, cwd=ROOT)


def build_answer_scaffold(question: str, asked_at: str) -> str:
    title = question.strip() or "Q&A Memo"
    return "\n".join(
        [
            "---",
            f"title: {json.dumps(title)}",
            f"asked_at: {json.dumps(asked_at)}",
            "type: answer",
            "answer_quality: memo-only",
            "scope: private",
            "query_class: synthesis",
            "sources_consulted: []",
            "retrieval_path: []",
            "fetch_required: false",
            "tags:",
            "  - kb/answer",
            "---",
            "",
            "# Question",
            "",
            question.strip() or "No question supplied.",
            "",
            "---",
            "",
            "# Answer",
            "",
            ANSWER_PLACEHOLDER,
            "",
            "## Vault Updates",
            "",
            "- None.",
            "",
        ]
    )


def update_frontmatter_field(text: str, field: str, value: str) -> tuple[str, bool]:
    if not text.startswith("---\n"):
        return text, False
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return text, False
    frontmatter_lines = parts[0][4:].splitlines()
    new_line = (
        f"{field}: {json.dumps(value)}"
        if field in {"title", "asked_at", "answer_quality"}
        else f"{field}: {value}"
    )
    for index, line in enumerate(frontmatter_lines):
        if line.startswith(f"{field}:"):
            if line.strip() == new_line:
                return text, False
            frontmatter_lines[index] = new_line
            return "---\n" + "\n".join(frontmatter_lines) + "\n---\n" + parts[1], True

    insert_at = len(frontmatter_lines)
    for index, line in enumerate(frontmatter_lines):
        if line.startswith("type:"):
            insert_at = index + 1
            break
    frontmatter_lines.insert(insert_at, new_line)
    return "---\n" + "\n".join(frontmatter_lines) + "\n---\n" + parts[1], True


def update_recent_answers(answer_path: Path) -> None:
    text = answer_path.read_text(encoding="utf-8")
    frontmatter, _ = parse_frontmatter(text)
    title = str(frontmatter.get("title") or answer_path.stem)
    asked_at = str(frontmatter.get("asked_at") or "")
    date_label = asked_at.split("T", 1)[0] if asked_at else answer_path.stem[:10]
    answer_target = answer_path.relative_to(CONFIG.vault_dir).with_suffix("").as_posix()
    new_bullet = f"- [[{answer_target}|{date_label}: {title}]]"

    home_text = CONFIG.home_note.read_text(encoding="utf-8")
    section_re = re.compile(r"(## Recent Answers\s*\n)(.*?)(?=\n## |\Z)", re.DOTALL)
    match = section_re.search(home_text)
    if not match:
        suffix = "\n" if not home_text.endswith("\n") else ""
        CONFIG.home_note.write_text(
            home_text + suffix + "\n## Recent Answers\n\n" + new_bullet + "\n", encoding="utf-8"
        )
        return

    body = match.group(2).strip("\n")
    lines = [line.rstrip() for line in body.splitlines()]
    lines = [line for line in lines if answer_target not in line]
    if lines and lines[0].strip():
        lines.insert(0, new_bullet)
    else:
        lines = [new_bullet] + [line for line in lines if line.strip()]
    new_section = "## Recent Answers\n\n" + "\n".join(lines).rstrip() + "\n"
    home_text = home_text[: match.start()] + new_section + home_text[match.end() :]
    CONFIG.home_note.write_text(home_text, encoding="utf-8")


def normalize_answer_quality(answer_path: Path) -> str:
    text = answer_path.read_text(encoding="utf-8")
    vault_updates = VAULT_UPDATES_RE.search(parse_frontmatter(text)[1])
    updates_text = vault_updates.group(1).strip() if vault_updates else ""
    has_durable_updates = bool(
        updates_text and updates_text != "- None." and updates_text != "None."
    )
    desired = "durable" if has_durable_updates else "memo-only"
    updated_text, changed = update_frontmatter_field(text, "answer_quality", desired)
    desired_scope = "shared" if desired == "durable" else "private"
    updated_text, scope_changed = update_frontmatter_field(updated_text, "scope", desired_scope)
    changed = changed or scope_changed
    if changed:
        answer_path.write_text(updated_text, encoding="utf-8")
    return desired


def _build_compile_plan_summary() -> str:
    plan_path = ROOT / ".tmp" / "compile_plan.json"
    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            to_summarize = plan.get("to_summarize", [])
            skip = plan.get("skip", [])
            flag = plan.get("flag_for_review", [])
            return (
                f"Loaded from `.tmp/compile_plan.json`: "
                f"{len(to_summarize)} source(s) to summarize, "
                f"{len(skip)} to skip, {len(flag)} flagged for review."
            )
        except Exception:
            pass
    try:
        registry = json.loads(CONFIG.registry_path.read_text(encoding="utf-8"))
        all_ids = {item["id"] for item in registry}
        existing_ids = {path.stem for path in CONFIG.summaries_dir.rglob("src-*.md")}
        to_summarize = sorted(all_ids - existing_ids)
    except Exception:
        return "Full vault compile run."
    if not to_summarize:
        return (
            "Full vault compile run — all registry sources already have summaries; "
            "focus on concept page synthesis and backlink updates."
        )
    first_five = ", ".join(to_summarize[:5])
    more = f", … and {len(to_summarize) - 5} more" if len(to_summarize) > 5 else ""
    return (
        f"Derived plan: {len(to_summarize)} source(s) need summaries "
        f"(first 5: {first_five}{more}). "
        f"Registry has {len(all_ids)} entries; {len(existing_ids)} already have notes."
    )


def cmd_compile(agent: str, show_prompt: bool = False) -> None:
    plan_summary = _build_compile_plan_summary()
    prompt = build_prompt("compile_prompt.md", plan_summary=plan_summary)
    if show_prompt:
        print(prompt.read_text(encoding="utf-8"))
        return
    agent_run(agent, prompt)


def cmd_heal(agent: str, show_prompt: bool = False) -> None:
    prompt = build_prompt("heal_prompt.md")
    if show_prompt:
        print(prompt.read_text(encoding="utf-8"))
        return
    agent_run(agent, prompt)


def cmd_ask(agent: str, question: str) -> None:
    asked_at = dt.datetime.now().replace(microsecond=0).isoformat()
    answer_path = CONFIG.answers_dir / f"{now_stamp()}_{slugify(question)}.md"
    if not answer_path.exists():
        write_text(answer_path, build_answer_scaffold(question, asked_at))
    web_fetch_policy = "allowed" if CONFIG.allow_web_fetch_during_qa else "disabled"
    prompt = build_prompt(
        "ask_prompt.md",
        question=question,
        answer_path=str(answer_path.relative_to(ROOT)),
        web_fetch_policy=web_fetch_policy,
    )
    agent_run(agent, prompt)
    if not answer_path.exists():
        raise FileNotFoundError(f"Answer memo was not written: {answer_path}")
    answer_text = answer_path.read_text(encoding="utf-8")
    if ANSWER_PLACEHOLDER in answer_text:
        raise RuntimeError(f"Answer memo still contains scaffold placeholders: {answer_path}")
    answer_quality = normalize_answer_quality(answer_path)
    if CONFIG.file_answer_back_into_vault:
        update_recent_answers(answer_path)
    else:
        print("Vault backfilling is disabled; skipping Home/TODO updates.")
    print(f"Answer written to {answer_path.relative_to(ROOT)}")
    print(f"Answer quality: {answer_quality}")
    if CONFIG.file_answer_back_into_vault:
        print(
            f"Home updated with {answer_path.relative_to(CONFIG.vault_dir).with_suffix('').as_posix()}"
        )


def cmd_render(agent: str, fmt: str, prompt_text: str) -> None:
    ensure_dir(CONFIG.outputs_dir)
    prompt = build_prompt("render_prompt.md", format=fmt, prompt=prompt_text)
    agent_run(agent, prompt)
