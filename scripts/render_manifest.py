from __future__ import annotations

import json
from pathlib import Path

from utils import CONFIG, ROOT, load_json


def main() -> None:
    registry = load_json(CONFIG.registry_path, default=[])
    manifest = {
        "sources": registry,
        "vault_files": sorted(str(p.relative_to(ROOT)) for p in CONFIG.vault_dir.rglob("*.md")),
    }
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
