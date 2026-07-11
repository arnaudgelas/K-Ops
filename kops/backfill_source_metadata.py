from __future__ import annotations

import argparse
import hashlib
import json
import re

from kops.utils import CONFIG, ROOT, load_json, now_stamp, save_json

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
    candidates = [
        value
        for value in (item.get("last_checked_at"), metadata.get("last_checked_at"))
        if isinstance(value, str) and value.strip()
    ]
    if not candidates:
        return fallback
    return max(candidates)


def backfill_item(item: dict, dry_run: bool = False) -> bool:
    metadata_path = RAW_DIR / item["id"] / "metadata.json"
    if not metadata_path.exists():
        return False

    metadata = load_json(metadata_path, default={})
    content_bytes = content_bytes_for(item, metadata)
    changed = False

    if content_bytes is not None:
        content_hash = sha256_bytes(content_bytes)
        current_hash = item.get("content_hash") or metadata.get("content_hash")

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
    else:
        current_checked_at = chosen_checked_at(item, metadata, now_stamp())
        for target in (item, metadata):
            if target.get("last_checked_at") != current_checked_at:
                target["last_checked_at"] = current_checked_at
                changed = True

    # Auto-recover missing github repository metadata fields from original.md/normalized.md
    kind = item.get("kind") or metadata.get("kind")
    if kind in {"github_repo_snapshot", "github-repo-snapshot"}:
        missing_fields = [
            f
            for f in [
                "branch",
                "git_commit",
                "tracked_file_count",
                "sampled_file_count",
                "sampled_paths",
                "omitted_paths_manifest",
                "coverage_policy",
            ]
            if f not in metadata or metadata[f] is None
        ]
        if missing_fields:
            original_path = item.get("original_path") or metadata.get("original_path")
            normalized_path = item.get("normalized_path") or metadata.get("normalized_path")
            txt = ""
            for p in (normalized_path, original_path):
                if p and (ROOT / p).exists():
                    try:
                        txt = (ROOT / p).read_text(encoding="utf-8")
                        break
                    except Exception:
                        pass
            if txt:
                parsed_meta = {}
                m = re.search(r"-\s*Branch:\s*`([^`]+)`", txt)
                if m:
                    parsed_meta["branch"] = m.group(1)
                    parsed_meta["git_branch"] = m.group(1)
                m = re.search(r"-\s*Commit:\s*`([^`]+)`", txt)
                if m:
                    parsed_meta["git_commit"] = m.group(1)
                m = re.search(r"-\s*Tracked file count:\s*`(\d+)`", txt)
                if m:
                    parsed_meta["tracked_file_count"] = int(m.group(1))
                sampled_paths = []
                for pm in re.finditer(r"-\s*Path:\s*`([^`]+)`", txt):
                    sampled_paths.append(pm.group(1))
                if sampled_paths:
                    parsed_meta["sampled_paths"] = sampled_paths
                    parsed_meta["sampled_file_count"] = len(sampled_paths)
                parsed_meta["omitted_paths_manifest"] = []
                parsed_meta["coverage_policy"] = {
                    "max_evidence_files": 20,
                    "max_architecture_files": 8,
                    "max_concept_files": 8,
                    "allowed_suffixes": [".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go"],
                    "special_names": ["LICENSE", "Makefile", "Dockerfile"],
                }
                for f, val in parsed_meta.items():
                    if f not in metadata or metadata[f] is None:
                        metadata[f] = val
                        changed = True
                    if f not in item or item[f] is None:
                        item[f] = val
                        changed = True

    # Process large source manifest if content is large
    from kops.fetch_sources import process_large_source
    from kops.kb_schema import normalize_source_kind

    normalized_path = item.get("normalized_path") or metadata.get("normalized_path")
    original_path = item.get("original_path") or metadata.get("original_path")
    content_file = None
    if normalized_path:
        content_file = ROOT / normalized_path
    if not content_file or not content_file.exists():
        if original_path:
            content_file = ROOT / original_path

    if content_file and content_file.exists():
        try:
            content_text = content_file.read_text(encoding="utf-8")
        except Exception:
            content_text = ""
        if len(content_text) > 10000:
            source_id = item["id"]
            source_dir = RAW_DIR / source_id
            source_url = item.get("source") or metadata.get("source") or ""
            is_pdf = item.get("kind") == "pdf" or str(source_url).lower().endswith(".pdf")
            pdf_path = None
            if is_pdf:
                for f in source_dir.glob("original*.pdf"):
                    pdf_path = f
                    break
            raw_html = None
            for f in source_dir.glob("original*.html"):
                try:
                    raw_html = f.read_text(encoding="utf-8")
                except Exception:
                    pass
                break

            manifest_rel = str((source_dir / "large_source_manifest.json").relative_to(ROOT))
            if not dry_run:
                manifest = process_large_source(
                    normalized_content=content_text,
                    source_dir=source_dir,
                    source_id=source_id,
                    is_pdf=is_pdf,
                    pdf_path=pdf_path,
                    raw_html=raw_html,
                    source_kind=normalize_source_kind(item.get("kind", "")),
                )
                if manifest:
                    if metadata.get("large_source_manifest_path") != manifest_rel:
                        metadata["large_source_manifest_path"] = manifest_rel
                        changed = True
                    if item.get("large_source_manifest_path") != manifest_rel:
                        item["large_source_manifest_path"] = manifest_rel
                        changed = True
            else:
                if (
                    metadata.get("large_source_manifest_path") != manifest_rel
                    or item.get("large_source_manifest_path") != manifest_rel
                ):
                    changed = True

    if changed and not dry_run:
        save_json(metadata_path, metadata)
    return changed


def backfill_source_metadata(
    all_items: bool = False, ids: list[str] | None = None, dry_run: bool = False
) -> None:
    if not all_items and not ids:
        raise SystemExit("Pass --all or one or more --id values.")

    registry = load_registry()
    wanted = set(ids or [])
    selected = [item for item in registry if all_items or item["id"] in wanted]

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill content hashes and source check timestamps into registry and raw metadata."
    )
    parser.add_argument("--all", action="store_true", help="Backfill every registry entry.")
    parser.add_argument(
        "--id", dest="ids", action="append", help="Backfill only the listed source ids."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report planned changes without writing files."
    )
    args = parser.parse_args()
    backfill_source_metadata(all_items=args.all, ids=args.ids, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
