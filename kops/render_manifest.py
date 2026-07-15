from __future__ import annotations

import argparse
import json
from pathlib import Path

from kops import source_override
from kops.utils import CONFIG, ROOT, ensure_dir, load_json


def build_manifest(include_flagged: bool = False) -> dict:
    """Render a manifest of the registry and vault files.

    Flagged/revoked/adversarial sources are excluded from ``sources`` by default
    and reported under ``excluded_sources`` (a real exclusion at the render
    surface, not just a report). Pass ``include_flagged=True`` for an admin view.
    """
    registry = load_json(CONFIG.registry_path, default=[])
    overrides = source_override.load_overrides()

    sources: list = []
    excluded: list[dict] = []
    for item in registry:
        if not isinstance(item, dict):
            sources.append(item)
            continue
        should_drop, reasons = source_override.should_exclude(
            item, command="render", include_flagged=include_flagged, overrides=overrides
        )
        if should_drop:
            excluded.append({"id": item.get("id"), "reasons": reasons})
            continue
        sources.append(item)

    return {
        "sources": sources,
        "excluded_sources": excluded,
        "vault_files": sorted(str(p.relative_to(ROOT)) for p in CONFIG.vault_dir.rglob("*.md")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a JSON manifest of the registry and vault files."
    )
    parser.add_argument("--output", help="Optional output path. Defaults to stdout.")
    parser.add_argument(
        "--include-flagged",
        action="store_true",
        help="Admin: include flagged/revoked/adversarial sources (default: excluded).",
    )
    args = parser.parse_args()

    manifest = build_manifest(include_flagged=args.include_flagged)
    rendered = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        output_path = Path(args.output).resolve()
        ensure_dir(output_path.parent)
        output_path.write_text(rendered, encoding="utf-8")
        print(output_path)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
