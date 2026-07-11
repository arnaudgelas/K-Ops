#!/usr/bin/env python3
"""
extract_repo_symbols.py — heuristic symbol extraction for github-repo-snapshot sources.

Usage:
    uv run python scripts/extract_repo_symbols.py [source_id ...]

If no source_ids are given, processes all github_repo_snapshot sources that do not yet
have a symbols.json file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from kops.kb_paths import ROOT  # noqa: E402

RAW_DIR = ROOT / "data" / "raw"

# Heuristic patterns
PY_DEF_RE = re.compile(r"^(class|def)\s+(\w+)", re.MULTILINE)
PY_IMPORT_RE = re.compile(r"^(?:from\s+\S+\s+import\s+.+|import\s+\S+.*)", re.MULTILINE)
JS_EXPORT_RE = re.compile(
    r"^export\s+(class|function|const|interface|type|enum)\s+(\w+)", re.MULTILINE
)
JS_IMPORT_RE = re.compile(
    r"^(?:import\s+.*?from\s+['\"].*?['\"]|const\s+\w+\s*=\s*require\s*\(['\"].*?['\"]\))",
    re.MULTILINE,
)
SECTION_H2_RE = re.compile(r"^##\s+(.+)", re.MULTILINE)
SECTION_H3_RE = re.compile(r"^###\s+(.+)", re.MULTILINE)

# Code fence detectors (used to identify language from fenced blocks)
CODE_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def _guess_language_from_fence(fence_lang: str) -> str | None:
    lang = fence_lang.lower().strip()
    if lang in {"python", "py"}:
        return "python"
    if lang in {"typescript", "ts", "tsx"}:
        return "typescript"
    if lang in {"javascript", "js", "jsx"}:
        return "javascript"
    return None


def _extract_from_text(text: str, source_id: str) -> dict:
    """Extract symbols and imports from raw markdown text."""
    symbols: list[dict] = []
    imports: list[str] = []
    notes: list[str] = []

    # Detect code fences and extract symbols from them
    for fence_match in CODE_FENCE_RE.finditer(text):
        lang = _guess_language_from_fence(fence_match.group(1))
        block = fence_match.group(2)
        fence_start_line = text[: fence_match.start()].count("\n") + 1

        if lang == "python":
            for m in PY_DEF_RE.finditer(block):
                line_in_block = block[: m.start()].count("\n")
                symbols.append(
                    {
                        "kind": m.group(1),  # "class" or "def"
                        "name": m.group(2),
                        "line": fence_start_line + line_in_block + 1,
                    }
                )
            for m in PY_IMPORT_RE.finditer(block):
                imports.append(m.group(0).strip())

        elif lang in {"typescript", "javascript"}:
            for m in JS_EXPORT_RE.finditer(block):
                kind_map = {
                    "class": "class",
                    "function": "function",
                    "const": "const",
                    "interface": "interface",
                    "type": "type",
                    "enum": "enum",
                }
                line_in_block = block[: m.start()].count("\n")
                symbols.append(
                    {
                        "kind": kind_map.get(m.group(1), m.group(1)),
                        "name": m.group(2),
                        "line": fence_start_line + line_in_block + 1,
                    }
                )
            for m in JS_IMPORT_RE.finditer(block):
                imports.append(m.group(0).strip())

    # Also scan raw (non-fenced) text for Python/JS patterns
    # Strip fences to avoid double-counting
    text_no_fences = CODE_FENCE_RE.sub("", text)

    for m in PY_DEF_RE.finditer(text_no_fences):
        # Only include if line is not indented (top-level)
        line_start = text_no_fences.rfind("\n", 0, m.start()) + 1
        line = text_no_fences[line_start : m.end()]
        if not line.startswith((" ", "\t")):
            lineno = text_no_fences[: m.start()].count("\n") + 1
            symbols.append({"kind": m.group(1), "name": m.group(2), "line": lineno})
    for m in PY_IMPORT_RE.finditer(text_no_fences):
        imports.append(m.group(0).strip())

    for m in JS_EXPORT_RE.finditer(text_no_fences):
        lineno = text_no_fences[: m.start()].count("\n") + 1
        kind_map = {
            "class": "class",
            "function": "function",
            "const": "const",
            "interface": "interface",
            "type": "type",
            "enum": "enum",
        }
        symbols.append(
            {"kind": kind_map.get(m.group(1), m.group(1)), "name": m.group(2), "line": lineno}
        )
    for m in JS_IMPORT_RE.finditer(text_no_fences):
        imports.append(m.group(0).strip())

    # Documented sections (## and ###) — always useful for architecture claims
    for m in SECTION_H2_RE.finditer(text):
        name = m.group(1).strip()
        # Skip purely decorative headings
        if name and name not in {
            "Summary",
            "Key Concepts",
            "Architectural Decisions",
            "Repository Signals",
            "Key Files",
            "Key Documents",
            "Related Notes",
            "Source Notes",
        }:
            lineno = text[: m.start()].count("\n") + 1
            symbols.append({"kind": "section", "name": name, "line": lineno})

    for m in SECTION_H3_RE.finditer(text):
        name = m.group(1).strip()
        if name:
            lineno = text[: m.start()].count("\n") + 1
            symbols.append({"kind": "subsection", "name": name, "line": lineno})

    # Deduplicate imports
    imports = sorted(set(i for i in imports if i.strip()))

    if not symbols and not imports:
        notes.append("no recognisable symbols or imports found in this snapshot")
    elif not any(s["kind"] in {"class", "def", "function", "const", "interface"} for s in symbols):
        notes.append("only documentation sections extracted; no code symbol definitions found")

    return {
        "source_id": source_id,
        "extraction_method": "heuristic-regex",
        "extraction_date": date.today().isoformat(),
        "symbols": symbols,
        "imports": imports,
        "extraction_notes": "; ".join(notes) if notes else "ok",
    }


def _collect_text_for_source(src_dir: Path, source_id: str) -> str:
    """Collect all text content for a source directory."""
    # Prefer normalized.md if present; otherwise, collect all part files then original
    normalized = src_dir / "normalized.md"
    if normalized.exists():
        return normalized.read_text(encoding="utf-8", errors="replace")

    # Check for part files (sorted)
    parts = sorted(src_dir.glob(f"{source_id}-part*.md"))
    if parts:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in parts)

    # Fall back to original.md
    original = src_dir / "original.md"
    if original.exists():
        return original.read_text(encoding="utf-8", errors="replace")

    return ""


def process_source(source_id: str, force: bool = False) -> bool:
    """Extract symbols for a single source. Returns True on success."""
    src_dir = RAW_DIR / source_id
    if not src_dir.is_dir():
        print(f"  [SKIP] {source_id}: directory not found", file=sys.stderr)
        return False

    # Check metadata to confirm it's a github_repo_snapshot
    meta_path = src_dir / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            kind = meta.get("kind", "")
            if kind != "github_repo_snapshot":
                print(
                    f"  [SKIP] {source_id}: kind={kind!r} (not github_repo_snapshot)",
                    file=sys.stderr,
                )
                return False
        except json.JSONDecodeError:
            pass

    out_path = src_dir / "symbols.json"
    if out_path.exists() and not force:
        print(f"  [SKIP] {source_id}: symbols.json already exists (use --force to re-extract)")
        return True

    text = _collect_text_for_source(src_dir, source_id)
    if not text:
        print(f"  [WARN] {source_id}: no text content found", file=sys.stderr)
        result = {
            "source_id": source_id,
            "extraction_method": "heuristic-regex",
            "extraction_date": date.today().isoformat(),
            "symbols": [],
            "imports": [],
            "extraction_notes": "no readable content found",
        }
    else:
        result = _extract_from_text(text, source_id)

    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    n_sym = len(result["symbols"])
    n_imp = len(result["imports"])
    print(f"  [OK]   {source_id}: {n_sym} symbols, {n_imp} imports → {out_path.relative_to(ROOT)}")
    return True


def find_all_github_sources() -> list[str]:
    """Return all source IDs with kind=github_repo_snapshot."""
    sources = []
    for src_dir in sorted(RAW_DIR.iterdir()):
        if not src_dir.is_dir() or not src_dir.name.startswith("src-"):
            continue
        meta_path = src_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            continue
        if meta.get("kind") == "github_repo_snapshot":
            sources.append(src_dir.name)
    return sources


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract heuristic symbol metadata from github-repo-snapshot sources."
    )
    parser.add_argument(
        "source_ids",
        nargs="*",
        metavar="SOURCE_ID",
        help="Source IDs to process. If omitted, processes all without symbols.json.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if symbols.json already exists.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_sources",
        help="Process ALL github_repo_snapshot sources (not just those without symbols.json).",
    )
    args = parser.parse_args()

    if args.source_ids:
        targets = args.source_ids
    elif args.all_sources:
        targets = find_all_github_sources()
    else:
        # Default: all github sources without symbols.json
        all_gh = find_all_github_sources()
        targets = [s for s in all_gh if not (RAW_DIR / s / "symbols.json").exists()]

    if not targets:
        print("No sources to process.")
        return

    print(f"Processing {len(targets)} source(s)...")
    ok = 0
    for src_id in targets:
        if process_source(src_id, force=args.force):
            ok += 1

    print(f"\nDone: {ok}/{len(targets)} processed successfully.")


if __name__ == "__main__":
    main()
