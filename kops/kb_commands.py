from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from kops.backfill_answer_quality import backfill_answer_quality
from kops.backfill_concept_quality import backfill_concept_quality
from kops.backfill_source_metadata import backfill_source_metadata
from kops.backfill_source_notes import backfill_source_notes
from kops.bootstrap_kb import bootstrap
from kops.export_obsidian_vault import export_vault
from kops.export_vault_index import export_vault_index
from kops.ingest_github_repo import ingest_repo, upsert_registry_entry
from kops.normalize_frontmatter import run_normalize_frontmatter
from kops.normalize_github_sources import normalize_github_sources
from kops.render_manifest import build_manifest
from kops.utils import CONFIG, ROOT, ensure_dir, now_stamp, resolve_content_path
from kops.vault_graph import (
    RETENTION_REPORT_PATH,
    load_graph,
    search_graph,
    traverse_graph,
    write_retention_report,
)
from kops.kb_quality import (
    run_claim_search as run_claim_search,
    run_clear_stale_flags as run_clear_stale_flags,
    run_contradiction_search as run_contradiction_search,
    run_extract_claims as run_extract_claims,
    run_extract_contradictions as run_extract_contradictions,
    run_lint as run_lint,
    run_scorecard as run_scorecard,
    run_stale_impact as run_stale_impact,
    run_validate_config as run_validate_config,
)


def run_fetch(input_path: str, branch: str | None = None, fail_fast: bool = False) -> None:
    from kops.ingest_sources import ingest_sources

    ingest_sources(input_path, fail_fast=fail_fast, branch=branch, refresh=False)


def run_add_source(source: str, branch: str | None = None, fail_fast: bool = False) -> None:
    from kops.ingest_sources import ingest_sources

    add_list = ROOT / ".tmp" / f"add-source-{now_stamp()}.txt"
    ensure_dir(add_list.parent)
    add_list.write_text(source.strip() + "\n", encoding="utf-8")
    ingest_sources(str(add_list), fail_fast=fail_fast, branch=branch, refresh=False)


def run_refresh_sources(branch: str | None = None, fail_fast: bool = False) -> Path:
    from kops.ingest_sources import ingest_sources

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
    ingest_sources(str(refresh_list), fail_fast=fail_fast, branch=branch, refresh=True)
    return refresh_list


def run_ingest_github(repo: str, branch: str | None = None) -> None:
    metadata = ingest_repo(repo, branch)
    upsert_registry_entry(metadata)
    print(f"Ingested {repo} -> {metadata['id']}")
    print(resolve_content_path(metadata))


def run_export_vault(output: str | None = None) -> None:
    created = export_vault(
        Path(output).resolve()
        if output
        else (CONFIG.outputs_dir / f"{ROOT.name}-obsidian-vault-{now_stamp()}.zip").resolve()
    )
    print(created)


def run_migrate_source_fields(dry_run: bool = False) -> None:
    """Batch-derive source_kind and ingested_at for source notes missing them, using data/registry.json."""
    from kops.kb_schema import normalize_source_kind
    import re

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
        body = text[fm_match.end() :]

        # Extract source_id from frontmatter
        sid_m = re.search(r"^source_id:\s*(\S+)", fm_block, re.MULTILINE)
        if not sid_m:
            continue
        sid = sid_m.group(1).strip("\"'")
        reg = reg_by_id.get(sid)
        if not reg:
            continue

        changed = False
        # source_kind
        if not re.search(r"^source_kind:", fm_block, re.MULTILINE):
            raw_kind = reg.get("kind", "")
            norm_kind = normalize_source_kind(raw_kind)
            fm_block += f"\nsource_kind: {norm_kind}"
            changed = True
        # ingested_at
        if not re.search(r"^ingested_at:", fm_block, re.MULTILINE):
            ingested_at = reg.get("ingested_at", "")
            if ingested_at:
                fm_block += f'\ningested_at: "{ingested_at}"'
                changed = True
        # source_url (use registry source even for non-HTTP paths; also fill empty values)
        existing_url_m = re.search(r'^source_url:\s*"?([^"\n]*)"?', fm_block, re.MULTILINE)
        has_nonempty_url = existing_url_m and existing_url_m.group(1).strip()
        if not has_nonempty_url:
            source_url = reg.get("source", "")
            if source_url:
                if existing_url_m:
                    fm_block = (
                        fm_block[: existing_url_m.start()]
                        + f'source_url: "{source_url}"'
                        + fm_block[existing_url_m.end() :]
                    )
                else:
                    fm_block += f'\nsource_url: "{source_url}"'
                changed = True
        # title (derive from title_guess if missing)
        if not re.search(r"^title:", fm_block, re.MULTILINE):
            title_guess = reg.get("title_guess", "")
            if title_guess:
                fm_block += f'\ntitle: "{title_guess}"'
                changed = True

        # Extract current source_kind and keys
        fm_lines = fm_block.splitlines()
        fm_keys = set()
        for line in fm_lines:
            m = re.match(r"^([a-zA-Z0-9_-]+):", line)
            if m:
                fm_keys.add(m.group(1))

        sk_match = re.search(r"^source_kind:\s*(\S+)", fm_block, re.MULTILINE)
        source_kind = sk_match.group(1).strip("\"'") if sk_match else "local-file"

        # Add kind-specific required fields if missing
        if source_kind == "github-repo-snapshot":
            if "git_commit" not in fm_keys:
                git_commit = reg.get("git_commit") or reg.get("commit") or "unknown"
                fm_block += f"\ngit_commit: {git_commit}"
                changed = True
            if "branch" not in fm_keys:
                branch = reg.get("git_branch") or reg.get("branch") or "main"
                fm_block += f"\nbranch: {branch}"
                changed = True
            if "tracked_file_count" not in fm_keys:
                tracked_file_count = reg.get("tracked_file_count", 0)
                fm_block += f"\ntracked_file_count: {tracked_file_count}"
                changed = True
            if "sampled_file_count" not in fm_keys:
                sampled_file_count = reg.get("sampled_file_count", 0)
                fm_block += f"\nsampled_file_count: {sampled_file_count}"
                changed = True
        elif source_kind == "paper-pdf":
            if "page_count" not in fm_keys:
                fm_block += "\npage_count: 0"
                changed = True
        elif source_kind == "arxiv-paper":
            if "arxiv_id" not in fm_keys:
                source_url = reg.get("source", "")
                arxiv_m = re.search(r"(?:abs|pdf)/(\\d+\\.\\d+)", source_url)
                arxiv_id = arxiv_m.group(1) if arxiv_m else "unknown"
                fm_block += f"\narxiv_id: {arxiv_id}"
                changed = True
            if "authors" not in fm_keys:
                fm_block += "\nauthors: unknown"
                changed = True
            if "published_date" not in fm_keys:
                pub_date = reg.get("published", reg.get("date", "unknown"))
                fm_block += f"\npublished_date: {pub_date}"
                changed = True
            if "abstract" not in fm_keys:
                fm_block += "\nabstract: unknown"
                changed = True
        elif source_kind == "github-file":
            if "github_url" not in fm_keys:
                source_url = reg.get("source", "unknown")
                fm_block += f'\ngithub_url: "{source_url}"'
                changed = True
            if "git_commit" not in fm_keys:
                git_commit = reg.get("commit", "unknown")
                fm_block += f"\ngit_commit: {git_commit}"
                changed = True
        elif source_kind == "official-doc":
            if "organization" not in fm_keys:
                fm_block += "\norganization: unknown"
                changed = True
        elif source_kind == "spec":
            if "organization" not in fm_keys:
                fm_block += "\norganization: unknown"
                changed = True
            if "version" not in fm_keys:
                fm_block += "\nversion: unknown"
                changed = True
            if "status" not in fm_keys:
                fm_block += "\nstatus: unknown"
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
    run_normalize_frontmatter(dry_run=dry_run)


def run_normalize_github_sources(dry_run: bool = False) -> None:
    normalize_github_sources(dry_run=dry_run)


def run_bootstrap(
    target: str, project_name: str | None = None, with_examples: bool = False, force: bool = False
) -> None:
    bootstrap(
        Path(target).expanduser().resolve(),
        project_name=project_name,
        with_examples=with_examples,
        force=force,
    )


def run_backfill_source_notes(dry_run: bool = False) -> None:
    backfill_source_notes(all_missing=True, dry_run=dry_run)
    from kops.backfill_source_notes import sync_source_note_frontmatter

    sync_source_note_frontmatter(dry_run=dry_run)


def run_backfill_source_metadata(dry_run: bool = False) -> None:
    backfill_source_metadata(all_items=True, dry_run=dry_run)


def run_backfill_concept_quality(dry_run: bool = False) -> None:
    backfill_concept_quality(all_pages=True, dry_run=dry_run)


def run_backfill_answer_quality(dry_run: bool = False) -> None:
    backfill_answer_quality(all_pages=True, dry_run=dry_run)


def run_export_index(output: str | None = None, fmt: str = "json") -> None:
    export_vault_index(output=output, fmt=fmt)


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
        print(
            f"  [{priority}]{lb} {item.get('source_id', '?')} — {item.get('failure_mode', '?')} — {item.get('workaround', '?')}"
        )
        if item.get("notes"):
            print(f"          {item['notes']}")


def run_generate_source_registry(output: str | None = None) -> None:
    import re

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
        "---",
        'title: "Source Registry"',
        "type: index",
        "tags:",
        "  - kb/index",
        "---",
        "# Source Registry",
        "",
        f"Flat lookup: source_id -> title, kind, origin. {len(rows)} sources.",
        "",
        "| source_id | kind | title | origin |",
        "|-----------|------|-------|--------|",
    ]
    for sid, kind, title, source, notes_path in rows:
        short_title = (title[:55] + "...") if len(title) > 55 else title
        short_source = (source[:55] + "...") if len(source) > 55 else source
        short_title = short_title.replace("|", "-")
        short_source = short_source.replace("|", "-")
        if notes_path:
            rel = notes_path.replace("notes/Sources/", "").replace(".md", "")
            sid_link = f"[[Sources/{rel}|{sid}]]"
        else:
            sid_link = sid
        lines.append(f"| {sid_link} | {kind} | {short_title} | {short_source} |")
    content = "\n".join(lines) + "\n"
    out_path = (
        Path(output).resolve() if output else ROOT / "notes" / "Indexes" / "Source_Registry.md"
    )
    ensure_dir(out_path.parent)
    out_path.write_text(content, encoding="utf-8")
    print(f"Wrote {len(rows)} sources to {out_path.relative_to(ROOT)}")


def run_render_manifest(output: str | None = None) -> None:
    manifest = build_manifest()
    rendered = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if output:
        output_path = Path(output).resolve()
        ensure_dir(output_path.parent)
        output_path.write_text(rendered, encoding="utf-8")
        print(output_path)
    else:
        print(rendered, end="")


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
    from kops.kb_suggest_links import run_suggest_links as _suggest

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


def run_build_graph(
    output: str | None = None,
    report_output: str | None = None,
    csv_output: str | None = None,
    *,
    check: bool = False,
    dry_run: bool = False,
) -> None:
    from kops.vault_graph import run as run_vault_graph

    run_vault_graph(
        output=output,
        report_output=report_output,
        csv_output=csv_output,
        check=check,
        dry_run=dry_run,
    )


def run_graph_audit(fmt: str = "text") -> None:
    from kops.vault_graph import graph_audit, load_graph

    report = graph_audit(load_graph())
    findings = report["antipatterns"]
    stats = report["stats"]

    if fmt == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    print(f"Graph audit  ({stats['total_nodes']} nodes, {stats['total_edges']} edges)")
    print(f"Concept degree: mean={stats['concept_degree_mean']}  max={stats['concept_degree_max']}")
    print()
    if not findings:
        print("No antipatterns detected.")
        return
    for f in findings:
        severity = f["severity"].upper()
        print(f"[{severity}] {f['code']}")
        print(f"  {f['message']}")
        for ex in f.get("examples", []):
            parts = [ex.get("title") or ex.get("id", "")]
            if "degree" in ex:
                parts.append(f"deg={ex['degree']}")
            if "source" in ex:
                parts.append(f"src={ex['source']}")
            print(f"    • {' | '.join(str(p) for p in parts)}")
        print()


def run_search_graph(query: str, limit: int = 10, scope: str = "all", fmt: str = "json") -> None:
    results = search_graph(load_graph(), query, limit=limit, scope=scope)
    if fmt == "json":
        print(
            json.dumps(
                {"query": query, "scope": scope, "results": results}, indent=2, ensure_ascii=False
            )
        )
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
                {
                    "start": start,
                    "depth": depth,
                    "scope": scope,
                    "relations": relations or [],
                    "results": results,
                },
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
        f"Retention report {'updated' if changed else 'unchanged'}: {report_path.relative_to(ROOT) if report_path.is_relative_to(ROOT) else report_path}"
    )


def run_install_agent_assets(
    agent: str = "all", scope: str = "both", dry_run: bool = False, force: bool = False
) -> None:
    cmd = [
        sys.executable,
        "-m",
        "kops.install_agent_assets",
        "--agent",
        agent,
        "--scope",
        scope,
    ]
    if dry_run:
        cmd.append("--dry-run")
    if force:
        cmd.append("--force")
    subprocess.run(cmd, check=True, cwd=ROOT)


def cmd_claim_map(concept: str, output: str = "stdout") -> None:
    """Generate a Mermaid argument-map diagram for a concept from claims.json."""
    import re
    import textwrap

    claims_path = ROOT / "data" / "claims.json"
    if not claims_path.exists():
        print(f"claims.json not found at {claims_path}")
        return

    payload = json.loads(claims_path.read_text(encoding="utf-8"))
    all_claims = payload.get("claims", [])
    concept_claims = [c for c in all_claims if c.get("concept") == concept]

    if not concept_claims:
        print(
            f"No claims found for concept '{concept}'. Check the stem matches claims.json 'concept' field."
        )
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


def run_generate_probes() -> None:
    """Generate diagnostic probes using generate_diagnostic_questions.py."""
    import subprocess

    cmd = [sys.executable, "-m", "kops.generate_diagnostic_questions"]
    subprocess.run(cmd, check=True)


def run_evaluate(
    limit: int | None = None,
    probe_id: str | None = None,
    workers: int = 5,
    verbose: bool = False,
) -> None:
    """Evaluate compilation and run the feedback loop."""
    import subprocess

    cmd = [sys.executable, "-m", "kops.evaluate_compilation"]
    if limit is not None:
        cmd.extend(["--limit", str(limit)])
    if probe_id is not None:
        cmd.extend(["--probe-id", probe_id])
    cmd.extend(["--workers", str(workers)])
    if verbose:
        cmd.append("--verbose")

    subprocess.run(cmd, check=True)

    print("\nRunning feedback loop...")
    feedback_cmd = [sys.executable, "-m", "kops.feedback_loop"]
    subprocess.run(feedback_cmd, check=True)


def run_compile_large_source(
    source_id: str,
    dry_run: bool = False,
    resume: bool = False,
    force: bool = False,
) -> None:
    """
    Route large sources (>50 pages with a v2 manifest) through the bottom-up
    summarization orchestrator in compile_large_source.py.

    Falls back to the standard compile path if the manifest is absent or the
    source is small.
    """
    manifest_path = ROOT / "data" / "raw" / source_id / "large_source_manifest.json"
    if not manifest_path.exists():
        print(
            f"No large_source_manifest.json for {source_id}; "
            "use 'compile' subcommand for standard sources."
        )
        return

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: could not load manifest for {source_id}: {e}")
        return

    if manifest.get("large_source_manifest_version") != 2:
        print(
            f"Manifest version is not 2 for {source_id}; "
            "run migrate_large_source_manifests.py first."
        )
        return

    node_count = len(manifest.get("nodes", []))
    if node_count <= 50:
        print(
            f"Source {source_id} has only {node_count} nodes; "
            "use standard 'compile' subcommand instead."
        )
        return

    cmd = [sys.executable, "-m", "kops.compile_large_source", source_id]
    if dry_run:
        cmd.append("--dry-run")
    if resume:
        cmd.append("--resume")
    if force:
        cmd.append("--force")
    subprocess.run(cmd, check=True, cwd=ROOT)
