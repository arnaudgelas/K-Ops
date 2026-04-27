from __future__ import annotations

import json
import math
import re
from collections import defaultdict, deque
from itertools import combinations
from pathlib import Path

from utils import CONFIG, ROOT
from vault_graph import (
    EVIDENCE_SECTION_RE,
    CONCEPT_LINK_RE,
    extract_section_links,
    load_graph,
    read_note,
)

# ── shared helpers ────────────────────────────────────────────────────────────

def _direct_concept_pairs(graph: dict) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for edge in graph["edges"]:
        if edge["relation"] == "related_to":
            s, t = edge["source"], edge["target"]
            if s.startswith("concept:") and t.startswith("concept:"):
                a = s.removeprefix("concept:")
                b = t.removeprefix("concept:")
                pairs.add((min(a, b), max(a, b)))
    return pairs


def _concept_stems(graph: dict) -> set[str]:
    return {n["id"].removeprefix("concept:") for n in graph["nodes"] if n["kind"] == "concept"}


def _wikilink_label(stem: str) -> str:
    return stem.replace("_", " ")


def _concept_adjacency(graph: dict) -> dict[str, set[str]]:
    """Undirected adjacency list over related_to edges between concept nodes."""
    adj: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        if edge["relation"] != "related_to":
            continue
        s, t = edge["source"], edge["target"]
        if s.startswith("concept:") and t.startswith("concept:"):
            a = s.removeprefix("concept:")
            b = t.removeprefix("concept:")
            adj[a].add(b)
            adj[b].add(a)
    return adj


def _bfs_distances(adj: dict[str, set[str]], source: str, max_depth: int = 3) -> dict[str, int]:
    """BFS from source; returns {node: distance} for distance <= max_depth."""
    dist: dict[str, int] = {source: 0}
    q: deque[str] = deque([source])
    while q:
        node = q.popleft()
        d = dist[node]
        if d >= max_depth:
            continue
        for nb in adj.get(node, ()):
            if nb not in dist:
                dist[nb] = d + 1
                q.append(nb)
    return dist


# ── approach 1: co-citation ───────────────────────────────────────────────────

def suggest_by_co_citation(graph: dict, min_score: int = 2, limit: int = 50) -> list[dict]:
    """
    Co-citation score(A, B) = # pages that link to both.
    Pairs above min_score without an existing related_to edge are returned.
    """
    existing = _direct_concept_pairs(graph)
    valid_stems = _concept_stems(graph)

    page_links: dict[str, set[str]] = {}
    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        _, body = read_note(path)
        links = set(CONCEPT_LINK_RE.findall(body)) & valid_stems
        links.discard(path.stem)
        page_links[path.stem] = links

    co_cite: dict[tuple[str, str], int] = defaultdict(int)
    for links in page_links.values():
        for a, b in combinations(sorted(links), 2):
            co_cite[(min(a, b), max(a, b))] += 1

    results = []
    for (a, b), score in sorted(co_cite.items(), key=lambda x: -x[1]):
        if score < min_score:
            break
        if (a, b) in existing:
            continue
        results.append({
            "approach": "co-citation",
            "concept_a": a,
            "concept_b": b,
            "score": score,
            "reason": f"co-cited in {score} page(s)",
        })
        if len(results) >= limit:
            break
    return results


# ── approach 2: shared-source clustering ─────────────────────────────────────

def suggest_by_shared_sources(graph: dict, min_shared: int = 2, limit: int = 50) -> list[dict]:
    """Pair score = # source summaries cited by both. Excludes already-linked pairs."""
    existing = _direct_concept_pairs(graph)

    concept_sources: dict[str, set[str]] = {}
    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        _, body = read_note(path)
        sources = set(extract_section_links(body, EVIDENCE_SECTION_RE))
        if sources:
            concept_sources[path.stem] = sources

    results = []
    stems = sorted(concept_sources)
    for i, a in enumerate(stems):
        for b in stems[i + 1:]:
            shared = concept_sources[a] & concept_sources[b]
            n = len(shared)
            if n < min_shared:
                continue
            key = (min(a, b), max(a, b))
            if key in existing:
                continue
            sample = sorted(shared)[:3]
            ellipsis = "..." if n > 3 else ""
            results.append({
                "approach": "shared-sources",
                "concept_a": key[0],
                "concept_b": key[1],
                "score": n,
                "shared_sources": sorted(shared),
                "reason": f"share {n} source(s): {', '.join(sample)}{ellipsis}",
            })

    results.sort(key=lambda x: -x["score"])
    return results[:limit]


# ── approach 3: vector similarity ────────────────────────────────────────────

def _tfidf_vectors(docs: list[str]) -> tuple[list[list[float]], str]:
    tokenize = lambda s: re.findall(r"[a-z]{3,}", s.lower())
    token_docs = [tokenize(d) for d in docs]
    N = len(docs)
    df: dict[str, int] = defaultdict(int)
    for tokens in token_docs:
        for t in set(tokens):
            df[t] += 1
    vocab = sorted(df)
    idf = {t: math.log((N + 1) / (df[t] + 1)) + 1 for t in vocab}
    idx = {t: i for i, t in enumerate(vocab)}
    vectors = []
    for tokens in token_docs:
        tf: dict[str, int] = defaultdict(int)
        for t in tokens:
            if t in idx:
                tf[t] += 1
        vec = [0.0] * len(vocab)
        total = max(len(tokens), 1)
        for t, count in tf.items():
            vec[idx[t]] = (count / total) * idf[t]
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        vectors.append(vec)
    return vectors, "tfidf"


def _neural_vectors(texts: list[str]) -> tuple[list[list[float]], str] | None:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        model = SentenceTransformer("all-MiniLM-L6-v2")
        vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vecs.tolist(), "sentence-transformers/all-MiniLM-L6-v2"
    except ImportError:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def suggest_by_embedding(graph: dict, threshold: float = 0.75, limit: int = 50) -> list[dict]:
    """
    Cosine similarity of concept text vectors (neural if available, TF-IDF fallback).
    Pairs above threshold without an existing edge are returned.
    """
    existing = _direct_concept_pairs(graph)
    concept_nodes = [n for n in graph["nodes"] if n["kind"] == "concept"]
    stems = [n["id"].removeprefix("concept:") for n in concept_nodes]
    texts = [n.get("search_text") or n["title"] for n in concept_nodes]

    result = _neural_vectors(texts)
    vectors, method = result if result is not None else _tfidf_vectors(texts)

    candidates = []
    for i in range(len(stems)):
        for j in range(i + 1, len(stems)):
            sim = _cosine(vectors[i], vectors[j])
            if sim < threshold:
                continue
            key = (min(stems[i], stems[j]), max(stems[i], stems[j]))
            if key in existing:
                continue
            candidates.append({
                "approach": f"embedding({method})",
                "concept_a": key[0],
                "concept_b": key[1],
                "score": round(sim, 4),
                "reason": f"vector similarity {sim:.3f} via {method}",
            })

    candidates.sort(key=lambda x: -x["score"])
    return candidates[:limit]


# ── approach 4: conceptual gravity ───────────────────────────────────────────

def suggest_by_conceptual_gravity(graph: dict, min_score: float = 0.5, limit: int = 50) -> list[dict]:
    """
    Gravitational attraction between A and B = (deg_A × deg_B) / dist(A,B)².
    Only considers pairs at graph distance 2 or 3 (not already linked).
    High-degree nodes with a short but non-direct path are strong candidates.
    """
    existing = _direct_concept_pairs(graph)
    adj = _concept_adjacency(graph)
    stems = list(_concept_stems(graph))
    degree = {s: len(adj.get(s, set())) for s in stems}

    candidates: dict[tuple[str, str], float] = {}
    for stem in stems:
        dists = _bfs_distances(adj, stem, max_depth=3)
        for other, d in dists.items():
            if d < 2:
                continue
            key = (min(stem, other), max(stem, other))
            if key in existing or key in candidates:
                continue
            g = (degree[stem] * degree.get(other, 0)) / (d * d)
            candidates[key] = g

    results = []
    for (a, b), score in sorted(candidates.items(), key=lambda x: -x[1]):
        if score < min_score:
            break
        results.append({
            "approach": "conceptual-gravity",
            "concept_a": a,
            "concept_b": b,
            "score": round(score, 3),
            "reason": f"gravity {score:.2f} (deg {degree[a]}×{degree[b]}, path ≥2)",
        })
        if len(results) >= limit:
            break
    return results


# ── approach 5: structural equivalence / analogical mapping ──────────────────

def suggest_by_analogical_mapping(graph: dict, min_jaccard: float = 0.25, limit: int = 50) -> list[dict]:
    """
    Jaccard similarity of neighbor sets: nodes playing the same structural role
    in the graph are "analogues" of each other and are good link candidates.
    High Jaccard + no direct link = structural gap.
    """
    existing = _direct_concept_pairs(graph)
    adj = _concept_adjacency(graph)
    stems = sorted(adj.keys())

    results = []
    for i, a in enumerate(stems):
        na = adj[a]
        if not na:
            continue
        for b in stems[i + 1:]:
            nb = adj[b]
            if not nb:
                continue
            key = (min(a, b), max(a, b))
            if key in existing:
                continue
            inter = len(na & nb)
            union = len(na | nb)
            if union == 0:
                continue
            j = inter / union
            if j < min_jaccard:
                continue
            shared_sample = sorted(na & nb)[:3]
            results.append({
                "approach": "analogical-mapping",
                "concept_a": key[0],
                "concept_b": key[1],
                "score": round(j, 4),
                "shared_neighbors": sorted(na & nb),
                "reason": f"Jaccard neighbor overlap {j:.3f}; share neighbours: {', '.join(shared_sample)}{'...' if len(na & nb) > 3 else ''}",
            })

    results.sort(key=lambda x: -x["score"])
    return results[:limit]


# ── approach 6: triadic closure ───────────────────────────────────────────────

def suggest_by_triadic_closure(graph: dict, min_common: int = 2, limit: int = 50) -> list[dict]:
    """
    Classic graph-theory: if A–B and B–C exist but not A–C, close the triangle.
    Score = number of distinct common neighbours (Adamic-Adar variant: count paths).
    Pairs with min_common shared neighbours and no direct link are returned.
    """
    existing = _direct_concept_pairs(graph)
    adj = _concept_adjacency(graph)

    common_nb: dict[tuple[str, str], set[str]] = defaultdict(set)
    for bridge, neighbours in adj.items():
        nb_list = sorted(neighbours)
        for a, b in combinations(nb_list, 2):
            key = (min(a, b), max(a, b))
            if key not in existing:
                common_nb[key].add(bridge)

    results = []
    for (a, b), bridges in sorted(common_nb.items(), key=lambda x: -len(x[1])):
        n = len(bridges)
        if n < min_common:
            break
        sample = sorted(bridges)[:3]
        results.append({
            "approach": "triadic-closure",
            "concept_a": a,
            "concept_b": b,
            "score": n,
            "bridge_nodes": sorted(bridges),
            "reason": f"{n} common neighbour(s): {', '.join(sample)}{'...' if n > 3 else ''}",
        })
        if len(results) >= limit:
            break
    return results


# ── approach 7: eigenvector centrality ───────────────────────────────────────

def _eigenvector_centrality(adj: dict[str, set[str]], max_iter: int = 200, tol: float = 1e-6) -> dict[str, float]:
    nodes = list(adj.keys())
    n = len(nodes)
    if n == 0:
        return {}
    vec = {v: 1.0 / n for v in nodes}
    for _ in range(max_iter):
        nv: dict[str, float] = {v: sum(vec.get(u, 0.0) for u in adj[v]) for v in nodes}
        norm = math.sqrt(sum(x * x for x in nv.values())) or 1.0
        nv = {v: x / norm for v, x in nv.items()}
        if sum(abs(nv[v] - vec[v]) for v in nodes) < tol:
            vec = nv
            break
        vec = nv
    return vec


def suggest_by_eigenvector_centrality(graph: dict, top_frac: float = 0.33, limit: int = 50) -> list[dict]:
    """
    Compute eigenvector centrality over the concept related_to graph.
    High-centrality nodes that are NOT directly linked represent structural gaps
    in the most influential part of the knowledge graph.
    Score = centrality_A × centrality_B (product of hub influence).
    """
    existing = _direct_concept_pairs(graph)
    adj = _concept_adjacency(graph)
    ev = _eigenvector_centrality(adj)
    if not ev:
        return []

    # Keep only top fraction by centrality
    threshold = sorted(ev.values(), reverse=True)[max(1, int(len(ev) * top_frac)) - 1]
    hubs = sorted([s for s, c in ev.items() if c >= threshold])

    results = []
    for i, a in enumerate(hubs):
        for b in hubs[i + 1:]:
            key = (min(a, b), max(a, b))
            if key in existing:
                continue
            score = ev[a] * ev[b]
            results.append({
                "approach": "eigenvector-centrality",
                "concept_a": key[0],
                "concept_b": key[1],
                "score": round(score, 6),
                "centralities": {key[0]: round(ev[key[0]], 4), key[1]: round(ev[key[1]], 4)},
                "reason": f"both high-centrality hubs (eig {ev[a]:.3f}×{ev[b]:.3f}={score:.4f})",
            })

    results.sort(key=lambda x: -x["score"])
    return results[:limit]


# ── approach 8: friction linking ─────────────────────────────────────────────

_CONTRAST_RE = re.compile(
    r"\b(in contrast|unlike|however|whereas|on the other hand|alternatively|"
    r"but (?:not|unlike|instead)|differs? from|as opposed to|instead of)\b",
    re.IGNORECASE,
)

def suggest_by_friction(graph: dict, min_friction: float = 0.15, limit: int = 50) -> list[dict]:
    """
    Friction pairs: high semantic similarity (same topic domain) but low shared-source
    overlap (different bodies of evidence) — they discuss the same space from divergent angles.
    Also amplified when one page's body explicitly uses contrast language near a mention
    of the other concept.

    Friction score = tfidf_sim × (1 − source_jaccard).
    """
    existing = _direct_concept_pairs(graph)
    concept_nodes = [n for n in graph["nodes"] if n["kind"] == "concept"]
    stems = [n["id"].removeprefix("concept:") for n in concept_nodes]
    texts = [n.get("search_text") or n["title"] for n in concept_nodes]

    vectors, _ = _tfidf_vectors(texts)

    # Source sets per concept
    concept_sources: dict[str, set[str]] = {}
    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        _, body = read_note(path)
        sources = set(extract_section_links(body, EVIDENCE_SECTION_RE))
        concept_sources[path.stem] = sources

    # Explicit contrast-language bonus: does page A mention B near a contrast phrase?
    contrast_pairs: set[tuple[str, str]] = set()
    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        _, body = read_note(path)
        # Find all concept links on the same line as contrast language
        for line in body.splitlines():
            if _CONTRAST_RE.search(line):
                for linked in CONCEPT_LINK_RE.findall(line):
                    if linked != path.stem:
                        key = (min(path.stem, linked), max(path.stem, linked))
                        contrast_pairs.add(key)

    results = []
    for i in range(len(stems)):
        for j in range(i + 1, len(stems)):
            key = (min(stems[i], stems[j]), max(stems[i], stems[j]))
            if key in existing:
                continue
            sim = _cosine(vectors[i], vectors[j])
            sa = concept_sources.get(stems[i], set())
            sb = concept_sources.get(stems[j], set())
            union = len(sa | sb)
            src_jaccard = len(sa & sb) / union if union else 0.0
            friction = sim * (1.0 - src_jaccard)
            contrast_bonus = 0.1 if key in contrast_pairs else 0.0
            total = friction + contrast_bonus
            if total < min_friction:
                continue
            detail = "contrast language detected; " if key in contrast_pairs else ""
            results.append({
                "approach": "friction",
                "concept_a": key[0],
                "concept_b": key[1],
                "score": round(total, 4),
                "tfidf_sim": round(sim, 4),
                "source_jaccard": round(src_jaccard, 4),
                "reason": f"{detail}friction {total:.3f} (sim {sim:.3f}, src overlap {src_jaccard:.3f})",
            })

    results.sort(key=lambda x: -x["score"])
    return results[:limit]


# ── approach 9: contradiction mapping ────────────────────────────────────────

_OPEN_QUESTIONS_RE = re.compile(r"## Open Questions\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_CONTRADICTIONS_PATH = ROOT / "data" / "contradictions.json"


def suggest_by_contradiction_mapping(graph: dict, limit: int = 50) -> list[dict]:
    """
    Two sub-signals:

    1. Shared-tension: concept pages that share the same source evidence AND both
       have conflicting/open-question entries in the contradiction registry →
       they dispute overlapping territory; link them explicitly.

    2. Cross-reference in Open Questions: a concept page's Open Questions section
       links to another concept → that citation signals unresolved tension and
       warrants an explicit (possibly "contradicts") edge.
    """
    existing = _direct_concept_pairs(graph)

    valid_stems = _concept_stems(graph)

    # Load contradiction registry — only keep records for concepts that have actual pages
    ctr_by_concept: dict[str, list[dict]] = defaultdict(list)
    if _CONTRADICTIONS_PATH.exists():
        try:
            payload = json.loads(_CONTRADICTIONS_PATH.read_text(encoding="utf-8"))
            for rec in payload.get("contradictions", []):
                stem = rec["concept"]
                if stem in valid_stems:
                    ctr_by_concept[stem].append(rec)
        except (json.JSONDecodeError, OSError):
            pass

    results: list[dict] = []
    seen: set[tuple[str, str]] = set()

    # Signal 1: shared contradiction sources
    ctr_concepts = sorted(ctr_by_concept.keys())
    for i, a in enumerate(ctr_concepts):
        sources_a = {sid for rec in ctr_by_concept[a] for sid in rec.get("source_ids", [])}
        for b in ctr_concepts[i + 1:]:
            sources_b = {sid for rec in ctr_by_concept[b] for sid in rec.get("source_ids", [])}
            shared = sources_a & sources_b
            if not shared:
                continue
            key = (min(a, b), max(a, b))
            if key in existing or key in seen:
                continue
            seen.add(key)
            results.append({
                "approach": "contradiction-mapping",
                "concept_a": key[0],
                "concept_b": key[1],
                "score": len(shared),
                "shared_contradiction_sources": sorted(shared)[:5],
                "reason": f"both have conflicting claims citing {len(shared)} shared source(s)",
                "link_type": "tension",
            })

    # Signal 2: Open Questions cross-references
    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        _, body = read_note(path)
        m = _OPEN_QUESTIONS_RE.search(body)
        if not m:
            continue
        oq_text = m.group(1)
        for linked in CONCEPT_LINK_RE.findall(oq_text):
            if linked not in valid_stems or linked == path.stem:
                continue
            key = (min(path.stem, linked), max(path.stem, linked))
            if key in existing or key in seen:
                continue
            seen.add(key)
            results.append({
                "approach": "contradiction-mapping",
                "concept_a": key[0],
                "concept_b": key[1],
                "score": 1,
                "reason": f"{path.stem} cites {linked} in Open Questions (unresolved tension)",
                "link_type": "tension",
            })

    results.sort(key=lambda x: -x["score"])
    return results[:limit]


# ── merge & output ────────────────────────────────────────────────────────────

ALL_APPROACHES = {
    "co-citation",
    "shared-sources",
    "embedding",
    "conceptual-gravity",
    "analogical-mapping",
    "triadic-closure",
    "eigenvector-centrality",
    "friction",
    "contradiction-mapping",
}


def run_suggest_links(
    approach: str = "all",
    min_co_cite: int = 2,
    min_shared: int = 2,
    emb_threshold: float = 0.75,
    min_gravity: float = 0.5,
    min_jaccard: float = 0.25,
    min_triadic: int = 2,
    ev_top_frac: float = 0.33,
    min_friction: float = 0.15,
    limit: int = 50,
) -> dict:
    """
    Run one or all suggestion approaches and merge into a ranked candidate list.
    Multi-signal pairs (confirmed by ≥2 independent methods) are ranked first.
    """
    graph = load_graph()
    active = ALL_APPROACHES if approach == "all" else {approach}

    rows: list[dict] = []
    if "co-citation" in active:
        rows.extend(suggest_by_co_citation(graph, min_score=min_co_cite, limit=limit))
    if "shared-sources" in active:
        rows.extend(suggest_by_shared_sources(graph, min_shared=min_shared, limit=limit))
    if "embedding" in active:
        rows.extend(suggest_by_embedding(graph, threshold=emb_threshold, limit=limit))
    if "conceptual-gravity" in active:
        rows.extend(suggest_by_conceptual_gravity(graph, min_score=min_gravity, limit=limit))
    if "analogical-mapping" in active:
        rows.extend(suggest_by_analogical_mapping(graph, min_jaccard=min_jaccard, limit=limit))
    if "triadic-closure" in active:
        rows.extend(suggest_by_triadic_closure(graph, min_common=min_triadic, limit=limit))
    if "eigenvector-centrality" in active:
        rows.extend(suggest_by_eigenvector_centrality(graph, top_frac=ev_top_frac, limit=limit))
    if "friction" in active:
        rows.extend(suggest_by_friction(graph, min_friction=min_friction, limit=limit))
    if "contradiction-mapping" in active:
        rows.extend(suggest_by_contradiction_mapping(graph, limit=limit))

    # Merge by canonical (a, b) pair; contradictions get a separate link_type tag
    merged: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        key = (min(r["concept_a"], r["concept_b"]), max(r["concept_a"], r["concept_b"]))
        merged[key].append(r)

    candidates = []
    for (a, b), signals in sorted(merged.items(), key=lambda x: (-len(x[1]), -max(s["score"] for s in x[1]))):
        link_types = list({s.get("link_type", "related") for s in signals})
        candidates.append({
            "concept_a": a,
            "concept_b": b,
            "signals": len(signals),
            "link_types": link_types,
            "approaches": [s["approach"] for s in signals],
            "scores": {s["approach"]: s["score"] for s in signals},
            "reasons": [s["reason"] for s in signals],
            "wikilink_in_a": f"[[Concepts/{b}|{_wikilink_label(b)}]]",
            "wikilink_in_b": f"[[Concepts/{a}|{_wikilink_label(a)}]]",
        })

    return {"total_candidates": len(candidates), "candidates": candidates[:limit]}
