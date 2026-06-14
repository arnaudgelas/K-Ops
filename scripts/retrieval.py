"""
retrieval.py — Hybrid retrieval baseline for the agkb vault.

Implements:
- Exact lookup by source_id / claim_id / concept slug
- BM25 full-text over source summaries and concept pages (from-scratch BM25)
- Retrieval trace: every result includes retrieval_method explaining why it was returned

Budget targets: index build ≤60s, single query ≤500ms, no network calls.
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap path so imports work whether called directly or via uv run
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from utils import CONFIG, ROOT, parse_frontmatter  # noqa: E402


# ---------------------------------------------------------------------------
# Lightweight BM25 implementation (~50 lines, no dependencies)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase and split on whitespace + punctuation."""
    return [tok for tok in re.split(r"[\W_]+", text.lower()) if tok]


class _BM25:
    """Okapi BM25 over a list of pre-tokenized documents."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.n = len(corpus)
        self.avgdl = sum(len(doc) for doc in corpus) / max(self.n, 1)
        self.dl: list[int] = [len(doc) for doc in corpus]
        # df: term -> document frequency
        self.df: dict[str, int] = {}
        for doc in corpus:
            for term in set(doc):
                self.df[term] = self.df.get(term, 0) + 1
        # tf: for each doc, term -> count
        self.tf: list[dict[str, int]] = []
        for doc in corpus:
            counts: dict[str, int] = {}
            for term in doc:
                counts[term] = counts.get(term, 0) + 1
            self.tf.append(counts)

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log((self.n - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, doc_idx: int, query_terms: list[str]) -> float:
        score = 0.0
        tf_doc = self.tf[doc_idx]
        dl = self.dl[doc_idx]
        denom_base = self.k1 * (1 - self.b + self.b * dl / self.avgdl)
        for term in query_terms:
            tf = tf_doc.get(term, 0)
            if tf == 0:
                continue
            score += self.idf(term) * (tf * (self.k1 + 1)) / (tf + denom_base)
        return score

    def get_top_n(self, query_terms: list[str], top_k: int = 10) -> list[tuple[int, float]]:
        scored = [(i, self.score(i, query_terms)) for i in range(self.n)]
        scored.sort(key=lambda x: -x[1])
        return [(i, s) for i, s in scored[:top_k] if s > 0.0]


# ---------------------------------------------------------------------------
# Record type
# ---------------------------------------------------------------------------


def _snippet(text: str, max_len: int = 200) -> str:
    """Return first max_len characters of text, stripped."""
    return text.strip()[:max_len]


def _make_result(
    record: dict,
    score: float,
    retrieval_method: str,
) -> dict:
    """Normalise an internal record into the public result shape."""
    text = record.get("search_text") or record.get("claim_text") or record.get("title") or ""
    return {
        "id": record["id"],
        "kind": record["kind"],
        "title": record.get("title") or record["id"],
        "score": round(score, 6),
        "retrieval_method": retrieval_method,
        "snippet": _snippet(text),
    }


# ---------------------------------------------------------------------------
# Main index class
# ---------------------------------------------------------------------------


class VaultIndex:
    """In-memory index over vault source summaries, concept pages, and claims."""

    def __init__(self) -> None:
        self._records: list[dict] = []  # all indexed records
        self._id_map: dict[str, list[int]] = {}  # id -> [record indices]
        self._bm25: _BM25 | None = None
        self._corpus: list[list[str]] = []
        self._built = False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _add_record(self, record: dict) -> None:
        idx = len(self._records)
        self._records.append(record)
        # Index by full id
        rid = record["id"]
        self._id_map.setdefault(rid, []).append(idx)
        # Also index by bare stem (part after the last colon or the raw id)
        bare = rid.split(":")[-1] if ":" in rid else rid
        if bare != rid:
            self._id_map.setdefault(bare, []).append(idx)
        # Index claim_id field if present (for backward compat)
        cid = record.get("claim_id")
        if cid and cid != rid:
            self._id_map.setdefault(cid, []).append(idx)

    # Maximum characters to read from each file for BM25 indexing.
    # Keeps build time well under 60 s even with 1 000+ source files.
    _MAX_INDEX_CHARS = 8_000

    def _read_index_text(self, path: Path) -> str:
        """Read up to _MAX_INDEX_CHARS bytes from path for indexing."""
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                return fh.read(self._MAX_INDEX_CHARS)
        except OSError:
            return ""

    def _index_sources(self) -> None:
        for path in sorted(CONFIG.summaries_dir.rglob("src-*.md")):
            text = self._read_index_text(path)
            if not text:
                continue
            fm, body = parse_frontmatter(text)
            stem = path.stem
            source_id = fm.get("source_id") or stem
            title = str(fm.get("title") or fm.get("title_guess") or stem)
            search_text = f"{title}\n{body}"
            record = {
                "id": source_id,
                "kind": "source",
                "title": title,
                "path": path.relative_to(ROOT).as_posix(),
                "search_text": search_text,
                "frontmatter": fm,
            }
            self._add_record(record)

    def _index_concepts(self) -> None:
        for path in sorted(CONFIG.concepts_dir.glob("*.md")):
            text = self._read_index_text(path)
            if not text:
                continue
            fm, body = parse_frontmatter(text)
            stem = path.stem
            title = str(fm.get("title") or stem)
            search_text = f"{title}\n{body}"
            record = {
                "id": stem,
                "kind": "concept",
                "title": title,
                "path": path.relative_to(ROOT).as_posix(),
                "search_text": search_text,
                "frontmatter": fm,
            }
            self._add_record(record)
            # Also add by concept slug as alternate id
            slug_id = f"concept:{stem}"
            if slug_id not in self._id_map:
                self._id_map[slug_id] = self._id_map.get(stem, [])

    def _index_claims(self) -> None:
        claims_path = ROOT / "data" / "claims.json"
        if not claims_path.exists():
            return
        try:
            data = json.loads(claims_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        claims = data.get("claims", []) if isinstance(data, dict) else data
        for claim in claims:
            claim_id = claim.get("claim_id") or claim.get("id")
            if not claim_id:
                continue
            claim_text = claim.get("claim_text") or claim.get("text") or ""
            concept = claim.get("concept") or ""
            title = claim_text[:96].rstrip(" ,;:") or claim_id
            search_text = f"{concept}\n{claim_text}"
            record = {
                "id": claim_id,
                "claim_id": claim_id,
                "kind": "claim",
                "title": title,
                "concept": concept,
                "search_text": search_text,
                "claim_text": claim_text,
                "frontmatter": {},
            }
            self._add_record(record)

    def build(self) -> None:
        """Index source summaries + concept pages + claims. Tokenise by whitespace+punctuation."""
        self._records = []
        self._id_map = {}
        self._corpus = []
        self._bm25 = None

        self._index_sources()
        self._index_concepts()
        self._index_claims()

        # Build BM25 corpus from all records
        self._corpus = [
            _tokenize(r.get("search_text") or r.get("title") or "") for r in self._records
        ]
        self._bm25 = _BM25(self._corpus)
        self._built = True

    def _ensure_built(self) -> None:
        if not self._built:
            self.build()

    # ------------------------------------------------------------------
    # Exact lookup
    # ------------------------------------------------------------------

    def exact(self, query_id: str) -> list[dict]:
        """Look up by source_id, claim_id, or concept slug. Returns matching records."""
        self._ensure_built()
        indices = self._id_map.get(query_id, [])
        results = []
        seen: set[int] = set()
        for idx in indices:
            if idx in seen:
                continue
            seen.add(idx)
            r = self._records[idx]
            results.append(_make_result(r, 1.0, "exact"))
        return results

    # ------------------------------------------------------------------
    # BM25
    # ------------------------------------------------------------------

    def bm25(self, query: str, top_k: int = 10) -> list[dict]:
        """BM25 search over indexed text. Returns scored results."""
        self._ensure_built()
        if self._bm25 is None:
            return []
        terms = _tokenize(query)
        if not terms:
            return []
        hits = self._bm25.get_top_n(terms, top_k=top_k)
        results = []
        for idx, score in hits:
            r = self._records[idx]
            results.append(_make_result(r, score, "bm25"))
        return results

    # ------------------------------------------------------------------
    # Combined search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 10, kind: str | None = None) -> list[dict]:
        """Combines exact + bm25. Returns results with retrieval_method field."""
        self._ensure_built()

        # Try exact first
        exact_results = self.exact(query)

        # BM25 for everything else
        bm25_results = self.bm25(query, top_k=top_k)

        # Merge: exact results first, then bm25 not already in exact set
        seen_ids: set[str] = set()
        combined: list[dict] = []
        for r in exact_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                combined.append(r)

        for r in bm25_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                combined.append(r)

        # Filter by kind if requested
        if kind:
            combined = [r for r in combined if r["kind"] == kind]

        return combined[:top_k]


# ---------------------------------------------------------------------------
# Module-level singleton for reuse
# ---------------------------------------------------------------------------

_INDEX: VaultIndex | None = None


def get_index(rebuild: bool = False) -> VaultIndex:
    """Return module-level singleton index, building on first access."""
    global _INDEX
    if _INDEX is None or rebuild:
        idx = VaultIndex()
        idx.build()
        _INDEX = idx
    return _INDEX


# ---------------------------------------------------------------------------
# CLI entry point (thin wrapper; full CLI in search_vault.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build and query the vault retrieval index.")
    parser.add_argument("query", help="Search query or ID")
    parser.add_argument("--top", type=int, default=10, help="Number of results")
    parser.add_argument("--kind", choices=["source", "concept", "claim"], default=None)
    args = parser.parse_args()

    t0 = time.perf_counter()
    idx = VaultIndex()
    idx.build()
    build_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    results = idx.search(args.query, top_k=args.top, kind=args.kind)
    query_ms = (time.perf_counter() - t1) * 1000

    print(f"Index build: {build_ms:.0f}ms | Query: {query_ms:.0f}ms")
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['kind']}] {r['id']} — {r['title'][:60]}")
        print(f"   score={r['score']:.4f} method={r['retrieval_method']}")
        print(f"   {r['snippet'][:120]}")
