from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import importlib.resources

from kops import runners
from kops import source_override
from kops.utils import (
    CONFIG,
    ROOT,
    ensure_dir,
    now_stamp,
    parse_frontmatter,
    slugify,
    write_text,
)
from kops.kb_schema import Validator

ANSWER_PLACEHOLDER = "__ANSWER_PENDING__"
VAULT_UPDATES_RE = re.compile(r"## Vault Updates\s+(.*?)(?:\n## |\Z)", re.DOTALL)


def build_prompt(template_name: str, **kwargs: str) -> Path:
    template = (
        importlib.resources.files("kops")
        .joinpath("templates", template_name)
        .read_text(encoding="utf-8")
    )
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
    """Backward-compatible generator runner (write-oriented, mutating flags).

    Retained as a thin shim so existing imports/monkeypatches keep working. New
    call sites should use :func:`mutating_agent_run` or :func:`readonly_agent_run`
    to make the execution role explicit (roadmap task S0.2).
    """
    runners.execute_generator(agent, prompt_path, full_auto=True, cwd=ROOT)


def readonly_agent_run(agent: str, prompt_path: Path) -> None:
    """Read-only generator role for answer generation.

    Same providers as the mutating role, but never grants write-oriented flags
    (no Codex ``--full-auto``). Used by ``ask``.
    """
    runners.execute_generator(agent, prompt_path, full_auto=False, cwd=ROOT)


def mutating_agent_run(agent: str, prompt_path: Path) -> runners.GitCheckpoint:
    """Mutating generator role wrapped in pre/post git checkpoints.

    Records repo HEAD + working-tree status before the run and a before/after
    diff record after, so uncommitted destructive changes stay visible and
    recoverable. Never auto-commits and never auto-reverts. Used by
    compile / heal / render / research-*.
    """
    before = runners.git_checkpoint_before(ROOT)
    try:
        agent_run(agent, prompt_path)
    finally:
        record = runners.git_checkpoint_after(before, ROOT)
        runners.persist_git_record(record, ROOT)
    return record


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
            "consequence_tier: exploratory",
            'context_package_hash: ""',
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


def _format_seed_retrieval_result(result: dict) -> str:
    parts = [
        f"- id: {result.get('id', '')}",
        f"  kind: {result.get('kind', '')}",
        f"  method: {result.get('retrieval_method', '')}",
        f"  score: {result.get('score', 0)}",
        f"  title: {result.get('title', '')}",
    ]
    if result.get("path"):
        parts.append(f"  path: {result['path']}")
    if result.get("source_id") and result.get("anchor"):
        parts.append(f"  source_anchor: {result['source_id']}#{result['anchor']}")
    snippet = " ".join(str(result.get("snippet") or "").split())
    if snippet:
        parts.append(f"  snippet: {snippet[:240]}")
    return "\n".join(parts)


def build_ask_retrieval_context(question: str, top_k: int = 8) -> str:
    try:
        from kops.retrieval import VaultIndex

        index = VaultIndex()
        index.build()
        # Security-critical: the ask context is fed verbatim into the agent
        # prompt, so a flagged/revoked/adversarial/prompt-injected source must
        # never reach it by default. ``command="ask"`` scopes which audited
        # overrides (if any) may re-admit a source for this surface only.
        results = index.search(question, top_k=top_k, command="ask")
    except Exception as exc:
        return (
            "Seed retrieval failed before agent handoff.\n"
            f"- error: {type(exc).__name__}: {exc}\n"
            "- fallback: follow the manual search strategy below."
        )

    if not results:
        return (
            "Seed retrieval returned 0 results.\n"
            "- retrieval_path entry to record if no follow-up search is used: "
            f"method=bm25, layer=concept, query={json.dumps(question)}, results_count=0"
        )

    rendered = [
        "Seed retrieval was run before agent handoff using VaultIndex.search.",
        f"- query: {question}",
        f"- results_count: {len(results)}",
        "- retrieval_path entry to include if you use these seeds: "
        f"method=bm25, layer=concept, query={json.dumps(question)}, results_count={len(results)}",
        "",
        "Results:",
    ]
    rendered.extend(_format_seed_retrieval_result(result) for result in results)
    return "\n".join(rendered)


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


def validate_answer_memo_after_agent(answer_path: Path) -> None:
    text = answer_path.read_text(encoding="utf-8")
    frontmatter, _ = parse_frontmatter(text)
    issues = Validator().validate_answer_memo(frontmatter, answer_path)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        rendered = "\n".join(f"- {issue.field}: {issue.message}" for issue in errors)
        raise RuntimeError(f"Answer memo schema validation failed for {answer_path}:\n{rendered}")

    retrieval_path = frontmatter.get("retrieval_path")
    if not isinstance(retrieval_path, list) or not retrieval_path:
        raise RuntimeError(
            f"Answer memo `{answer_path.relative_to(ROOT)}` must populate non-empty `retrieval_path`."
        )

    if "fetch_required" not in frontmatter:
        raise RuntimeError(
            f"Answer memo `{answer_path.relative_to(ROOT)}` must set `fetch_required`."
        )


def _registry_entry_flag_reasons(entry: dict) -> list[str]:
    """Flag reasons for a registry entry.

    Delegates to the canonical ``source_override.frontmatter_flag_reasons`` so the
    compile planner, claim admission, and every serving surface share one
    definition of "flagged" (notably including ``deleted-from-origin``, which an
    earlier inline copy of this set omitted) and cannot drift apart.
    """
    return source_override.frontmatter_flag_reasons(entry)


def _build_compile_plan() -> dict:
    registry = json.loads(CONFIG.registry_path.read_text(encoding="utf-8"))
    existing_ids = {path.stem for path in CONFIG.summaries_dir.rglob("src-*.md")}
    all_ids = {item["id"] for item in registry if item.get("id")}

    overrides = source_override.load_overrides()
    flagged: list[dict] = []
    flagged_ids: set[str] = set()
    for item in registry:
        source_id = item.get("id")
        if not source_id:
            continue
        excluded, reasons = source_override.should_exclude(
            item, command="compile", overrides=overrides
        )
        if not reasons:
            continue
        if excluded:
            flagged_ids.add(source_id)
        flagged.append({"id": source_id, "reasons": reasons})

    return {
        "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "registry_count": len(registry),
        "to_summarize": sorted(all_ids - existing_ids - flagged_ids),
        "skip": sorted(existing_ids & all_ids),
        "flag_for_review": flagged,
    }


def _format_compile_plan_summary(plan: dict) -> str:
    to_summarize = plan.get("to_summarize", [])
    skip = plan.get("skip", [])
    flag = plan.get("flag_for_review", [])
    lines = [
        "Deterministic compile plan written to `.tmp/compile_plan.json`.",
        f"- registry_count: {plan.get('registry_count', 0)}",
        f"- to_summarize_count: {len(to_summarize)}",
        f"- skip_count: {len(skip)}",
        f"- flag_for_review_count: {len(flag)}",
    ]
    if to_summarize:
        lines.append("- to_summarize:")
        lines.extend(f"  - {source_id}" for source_id in to_summarize)
    if flag:
        lines.append("- flag_for_review:")
        for item in flag:
            reasons = ", ".join(item.get("reasons") or [])
            lines.append(f"  - {item.get('id')}: {reasons}")
    return "\n".join(lines)


def _build_compile_plan_summary() -> str:
    plan_path = ROOT / ".tmp" / "compile_plan.json"
    try:
        plan = _build_compile_plan()
        ensure_dir(plan_path.parent)
        plan_path.write_text(
            json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return _format_compile_plan_summary(plan)
    except Exception:
        return "Full vault compile run."


def _run_with_inner_verify(agent: str, prompt: Path, verify: bool) -> None:
    """Run the agent, then (unless disabled) verify the write did not regress the vault."""
    from kops import inner_loop

    before = inner_loop.snapshot() if verify else None
    mutating_agent_run(agent, prompt)
    if verify and before is not None:
        inner_loop.report(inner_loop.verify_agent_write(before))


def cmd_compile(agent: str, show_prompt: bool = False, verify: bool = True) -> None:
    plan_summary = _build_compile_plan_summary()
    prompt = build_prompt("compile_prompt.md", plan_summary=plan_summary)
    if show_prompt:
        print(prompt.read_text(encoding="utf-8"))
        return
    _run_with_inner_verify(agent, prompt, verify)


def cmd_heal(agent: str, show_prompt: bool = False, verify: bool = True) -> None:
    prompt = build_prompt("heal_prompt.md")
    if show_prompt:
        print(prompt.read_text(encoding="utf-8"))
        return
    _run_with_inner_verify(agent, prompt, verify)


def cmd_ask(agent: str, question: str, tier: str = "exploratory") -> None:
    from kops import output_gate

    asked_at = dt.datetime.now().replace(microsecond=0).isoformat()
    answer_path = CONFIG.answers_dir / f"{now_stamp()}_{slugify(question)}.md"
    if not answer_path.exists():
        write_text(answer_path, build_answer_scaffold(question, asked_at))
    web_fetch_policy = "allowed" if CONFIG.allow_web_fetch_during_qa else "disabled"
    retrieval_context = build_ask_retrieval_context(question)

    def _generate(claim_guidance: str, path: Path | None) -> str:
        # The consequence gate (output_gate.serve_ask) governs the outcome; this
        # closure is the generator seam it drives. The full ask prompt still
        # injects the seed retrieval context and now also the tier + admitted
        # claim ids + citation rule the gate froze into the context package.
        prompt = build_prompt(
            "ask_prompt.md",
            question=question,
            answer_path=str(answer_path.relative_to(ROOT)),
            web_fetch_policy=web_fetch_policy,
            retrieval_context=retrieval_context,
            tier=tier,
            claim_guidance=claim_guidance,
        )
        readonly_agent_run(agent, prompt)
        return answer_path.read_text(encoding="utf-8") if answer_path.exists() else ""

    result = output_gate.serve_ask(question, tier, generate=_generate, answer_path=answer_path)

    if result["decision"] in {"refuse", "abstain"}:
        print(f"Answer refused at consequence tier '{tier}' (decision: {result['decision']}).")
        print(f"Context package: {result['package_hash']}")
        print(f"Audit event: {result['audit_event_id']}")
        return

    if not answer_path.exists():
        raise FileNotFoundError(f"Answer memo was not written: {answer_path}")
    answer_text = answer_path.read_text(encoding="utf-8")
    if ANSWER_PLACEHOLDER in answer_text:
        raise RuntimeError(f"Answer memo still contains scaffold placeholders: {answer_path}")
    validate_answer_memo_after_agent(answer_path)
    answer_quality = normalize_answer_quality(answer_path)
    if CONFIG.file_answer_back_into_vault:
        update_recent_answers(answer_path)
    else:
        print("Vault backfilling is disabled; skipping Home/TODO updates.")
    print(f"Answer written to {answer_path.relative_to(ROOT)}")
    print(f"Answer quality: {answer_quality}")
    print(f"Consequence decision: {result['decision']} (tier: {tier})")
    if CONFIG.file_answer_back_into_vault:
        print(
            f"Home updated with {answer_path.relative_to(CONFIG.vault_dir).with_suffix('').as_posix()}"
        )


def cmd_render(agent: str, fmt: str, prompt_text: str, tier: str = "exploratory") -> None:
    from kops import output_gate

    ensure_dir(CONFIG.outputs_dir)
    gate = output_gate.gate_render(prompt_text, tier)
    if gate["decision"] in {"refuse", "abstain"}:
        print(
            f"Render refused at consequence tier '{tier}' (decision: {gate['decision']}): "
            "the evidence a render would rely on did not clear the gate."
        )
        print(f"Context package: {gate['package_hash']}")
        print(f"Audit event: {gate['audit_event_id']}")
        return
    prompt = build_prompt("render_prompt.md", format=fmt, prompt=prompt_text, tier=tier)
    mutating_agent_run(agent, prompt)
