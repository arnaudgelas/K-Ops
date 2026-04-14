from __future__ import annotations

import argparse
from pathlib import Path

from ingest_github_repo import github_clone_url, github_home_url, parse_github_repo
from utils import CONFIG, ROOT, load_json, save_json


def normalize_source_note(note_path: Path, canonical_repo: str, github_home: str) -> bool:
    text = note_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    changed = False

    canonical_line = f"- Canonical Repository: `{canonical_repo}`\n"
    home_line = f"- GitHub Home: `{github_home}`\n"

    source_index = next((i for i, line in enumerate(lines) if line.startswith("- Source: `")), None)
    canonical_index = next((i for i, line in enumerate(lines) if line.startswith("- Canonical Repository: `")), None)
    home_index = next((i for i, line in enumerate(lines) if line.startswith("- GitHub Home: `")), None)

    if source_index is None:
        return False

    if canonical_index is None:
        lines.insert(source_index + 1, canonical_line)
        changed = True
        canonical_index = source_index + 1
    elif lines[canonical_index] != canonical_line:
        lines[canonical_index] = canonical_line
        changed = True

    if home_index is None:
        lines.insert(canonical_index + 1, home_line)
        changed = True
    elif lines[home_index] != home_line:
        lines[home_index] = home_line
        changed = True

    if changed:
        note_path.write_text("".join(lines), encoding="utf-8")

    return changed


def run(dry_run: bool = False) -> None:
    registry = load_json(CONFIG.registry_path, default=[])
    registry_changed = False
    touched_ids: list[str] = []

    for entry in registry:
        source = entry.get("source", "")
        if "github.com/" not in source:
            continue
        try:
            parse_github_repo(source)
        except ValueError:
            continue

        canonical_repo = github_clone_url(source)
        github_home = github_home_url(source)
        entry_changed = False

        if entry.get("canonical_repository") != canonical_repo:
            entry["canonical_repository"] = canonical_repo
            entry_changed = True
        if entry.get("github_home") != github_home:
            entry["github_home"] = github_home
            entry_changed = True

        metadata_path = ROOT / "data" / "raw" / entry["id"] / "metadata.json"
        if metadata_path.exists():
            metadata = load_json(metadata_path, default={})
            metadata_changed = False
            if metadata.get("canonical_repository") != canonical_repo:
                metadata["canonical_repository"] = canonical_repo
                metadata_changed = True
            if metadata.get("github_home") != github_home:
                metadata["github_home"] = github_home
                metadata_changed = True
            if metadata_changed and not dry_run:
                save_json(metadata_path, metadata)
            entry_changed = entry_changed or metadata_changed

        note_path = CONFIG.summaries_dir / f"{entry['id']}.md"
        if note_path.exists() and not dry_run:
            note_changed = normalize_source_note(note_path, canonical_repo, github_home)
            entry_changed = entry_changed or note_changed
        elif note_path.exists():
            note_text = note_path.read_text(encoding="utf-8")
            if "- Canonical Repository: `" not in note_text or "- GitHub Home: `" not in note_text:
                entry_changed = True

        if entry_changed:
            touched_ids.append(entry["id"])
            registry_changed = True

    if registry_changed and not dry_run:
        save_json(CONFIG.registry_path, registry)

    if touched_ids:
        mode = "Would normalize" if dry_run else "Normalized"
        print(f"{mode} {len(touched_ids)} GitHub-backed source(s):")
        for source_id in touched_ids:
            print(f"- {source_id}")
    else:
        print("No GitHub-backed sources needed normalization")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize GitHub-backed sources by recording their canonical repository and GitHub home URLs."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing files.")
    args = parser.parse_args()

    registry = load_json(CONFIG.registry_path, default=[])
    registry_changed = False
    touched_ids: list[str] = []

    for entry in registry:
        source = entry.get("source", "")
        if "github.com/" not in source:
            continue

        try:
            parse_github_repo(source)
        except ValueError:
            continue

        canonical_repo = github_clone_url(source)
        github_home = github_home_url(source)
        entry_changed = False

        if entry.get("canonical_repository") != canonical_repo:
            entry["canonical_repository"] = canonical_repo
            entry_changed = True

        if entry.get("github_home") != github_home:
            entry["github_home"] = github_home
            entry_changed = True

        metadata_path = ROOT / "data" / "raw" / entry["id"] / "metadata.json"
        if metadata_path.exists():
            metadata = load_json(metadata_path, default={})
            metadata_changed = False

            if metadata.get("canonical_repository") != canonical_repo:
                metadata["canonical_repository"] = canonical_repo
                metadata_changed = True

            if metadata.get("github_home") != github_home:
                metadata["github_home"] = github_home
                metadata_changed = True

            if metadata_changed and not args.dry_run:
                save_json(metadata_path, metadata)
            entry_changed = entry_changed or metadata_changed

        note_path = CONFIG.summaries_dir / f"{entry['id']}.md"
        if note_path.exists() and not args.dry_run:
            note_changed = normalize_source_note(note_path, canonical_repo, github_home)
            entry_changed = entry_changed or note_changed
        elif note_path.exists():
            note_text = note_path.read_text(encoding="utf-8")
            if "- Canonical Repository: `" not in note_text or "- GitHub Home: `" not in note_text:
                entry_changed = True

        if entry_changed:
            touched_ids.append(entry["id"])
            registry_changed = True

    if registry_changed and not args.dry_run:
        save_json(CONFIG.registry_path, registry)

    if touched_ids:
        mode = "Would normalize" if args.dry_run else "Normalized"
        print(f"{mode} {len(touched_ids)} GitHub-backed source(s):")
        for source_id in touched_ids:
            print(f"- {source_id}")
    else:
        print("No GitHub-backed sources needed normalization")


if __name__ == "__main__":
    main()
