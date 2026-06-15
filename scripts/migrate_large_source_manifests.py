"""Migrate large_source_manifest.json files from v1 (flat segments) to v2 (nodes array).

Usage:
    uv run python scripts/migrate_large_source_manifests.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve repo root relative to this script's location
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
RAW_DIR = ROOT / "data" / "raw"
FINDINGS_DIR = ROOT / "research" / "findings"
MIGRATIONS_DIR = ROOT / "data" / "migrations"


def to_anchor(title: str) -> str:
    """Convert a title string to a kebab-case anchor suitable for Markdown headings."""
    s = title.lower().strip()
    # Remove "type: " prefix if present (e.g. "heading: Introduction" → "introduction")
    s = re.sub(r"^[a-z_]+: ", "", s)
    s = re.sub(r"[^a-z0-9 \-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    if not s or not s[0].isalnum():
        s = "section-" + s
    return s[:60]


def infer_level(seg_type: str) -> int:
    """Map a v1 segment type to a node level (0=document, 1=top-level, 2=nested)."""
    top_level = {
        "page",
        "file",
        "speaker",
        "paragraph",
        "heading",
        "method",
        "results",
        "abstract",
        "limitations",
        "references",
        "segment",
    }
    nested = {"class", "function", "table", "figure", "caption"}
    if seg_type in top_level:
        return 1
    if seg_type in nested:
        return 2
    return 1


def build_node(segment: dict, order: int) -> dict:
    """Convert a v1 segment dict into a v2 node dict."""
    seg_type = segment.get("type", "segment")
    title = segment.get("title", "")
    anchor = to_anchor(title) or f"node-{order}"

    return {
        "node_id": segment["id"],
        "parent_id": None,
        "order": order,
        "level": infer_level(seg_type),
        "type": seg_type,
        "title": title,
        "anchor": anchor,
        "start_char": segment.get("start_char", 0),
        "end_char": segment.get("end_char", 0),
        "page_start": None,
        "page_end": None,
        "content_hash": segment.get("content_hash", ""),
        "extraction_method": "backfill-v1",
        "confidence": "low",
        "warnings": ["backfilled-from-v1-segments-no-hierarchy"],
        "source_note_heading": None,
    }


def migrate_manifest(path: Path, dry_run: bool = False) -> str:
    """Migrate a single manifest. Returns 'migrated', 'skipped', or 'failed:<reason>'."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"failed:invalid-json:{exc}"

    if manifest.get("large_source_manifest_version") == 2:
        return "skipped"

    segments = manifest.get("segments")
    if segments is None:
        # No segments — write v2 with empty nodes
        segments = []

    if not isinstance(segments, list):
        return "failed:segments-not-a-list"

    try:
        nodes = [build_node(seg, idx) for idx, seg in enumerate(segments)]
    except Exception as exc:
        return f"failed:node-build-error:{exc}"

    manifest["large_source_manifest_version"] = 2
    manifest["nodes"] = nodes

    if not dry_run:
        # Atomic write via temp file then rename
        tmp_path = path.with_suffix(".json.tmp")
        try:
            tmp_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            tmp_path.replace(path)
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            return f"failed:write-error:{exc}"

    return "migrated"


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate large_source_manifest.json v1 → v2")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing changes")
    args = parser.parse_args()

    manifests = sorted(RAW_DIR.glob("*/large_source_manifest.json"))
    print(f"Found {len(manifests)} manifest file(s) under {RAW_DIR}")

    migrated: list[Path] = []
    skipped: list[Path] = []
    failures: list[tuple[Path, str]] = []

    for mf in manifests:
        result = migrate_manifest(mf, dry_run=args.dry_run)
        if result == "migrated":
            migrated.append(mf)
        elif result == "skipped":
            skipped.append(mf)
        else:
            failures.append((mf, result))
            print(f"  FAILED {mf.parent.name}: {result}", file=sys.stderr)

    action = "Would migrate" if args.dry_run else "Migrated"
    print(
        f"{action}: {len(migrated)}, already v2 (skipped): {len(skipped)}, failures: {len(failures)}"
    )

    # Write findings gap report
    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    gaps_path = FINDINGS_DIR / "large_source_manifest_gaps.md"
    if failures:
        lines = [
            "# Large Source Manifest v2 Migration Gaps",
            "",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"Dry-run: {args.dry_run}",
            "",
            f"## Failures ({len(failures)})",
            "",
        ]
        for fp, reason in failures:
            lines.append(f"- `{fp}`: {reason}")
        gaps_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Gap report written: {gaps_path}")
    else:
        # Clear any previous gap report
        if gaps_path.exists():
            gaps_path.write_text(
                f"# Large Source Manifest v2 Migration Gaps\n\nNo failures as of {datetime.now(timezone.utc).isoformat()}.\n",
                encoding="utf-8",
            )
        print("No failures — gap report cleared.")

    # Write migration record (only on real run)
    if not args.dry_run:
        MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "task": "A6",
            "date": "2026-06-15",
            "run_at": datetime.now(timezone.utc).isoformat(),
            "description": "Added large_source_manifest_version: 2 and nodes array to all large_source_manifest.json files",
            "files_migrated": len(migrated),
            "files_skipped": len(skipped),
            "files_failed": len(failures),
            "failures": [{"path": str(fp), "reason": r} for fp, r in failures],
            "pre_state": "v1 manifests with flat segments list, no parent/level/confidence fields",
            "post_state": "v2 manifests with both segments (unchanged) and nodes (backfilled from segments with confidence: low)",
            "validation_added": "kb_schema.py::Validator.validate_large_source_manifest()",
            "inverse": "Remove large_source_manifest_version and nodes keys from all large_source_manifest.json files",
        }
        record_path = MIGRATIONS_DIR / "A6_20260615.json"
        record_path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Migration record written: {record_path}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
