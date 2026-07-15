from __future__ import annotations

import argparse
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from kops import source_override
from kops.utils import CONFIG, ROOT, ensure_dir, now_stamp, parse_frontmatter


DEFAULT_EXCLUDES = {
    ".obsidian/workspace.json",
    ".obsidian/workspace-mobile.json",
}


def _flagged_source_note_skipper(
    include_flagged: bool,
) -> Callable[[Path], bool]:
    """Return a predicate that skips flagged/revoked/adversarial source notes.

    A flagged source's summary note must not ship in an export by default. Only
    ``notes/Sources/src-*.md`` notes carry ``source_status`` frontmatter, so only
    those are inspected; everything else copies unchanged.
    """
    overrides = source_override.load_overrides()

    def _skip(path: Path) -> bool:
        if include_flagged:
            return False
        if path.suffix != ".md" or not path.name.startswith("src-"):
            return False
        try:
            frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            return False
        excluded, _ = source_override.should_exclude(
            frontmatter, command="export", overrides=overrides
        )
        return excluded

    return _skip


def copy_tree(src: Path, dst: Path, skip: Callable[[Path], bool] | None = None) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        rel_text = rel.as_posix()
        if rel_text in DEFAULT_EXCLUDES:
            continue
        if skip is not None and path.is_file() and skip(path):
            continue
        target = dst / rel
        if path.is_dir():
            ensure_dir(target)
            continue
        ensure_dir(target.parent)
        shutil.copy2(path, target)


def build_export_staging(staging_root: Path, include_flagged: bool = False) -> Path:
    vault_root = staging_root / ROOT.name
    ensure_dir(vault_root)
    copy_tree(ROOT / ".obsidian", vault_root / ".obsidian")
    copy_tree(
        CONFIG.vault_dir,
        vault_root / CONFIG.vault_dir.name,
        skip=_flagged_source_note_skipper(include_flagged),
    )
    return vault_root


def export_vault(output_path: Path, include_flagged: bool = False) -> Path:
    ensure_dir(output_path.parent)
    with tempfile.TemporaryDirectory(prefix="obsidian-vault-export-") as tmp_dir:
        staging_root = Path(tmp_dir)
        vault_root = build_export_staging(staging_root, include_flagged=include_flagged)
        archive_base = output_path.with_suffix("")
        created = shutil.make_archive(
            base_name=str(archive_base),
            format="zip",
            root_dir=staging_root,
            base_dir=vault_root.name,
        )
    return Path(created)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the Obsidian vault contents as a zip archive."
    )
    parser.add_argument(
        "--output",
        help="Output zip path. Defaults to outputs/<repo>-obsidian-vault-<timestamp>.zip",
    )
    parser.add_argument(
        "--include-flagged",
        action="store_true",
        help="Admin: include flagged/revoked/adversarial source notes (default: excluded).",
    )
    args = parser.parse_args()

    output = (
        Path(args.output).resolve()
        if args.output
        else (CONFIG.outputs_dir / f"{ROOT.name}-obsidian-vault-{now_stamp()}.zip").resolve()
    )
    created = export_vault(output, include_flagged=args.include_flagged)
    print(created)


if __name__ == "__main__":
    main()
