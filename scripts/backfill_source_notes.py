from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
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
        text = " ".join(line.strip() for line in summary_match.group(1).splitlines() if line.strip())
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
        if stripped.startswith("#") or stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("|"):
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs[0] if paragraphs else f"This source captures `{item.get('source', item['id'])}`."


def infer_kind_label(item: dict) -> str:
    source = str(item.get("source", ""))
    if "arxiv.org" in source:
        return "arXiv paper"
    mapping = {
        "file": "file",
        "url": "url",
        "github_repo_snapshot": "GitHub repository snapshot",
    }
    return mapping.get(item.get("kind", ""), item.get("kind", "source"))


def infer_evidence_strength(item: dict, normalized_text: str) -> str:
    existing = item.get("evidence_strength")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()

    kind = item.get("kind")
    source = item.get("source", "")
    if "arxiv.org" in source:
        return "primary-doc"
    if kind == "github_repo_snapshot" or "github.com/" in source:
        return "primary-doc"
    if kind in {"article", "url"}:
        return "secondary"
    if kind == "file":
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
    normalized_path = ROOT / item["normalized_path"]
    normalized_text = normalized_path.read_text(encoding="utf-8")
    title = infer_title(item, normalized_text)
    summary = infer_summary(item, normalized_text)
    kind_label = infer_kind_label(item)
    evidence_strength = infer_evidence_strength(item, normalized_text)
    related_concepts = related_concepts_for(item)

    lines = [
        "---",
        f'title: "{title}"',
        "type: source-summary",
        f"source_id: {item['id']}",
        f"evidence_strength: {evidence_strength}",
        "tags:",
        "  - kb/source",
        "aliases:",
        f'  - "source-{item["id"]}"',
        "---",
        f"# Source Summary: {item['id']}",
        "",
        f"- Source: `{item['source']}`",
    ]
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
        lines.append("- This repository snapshot appears to duplicate the same canonical GitHub repo already captured elsewhere in the vault, so it should not be cited as distinct evidence.")

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


def run(all_missing: bool = True, ids: list[str] | None = None, dry_run: bool = False) -> None:
    registry = load_registry()
    existing = {path.stem for path in SOURCES_DIR.glob("src-*.md")}

    selected: list[dict] = []
    if all_missing:
        selected = [item for item in registry if item["id"] not in existing]
    elif ids:
        wanted = set(ids)
        selected = [item for item in registry if item["id"] in wanted]

    for item in selected:
        note_path = SOURCES_DIR / f'{item["id"]}.md'
        if dry_run:
            print(f"Would write {note_path.relative_to(ROOT)}")
        else:
            note_path.write_text(build_note(item), encoding="utf-8")
            print(f"Wrote {note_path.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing source-summary notes from registry artifacts.")
    parser.add_argument("--all-missing", action="store_true")
    parser.add_argument("--id", dest="ids", action="append")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing notes.")
    args = parser.parse_args()

    registry = load_registry()
    existing = {path.stem for path in SOURCES_DIR.glob("src-*.md")}

    selected: list[dict] = []
    if args.all_missing:
        selected = [item for item in registry if item["id"] not in existing]
    elif args.ids:
        wanted = set(args.ids)
        selected = [item for item in registry if item["id"] in wanted]
    else:
        raise SystemExit("Pass --all-missing or one or more --id values.")

    for item in selected:
        note_path = SOURCES_DIR / f'{item["id"]}.md'
        if args.dry_run:
            print(f"Would write {note_path.relative_to(ROOT)}")
        else:
            note_path.write_text(build_note(item), encoding="utf-8")
            print(f"Wrote {note_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
