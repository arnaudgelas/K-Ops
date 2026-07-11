from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from utils import resolve_content_path

from kb_paths import ROOT  # noqa: E402
REGISTRY_PATH = ROOT / "data" / "registry.json"
SOURCES_DIR = ROOT / "notes" / "Sources"


def load_registry() -> list[dict]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def infer_title(item: dict, normalized_text: str) -> str:
    for line in normalized_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip().strip("`")
    guess = item.get("title_guess", item["id"])
    return re.sub(r"\s+", " ", guess).strip()


def infer_summary(item: dict, normalized_text: str) -> str:
    summary_match = re.search(r"## Summary\s+(.+?)(?:\n## |\Z)", normalized_text, re.DOTALL)
    if summary_match:
        text = " ".join(
            line.strip() for line in summary_match.group(1).splitlines() if line.strip()
        )
        if text:
            return text

    paragraphs: list[str] = []
    current: list[str] = []
    for line in normalized_text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if (
            stripped.startswith("#")
            or stripped.startswith("- ")
            or stripped.startswith("* ")
            or stripped.startswith("|")
        ):
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return (
        paragraphs[0] if paragraphs else f"This source captures `{item.get('source', item['id'])}`."
    )


def infer_kind_label(item: dict) -> str:
    source = str(item.get("source", ""))
    if "arxiv.org" in source:
        return "arXiv paper"
    mapping = {
        "file": "file",
        "url": "url",
        "github_repo_snapshot": "GitHub repository snapshot",
    }
    return str(mapping.get(item.get("kind", ""), item.get("kind", "source")))


def infer_evidence_strength(item: dict, normalized_text: str) -> str:
    existing = item.get("evidence_strength")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()

    # Load metadata.json inside the raw directory for the source to check metadata
    metadata = {}
    metadata_path = ROOT / "data" / "raw" / item["id"] / "metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing_meta = metadata.get("evidence_strength")
    if isinstance(existing_meta, str) and existing_meta.strip():
        return existing_meta.strip()

    kind = item.get("kind") or metadata.get("kind")
    source = item.get("source") or metadata.get("source") or ""
    if "arxiv.org" in source:
        return "primary-doc"
    if kind in ("github_repo_snapshot", "github-repo-snapshot") or "github.com/" in source:
        # Check if coverage is partial
        sampled = item.get("sampled_file_count") or metadata.get("sampled_file_count")
        tracked = item.get("tracked_file_count") or metadata.get("tracked_file_count")
        if sampled is not None and tracked is not None and int(sampled) < int(tracked):
            return "primary-doc-partial"
        return "primary-doc"
    if kind in {"article", "url", "blog"}:
        return "secondary"
    if kind == "file" or kind == "local-file":
        return "primary-doc"
    if not normalized_text.strip():
        return "stub"
    return "secondary"


def related_concepts_for(item: dict) -> list[str]:
    source = item.get("source", "")
    if "agentic-engineering-manifesto" in source or "/Users/arnaud/dev/arwi/manifesto/" in source:
        if item["id"] == "src-36dfd688a7":
            return []
        return ["Concepts/Agentic_Engineering_Manifesto"]
    return []


def build_note(item: dict) -> str:
    normalized_text = Path(resolve_content_path(item)).read_text(encoding="utf-8")
    title = infer_title(item, normalized_text)
    summary = infer_summary(item, normalized_text)
    kind_label = infer_kind_label(item)
    evidence_strength = infer_evidence_strength(item, normalized_text)
    related_concepts = related_concepts_for(item)

    from kb_schema import normalize_source_kind

    source_kind = normalize_source_kind(item.get("kind", ""))

    # Load manifest if it exists to retrieve extraction/preservation details
    manifest_path = ROOT / "data" / "raw" / item["id"] / "large_source_manifest.json"
    extraction_coverage = None
    layout_preserved = False
    tables_preserved = False
    figures_preserved = False

    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            extraction_coverage = manifest.get("text_extraction_coverage")
            tables = manifest.get("tables_detected", [])
            figures = manifest.get("figures_detected", [])
            if tables:
                tables_preserved = True
            if figures:
                figures_preserved = True
        except Exception:
            pass
    elif source_kind in ("paper-pdf", "arxiv-paper") or str(
        item.get("source", "")
    ).lower().endswith(".pdf"):
        extraction_coverage = 100.0

    lines = [
        "---",
        f'title: "{title}"',
        "type: source-summary",
        f"source_id: {item['id']}",
        f'source_url: "{item.get("source", "")}"',
        f"source_kind: {source_kind}",
        f"evidence_strength: {evidence_strength}",
        "source_status: active",
        f"extraction_coverage: {json.dumps(extraction_coverage)}",
        f"layout_preserved: {json.dumps(layout_preserved)}",
        f"tables_preserved: {json.dumps(tables_preserved)}",
        f"figures_preserved: {json.dumps(figures_preserved)}",
        f'ingested_at: "{item.get("ingested_at", "")}"',
        "tags:",
        "  - kb/source",
        "aliases:",
        f'  - "source-{item["id"]}"',
    ]

    # Add kind-specific fields
    if source_kind == "github-repo-snapshot":
        git_commit = item.get("git_commit") or item.get("commit") or "unknown"
        lines.append(f"git_commit: {git_commit}")
        branch = item.get("git_branch") or item.get("branch") or "main"
        lines.append(f"branch: {branch}")
        tracked_file_count = item.get("tracked_file_count", 0)
        lines.append(f"tracked_file_count: {tracked_file_count}")
        sampled_file_count = item.get("sampled_file_count", 0)
        lines.append(f"sampled_file_count: {sampled_file_count}")
    elif source_kind == "paper-pdf":
        lines.append("page_count: 0")
    elif source_kind == "arxiv-paper":
        source_url = item.get("source", "")
        arxiv_m = re.search(r"(?:abs|pdf)/(\\d+\\.\\d+)", source_url)
        arxiv_id = arxiv_m.group(1) if arxiv_m else "unknown"
        lines.append(f"arxiv_id: {arxiv_id}")
        lines.append("authors: unknown")
        pub_date = item.get("published", item.get("date", "unknown"))
        lines.append(f"published_date: {pub_date}")
        lines.append("abstract: unknown")
    elif source_kind == "github-file":
        source_url = item.get("source", "unknown")
        lines.append(f'github_url: "{source_url}"')
        git_commit = item.get("commit", "unknown")
        lines.append(f"git_commit: {git_commit}")
    elif source_kind == "official-doc":
        lines.append("organization: unknown")
    elif source_kind == "spec":
        lines.append("organization: unknown")
        lines.append("version: unknown")
        lines.append("status: unknown")
    elif source_kind == "imported-model-report":
        lines.append("authority: lead_only")
        lines.append("verification_state: needs_primary_sources")
    elif source_kind == "citation-stub":
        canonical_url = item.get("canonical_url") or item.get("source") or "unknown"
        lines.append(f'canonical_url: "{canonical_url}"')
        lines.append("authority: lead_only")
        lines.append("verification_state: needs_fetch")

    lines.append("---")
    lines.extend(
        [
            f"# Source Summary: {item['id']}",
            "",
            f"- Source: `{item['source']}`",
        ]
    )
    if item.get("canonical_repository"):
        lines.append(f"- Canonical Repository: `{item['canonical_repository']}`")
    if item.get("github_home"):
        lines.append(f"- GitHub Home: `{item['github_home']}`")
    lines.extend(
        [
            f"- Title: `{title}`",
            f"- Ingested: `{item['ingested_at']}`",
            f"- Kind: {kind_label}",
            "",
            "## Summary",
            "",
            summary,
            "",
            "## Evidence Notes",
            "",
            "- This note was backfilled from the registry and normalized artifact.",
        ]
    )
    if item["id"] == "src-36dfd688a7":
        lines.append(
            "- This repository snapshot appears to duplicate the same canonical GitHub repo already captured elsewhere in the vault, so it should not be cited as distinct evidence."
        )

    if related_concepts:
        lines.extend(["", "## Related Concepts", ""])
        for concept in related_concepts:
            label = concept.split("/")[-1]
            lines.append(f"- [[{concept}|{label}]]")

    lines.extend(["", "## Backlinks", "", "- [[Home]]"])
    if related_concepts:
        for concept in related_concepts:
            label = concept.split("/")[-1]
            lines.append(f"- [[{concept}|{label}]]")
    lines.append("")
    return "\n".join(lines)


def source_subdir(item: dict) -> Path:
    """Return the appropriate Sources subfolder for a registry item."""
    source = str(item.get("source", ""))
    kind = item.get("kind", "")
    if kind == "github_repo_snapshot" or ("github.com/" in source and kind != "url"):
        return SOURCES_DIR / "github"
    if "arxiv.org" in source:
        return SOURCES_DIR / "arxiv"
    if "medium.com" in source:
        return SOURCES_DIR / "medium"
    if "substack.com" in source:
        return SOURCES_DIR / "substack"
    manifesto_markers = ("agentic-engineering-manifesto", "/Users/arnaud/dev/arwi/manifesto/")
    if any(m in source for m in manifesto_markers):
        return SOURCES_DIR / "agentic-engineering-manifesto"
    return SOURCES_DIR


def backfill_source_notes(
    all_missing: bool = False, ids: list[str] | None = None, dry_run: bool = False
) -> None:
    registry = load_registry()
    existing = {path.stem for path in SOURCES_DIR.rglob("src-*.md")}

    selected: list[dict] = []
    if all_missing:
        selected = [item for item in registry if item["id"] not in existing]
    elif ids:
        wanted = set(ids)
        selected = [item for item in registry if item["id"] in wanted]
    else:
        raise SystemExit("Pass --all-missing or one or more --id values.")

    for item in selected:
        subdir = source_subdir(item)
        subdir.mkdir(parents=True, exist_ok=True)
        note_path = subdir / f"{item['id']}.md"
        if dry_run:
            print(f"Would write {note_path.relative_to(ROOT)}")
        else:
            note_path.write_text(build_note(item), encoding="utf-8")
            print(f"Wrote {note_path.relative_to(ROOT)}")


def sync_source_note_frontmatter(dry_run: bool = False) -> None:
    from utils import parse_frontmatter, dump_frontmatter

    registry = load_registry()
    reg_by_id = {item["id"]: item for item in registry}

    count = 0
    for path in sorted(SOURCES_DIR.rglob("src-*.md")):
        source_id = path.stem
        item = reg_by_id.get(source_id)
        if not item:
            continue

        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)

        # Load manifest
        manifest_path = ROOT / "data" / "raw" / source_id / "large_source_manifest.json"
        extraction_coverage = None
        layout_preserved = False
        tables_preserved = False
        figures_preserved = False

        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                extraction_coverage = manifest.get("text_extraction_coverage")
                tables = manifest.get("tables_detected", [])
                figures = manifest.get("figures_detected", [])
                if tables:
                    tables_preserved = True
                if figures:
                    figures_preserved = True
            except Exception:
                pass
        elif frontmatter.get("source_kind") in ("paper-pdf", "arxiv-paper") or str(
            frontmatter.get("source_url", "")
        ).lower().endswith(".pdf"):
            extraction_coverage = 100.0

        # Check if this is a partial GitHub repo snapshot and update its strength to primary-doc-partial
        metadata_path = ROOT / "data" / "raw" / source_id / "metadata.json"
        if metadata_path.exists():
            try:
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                sampled = meta.get("sampled_file_count")
                tracked = meta.get("tracked_file_count")
                if sampled is not None and tracked is not None and int(sampled) < int(tracked):
                    if frontmatter.get("evidence_strength") == "primary-doc":
                        frontmatter["evidence_strength"] = "primary-doc-partial"
            except Exception:
                pass

        # Check if fields are already present and equal
        changed = False
        for field, val in [
            ("extraction_coverage", extraction_coverage),
            ("layout_preserved", layout_preserved),
            ("tables_preserved", tables_preserved),
            ("figures_preserved", figures_preserved),
        ]:
            if frontmatter.get(field) != val:
                frontmatter[field] = val
                changed = True

        # Ensure source_status
        if "source_status" not in frontmatter:
            frontmatter["source_status"] = "active"
            changed = True

        # Ensure tags
        tags = frontmatter.get("tags")
        if not tags:
            frontmatter["tags"] = ["kb/source"]
            changed = True
        elif isinstance(tags, list):
            if "kb/source" not in tags:
                frontmatter["tags"] = tags + ["kb/source"]
                changed = True
        else:
            frontmatter["tags"] = [tags] if "kb/source" == tags else [tags, "kb/source"]
            changed = True

        # Ensure kind-specific fields for imported-model-report & citation-stub
        source_kind = frontmatter.get("source_kind")
        if source_kind == "imported-model-report":
            if frontmatter.get("authority") != "lead_only":
                frontmatter["authority"] = "lead_only"
                changed = True
            if frontmatter.get("verification_state") != "needs_primary_sources":
                frontmatter["verification_state"] = "needs_primary_sources"
                changed = True
        elif source_kind == "citation-stub":
            if not frontmatter.get("canonical_url"):
                frontmatter["canonical_url"] = frontmatter.get("source_url") or "unknown"
                changed = True
            if frontmatter.get("authority") != "lead_only":
                frontmatter["authority"] = "lead_only"
                changed = True
            if frontmatter.get("verification_state") != "needs_fetch":
                frontmatter["verification_state"] = "needs_fetch"
                changed = True

        if changed:
            count += 1
            if not dry_run:
                new_text = dump_frontmatter(frontmatter) + body
                path.write_text(new_text, encoding="utf-8")

    mode = "Would update" if dry_run else "Updated"
    print(f"{mode} frontmatter of {count} source note(s)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill missing source-summary notes from registry artifacts."
    )
    parser.add_argument("--all-missing", action="store_true")
    parser.add_argument("--id", dest="ids", action="append")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print planned changes without writing notes."
    )
    args = parser.parse_args()
    if args.all_missing or args.ids:
        backfill_source_notes(all_missing=args.all_missing, ids=args.ids, dry_run=args.dry_run)
    sync_source_note_frontmatter(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
