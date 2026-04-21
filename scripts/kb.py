from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from utils import (
    CONFIG,
    ROOT,
    agent_run,
    build_prompt,
    build_runtime_prompt,
    dump_frontmatter,
    ensure_dir,
    now_stamp,
    parse_frontmatter,
    shell_join,
    slugify,
    write_text,
)
from vault_graph import (
    GRAPH_PATH,
    RETENTION_REPORT_PATH,
    build_nodes_and_edges,
    export_csv_rows,
    load_graph,
    save_graph,
    search_graph,
    traverse_graph,
    write_retention_report,
)
import render_manifest as _rm
import backfill_answer_quality as _baq
import backfill_concept_quality as _bcq
import backfill_source_metadata as _bsm
import backfill_source_notes as _bsn
import claim_registry as _cr
import contradiction_registry as _conr
import install_agent_assets as _iaa
import lint_vault as _lint
import normalize_github_sources as _ngs
import research_workflow as _rw
import vault_scorecard as _vs

OUTPUTS = CONFIG.outputs_dir
ANSWER_PLACEHOLDER = "__ANSWER_PENDING__"
ANSWER_QUALITY_VALUES = {"memo-only", "durable"}
ANSWER_SCOPE_VALUES = {"private", "shared"}
VAULT_UPDATES_RE = re.compile(r"## Vault Updates\s+(.*?)(?:\n## |\Z)", re.DOTALL)


# ---------------------------------------------------------------------------
# Answer-workflow helpers
# ---------------------------------------------------------------------------


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
        CONFIG.home_note.write_text(
            home_text + suffix + "\n## Recent Answers\n\n" + new_bullet + "\n",
            encoding="utf-8",
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


# ---------------------------------------------------------------------------
# Source / ingest runners
# ---------------------------------------------------------------------------


def run_fetch(input_path: str, branch: str | None = None, fail_fast: bool = False) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / "ingest_sources.py"), "--input", input_path]
    if fail_fast:
        cmd.append("--fail-fast")
    if branch:
        cmd.extend(["--branch", branch])
    subprocess.run(cmd, check=True, cwd=ROOT)


def run_refresh_sources(
    branch: str | None = None, fail_fast: bool = False
) -> tuple[Path, list[str]]:
    """Re-fetch all registered sources and report which ones changed content.

    Returns ``(refresh_list_path, changed_source_ids)``.  The changed list is
    populated by running ``backfill-source-metadata`` after the fetch, comparing
    the new content hashes against the previously stored ones.  Callers use the
    list to decide whether a compile pass is necessary.
    """
    registry = json.loads(CONFIG.registry_path.read_text(encoding="utf-8"))
    refresh_list = ROOT / ".tmp" / f"refresh-sources-{now_stamp()}.txt"
    ensure_dir(refresh_list.parent)
    seen: set[str] = set()
    sources: list[str] = []
    for item in registry:
        source = item.get("source")
        if not source or source in seen:
            continue
        seen.add(source)
        sources.append(source)
    refresh_list.write_text("\n".join(sources) + "\n", encoding="utf-8")
    cmd = [sys.executable, str(ROOT / "scripts" / "ingest_sources.py"), "--input", str(refresh_list), "--refresh"]
    if fail_fast:
        cmd.append("--fail-fast")
    if branch:
        cmd.extend(["--branch", branch])
    subprocess.run(cmd, check=True, cwd=ROOT)
    # Detect which sources actually changed by comparing content hashes.
    changed = _bsm.run(all=True)
    return refresh_list, changed


def run_ingest_github(repo: str, branch: str | None = None) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / "ingest_github_repo.py"), "--repo", repo]
    if branch:
        cmd.extend(["--branch", branch])
    subprocess.run(cmd, check=True, cwd=ROOT)


def run_export_vault(output: str | None = None) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / "export_obsidian_vault.py")]
    if output:
        cmd.extend(["--output", output])
    subprocess.run(cmd, check=True, cwd=ROOT)


def run_normalize_github_sources(dry_run: bool = False) -> None:
    _ngs.run(dry_run=dry_run)


def run_bootstrap(
    target: str,
    project_name: str | None = None,
    with_examples: bool = False,
    force: bool = False,
) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / "bootstrap_kb.py"), "--target", target]
    if project_name:
        cmd.extend(["--project-name", project_name])
    if with_examples:
        cmd.append("--with-examples")
    if force:
        cmd.append("--force")
    subprocess.run(cmd, check=True, cwd=ROOT)


def run_install_agent_assets(
    agent: str = "all",
    scope: str = "both",
    dry_run: bool = False,
    force: bool = False,
) -> None:
    results = _iaa.install_agent_assets(
        agent=agent,
        scope=scope,
        project_root=ROOT,
        home_root=None,
        dry_run=dry_run,
        overwrite=force,
    )
    for line in results:
        print(line)
    if dry_run and any(not line.startswith("skipped") for line in results):
        raise SystemExit(1)


def run_backfill_source_notes(dry_run: bool = False) -> None:
    _bsn.run(all_missing=True, dry_run=dry_run)


def run_backfill_source_metadata(dry_run: bool = False) -> list[str]:
    return _bsm.run(all=True, dry_run=dry_run)


def run_backfill_concept_quality(dry_run: bool = False) -> None:
    _bcq.run(all=True, dry_run=dry_run)


def run_backfill_answer_quality(dry_run: bool = False) -> None:
    _baq.run(all=True, dry_run=dry_run)


def run_export_index(output: str | None = None, fmt: str = "json") -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / "export_vault_index.py"), "--format", fmt]
    if output:
        cmd.extend(["--output", output])
    subprocess.run(cmd, check=True, cwd=ROOT)


def run_build_graph(
    output: str | None = None,
    report_output: str | None = None,
    csv_output: str | None = None,
) -> None:
    graph = build_nodes_and_edges()
    graph_path = Path(output).resolve() if output else GRAPH_PATH
    changed = save_graph(graph, graph_path)
    report_path = Path(report_output).resolve() if report_output else RETENTION_REPORT_PATH
    report_changed = write_retention_report(graph, path=report_path)
    csv_changed = False
    if csv_output:
        csv_path = Path(csv_output).resolve()
        ensure_dir(csv_path.parent)
        rows = export_csv_rows(graph)
        fieldnames = sorted({key for row in rows for key in row.keys()})
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        csv_changed = True
    print(
        f"Graph {'updated' if changed else 'unchanged'}: "
        f"{graph_path.relative_to(ROOT) if graph_path.is_relative_to(ROOT) else graph_path}"
    )
    print(
        f"Retention report {'updated' if report_changed else 'unchanged'}: "
        f"{report_path.relative_to(ROOT) if report_path.is_relative_to(ROOT) else report_path}"
    )
    if csv_output:
        print(f"Graph CSV {'written' if csv_changed else 'unchanged'}: {Path(csv_output).resolve()}")


def run_search_graph(query: str, limit: int = 10, scope: str = "all", fmt: str = "json") -> None:
    results = search_graph(load_graph(), query, limit=limit, scope=scope)
    if fmt == "json":
        print(json.dumps({"query": query, "scope": scope, "results": results}, indent=2, ensure_ascii=False))
        return
    if not results:
        print("No matches.")
        return
    for item in results:
        print(f"- {item['kind']}: {item['title']} ({item['path']}) score={item['score']}")


def run_traverse_graph(
    start: str,
    depth: int = 2,
    relations: list[str] | None = None,
    scope: str = "all",
    fmt: str = "json",
) -> None:
    graph = load_graph()
    rel_filter = set(relations) if relations else None
    results = traverse_graph(graph, start, depth=depth, relations=rel_filter, scope=scope)
    if fmt == "json":
        print(
            json.dumps(
                {"start": start, "depth": depth, "scope": scope, "relations": relations or [], "results": results},
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    if not results:
        print("No traversal results.")
        return
    for item in results:
        node = item["node"]
        print(f"- depth {item['depth']}: {node['kind']} {node['title']} via {item['via']}")


def run_retention_report(output: str | None = None, limit: int = 50) -> None:
    graph = load_graph()
    report_path = Path(output).resolve() if output else RETENTION_REPORT_PATH
    changed = write_retention_report(graph, path=report_path, limit=limit)
    print(
        f"Retention report {'updated' if changed else 'unchanged'}: "
        f"{report_path.relative_to(ROOT) if report_path.is_relative_to(ROOT) else report_path}"
    )


def run_validate_config() -> None:
    """Print a summary of the loaded config and confirm all required keys are present."""
    from utils import load_config, _REQUIRED_KEYS

    cfg = load_config()
    print(f"Config OK: {cfg.project_name}")
    print(f"  raw_dir:       {cfg.raw_dir}")
    print(f"  vault_dir:     {cfg.vault_dir}")
    print(f"  research_dir:  {cfg.research_dir}")
    print(f"  outputs_dir:   {cfg.outputs_dir}")
    print(f"  allow_web_fetch_during_qa:   {cfg.allow_web_fetch_during_qa}")
    print(f"  file_answer_back_into_vault: {cfg.file_answer_back_into_vault}")
    print(f"  use_obsidian_wikilinks:      {cfg.use_obsidian_wikilinks}")
    missing_dirs = [
        d
        for d in (cfg.raw_dir, cfg.vault_dir, cfg.concepts_dir, cfg.summaries_dir)
        if not d.exists()
    ]
    if missing_dirs:
        print("\nWarning: the following configured directories do not exist yet:")
        for d in missing_dirs:
            print(f"  {d}")
    else:
        print("  All configured directories exist.")


def run_maintenance(agent: str | None = None) -> None:
    if agent:
        _refresh_list, changed = run_refresh_sources()
        if changed:
            affected = propagate_stale_flags(changed)
            if affected:
                print(f"Flagged {len(affected)} concept(s) for revalidation.")
        cmd_compile(agent)
    run_normalize_github_sources()
    run_backfill_source_notes()
    run_backfill_source_metadata()
    run_backfill_concept_quality()
    run_backfill_answer_quality()
    run_extract_claims()
    run_extract_contradictions()
    run_build_graph()
    run_lint(fix_backlinks=True)
    run_retention_report(limit=10)
    run_scorecard()


def run_lint(strict: bool = False, fix_backlinks: bool = False) -> None:
    exit_code = _lint.run(strict=strict, fix_backlinks=fix_backlinks)
    if exit_code != 0:
        raise SystemExit(exit_code)


def propagate_stale_flags(changed_source_ids: list[str]) -> list[Path]:
    """Set ``revalidation_required: true`` on notes that cite changed sources.

    Scans concept pages (via Evidence section wikilinks) and answer memos
    (via ``sources_consulted`` frontmatter).  Any page that references at least
    one of the changed source IDs gets flagged unless already flagged.

    Returns the list of newly-flagged paths (concepts + answers combined).
    """
    if not changed_source_ids:
        return []
    changed_set = set(changed_source_ids)
    affected: list[Path] = []

    # --- Concept pages ---
    for page_path in sorted(CONFIG.concepts_dir.glob("*.md")):
        text = page_path.read_text(encoding="utf-8")
        cited = _lint.extract_evidence_source_ids(text)
        if not cited.intersection(changed_set):
            continue
        frontmatter, body = parse_frontmatter(text)
        if frontmatter.get("revalidation_required"):
            continue
        frontmatter["revalidation_required"] = True
        page_path.write_text(dump_frontmatter(frontmatter) + body, encoding="utf-8")
        affected.append(page_path)

    # --- Answer memos ---
    for page_path in sorted(CONFIG.answers_dir.glob("*.md")):
        text = page_path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        if frontmatter.get("type") != "answer":
            continue
        sc = frontmatter.get("sources_consulted")
        consulted = set(sc) if isinstance(sc, list) else set()
        if not consulted.intersection(changed_set):
            continue
        if frontmatter.get("revalidation_required"):
            continue
        frontmatter["revalidation_required"] = True
        page_path.write_text(dump_frontmatter(frontmatter) + body, encoding="utf-8")
        affected.append(page_path)

    return affected


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


def run_extract_claims() -> None:
    _cr.run()


def run_extract_contradictions() -> None:
    _conr.run()


def run_contradiction_search(query: str, limit: int = 20, fmt: str = "text") -> None:
    recs = _conr.load_contradictions()
    results = _conr.search_contradictions(recs, query, limit=limit)
    if fmt == "json":
        print(json.dumps({"query": query, "count": len(results), "results": results}, indent=2, ensure_ascii=False))
        return
    if not results:
        print("No matching contradiction records.")
        return
    for item in results:
        status = "documented" if item["documented"] else "UNDOCUMENTED"
        oq = item["open_question"] or "(no open question)"
        print(f"[{status}] {item['concept']} — {oq}")
        if item["source_ids"]:
            print(f"  sources: {', '.join(item['source_ids'])}")
        if item["claim_ids"]:
            print(f"  claims : {', '.join(item['claim_ids'])}")


def run_scorecard(output: str | None = None, fmt: str = "text") -> None:
    from vault_scorecard import run as _sc_run, print_summary as _sc_print, SCORECARD_PATH
    out_path = Path(output).resolve() if output else None
    scorecard = _sc_run(output=out_path)
    saved_path = out_path or SCORECARD_PATH
    if fmt == "json":
        print(json.dumps(scorecard, indent=2, ensure_ascii=False))
    else:
        _sc_print(scorecard)
        print(f"Scorecard saved: {saved_path.relative_to(ROOT) if saved_path.is_relative_to(ROOT) else saved_path}")


def run_eval_setup() -> None:
    """Create the golden Q&A evaluation scaffold if it does not exist."""
    import yaml
    eval_path = ROOT / "tests" / "qa_golden.yaml"
    if eval_path.exists():
        print(f"Eval scaffold already exists: {eval_path.relative_to(ROOT)}")
        return
    scaffold = {
        "version": "1.0",
        "description": (
            "Golden Q&A evaluation set for K-Ops vault quality assurance. "
            "Add questions whose answers should be consistently derivable from the vault."
        ),
        "questions": [
            {
                "id": "q001",
                "question": "What is the core purpose of K-Ops?",
                "expected_themes": ["knowledge base", "agent", "Obsidian", "ingest"],
                "expected_sources": [],
                "expected_concepts": [],
                "notes": "Should be answerable from OPERATING_RULES.md or notes/Home.md",
            }
        ],
    }
    eval_path.write_text(
        yaml.safe_dump(scaffold, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"Eval scaffold created: {eval_path.relative_to(ROOT)}")
    print("Add questions to tests/qa_golden.yaml, then run 'eval-check' to validate.")


def run_eval_check() -> None:
    """Validate the golden Q&A file structure and print a summary."""
    import yaml
    eval_path = ROOT / "tests" / "qa_golden.yaml"
    if not eval_path.exists():
        print("No eval file found. Run 'eval-setup' to create it.")
        raise SystemExit(1)
    try:
        data = yaml.safe_load(eval_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"YAML parse error in {eval_path.relative_to(ROOT)}: {exc}")
        raise SystemExit(1)
    if not isinstance(data, dict) or "questions" not in data:
        print("Invalid eval file: missing 'questions' key.")
        raise SystemExit(1)
    questions = data["questions"]
    if not isinstance(questions, list):
        print("Invalid eval file: 'questions' must be a list.")
        raise SystemExit(1)
    errors: list[str] = []
    for idx, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            errors.append(f"  q{idx}: not a mapping")
            continue
        for field in ("id", "question"):
            if not q.get(field):
                errors.append(f"  {q.get('id', f'q{idx}')}: missing required field '{field}'")
    if errors:
        print(f"Eval check FAILED ({len(errors)} error(s)):")
        for err in errors:
            print(err)
        raise SystemExit(1)
    print(
        f"Eval check OK: {len(questions)} question(s) in "
        f"{eval_path.relative_to(ROOT)} (version {data.get('version', '?')})"
    )


def run_claim_search(query: str, limit: int = 20, fmt: str = "text") -> None:
    claims = _cr.load_claims()
    results = _cr.search_claims(claims, query, limit=limit)
    if fmt == "json":
        print(json.dumps({"query": query, "count": len(results), "results": results}, indent=2, ensure_ascii=False))
        return
    if not results:
        print("No matching claims.")
        return
    for item in results:
        print(f"[{item['claim_quality'] or '?'}] {item['concept']} — {item['text']}")
        if item["source_ids"]:
            print(f"  sources: {', '.join(item['source_ids'])}")


def run_stale_impact(fmt: str = "text") -> None:
    """Report concepts and answers flagged for revalidation after upstream source changes."""
    flagged: list[dict] = []

    for page_path in sorted(CONFIG.concepts_dir.glob("*.md")):
        text = page_path.read_text(encoding="utf-8")
        frontmatter, _ = parse_frontmatter(text)
        if not frontmatter.get("revalidation_required"):
            continue
        cited = sorted(_lint.extract_evidence_source_ids(text))
        flagged.append(
            {
                "kind": "concept",
                "path": page_path.relative_to(ROOT).as_posix(),
                "title": str(frontmatter.get("title") or page_path.stem),
                "quality": str(frontmatter.get("claim_quality") or ""),
                "cited_sources": cited,
            }
        )

    for page_path in sorted(CONFIG.answers_dir.glob("*.md")):
        text = page_path.read_text(encoding="utf-8")
        frontmatter, _ = parse_frontmatter(text)
        if frontmatter.get("type") != "answer" or not frontmatter.get("revalidation_required"):
            continue
        sc = frontmatter.get("sources_consulted")
        consulted = sorted(sc) if isinstance(sc, list) else []
        flagged.append(
            {
                "kind": "answer",
                "path": page_path.relative_to(ROOT).as_posix(),
                "title": str(frontmatter.get("title") or page_path.stem),
                "quality": str(frontmatter.get("answer_quality") or ""),
                "cited_sources": consulted,
            }
        )

    if fmt == "json":
        print(json.dumps({"count": len(flagged), "flagged": flagged}, indent=2, ensure_ascii=False))
        return
    if not flagged:
        print("No notes flagged for revalidation.")
        return
    print(f"{len(flagged)} note(s) flagged for revalidation:")
    for item in flagged:
        sources_label = ", ".join(item["cited_sources"]) or "none"
        print(f"  - [{item['kind']}] {item['path']} (quality: {item['quality']}, sources: {sources_label})")


def run_clear_stale_flags(dry_run: bool = False) -> None:
    """Remove ``revalidation_required`` from all concept pages and answer memos."""
    cleared: list[str] = []
    scan_paths = list(sorted(CONFIG.concepts_dir.glob("*.md"))) + list(sorted(CONFIG.answers_dir.glob("*.md")))
    for page_path in scan_paths:
        text = page_path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        if not frontmatter.pop("revalidation_required", None):
            continue
        if not dry_run:
            page_path.write_text(dump_frontmatter(frontmatter) + body, encoding="utf-8")
        cleared.append(page_path.relative_to(ROOT).as_posix())
    label = "Would clear" if dry_run else "Cleared"
    print(f"{label} revalidation flags from {len(cleared)} note(s)")
    for path in cleared:
        print(f"  - {path}")


# ---------------------------------------------------------------------------
# Top-level command functions
# ---------------------------------------------------------------------------


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
    ensure_dir(OUTPUTS)
    prompt = build_prompt("render_prompt.md", format=fmt, prompt=prompt_text)
    agent_run(agent, prompt, command=f"render-{fmt}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Living research vault workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("--input", required=True)
    p_ingest.add_argument("--branch", help="Optional branch override for GitHub repository URLs in the input list.")
    p_ingest.add_argument("--fail-fast", action="store_true")

    p_ingest_github = sub.add_parser("ingest-github")
    p_ingest_github.add_argument("--repo", required=True)
    p_ingest_github.add_argument("--branch")
    p_ingest_github.add_argument("--compile-agent", choices=["codex", "claude", "gemini"])

    p_compile = sub.add_parser("compile")
    p_compile.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_compile.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the prompt that would be sent without invoking the agent.",
    )

    p_refresh = sub.add_parser("refresh")
    p_refresh.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_refresh.add_argument("--branch", help="Optional branch override for GitHub repository URLs during refresh.")
    p_refresh.add_argument("--fail-fast", action="store_true")
    p_refresh.add_argument(
        "--force-compile",
        action="store_true",
        help="Run compile even if no source content changed.",
    )

    p_heal = sub.add_parser("heal")
    p_heal.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_heal.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the prompt that would be sent without invoking the agent.",
    )

    p_ask = sub.add_parser("ask")
    p_ask.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_ask.add_argument("--question", required=True)

    p_render = sub.add_parser("render")
    p_render.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_render.add_argument("--format", required=True, choices=["memo", "slides", "outline", "report"])
    p_render.add_argument("--prompt", required=True)

    p_install_assets = sub.add_parser("install-agent-assets")
    p_install_assets.add_argument("--agent", choices=["all", "claude", "gemini", "codex"], default="all")
    p_install_assets.add_argument("--scope", choices=["project", "home", "both"], default="both")
    p_install_assets.add_argument("--dry-run", action="store_true")
    p_install_assets.add_argument("--force", action="store_true")

    p_research_start = sub.add_parser("research-start")
    p_research_start.add_argument("--topic", required=True)
    p_research_start.add_argument("--tier", choices=sorted(_rw.RESEARCH_TIERS), default="standard")

    p_research_status = sub.add_parser("research-status")
    p_research_status.add_argument("topic", nargs="?", default=None)
    p_research_status.add_argument("--topic", dest="topic_opt")

    p_research_collect = sub.add_parser("research-collect")
    p_research_collect.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_research_collect.add_argument("--topic", required=True)
    p_research_collect.add_argument("--tier", choices=sorted(_rw.RESEARCH_TIERS), default="standard")

    p_research_review = sub.add_parser("research-review")
    p_research_review.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_research_review.add_argument("--topic", required=True)
    p_research_review.add_argument("--tier", choices=sorted(_rw.RESEARCH_TIERS), default="standard")

    p_research_report = sub.add_parser("research-report")
    p_research_report.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_research_report.add_argument("--topic", required=True)
    p_research_report.add_argument("--tier", choices=sorted(_rw.RESEARCH_TIERS), default="standard")
    p_research_report.add_argument("--allow-missing-review", action="store_true")

    p_research_import = sub.add_parser("research-import")
    p_research_import.add_argument("--topic", required=True)
    p_research_import.add_argument("--path", required=True)
    p_research_import.add_argument(
        "--provider",
        choices=["gemini", "openai", "claude", "perplexity", "other"],
        default="other",
    )
    p_research_import.add_argument("--origin")
    p_research_import.add_argument("--tier", choices=sorted(_rw.RESEARCH_TIERS), default="standard")

    p_research_archive = sub.add_parser("research-archive")
    p_research_archive.add_argument("--topic", required=True)

    p_export = sub.add_parser("export-vault")
    p_export.add_argument("--output")

    p_export_index = sub.add_parser("export-index")
    p_export_index.add_argument("--output")
    p_export_index.add_argument("--format", choices=["json", "csv"], default="json")

    p_build_graph = sub.add_parser("build-graph")
    p_build_graph.add_argument("--output")
    p_build_graph.add_argument("--report-output")
    p_build_graph.add_argument("--csv-output")

    p_search = sub.add_parser("search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--scope", choices=["all", "shared"], default="all")
    p_search.add_argument("--format", choices=["json", "text"], default="json")

    p_traverse = sub.add_parser("graph-traverse")
    p_traverse.add_argument("--start", required=True)
    p_traverse.add_argument("--depth", type=int, default=2)
    p_traverse.add_argument("--relation", action="append")
    p_traverse.add_argument("--scope", choices=["all", "shared"], default="all")
    p_traverse.add_argument("--format", choices=["json", "text"], default="json")

    p_retention = sub.add_parser("retention-report")
    p_retention.add_argument("--output")
    p_retention.add_argument("--limit", type=int, default=50)

    p_normalize_github = sub.add_parser("normalize-github-sources")
    p_normalize_github.add_argument("--dry-run", action="store_true")

    sub.add_parser("validate", help="Print the loaded config and verify all required paths.")

    p_bootstrap = sub.add_parser("bootstrap")
    p_bootstrap.add_argument("--target", required=True, help="Directory for the new blank starter vault.")
    p_bootstrap.add_argument("--project-name", help="Optional project name to write into the generated config.")
    p_bootstrap.add_argument("--with-examples", action="store_true", help="Add a tiny examples folder with starter input files.")
    p_bootstrap.add_argument("--force", action="store_true", help="Overwrite the starter scaffold even if the target already exists.")

    p_backfill_metadata = sub.add_parser("backfill-source-metadata")
    p_backfill_metadata.add_argument("--dry-run", action="store_true")

    p_backfill_concept_quality = sub.add_parser("backfill-concept-quality")
    p_backfill_concept_quality.add_argument("--dry-run", action="store_true")

    p_backfill_answer_quality = sub.add_parser("backfill-answer-quality")
    p_backfill_answer_quality.add_argument("--dry-run", action="store_true")

    p_backfill_notes = sub.add_parser("backfill-source-notes")
    p_backfill_notes.add_argument("--dry-run", action="store_true")

    p_maintain = sub.add_parser("maintenance")
    p_maintain.add_argument(
        "--agent",
        choices=["codex", "claude", "gemini"],
        help="Optional agent to refresh and compile before the mechanical maintenance pass.",
    )

    sub.add_parser("extract-claims", help="Extract atomic claims from concept pages and write data/claims.json.")

    p_claim_search = sub.add_parser("claim-search", help="Search the claims registry by keyword.")
    p_claim_search.add_argument("--query", required=True)
    p_claim_search.add_argument("--limit", type=int, default=20)
    p_claim_search.add_argument("--format", choices=["text", "json"], default="text")

    p_stale_impact = sub.add_parser("stale-impact", help="Report concept pages flagged for revalidation after source changes.")
    p_stale_impact.add_argument("--format", choices=["text", "json"], default="text")

    p_clear_stale = sub.add_parser("clear-stale-flags", help="Remove revalidation_required flags from all concept pages and answers.")
    p_clear_stale.add_argument("--dry-run", action="store_true")

    p_scorecard = sub.add_parser("scorecard", help="Compute vault health scorecard and write data/scorecard.json.")
    p_scorecard.add_argument("--output", help="Override output path.")
    p_scorecard.add_argument("--format", choices=["text", "json"], default="text")

    sub.add_parser("eval-setup", help="Create the golden Q&A evaluation scaffold at tests/qa_golden.yaml.")

    sub.add_parser("eval-check", help="Validate the golden Q&A file at tests/qa_golden.yaml.")

    sub.add_parser("extract-contradictions", help="Extract contradiction records from conflicting concepts and write data/contradictions.json.")

    p_contradiction_search = sub.add_parser("contradiction-search", help="Search the contradiction registry by keyword.")
    p_contradiction_search.add_argument("--query", required=True)
    p_contradiction_search.add_argument("--limit", type=int, default=20)
    p_contradiction_search.add_argument("--format", choices=["text", "json"], default="text")

    p_lint = sub.add_parser("lint")
    p_lint.add_argument("--strict", action="store_true")
    p_lint.add_argument("--fix-backlinks", action="store_true")

    sub.add_parser("render-manifest", help="Print a JSON manifest of the registry and vault files.")

    args = parser.parse_args()

    if args.command == "ingest":
        run_fetch(args.input, branch=args.branch, fail_fast=args.fail_fast)
    elif args.command == "ingest-github":
        run_ingest_github(args.repo, args.branch)
        if args.compile_agent:
            cmd_compile(args.compile_agent)
    elif args.command == "compile":
        cmd_compile(args.agent, dry_run=args.dry_run)
    elif args.command == "refresh":
        _refresh_list, changed = run_refresh_sources(branch=args.branch, fail_fast=args.fail_fast)
        if changed or args.force_compile:
            if changed:
                print(f"{len(changed)} source(s) changed content — running compile.")
                affected = propagate_stale_flags(changed)
                if affected:
                    print(f"Flagged {len(affected)} concept(s) for revalidation (run 'stale-impact' to review):")
                    for p in affected:
                        print(f"  - {p.relative_to(ROOT)}")
            else:
                print("--force-compile set — running compile despite no content changes.")
            cmd_compile(args.agent)
        else:
            print("All sources unchanged — skipping compile.")
    elif args.command == "heal":
        cmd_heal(args.agent, dry_run=args.dry_run)
    elif args.command == "ask":
        cmd_ask(args.agent, args.question)
    elif args.command == "render":
        cmd_render(args.agent, args.format, args.prompt)
    elif args.command == "install-agent-assets":
        run_install_agent_assets(agent=args.agent, scope=args.scope, dry_run=args.dry_run, force=args.force)
    elif args.command == "research-start":
        _rw.cmd_research_start(args.topic, tier=args.tier)
    elif args.command == "research-status":
        _rw.cmd_research_status(args.topic_opt or args.topic or "all")
    elif args.command == "research-collect":
        _rw.cmd_research_collect(args.agent, args.topic, tier=args.tier)
    elif args.command == "research-review":
        _rw.cmd_research_review(args.agent, args.topic, tier=args.tier)
    elif args.command == "research-report":
        _rw.cmd_research_report(args.agent, args.topic, tier=args.tier, require_review=not args.allow_missing_review)
    elif args.command == "research-import":
        _rw.cmd_research_import(args.topic, args.path, args.provider, canonical_origin=args.origin, tier=args.tier)
    elif args.command == "research-archive":
        _rw.cmd_research_archive(args.topic)
    elif args.command == "export-vault":
        run_export_vault(args.output)
    elif args.command == "export-index":
        run_export_index(output=args.output, fmt=args.format)
    elif args.command == "build-graph":
        run_build_graph(output=args.output, report_output=args.report_output, csv_output=args.csv_output)
    elif args.command == "search":
        run_search_graph(args.query, limit=args.limit, scope=args.scope, fmt=args.format)
    elif args.command == "graph-traverse":
        run_traverse_graph(args.start, depth=args.depth, relations=args.relation, scope=args.scope, fmt=args.format)
    elif args.command == "retention-report":
        run_retention_report(output=args.output, limit=args.limit)
    elif args.command == "normalize-github-sources":
        run_normalize_github_sources(dry_run=args.dry_run)
    elif args.command == "bootstrap":
        run_bootstrap(
            target=args.target,
            project_name=args.project_name,
            with_examples=args.with_examples,
            force=args.force,
        )
    elif args.command == "backfill-source-notes":
        run_backfill_source_notes(dry_run=args.dry_run)
    elif args.command == "backfill-source-metadata":
        run_backfill_source_metadata(dry_run=args.dry_run)
    elif args.command == "backfill-concept-quality":
        run_backfill_concept_quality(dry_run=args.dry_run)
    elif args.command == "backfill-answer-quality":
        run_backfill_answer_quality(dry_run=args.dry_run)
    elif args.command == "maintenance":
        run_maintenance(agent=args.agent)
    elif args.command == "extract-claims":
        run_extract_claims()
    elif args.command == "claim-search":
        run_claim_search(args.query, limit=args.limit, fmt=args.format)
    elif args.command == "stale-impact":
        run_stale_impact(fmt=args.format)
    elif args.command == "clear-stale-flags":
        run_clear_stale_flags(dry_run=args.dry_run)
    elif args.command == "scorecard":
        run_scorecard(output=args.output, fmt=args.format)
    elif args.command == "eval-setup":
        run_eval_setup()
    elif args.command == "eval-check":
        run_eval_check()
    elif args.command == "extract-contradictions":
        run_extract_contradictions()
    elif args.command == "contradiction-search":
        run_contradiction_search(args.query, limit=args.limit, fmt=args.format)
    elif args.command == "lint":
        run_lint(strict=args.strict, fix_backlinks=args.fix_backlinks)
    elif args.command == "render-manifest":
        _rm.main()
    elif args.command == "validate":
        run_validate_config()


if __name__ == "__main__":
    main()
