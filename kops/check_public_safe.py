"""Leak tripwire for the public tooling repository.

This repo is meant to hold the *tooling* plus a small curated demo vault — never
a real corpus. If a sync from a private vault ever drags real source data in,
this check fails loudly in CI instead of silently publishing it.

It is intentionally crude (counts, not content): the private vault is data-rich,
the public demo is data-poor, so a simple ceiling separates them cleanly. Raise
the ceiling deliberately if the curated demo legitimately grows.

Thresholds override via env: KB_MAX_PUBLIC_SOURCES, KB_MAX_PUBLIC_RAW_FILES.
"""

from __future__ import annotations

import json
import os
import sys

from kops.kb_paths import ROOT

MAX_SOURCES = int(os.environ.get("KB_MAX_PUBLIC_SOURCES", "25"))
MAX_RAW_FILES = int(os.environ.get("KB_MAX_PUBLIC_RAW_FILES", "60"))


def _count_sources() -> int:
    registry = ROOT / "data" / "registry.json"
    if not registry.exists():
        return 0
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    if isinstance(data, dict):  # tolerate {"sources": [...]} or id-keyed map
        data = data.get("sources", list(data.values()))
    return len(data) if isinstance(data, list) else 0


def _count_raw_files() -> int:
    raw = ROOT / "data" / "raw"
    if not raw.exists():
        return 0
    return sum(1 for p in raw.rglob("*") if p.is_file())


def main() -> int:
    sources = _count_sources()
    raw_files = _count_raw_files()
    problems = []
    if sources > MAX_SOURCES:
        problems.append(f"registry has {sources} sources (public ceiling {MAX_SOURCES})")
    if raw_files > MAX_RAW_FILES:
        problems.append(f"data/raw has {raw_files} files (public ceiling {MAX_RAW_FILES})")

    if problems:
        print("PUBLIC-SAFETY TRIPWIRE FAILED — this looks like a private corpus:")
        for p in problems:
            print(f"  - {p}")
        print(
            "\nThe public repo must contain only the demo vault. If a real vault leaked in,\n"
            "do NOT commit. If the demo genuinely grew, raise KB_MAX_PUBLIC_* deliberately."
        )
        return 1

    print(
        f"public-safe: {sources} sources, {raw_files} raw files (ceilings {MAX_SOURCES}/{MAX_RAW_FILES})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
