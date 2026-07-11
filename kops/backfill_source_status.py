"""Backfill source_status: active on all source notes that are missing the field."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from kops.utils import CONFIG, parse_frontmatter

SOURCES_DIR = CONFIG.summaries_dir
FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DEFAULT_STATUS = "active"


def backfill_file(path: Path, dry_run: bool = False) -> bool:
    """Add source_status: active if missing. Returns True if the file was (or would be) changed."""
    text = path.read_text(encoding="utf-8")
    fm_match = FRONT_RE.match(text)
    if not fm_match:
        return False

    frontmatter, _ = parse_frontmatter(text)
    if "source_status" in frontmatter:
        return False  # already has the field

    fm_block = fm_match.group(1)
    body = text[fm_match.end() :]

    # Insert source_status after source_id if present, otherwise at end of frontmatter block
    insert_line = f"source_status: {DEFAULT_STATUS}\n"
    m = re.search(r"^source_id:[^\n]*\n", fm_block, re.MULTILINE)
    if m:
        fm_block = fm_block[: m.end()] + insert_line + fm_block[m.end() :]
    else:
        fm_block = fm_block.rstrip("\n") + "\n" + insert_line

    new_text = f"---\n{fm_block}\n---\n{body}"
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def run(dry_run: bool = False) -> None:
    updated = 0
    already_had = 0
    for path in sorted(SOURCES_DIR.rglob("*.md")):
        changed = backfill_file(path, dry_run=dry_run)
        if changed:
            updated += 1
            label = "(dry-run) would update" if dry_run else "updated"
            print(f"  {label}: {path.relative_to(SOURCES_DIR.parent.parent)}")
        else:
            already_had += 1

    label = "would update" if dry_run else "updated"
    print(f"\nDone: {label} {updated} file(s), {already_had} already had source_status.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill source_status: active on source notes missing the field."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing any files.",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
