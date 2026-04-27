"""
graph_link_candidates.py
========================
Proposes missing concept-to-concept links using four learning / graph theories:

  1. Hebbian co-citation  — concepts cited together by the same source fire together;
                            raw co-citation count.
  2. PMI                  — pointwise mutual information; penalises spurious co-citation
                            from very popular hub concepts.
  3. Jaccard similarity   — fraction of shared concept-neighbours; finds structural
                            equivalents that are not yet wired together.
  4. Spreading activation — random-walk proximity; surfaces concepts reachable via many
                            short paths that still lack a direct edge.

Output: ranked table printed to stdout and written to data/graph/link_candidates.json.

Usage (from repo root):
    uv run python scripts/graph_link_candidates.py [--top N] [--min-count M]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

# ── locate repo root and import vault utilities ──────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vault_graph import build_nodes_and_edges, GRAPH_PATH  # noqa: E402

CANDIDATES_PATH = ROOT / "data" / "graph" / "link_candidates.json"

# strip Hebbian / friction / analogical annotations from link targets so we can
# compare plain concept stems
ANNOTATION_RE = re.compile(r"\s*\*\(.*?\)\*\s*$")


# ── graph loading ─────────────────────────────────────────────────────────────

def load_graph() -> dict:
    if GRAPH_PATH.exists():
        return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    print("[graph_link_candidates] graph not cached — building now …", file=sys.stderr)
    return build_nodes_and_edges()


# ── helpers ───────────────────────────────────────────────────────────────────

def concept_nodes(graph: dict) -> dict[str, dict]:
    return {n["id"]: n for n in graph["nodes"] if n["kind"] == "concept"}


def existing_concept_edges(graph: dict) -> set[tuple[str, str]]:
    """Return all directed concept→concept edges that already exist."""
    existing: set[tuple[str, str]] = set()
    for edge in graph["edges"]:
        if edge["relation"] == "related_to":
            s, t = edge["source"], edge["target"]
            if s.startswith("concept:") and t.startswith("concept:"):
                existing.add((s, t))
                existing.add((t, s))   # treat as undirected
    return existing


def source_to_concepts(graph: dict) -> dict[str, set[str]]:
    """Map each source node id → set of concept node ids it supports."""
    s2c: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        if edge["relation"] == "supports_concept":
            src, tgt = edge["source"], edge["target"]
            if src.startswith("source:") and tgt.startswith("concept:"):
                s2c[src].add(tgt)
    return s2c


def concept_to_sources(s2c: dict[str, set[str]]) -> dict[str, set[str]]:
    c2s: dict[str, set[str]] = defaultdict(set)
    for src, concepts in s2c.items():
        for c in concepts:
            c2s[c].add(src)
    return c2s


# ── Theory 1 & 2: Hebbian co-citation + PMI ──────────────────────────────────

def hebbian_and_pmi(
    concepts: dict[str, dict],
    s2c: dict[str, set[str]],
    c2s: dict[str, set[str]],
    existing: set[tuple[str, str]],
) -> list[dict]:
    """
    For every pair (A, B) that share at least one source:
      co_count = |sources(A) ∩ sources(B)|
      PMI      = log2( P(A,B) / (P(A) * P(B)) )
               = log2( co_count * N_sources / (|sources(A)| * |sources(B)|) )
    """
    N = len(s2c)  # total sources
    concept_ids = list(concepts.keys())
    results: list[dict] = []
    seen: set[frozenset] = set()

    for i, ca in enumerate(concept_ids):
        sa = c2s.get(ca, set())
        if not sa:
            continue
        for cb in concept_ids[i + 1:]:
            pair = frozenset({ca, cb})
            if pair in seen:
                continue
            seen.add(pair)
            if (ca, cb) in existing:
                continue
            sb = c2s.get(cb, set())
            if not sb:
                continue
            shared = sa & sb
            co = len(shared)
            if co == 0:
                continue
            # PMI
            pmi = math.log2((co * N) / (len(sa) * len(sb))) if N > 0 else 0.0
            results.append(
                {
                    "a": ca,
                    "b": cb,
                    "a_title": concepts[ca]["title"],
                    "b_title": concepts[cb]["title"],
                    "co_citation": co,
                    "pmi": round(pmi, 3),
                    "shared_sources": sorted(shared),
                }
            )

    return results


# ── Theory 3: Jaccard similarity on the concept graph ────────────────────────

def jaccard_similarity(
    concepts: dict[str, dict],
    existing: set[tuple[str, str]],
    graph: dict,
) -> list[dict]:
    """
    neighbours(A) = set of concept nodes directly linked to A.
    Jaccard(A,B)  = |N(A) ∩ N(B)| / |N(A) ∪ N(B)|
    Only report pairs with Jaccard > 0 that have no direct edge.
    """
    # build neighbour sets
    neighbours: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        if edge["relation"] == "related_to":
            s, t = edge["source"], edge["target"]
            if s.startswith("concept:") and t.startswith("concept:"):
                neighbours[s].add(t)
                neighbours[t].add(s)

    concept_ids = list(concepts.keys())
    results: list[dict] = []
    seen: set[frozenset] = set()

    for i, ca in enumerate(concept_ids):
        na = neighbours.get(ca, set())
        if not na:
            continue
        for cb in concept_ids[i + 1:]:
            pair = frozenset({ca, cb})
            if pair in seen:
                continue
            seen.add(pair)
            if (ca, cb) in existing:
                continue
            nb = neighbours.get(cb, set())
            if not nb:
                continue
            intersection = na & nb
            union = na | nb
            if not intersection:
                continue
            j = len(intersection) / len(union)
            results.append(
                {
                    "a": ca,
                    "b": cb,
                    "a_title": concepts[ca]["title"],
                    "b_title": concepts[cb]["title"],
                    "jaccard": round(j, 4),
                    "shared_neighbours": sorted(intersection),
                    "shared_neighbour_count": len(intersection),
                }
            )

    results.sort(key=lambda r: -r["jaccard"])
    return results


# ── Theory 4: Spreading activation (random-walk proximity) ───────────────────

def spreading_activation(
    concepts: dict[str, dict],
    existing: set[tuple[str, str]],
    graph: dict,
    decay: float = 0.5,
    steps: int = 3,
    top_seeds: int = 20,
) -> list[dict]:
    """
    Start activation = 1.0 at each seed concept.
    At each step, spread fraction `decay` equally to concept neighbours.
    After `steps` rounds, pairs (seed, reached) with no direct edge and
    high activation are candidates.
    We run seeds = highest-inbound-degree concepts (eigenvector-centrality proxy).
    """
    # build adjacency for concepts only
    adj: dict[str, list[str]] = defaultdict(list)
    for edge in graph["edges"]:
        if edge["relation"] == "related_to":
            s, t = edge["source"], edge["target"]
            if s.startswith("concept:") and t.startswith("concept:"):
                adj[s].append(t)

    # pick seeds: concepts with highest out-degree
    degree = {cid: len(adj.get(cid, [])) for cid in concepts}
    seeds = sorted(degree, key=lambda c: -degree[c])[:top_seeds]

    pair_activation: dict[frozenset, float] = defaultdict(float)

    for seed in seeds:
        activation: dict[str, float] = {seed: 1.0}
        for _ in range(steps):
            new_activation: dict[str, float] = {}
            for node, act in activation.items():
                nbrs = adj.get(node, [])
                if not nbrs:
                    continue
                spread = act * decay / len(nbrs)
                for nbr in nbrs:
                    new_activation[nbr] = new_activation.get(nbr, 0.0) + spread
            # accumulate
            for node, act in new_activation.items():
                activation[node] = activation.get(node, 0.0) + act
        # record (seed, reached) pairs
        for reached, act in activation.items():
            if reached == seed:
                continue
            if not reached.startswith("concept:"):
                continue
            pair = frozenset({seed, reached})
            if (seed, reached) in existing:
                continue
            pair_activation[pair] = max(pair_activation[pair], act)

    results = []
    for pair, act in pair_activation.items():
        a, b = sorted(pair)
        results.append(
            {
                "a": a,
                "b": b,
                "a_title": concepts.get(a, {}).get("title", a),
                "b_title": concepts.get(b, {}).get("title", b),
                "activation": round(act, 5),
            }
        )
    results.sort(key=lambda r: -r["activation"])
    return results


# ── Merge and rank all candidates ────────────────────────────────────────────

def merge_candidates(
    hebbian: list[dict],
    jaccard: list[dict],
    activation: list[dict],
    min_co: int,
    min_pmi: float,
    min_jaccard: float,
    min_activation: float,
) -> list[dict]:
    """
    Combine signals into a unified candidate list.
    Score = normalised sum of whichever signals fire above threshold.
    """
    scores: dict[frozenset, dict] = {}

    def key(a: str, b: str) -> frozenset:
        return frozenset({a, b})

    # Hebbian / PMI
    for r in hebbian:
        if r["co_citation"] < min_co or r["pmi"] < min_pmi:
            continue
        k = key(r["a"], r["b"])
        entry = scores.setdefault(k, {
            "a": r["a"], "b": r["b"],
            "a_title": r["a_title"], "b_title": r["b_title"],
            "signals": [], "score": 0.0,
        })
        entry["co_citation"] = r["co_citation"]
        entry["pmi"] = r["pmi"]
        entry["signals"].append(f"hebbian({r['co_citation']})")
        entry["score"] += r["co_citation"] * 0.4 + max(0.0, r["pmi"]) * 0.3

    # Jaccard
    for r in jaccard:
        if r["jaccard"] < min_jaccard:
            continue
        k = key(r["a"], r["b"])
        entry = scores.setdefault(k, {
            "a": r["a"], "b": r["b"],
            "a_title": r["a_title"], "b_title": r["b_title"],
            "signals": [], "score": 0.0,
        })
        entry["jaccard"] = r["jaccard"]
        entry["shared_neighbours"] = r["shared_neighbours"]
        entry["signals"].append(f"jaccard({r['jaccard']:.3f})")
        entry["score"] += r["jaccard"] * 5.0

    # Spreading activation
    for r in activation:
        if r["activation"] < min_activation:
            continue
        k = key(r["a"], r["b"])
        entry = scores.setdefault(k, {
            "a": r["a"], "b": r["b"],
            "a_title": r["a_title"], "b_title": r["b_title"],
            "signals": [], "score": 0.0,
        })
        entry["activation"] = r["activation"]
        entry["signals"].append(f"activation({r['activation']:.4f})")
        entry["score"] += r["activation"] * 2.0

    # keep only multi-signal candidates (confirmed by ≥ 2 independent theories)
    multi = [v for v in scores.values() if len(v["signals"]) >= 2]
    multi.sort(key=lambda r: -r["score"])
    return multi


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Propose missing concept links via graph learning theories.")
    parser.add_argument("--top", type=int, default=40, help="Max candidates to display")
    parser.add_argument("--min-co", type=int, default=2, help="Minimum co-citation count (Hebbian threshold)")
    parser.add_argument("--min-pmi", type=float, default=0.5, help="Minimum PMI score")
    parser.add_argument("--min-jaccard", type=float, default=0.15, help="Minimum Jaccard similarity")
    parser.add_argument("--min-activation", type=float, default=0.05, help="Minimum spreading activation score")
    parser.add_argument("--multi-only", action="store_true", default=True,
                        help="Only show candidates confirmed by ≥2 independent signals (default: on)")
    args = parser.parse_args()

    print("Loading graph …", file=sys.stderr)
    graph = load_graph()
    concepts = concept_nodes(graph)
    existing = existing_concept_edges(graph)
    s2c = source_to_concepts(graph)
    c2s = concept_to_sources(s2c)

    print(f"  {len(concepts)} concept nodes, {len(existing)//2} existing concept edges, "
          f"{len(s2c)} source→concept mappings", file=sys.stderr)

    print("Running Hebbian co-citation + PMI …", file=sys.stderr)
    heb = hebbian_and_pmi(concepts, s2c, c2s, existing)
    print(f"  {len(heb)} candidate pairs with co-citation ≥ 1", file=sys.stderr)

    print("Running Jaccard similarity …", file=sys.stderr)
    jac = jaccard_similarity(concepts, existing, graph)
    print(f"  {len(jac)} candidate pairs with Jaccard > 0", file=sys.stderr)

    print("Running spreading activation …", file=sys.stderr)
    act = spreading_activation(concepts, existing, graph)
    print(f"  {len(act)} candidate pairs with activation > 0", file=sys.stderr)

    print("Merging signals …", file=sys.stderr)
    candidates = merge_candidates(
        heb, jac, act,
        min_co=args.min_co,
        min_pmi=args.min_pmi,
        min_jaccard=args.min_jaccard,
        min_activation=args.min_activation,
    )

    top = candidates[:args.top]
    print(f"\n{'Rank':<5} {'Score':>6}  {'Signals':<40}  A  ↔  B")
    print("-" * 100)
    for i, c in enumerate(top, 1):
        sigs = " | ".join(c["signals"])
        print(f"{i:<5} {c['score']:>6.2f}  {sigs:<40}  "
              f"{c['a_title'][:35]:<35}  ↔  {c['b_title'][:35]}")
        if "shared_neighbours" in c:
            nbrs = [n.replace("concept:", "") for n in c["shared_neighbours"][:4]]
            print(f"       shared neighbours: {', '.join(nbrs)}")

    # save JSON
    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATES_PATH.write_text(
        json.dumps(
            {
                "total": len(candidates),
                "shown": len(top),
                "thresholds": {
                    "min_co_citation": args.min_co,
                    "min_pmi": args.min_pmi,
                    "min_jaccard": args.min_jaccard,
                    "min_activation": args.min_activation,
                },
                "candidates": candidates,
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"\nFull results saved → {CANDIDATES_PATH.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
