from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from utils import CONFIG, ROOT, load_json, now_stamp, save_json

REGISTRY_PATH = CONFIG.registry_path
RAW_DIR = CONFIG.raw_dir


def load_registry() -> list[dict]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_bytes_for(item: dict, metadata: dict) -> bytes | None:
    original_path = item.get("original_path") or metadata.get("original_path")
    if original_path:
        path = ROOT / original_path
        if path.exists():
            return path.read_bytes()
    normalized_path = item.get("normalized_path") or metadata.get("normalized_path")
    if not normalized_path:
        return None
    normalized_file = ROOT / normalized_path
    if normalized_file.exists():
        return normalized_file.read_bytes()
    return None


def chosen_checked_at(item: dict, metadata: dict, fallback: str) -> str:
    candidates = [value for value in (item.get("last_checked_at"), metadata.get("last_checked_at")) if isinstance(value, str) and value.strip()]
    if not candidates:
        return fallback
    return max(candidates)


def backfill_item(item: dict, dry_run: bool = False) -> bool:
    metadata_path = RAW_DIR / item["id"] / "metadata.json"
    if not metadata_path.exists():
        return False

    metadata = load_json(metadata_path, default={})
    content_bytes = content_bytes_for(item, metadata)
    if content_bytes is None:
        return False

    content_hash = sha256_bytes(content_bytes)
    current_hash = item.get("content_hash") or metadata.get("content_hash")
    changed = False

    if current_hash != content_hash:
        checked_at = now_stamp()
        for target in (item, metadata):
            if target.get("content_hash") != content_hash:
                target["content_hash"] = content_hash
                changed = True
            if target.get("last_checked_at") != checked_at:
                target["last_checked_at"] = checked_at
                changed = True
    else:
        current_checked_at = chosen_checked_at(item, metadata, now_stamp())
        for target in (item, metadata):
            if target.get("content_hash") != content_hash:
                target["content_hash"] = content_hash
                changed = True
            if target.get("last_checked_at") != current_checked_at:
                target["last_checked_at"] = current_checked_at
                changed = True

    if changed and not dry_run:
        save_json(metadata_path, metadata)
    return changed


def run(all: bool = True, ids: list[str] | None = None, dry_run: bool = False) -> list[str]:
    """Backfill content hashes and timestamps.

    Returns the list of source IDs whose content hash changed (or was set for
    the first time).  Callers can use this to decide whether downstream steps
    (e.g. compile) are worth running.
    """
    registry = load_registry()
    wanted = set(ids or [])
    selected = [item for item in registry if all or item["id"] in wanted]

    touched: list[str] = []
    registry_changed = False
    for item in selected:
        changed = backfill_item(item, dry_run=dry_run)
        if changed:
            touched.append(item["id"])
            registry_changed = True

    if registry_changed and not dry_run:
        save_json(REGISTRY_PATH, registry)

    if touched:
        mode = "Would backfill" if dry_run else "Backfilled"
        print(f"{mode} {len(touched)} source(s):")
        for source_id in touched:
            print(f"- {source_id}")
    else:
        print("No source metadata needed backfilling")

    return touched


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill content hashes and source check timestamps into registry and raw metadata.")
    parser.add_argument("--all", action="store_true", help="Backfill every registry entry.")
    parser.add_argument("--id", dest="ids", action="append", help="Backfill only the listed source ids.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned changes without writing files.")
    args = parser.parse_args()

    if not args.all and not args.ids:
        raise SystemExit("Pass --all or one or more --id values.")

    registry = load_registry()
    wanted = set(args.ids or [])
    selected = [item for item in registry if args.all or item["id"] in wanted]

    touched: list[str] = []
    registry_changed = False
    for item in selected:
        changed = backfill_item(item, dry_run=args.dry_run)
        if changed:
            touched.append(item["id"])
            registry_changed = True

    if registry_changed and not args.dry_run:
        save_json(REGISTRY_PATH, registry)

    if touched:
        mode = "Would backfill" if args.dry_run else "Backfilled"
        print(f"{mode} {len(touched)} source(s):")
        for source_id in touched:
            print(f"- {source_id}")
    else:
        print("No source metadata needed backfilling")


if __name__ == "__main__":
    main()
