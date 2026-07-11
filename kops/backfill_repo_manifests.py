"""Backfill repo_manifest.json for all github_repo_snapshot sources in data/raw/.

Also handles legacy 'repo' kind sources by shallow-cloning to extract manifest data.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Ensure scripts directory is importable when run directly
_scripts_dir = Path(__file__).parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from kops.utils import CONFIG, load_json, save_json, now_stamp  # noqa: E402

RAW_DIR = CONFIG.raw_dir


def compute_coverage_completeness(tracked: int | None, sampled: int | None) -> str:
    if tracked is None or sampled is None:
        return "unknown"
    if tracked == 0 and sampled == 0:
        return "full"
    if sampled >= tracked:
        return "full"
    return "partial"


def build_manifest(metadata: dict) -> dict:
    git_commit = metadata.get("git_commit") or None
    branch = metadata.get("branch") or metadata.get("git_branch") or None
    tracked = metadata.get("tracked_file_count")
    sampled = metadata.get("sampled_file_count")
    sampled_paths = metadata.get("sampled_paths")
    omitted_paths = metadata.get("omitted_paths_manifest")
    coverage_policy = metadata.get("coverage_policy")

    # Normalise "unknown" sentinel to None
    if git_commit == "unknown":
        git_commit = None

    legacy = git_commit is None and tracked is None and sampled is None

    coverage_completeness = compute_coverage_completeness(
        int(tracked) if tracked is not None else None,
        int(sampled) if sampled is not None else None,
    )

    return {
        "source_id": metadata.get("id"),
        "source_kind": "github-repo-snapshot",
        "git_commit": git_commit,
        "branch": branch,
        "tracked_file_count": tracked,
        "sampled_file_count": sampled,
        "sampled_paths": sampled_paths if sampled_paths is not None else [],
        "omitted_paths_manifest": omitted_paths if omitted_paths is not None else [],
        "coverage_policy": coverage_policy,
        "coverage_completeness": coverage_completeness,
        "legacy_no_data": legacy,
    }


def _clone_manifest(source_id: str, repo_url: str) -> dict | None:
    """Shallow-clone repo_url and return a manifest dict, or None on failure."""
    from kops.ingest_github_repo import (
        clone_repo,
        collect_candidate_files,
        detect_branch,
        detect_commit,
        list_tracked_files,
        MAX_EVIDENCE_FILES,
        MAX_ARCHITECTURE_FILES,
        MAX_CONCEPT_FILES,
        TEXT_SUFFIXES,
        SPECIAL_TEXT_NAMES,
    )

    try:
        clone_dir = clone_repo(repo_url, None)
        clone_root = clone_dir.parent
        try:
            branch = detect_branch(clone_dir)
            commit = detect_commit(clone_dir)
            tracked = list_tracked_files(clone_dir)
            sampled = collect_candidate_files(clone_dir, tracked)
            sampled_set = set(sampled)
            sampled_paths = [p.relative_to(clone_dir).as_posix() for p in sampled]
            omitted_paths = [
                p.relative_to(clone_dir).as_posix() for p in tracked if p not in sampled_set
            ]
            tracked_count = len(tracked)
            sampled_count = len(sampled)
            coverage_completeness = "full" if sampled_count >= tracked_count else "partial"
            return {
                "source_id": source_id,
                "source_kind": "github-repo-snapshot",
                "git_commit": commit,
                "branch": branch,
                "tracked_file_count": tracked_count,
                "sampled_file_count": sampled_count,
                "sampled_paths": sampled_paths,
                "omitted_paths_manifest": omitted_paths,
                "coverage_policy": {
                    "max_evidence_files": MAX_EVIDENCE_FILES,
                    "max_architecture_files": MAX_ARCHITECTURE_FILES,
                    "max_concept_files": MAX_CONCEPT_FILES,
                    "allowed_suffixes": sorted(TEXT_SUFFIXES),
                    "special_names": sorted(SPECIAL_TEXT_NAMES),
                },
                "coverage_completeness": coverage_completeness,
                "legacy_no_data": False,
            }
        finally:
            shutil.rmtree(clone_root, ignore_errors=True)
    except Exception as exc:
        print(f"    ERROR cloning {repo_url}: {exc}")
        return None


def _process_repo_kind(src_dir: Path, metadata: dict) -> dict:
    """Clone a legacy 'repo' kind source and return a manifest (or stub on failure)."""
    source_id = src_dir.name
    url = (
        metadata.get("canonical_repository")
        or metadata.get("github_home")
        or metadata.get("source", "")
    ).rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]

    print(f"  CLONE {source_id} <- {url}")
    manifest = _clone_manifest(source_id, url)
    if manifest is None:
        return {
            "source_id": source_id,
            "source_kind": "github-repo-snapshot",
            "git_commit": None,
            "branch": None,
            "tracked_file_count": None,
            "sampled_file_count": None,
            "sampled_paths": [],
            "omitted_paths_manifest": [],
            "coverage_policy": None,
            "coverage_completeness": "unknown",
            "legacy_no_data": True,
            "error": "clone-failed",
        }

    # Backfill metadata.json with what we learned
    metadata["git_commit"] = manifest["git_commit"]
    metadata["git_branch"] = manifest["branch"]
    metadata["branch"] = manifest["branch"]
    metadata["tracked_file_count"] = manifest["tracked_file_count"]
    metadata["sampled_file_count"] = manifest["sampled_file_count"]
    metadata["sampled_paths"] = manifest["sampled_paths"]
    metadata["evidence_strength"] = (
        "primary-doc" if manifest["coverage_completeness"] == "full" else "primary-doc-partial"
    )
    metadata["last_checked_at"] = now_stamp()
    save_json(src_dir / "metadata.json", metadata)
    print(
        f"    OK  tracked={manifest['tracked_file_count']} "
        f"sampled={manifest['sampled_file_count']} "
        f"commit={manifest['git_commit'][:8]}"
    )
    return manifest


def main() -> None:
    total = 0
    full = 0
    partial = 0
    unknown = 0
    skipped = 0
    already_exists = 0
    cloned = 0
    clone_errors = 0

    for src_dir in sorted(RAW_DIR.iterdir()):
        if not src_dir.is_dir():
            continue
        metadata_path = src_dir / "metadata.json"
        if not metadata_path.exists():
            continue

        try:
            metadata = load_json(metadata_path, {})
        except Exception as exc:
            print(f"  [WARN] Could not read {metadata_path}: {exc}")
            continue

        kind = metadata.get("kind", "")
        manifest_path = src_dir / "repo_manifest.json"

        if kind == "github_repo_snapshot":
            if manifest_path.exists():
                already_exists += 1
                total += 1
                try:
                    existing = load_json(manifest_path, {})
                    cc = existing.get("coverage_completeness", "unknown")
                    if cc == "full":
                        full += 1
                    elif cc == "partial":
                        partial += 1
                    else:
                        unknown += 1
                except Exception:
                    unknown += 1
                continue

            manifest = build_manifest(metadata)
            save_json(manifest_path, manifest)
            total += 1
            cc = manifest["coverage_completeness"]
            if cc == "full":
                full += 1
            elif cc == "partial":
                partial += 1
            else:
                unknown += 1

        elif kind == "repo":
            if manifest_path.exists():
                already_exists += 1
                total += 1
                try:
                    existing = load_json(manifest_path, {})
                    cc = existing.get("coverage_completeness", "unknown")
                    if cc == "full":
                        full += 1
                    elif cc == "partial":
                        partial += 1
                    else:
                        unknown += 1
                except Exception:
                    unknown += 1
                continue

            manifest = _process_repo_kind(src_dir, metadata)
            save_json(manifest_path, manifest)
            total += 1
            cloned += 1
            cc = manifest.get("coverage_completeness", "unknown")
            if manifest.get("error") == "clone-failed":
                clone_errors += 1
                unknown += 1
            elif cc == "full":
                full += 1
            elif cc == "partial":
                partial += 1
            else:
                unknown += 1

        else:
            skipped += 1
            continue

    written = total - already_exists
    print(f"\ngithub_repo_snapshot + repo sources processed : {total}")
    print(f"  Already had repo_manifest.json              : {already_exists}")
    print(f"  Newly written (from metadata)               : {written - cloned}")
    print(f"  Newly written (from clone)                  : {cloned}")
    print(f"  Clone failures (stub written)               : {clone_errors}")
    print(f"  coverage_completeness=full                  : {full}")
    print(f"  coverage_completeness=partial               : {partial}")
    print(f"  coverage_completeness=unknown               : {unknown}")
    print(f"Non-github sources skipped                    : {skipped}")


if __name__ == "__main__":
    main()
