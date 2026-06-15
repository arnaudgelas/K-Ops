"""
search_vault.py — CLI for hybrid vault retrieval.

Usage:
    uv run python scripts/search_vault.py "<query>" [--top 10] [--kind source|concept|claim]

Output: numbered results with id, kind, score, retrieval_method, snippet.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from retrieval import VaultIndex  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hybrid vault search: exact ID lookup + BM25 full-text."
    )
    parser.add_argument("query", help="Search query, source_id, claim_id, or concept slug")
    parser.add_argument(
        "--top", type=int, default=10, help="Maximum results to return (default 10)"
    )
    parser.add_argument(
        "--kind",
        choices=["source", "concept", "claim", "source-section"],
        default=None,
        help="Filter results by kind",
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="Only build the index and report timing, do not search",
    )
    args = parser.parse_args()

    # Build index
    t_build_start = time.perf_counter()
    idx = VaultIndex()
    idx.build()
    build_ms = (time.perf_counter() - t_build_start) * 1000

    if args.build_only:
        print(f"Index build: {build_ms:.0f}ms")
        return

    # Run query
    t_query_start = time.perf_counter()
    results = idx.search(args.query, top_k=args.top, kind=args.kind)
    query_ms = (time.perf_counter() - t_query_start) * 1000

    # Output
    print(f"Query: {args.query!r}  |  build={build_ms:.0f}ms  query={query_ms:.0f}ms")
    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, 1):
        print(
            f"\n{i}. [{r['kind']}] {r['id']}"
            f"\n   Title  : {r['title'][:80]}"
            f"\n   Score  : {r['score']:.4f}"
            f"\n   Method : {r['retrieval_method']}"
            f"\n   Snippet: {r['snippet'][:160]}"
        )


if __name__ == "__main__":
    main()
