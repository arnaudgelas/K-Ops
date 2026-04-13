from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from utils import CONFIG, ROOT, ensure_dir, now_stamp


DEFAULT_EXCLUDES = {
    ".obsidian/workspace.json",
    ".obsidian/workspace-mobile.json",
}


def copy_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        rel_text = rel.as_posix()
        if rel_text in DEFAULT_EXCLUDES:
            continue
        target = dst / rel
        if path.is_dir():
            ensure_dir(target)
            continue
        ensure_dir(target.parent)
        shutil.copy2(path, target)


def build_export_staging(staging_root: Path) -> Path:
    vault_root = staging_root / ROOT.name
    ensure_dir(vault_root)
    copy_tree(ROOT / ".obsidian", vault_root / ".obsidian")
    copy_tree(CONFIG.vault_dir, vault_root / CONFIG.vault_dir.name)
    return vault_root


def export_vault(output_path: Path) -> Path:
    ensure_dir(output_path.parent)
    with tempfile.TemporaryDirectory(prefix="obsidian-vault-export-") as tmp_dir:
        staging_root = Path(tmp_dir)
        vault_root = build_export_staging(staging_root)
        archive_base = output_path.with_suffix("")
        created = shutil.make_archive(
            base_name=str(archive_base),
            format="zip",
            root_dir=staging_root,
            base_dir=vault_root.name,
        )
    return Path(created)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the Obsidian vault contents as a zip archive.")
    parser.add_argument(
        "--output",
        help="Output zip path. Defaults to outputs/<repo>-obsidian-vault-<timestamp>.zip",
    )
    args = parser.parse_args()

    output = (
        Path(args.output).resolve()
        if args.output
        else (CONFIG.outputs_dir / f"{ROOT.name}-obsidian-vault-{now_stamp()}.zip").resolve()
    )
    created = export_vault(output)
    print(created)


if __name__ == "__main__":
    main()
