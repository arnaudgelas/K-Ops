from __future__ import annotations

import argparse
import json
from pathlib import Path

from utils import CONFIG, ROOT, ensure_dir, load_json


def build_manifest() -> dict:
    registry = load_json(CONFIG.registry_path, default=[])
    return {
        "sources": registry,
        "vault_files": sorted(str(p.relative_to(ROOT)) for p in CONFIG.vault_dir.rglob("*.md")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a JSON manifest of the registry and vault files."
    )
    parser.add_argument("--output", help="Optional output path. Defaults to stdout.")
    args = parser.parse_args()

    manifest = build_manifest()
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
