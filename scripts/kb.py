from __future__ import annotations

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
import kb_eval as _ke
import kb_runtime as _kr
import research_workflow as _rw
import vault_scorecard as _vs

OUTPUTS = CONFIG.outputs_dir


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


def run_validate_config(strict: bool = False) -> None:
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
    if strict:
        try:
            import kb_schema as _ks
            _ks.validate_config(cfg)
            print("  Schema validation passed.")
        except ImportError:
            print("  Warning: kb_schema.py not found — strict schema validation skipped.")
        except Exception as exc:
            raise SystemExit(f"[validate --strict] Schema validation failed: {exc}")


def _clean_tmp(max_age_days: int = 7) -> None:
    import time

    tmp_dir = ROOT / ".tmp"
    if not tmp_dir.exists():
        return
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for path in tmp_dir.iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    print(f"Cleaned {removed} file(s) from .tmp/ (older than {max_age_days} days)")


def run_maintenance(agent: str | None = None, clean_tmp: bool = False) -> None:
    if clean_tmp:
        _clean_tmp()
    if agent:
        _refresh_list, changed = run_refresh_sources()
        if changed:
            affected = propagate_stale_flags(changed)
            if affected:
                print(f"Flagged {len(affected)} concept(s) for revalidation.")
        _kr.cmd_compile(agent)
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
    _ke.run_eval_setup()


def run_eval_check() -> None:
    _ke.run_eval_check()


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
# New command runners (ported from agkb)
# ---------------------------------------------------------------------------


def cmd_claim_map(concept: str, output: str = "stdout") -> None:
    """Generate a Mermaid argument-map diagram for a concept from claims.json."""
    import textwrap

    claims_path = ROOT / "data" / "claims.json"
    if not claims_path.exists():
        print(f"claims.json not found at {claims_path}")
        return

    payload = json.loads(claims_path.read_text(encoding="utf-8"))
    all_claims = payload.get("claims", [])
    concept_claims = [c for c in all_claims if c.get("concept") == concept]

    if not concept_claims:
        print(f"No claims found for concept '{concept}'. Check the stem matches claims.json 'concept' field.")
        return

    def safe_id(text: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_]", "_", text)

    def trunc(text: str, n: int = 55) -> str:
        return textwrap.shorten(text, width=n, placeholder="…")

    lines: list[str] = ["graph TD"]
    concept_node = safe_id(concept)
    lines.append(f'    {concept_node}["{concept}"]')
    lines.append("")

    source_ids: set[str] = set()
    for claim in concept_claims:
        cid = safe_id(claim["id"])
        label = trunc(claim.get("text", ""))
        lines.append(f'    {cid}["{label}"]')
        lines.append(f"    {concept_node} --> {cid}")
        for sid in claim.get("source_ids", []):
            source_ids.add(sid)
            src_node = safe_id(sid)
            lines.append(f"    {cid} --> {src_node}")
    lines.append("")

    for sid in sorted(source_ids):
        src_node = safe_id(sid)
        lines.append(f'    {src_node}(["{sid}"])')

    diagram = "\n".join(lines)

    if output == "stdout":
        print(diagram)
    else:
        out_path = ROOT / "outputs" / f"{concept}_argument_map.mermaid"
        ensure_dir(out_path.parent)
        out_path.write_text(diagram + "\n", encoding="utf-8")
        print(f"Argument map written to {out_path.relative_to(ROOT)}")


def run_suggest_links(
    approach: str = "all",
    min_co_cite: int = 2,
    min_shared: int = 2,
    emb_threshold: float = 0.75,
    min_gravity: float = 0.5,
    min_jaccard: float = 0.25,
    min_triadic: int = 2,
    ev_top_frac: float = 0.33,
    min_friction: float = 0.15,
    limit: int = 50,
    fmt: str = "json",
    output: str | None = None,
) -> None:
    try:
        from kb_suggest_links import run_suggest_links as _suggest
    except ImportError:
        raise SystemExit("kb_suggest_links.py not found — install it or copy from agkb/scripts/.")

    data = _suggest(
        approach=approach,
        min_co_cite=min_co_cite,
        min_shared=min_shared,
        emb_threshold=emb_threshold,
        min_gravity=min_gravity,
        min_jaccard=min_jaccard,
        min_triadic=min_triadic,
        ev_top_frac=ev_top_frac,
        min_friction=min_friction,
        limit=limit,
    )

    if output:
        out_path = Path(output).resolve()
        ensure_dir(out_path.parent)
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Suggestions written to {out_path} ({data['total_candidates']} candidates)")
        return

    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    if not data["candidates"]:
        print("No new link candidates found.")
        return
    for c in data["candidates"]:
        stars = "*" * c["signals"]
        print(f"{stars} {c['concept_a']}  <->  {c['concept_b']}")
        for reason in c["reasons"]:
            print(f"    {reason}")
        print(f"    Add to {c['concept_a']}: {c['wikilink_in_a']}")
        print(f"    Add to {c['concept_b']}: {c['wikilink_in_b']}")


def run_migrate_source_fields(dry_run: bool = False) -> None:
    """Batch-derive source_kind and ingested_at for source notes missing them, using data/registry.json."""
    registry = json.loads(CONFIG.registry_path.read_text(encoding="utf-8"))
    reg_by_id = {item["id"]: item for item in registry}

    FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

    fixed = 0
    skipped = 0
    for path in sorted(CONFIG.summaries_dir.rglob("src-*.md")):
        text = path.read_text(encoding="utf-8")
        fm_match = FRONT_RE.match(text)
        if not fm_match:
            continue
        fm_block = fm_match.group(1)
        body = text[fm_match.end():]

        sid_m = re.search(r"^source_id:\s*(\S+)", fm_block, re.MULTILINE)
        if not sid_m:
            continue
        sid = sid_m.group(1).strip('"\'')
        reg = reg_by_id.get(sid)
        if not reg:
            continue

        changed = False
        if not re.search(r"^source_kind:", fm_block, re.MULTILINE):
            raw_kind = reg.get("kind", "")
            fm_block += f"\nsource_kind: {raw_kind}"
            changed = True
        if not re.search(r"^ingested_at:", fm_block, re.MULTILINE):
            ingested_at = reg.get("ingested_at", "")
            if ingested_at:
                fm_block += f"\ningested_at: \"{ingested_at}\""
                changed = True
        existing_url_m = re.search(r'^source_url:\s*"?([^"\n]*)"?', fm_block, re.MULTILINE)
        has_nonempty_url = existing_url_m and existing_url_m.group(1).strip()
        if not has_nonempty_url:
            source_url = reg.get("source", "")
            if source_url:
                if existing_url_m:
                    fm_block = fm_block[:existing_url_m.start()] + f'source_url: "{source_url}"' + fm_block[existing_url_m.end():]
                else:
                    fm_block += f"\nsource_url: \"{source_url}\""
                changed = True
        if not re.search(r"^title:", fm_block, re.MULTILINE):
            title_guess = reg.get("title_guess", "")
            if title_guess:
                fm_block += f"\ntitle: \"{title_guess}\""
                changed = True

        if changed:
            new_text = f"---\n{fm_block}\n---\n{body}"
            if not dry_run:
                path.write_text(new_text, encoding="utf-8")
            fixed += 1
        else:
            skipped += 1

    label = "would fix" if dry_run else "fixed"
    print(f"migrate-source-fields: {label} {fixed} source note(s), {skipped} already complete")


def run_normalize_frontmatter_cmd(dry_run: bool = False) -> None:
    try:
        from normalize_frontmatter import run_normalize_frontmatter
        run_normalize_frontmatter(dry_run=dry_run)
    except ImportError:
        raise SystemExit("normalize_frontmatter.py not found — install it or copy from agkb/scripts/.")


def run_fetch_queue(fmt: str = "text") -> None:
    queue_path = ROOT / "data" / "fetch_queue.json"
    if not queue_path.exists():
        print("data/fetch_queue.json not found. Run: touch data/fetch_queue.json")
        return
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    blocked = data.get("blocked", [])
    if fmt == "json":
        print(json.dumps(blocked, indent=2, ensure_ascii=False))
        return
    print(f"Fetch queue: {len(blocked)} blocked URL(s)")
    for item in blocked:
        priority = item.get("priority", "?")
        lb = " [LOAD-BEARING]" if item.get("load_bearing") else ""
        print(f"  [{priority}]{lb} {item.get('source_id','?')} — {item.get('failure_mode','?')} — {item.get('workaround','?')}")
        if item.get("notes"):
            print(f"          {item['notes']}")


def run_generate_source_registry(output: str | None = None) -> None:
    registry = json.loads(CONFIG.registry_path.read_text(encoding="utf-8"))
    TITLE_RE = re.compile(r'^title:\s*["\'](.+?)["\']', re.MULTILINE)
    rows = []
    for item in registry:
        sid = item.get("id", "")
        source = item.get("source", "")
        kind = item.get("kind", "")
        notes_path = item.get("notes_path", "")
        title = item.get("title_guess", sid)
        if notes_path:
            npath = ROOT / notes_path
            if npath.exists():
                m = TITLE_RE.search(npath.read_text(encoding="utf-8"))
                if m:
                    title = m.group(1)
        rows.append((sid, kind, title, source, notes_path))
    rows.sort(key=lambda x: x[0])
    lines = [
        '---',
        'title: "Source Registry"',
        'type: index',
        'tags:',
        '  - kb/index',
        '---',
        '# Source Registry',
        '',
        f'Flat lookup: source_id -> title, kind, origin. {len(rows)} sources.',
        '',
        '| source_id | kind | title | origin |',
        '|-----------|------|-------|--------|',
    ]
    for sid, kind, title, source, notes_path in rows:
        short_title = (title[:55] + '...') if len(title) > 55 else title
        short_source = (source[:55] + '...') if len(source) > 55 else source
        short_title = short_title.replace('|', '-')
        short_source = short_source.replace('|', '-')
        if notes_path:
            rel = notes_path.replace('notes/Sources/', '').replace('.md', '')
            sid_link = f'[[Sources/{rel}|{sid}]]'
        else:
            sid_link = sid
        lines.append(f'| {sid_link} | {kind} | {short_title} | {short_source} |')
    content = '\n'.join(lines) + '\n'
    out_path = Path(output).resolve() if output else ROOT / 'notes' / 'Indexes' / 'Source_Registry.md'
    ensure_dir(out_path.parent)
    out_path.write_text(content, encoding='utf-8')
    print(f"Wrote {len(rows)} sources to {out_path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    from kb_commands import main as _main

    _main()


if __name__ == "__main__":
    main()
