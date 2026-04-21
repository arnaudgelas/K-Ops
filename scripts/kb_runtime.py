from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from utils import CONFIG, ROOT, agent_run, build_prompt, build_runtime_prompt, now_stamp, parse_frontmatter, slugify, write_text

ANSWER_PLACEHOLDER = "__ANSWER_PENDING__"
VAULT_UPDATES_RE = re.compile(r"## Vault Updates\s+(.*?)(?:\n## |\Z)", re.DOTALL)


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
            "sources_consulted: []",
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
        CONFIG.home_note.write_text(home_text + suffix + "\n## Recent Answers\n\n" + new_bullet + "\n", encoding="utf-8")
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
    frontmatter, body = parse_frontmatter(text)
    vault_updates = VAULT_UPDATES_RE.search(body)
    updates_text = vault_updates.group(1).strip() if vault_updates else ""
    has_durable_updates = bool(updates_text and updates_text != "- None." and updates_text != "None.")
    desired = "durable" if has_durable_updates else "memo-only"
    updated_text, changed = update_frontmatter_field(text, "answer_quality", desired)
    desired_scope = "shared" if desired == "durable" else "private"
    updated_text, scope_changed = update_frontmatter_field(updated_text, "scope", desired_scope)
    changed = changed or scope_changed
    if changed:
        answer_path.write_text(updated_text, encoding="utf-8")
    return desired


def run_triage() -> tuple[Path, str]:
    """Determine which sources need summaries, which are done, which are flagged.

    Reads ``data/registry.json`` and scans ``notes/Sources/`` to classify each
    source_id.  Writes ``.tmp/compile_plan.json`` and returns ``(plan_path,
    human_readable_summary)`` for injection into the compile prompt.
    """
    if not CONFIG.registry_path.exists():
        plan = {"to_summarize": [], "skip": [], "flag_for_review": []}
        summary = "No registry found — nothing to compile."
        return _write_triage_plan(plan), summary

    registry = json.loads(CONFIG.registry_path.read_text(encoding="utf-8"))
    existing_summaries = {p.stem for p in CONFIG.summaries_dir.glob("src-*.md")} if CONFIG.summaries_dir.exists() else set()

    to_summarize: list[str] = []
    skip: list[str] = []
    flag_for_review: list[str] = []

    seen: set[str] = set()
    for item in registry:
        source_id = item.get("source_id") or ""
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        raw_paths = list((ROOT / "data" / "raw").glob(f"{source_id}.*"))
        raw_size = sum(p.stat().st_size for p in raw_paths if p.exists())
        if source_id in existing_summaries:
            skip.append(source_id)
            continue
        if raw_size < 200:
            flag_for_review.append(source_id)
            continue
        # Detect imported model reports from registry metadata
        source_kind = item.get("source_kind") or ""
        if source_kind == "imported_model_report":
            flag_for_review.append(source_id)
        else:
            to_summarize.append(source_id)

    # Also check source notes for source_kind: imported_model_report not yet caught above
    if CONFIG.summaries_dir.exists():
        for p in CONFIG.summaries_dir.glob("src-*.md"):
            if p.stem in seen:
                continue
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
            if fm.get("source_kind") == "imported_model_report" and p.stem not in existing_summaries:
                flag_for_review.append(p.stem)
                seen.add(p.stem)

    plan = {
        "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "to_summarize": to_summarize,
        "skip": skip,
        "flag_for_review": flag_for_review,
    }
    plan_path = _write_triage_plan(plan)

    lines = [
        f"Triage complete ({plan_path.relative_to(ROOT)}):",
        f"  to_summarize   : {len(to_summarize)} source(s)",
        f"  skip (done)    : {len(skip)} source(s)",
        f"  flag_for_review: {len(flag_for_review)} source(s) (empty raw or model-generated)",
    ]
    if to_summarize:
        lines.append(f"  IDs to process : {', '.join(to_summarize[:10])}"
                     + (" …" if len(to_summarize) > 10 else ""))
    if flag_for_review:
        lines.append(f"  Flagged IDs    : {', '.join(flag_for_review)}")
    summary = "\n".join(lines)
    print(summary)
    return plan_path, summary


def _write_triage_plan(plan: dict) -> Path:
    plan_path = ROOT / ".tmp" / "compile_plan.json"
    ensure_dir(plan_path.parent)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return plan_path


def cmd_compile(agent: str, dry_run: bool = False) -> None:
    _plan_path, plan_summary = run_triage()
    prompt = build_prompt("compile_prompt.md", plan_summary=plan_summary)
    if dry_run:
        print("--- compile prompt (dry-run, agent not invoked) ---")
        print(prompt.read_text(encoding="utf-8"))
        return
    agent_run(agent, prompt, command="compile")


def cmd_heal(agent: str, dry_run: bool = False) -> None:
    prompt = build_prompt("heal_prompt.md")
    if dry_run:
        print("--- heal prompt (dry-run, agent not invoked) ---")
        print(prompt.read_text(encoding="utf-8"))
        return
    agent_run(agent, prompt, command="heal")


def cmd_ask(agent: str, question: str) -> None:
    asked_at = dt.datetime.now().replace(microsecond=0).isoformat()
    answer_path = CONFIG.answers_dir / f"{now_stamp()}_{slugify(question)}.md"
    if not answer_path.exists():
        write_text(answer_path, build_answer_scaffold(question, asked_at))
    prompt = build_prompt(
        "ask_prompt.md",
        question=question,
        answer_path=str(answer_path.relative_to(ROOT)),
    )
    agent_run(agent, prompt, command="ask")
    if not answer_path.exists():
        raise FileNotFoundError(f"Answer memo was not written: {answer_path}")
    answer_text = answer_path.read_text(encoding="utf-8")
    if ANSWER_PLACEHOLDER in answer_text:
        raise RuntimeError(f"Answer memo still contains scaffold placeholders: {answer_path}")
    answer_quality = normalize_answer_quality(answer_path)
    update_recent_answers(answer_path)
    print(f"Answer written to {answer_path.relative_to(ROOT)}")
    print(f"Answer quality: {answer_quality}")
    print(f"Home updated with {answer_path.relative_to(CONFIG.vault_dir).with_suffix('').as_posix()}")


def cmd_render(agent: str, fmt: str, prompt_text: str) -> None:
    ensure_prompt = build_runtime_prompt  # keep the module's prompt helper available for callers
    _ = ensure_prompt
    prompt = build_prompt("render_prompt.md", format=fmt, prompt=prompt_text)
    agent_run(agent, prompt, command=f"render-{fmt}")
