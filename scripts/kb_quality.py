from __future__ import annotations

import json
from pathlib import Path

from claim_registry import load_claims, run as run_claim_registry, search_claims
from contradiction_registry import (
    load_contradictions,
    run as run_contradiction_registry,
    search_contradictions,
)
from utils import CONFIG, ROOT, dump_frontmatter, parse_frontmatter
from vault_scorecard import SCORECARD_PATH, print_summary as print_scorecard_summary, run as run_scorecard_registry


def run_lint(*, strict: bool = False, fix_backlinks: bool = False) -> None:
    from lint_vault import lint_vault

    lint_vault(strict=strict, fix_backlinks=fix_backlinks)


def run_validate_config(strict: bool = False) -> None:
    print(f"Project: {CONFIG.project_name}")
    print(f"Config: {ROOT / 'config' / 'kb_config.yaml'}")
    checks = [
        ("raw", CONFIG.raw_dir),
        ("registry", CONFIG.registry_path),
        ("vault", CONFIG.vault_dir),
        ("concepts", CONFIG.concepts_dir),
        ("sources", CONFIG.summaries_dir),
        ("answers", CONFIG.answers_dir),
        ("outputs", CONFIG.outputs_dir),
        ("research", CONFIG.research_dir),
        ("home", CONFIG.home_note),
        ("todo", CONFIG.todo_note),
    ]
    missing: list[str] = []
    for label, path in checks:
        status = "ok" if path.exists() else "missing"
        print(f"- {label}: {path} [{status}]")
        if not path.exists():
            missing.append(label)
    if missing:
        raise SystemExit(1)
    if strict:
        from kb_schema import run_strict_validation
        error_count = run_strict_validation()
        if error_count:
            raise SystemExit(1)


def run_extract_claims() -> None:
    run_claim_registry()


def run_claim_search(query: str, limit: int = 20, fmt: str = "text") -> None:
    claims = load_claims()
    results = search_claims(claims, query, limit=limit)
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


def run_extract_contradictions() -> None:
    run_contradiction_registry()


def run_contradiction_search(query: str, limit: int = 20, fmt: str = "text") -> None:
    contradictions = load_contradictions()
    results = search_contradictions(contradictions, query, limit=limit)
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
    out_path = Path(output).resolve() if output else None
    scorecard = run_scorecard_registry(output=out_path)
    saved_path = out_path or SCORECARD_PATH
    if fmt == "json":
        print(json.dumps(scorecard, indent=2, ensure_ascii=False))
        return
    print_scorecard_summary(scorecard)
    print(f"Scorecard saved: {saved_path.relative_to(ROOT) if saved_path.is_relative_to(ROOT) else saved_path}")


def run_stale_impact(fmt: str = "text") -> None:
    flagged: list[dict] = []
    for page_path in sorted(CONFIG.concepts_dir.glob("*.md")):
        text = page_path.read_text(encoding="utf-8")
        frontmatter, _ = parse_frontmatter(text)
        if not frontmatter.get("revalidation_required"):
            continue
        flagged.append(
            {
                "kind": "concept",
                "path": page_path.relative_to(ROOT).as_posix(),
                "title": str(frontmatter.get("title") or page_path.stem),
                "quality": str(frontmatter.get("claim_quality") or ""),
            }
        )
    for page_path in sorted(CONFIG.answers_dir.glob("*.md")):
        text = page_path.read_text(encoding="utf-8")
        frontmatter, _ = parse_frontmatter(text)
        if frontmatter.get("type") != "answer" or not frontmatter.get("revalidation_required"):
            continue
        flagged.append(
            {
                "kind": "answer",
                "path": page_path.relative_to(ROOT).as_posix(),
                "title": str(frontmatter.get("title") or page_path.stem),
                "quality": str(frontmatter.get("answer_quality") or ""),
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
        print(f"  - [{item['kind']}] {item['path']} (quality: {item['quality']})")


def run_clear_stale_flags(dry_run: bool = False) -> None:
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
