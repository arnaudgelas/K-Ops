from __future__ import annotations

import argparse
from pathlib import Path

from fetch_sources import ingest_one, is_url, read_input_list
from ingest_github_repo import ingest_repo, parse_github_repo
from utils import CONFIG, ROOT, load_json, save_json


def looks_like_github_repo_url(value: str) -> bool:
    try:
        parse_github_repo(value)
        return True
    except ValueError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a mixed list of URLs and local files, routing GitHub repository URLs to the repo snapshot flow."
    )
    parser.add_argument("--input", required=True, help="Path to a newline-delimited list of URLs or local paths")
    parser.add_argument("--fail-fast", action="store_true", help="Stop at the first ingestion error.")
    parser.add_argument("--branch", help="Optional branch override for GitHub repository URLs.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch and overwrite existing sources instead of skipping items already present in the registry.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = (ROOT / input_path).resolve()

    items = read_input_list(input_path)
    registry = load_json(CONFIG.registry_path, default=[])
    existing_sources = {entry["source"] for entry in registry}

    new_entries = []
    failures: list[tuple[str, str]] = []

    for item in items:
        if item in existing_sources and not args.refresh:
            print(f"Skipping already ingested source: {item}")
            continue

        try:
            if is_url(item) and looks_like_github_repo_url(item):
                entry = ingest_repo(item, branch=args.branch)
            else:
                entry = ingest_one(item)
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            failures.append((item, message))
            print(f"Failed to ingest {item}: {message}")
            if args.fail_fast:
                break
            continue

        new_entries.append(entry)
        print(f"Ingested {item} -> {entry['id']}")

    if new_entries:
        if args.refresh:
            existing_by_id = {entry["id"]: index for index, entry in enumerate(registry)}
            for entry in new_entries:
                index = existing_by_id.get(entry["id"])
                if index is None:
                    registry.append(entry)
                else:
                    registry[index] = entry
        else:
            registry.extend(new_entries)
        save_json(CONFIG.registry_path, registry)
        action = "Refreshed" if args.refresh else "Updated"
        print(f"{action} registry with {len(new_entries)} source(s)")
    else:
        print("No new sources ingested" if not args.refresh else "No sources refreshed")

    if failures:
        print("")
        print(f"Ingestion completed with {len(failures)} failure(s):")
        for item, message in failures:
            print(f"- {item}: {message}")


if __name__ == "__main__":
    main()
