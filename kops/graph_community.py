"""Community / bridge / gap audit over the concept knowledge graph.

Where ``graph_link_candidates.py`` predicts *pairwise* links (Hebbian/PMI/Jaccard/
spreading-activation) and ``vault_graph.graph_audit`` flags *local* antipatterns
(hub outliers), this module analyses the *global* structure of the concept graph:

- **Communities** — greedy-modularity (Louvain local-moving) clusters of concepts.
  Reproducible: deterministic node ordering, no randomness.
- **Cohesion** — the graph's modularity, plus each community's internal-weight
  fraction. A cluster held together loosely, or by a single source, is fragile.
- **Bridge nodes** — concepts with high betweenness centrality (Brandes). These are
  structural chokepoints: their staleness or revocation has outsized blast radius.
  This is the "weak high-centrality claims" audit item from design.md, at concept level.
- **Gaps** — pairs of concepts in *different* communities that share sources but carry
  no direct link ("surprising connections" / missing bridges), and communities held to
  the rest of the vault by a single connector (single points of failure).

The concept projection is an undirected weighted graph: concepts are joined by
``related_to`` links and by shared sources (two concepts citing the same source).

Pure Python, no third-party dependency. Writes ``data/graph/community_audit.json``.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict, deque

from kops.utils import ROOT, ensure_dir, save_json

COMMUNITY_AUDIT_PATH = ROOT / "data" / "graph" / "community_audit.json"

# Edge weight for an explicit Related-Concepts link vs. one shared source.
_RELATED_WEIGHT = 2.0
_SHARED_SOURCE_WEIGHT = 1.0
# A gap is only reported when two unlinked concepts share at least this many sources.
_DEFAULT_MIN_SHARED = 1


# ---------------------------------------------------------------------------
# Concept projection
# ---------------------------------------------------------------------------


def _concept_sources(graph: dict) -> dict[str, set[str]]:
    """Map each concept node id to the set of source node ids it draws on.

    Combines direct ``cites_source`` edges and claim ``supported_by`` edges
    (claim ``derived_from`` concept + claim ``supported_by`` source).
    """
    claim_concept: dict[str, str] = {}
    claim_sources: dict[str, set[str]] = defaultdict(set)
    concept_sources: dict[str, set[str]] = defaultdict(set)

    for edge in graph.get("edges", []):
        rel = edge.get("relation")
        src, tgt = edge.get("source"), edge.get("target")
        if rel == "cites_source" and str(src).startswith("concept:"):
            concept_sources[src].add(tgt)
        elif rel == "derived_from" and str(src).startswith("claim:"):
            claim_concept[src] = tgt
        elif rel == "has_claim" and str(tgt).startswith("claim:"):
            claim_concept[tgt] = src
        elif rel == "supported_by" and str(src).startswith("claim:"):
            claim_sources[src].add(tgt)

    for claim_id, concept_id in claim_concept.items():
        concept_sources[concept_id] |= claim_sources.get(claim_id, set())

    return concept_sources


def build_projection(
    graph: dict,
) -> tuple[list[str], dict[frozenset, float], dict[str, set[str]], set[frozenset]]:
    """Return (concept_ids, undirected weighted edges, concept->sources, explicit links).

    ``explicit_links`` holds only concept pairs joined by a Related-Concepts
    (``related_to``) wikilink — distinct from the weighted projection, which also
    joins concepts that merely share a source. Gap detection keys off the former.
    """
    concept_ids = sorted(n["id"] for n in graph.get("nodes", []) if n.get("kind") == "concept")
    concept_set = set(concept_ids)
    weights: dict[frozenset, float] = defaultdict(float)
    explicit_links: set[frozenset] = set()

    for edge in graph.get("edges", []):
        if edge.get("relation") != "related_to":
            continue
        a, b = edge.get("source"), edge.get("target")
        if a in concept_set and b in concept_set and a != b:
            weights[frozenset((a, b))] += _RELATED_WEIGHT / 2.0  # both directions present
            explicit_links.add(frozenset((a, b)))

    concept_sources = _concept_sources(graph)
    # Restrict to concepts that are actually nodes.
    concept_sources = {c: s for c, s in concept_sources.items() if c in concept_set}

    source_to_concepts: dict[str, set[str]] = defaultdict(set)
    for concept, sources in concept_sources.items():
        for source in sources:
            source_to_concepts[source].add(concept)
    for concepts in source_to_concepts.values():
        members = sorted(concepts)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                weights[frozenset((members[i], members[j]))] += _SHARED_SOURCE_WEIGHT

    return concept_ids, dict(weights), concept_sources, explicit_links


# ---------------------------------------------------------------------------
# Community detection (Louvain local-moving, single level, deterministic)
# ---------------------------------------------------------------------------


def detect_communities(nodes: list[str], weights: dict[frozenset, float]) -> dict[str, int]:
    """Assign each node a community id via greedy modularity optimisation."""
    adj: dict[str, dict[str, float]] = {n: {} for n in nodes}
    for pair, w in weights.items():
        a, b = tuple(pair)
        if a not in adj or b not in adj:
            continue
        adj[a][b] = adj[a].get(b, 0.0) + w
        adj[b][a] = adj[b].get(a, 0.0) + w

    k = {n: sum(adj[n].values()) for n in nodes}
    m2 = sum(k.values())  # 2m
    comm = {n: n for n in nodes}
    if m2 == 0:
        return _compact(comm, nodes)

    sigma_tot: dict[str, float] = {n: k[n] for n in nodes}
    for _pass in range(50):
        improved = False
        for n in sorted(nodes):
            c_old = comm[n]
            sigma_tot[c_old] -= k[n]
            neigh_comm: dict[str, float] = defaultdict(float)
            for nb, w in adj[n].items():
                neigh_comm[comm[nb]] += w

            best_c = c_old
            best_gain = neigh_comm.get(c_old, 0.0) - k[n] * sigma_tot.get(c_old, 0.0) / m2
            for c, w_in in sorted(neigh_comm.items()):
                if c == c_old:
                    continue
                gain = w_in - k[n] * sigma_tot.get(c, 0.0) / m2
                if gain > best_gain + 1e-12:
                    best_gain, best_c = gain, c

            comm[n] = best_c
            sigma_tot[best_c] = sigma_tot.get(best_c, 0.0) + k[n]
            if best_c != c_old:
                improved = True
        if not improved:
            break

    return _compact(comm, nodes)


def _compact(comm: dict[str, str], nodes: list[str]) -> dict[str, int]:
    """Relabel community representatives to 0..N-1, ordered by smallest member id."""
    groups: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        groups[comm[n]].append(n)
    ordered = sorted(groups.values(), key=lambda members: min(members))
    label: dict[str, int] = {}
    for idx, members in enumerate(ordered):
        for n in members:
            label[n] = idx
    return label


def modularity(nodes: list[str], weights: dict[frozenset, float], comm: dict[str, int]) -> float:
    """Newman modularity Q of the partition (global cohesion score)."""
    adj: dict[str, dict[str, float]] = {n: {} for n in nodes}
    for pair, w in weights.items():
        a, b = tuple(pair)
        if a in adj and b in adj:
            adj[a][b] = adj[a].get(b, 0.0) + w
            adj[b][a] = adj[b].get(a, 0.0) + w
    k = {n: sum(adj[n].values()) for n in nodes}
    m2 = sum(k.values())
    if m2 == 0:
        return 0.0
    m = m2 / 2.0
    l_in: dict[int, float] = defaultdict(float)
    deg: dict[int, float] = defaultdict(float)
    for pair, w in weights.items():
        a, b = tuple(pair)
        if a in comm and b in comm and comm[a] == comm[b]:
            l_in[comm[a]] += w
    for n in nodes:
        deg[comm[n]] += k[n]
    q = 0.0
    for c in deg:
        q += l_in.get(c, 0.0) / m - (deg[c] / m2) ** 2
    return round(q, 4)


# ---------------------------------------------------------------------------
# Betweenness centrality (Brandes, unweighted)
# ---------------------------------------------------------------------------


def betweenness(nodes: list[str], weights: dict[frozenset, float]) -> dict[str, float]:
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for pair in weights:
        a, b = tuple(pair)
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)

    cb: dict[str, float] = {n: 0.0 for n in nodes}
    for s in nodes:
        stack: list[str] = []
        preds: dict[str, list[str]] = {n: [] for n in nodes}
        sigma: dict[str, float] = {n: 0.0 for n in nodes}
        dist: dict[str, int] = {n: -1 for n in nodes}
        sigma[s] = 1.0
        dist[s] = 0
        queue: deque[str] = deque([s])
        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in sorted(adj[v]):
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    preds[w].append(v)
        delta: dict[str, float] = {n: 0.0 for n in nodes}
        while stack:
            w = stack.pop()
            for v in preds[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                cb[w] += delta[w]
    # Undirected: each shortest path counted twice.
    return {n: round(cb[n] / 2.0, 4) for n in nodes}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def community_audit(graph: dict, min_shared: int = _DEFAULT_MIN_SHARED, top: int = 10) -> dict:
    nodes, weights, concept_sources, explicit_links = build_projection(graph)
    title_of = {
        n["id"]: n.get("title") or n["id"]
        for n in graph.get("nodes", [])
        if n.get("kind") == "concept"
    }

    comm = detect_communities(nodes, weights)
    q = modularity(nodes, weights, comm)
    cb = betweenness(nodes, weights)

    adj: dict[str, dict[str, float]] = defaultdict(dict)
    for pair, w in weights.items():
        a, b = tuple(pair)
        adj[a][b] = w
        adj[b][a] = w

    members_by_comm: dict[int, list[str]] = defaultdict(list)
    for n in nodes:
        members_by_comm[comm[n]].append(n)

    # ── communities + cohesion ───────────────────────────────────────────
    communities: list[dict] = []
    for cid in sorted(members_by_comm):
        members = sorted(members_by_comm[cid])
        internal = external = 0.0
        for n in members:
            for nb, w in adj[n].items():
                if comm.get(nb) == cid:
                    internal += w
                else:
                    external += w
        internal /= 2.0  # counted from both endpoints inside the community
        total = internal + external
        source_sig: dict[str, int] = defaultdict(int)
        for n in members:
            for s in concept_sources.get(n, set()):
                source_sig[s] += 1
        communities.append(
            {
                "community_id": cid,
                "size": len(members),
                "members": [{"id": n, "title": title_of.get(n, n)} for n in members],
                "internal_cohesion": round(internal / total, 3) if total else None,
                "top_shared_sources": [
                    s
                    for s, _ in sorted(source_sig.items(), key=lambda kv: (-kv[1], kv[0]))
                    if source_sig[s] >= 2
                ][:5],
            }
        )

    # ── bridge nodes ─────────────────────────────────────────────────────
    bridges = []
    for n in sorted(nodes, key=lambda x: (-cb[x], x)):
        cross = sum(1 for nb in adj[n] if comm.get(nb) != comm[n])
        if cb[n] <= 0 and cross == 0:
            continue
        bridges.append(
            {
                "id": n,
                "title": title_of.get(n, n),
                "community_id": comm[n],
                "betweenness": cb[n],
                "cross_community_edges": cross,
            }
        )
    bridges = bridges[:top]

    # ── fragile communities (single point of contact to the rest) ────────
    fragile: list[dict] = []
    for cid, members in members_by_comm.items():
        if len(members) < 2:
            continue
        connectors = [n for n in members if any(comm.get(nb) != cid for nb in adj[n])]
        if len(connectors) == 1:
            n = connectors[0]
            fragile.append(
                {
                    "community_id": cid,
                    "size": len(members),
                    "sole_connector": {"id": n, "title": title_of.get(n, n)},
                }
            )

    # ── gaps: cross-community concept pairs sharing sources but unlinked ──
    gaps: list[dict] = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            if comm[a] == comm[b]:
                continue
            if frozenset((a, b)) in explicit_links:  # already editorially linked
                continue
            shared = concept_sources.get(a, set()) & concept_sources.get(b, set())
            if len(shared) >= min_shared:
                gaps.append(
                    {
                        "concept_a": {
                            "id": a,
                            "title": title_of.get(a, a),
                            "community_id": comm[a],
                        },
                        "concept_b": {
                            "id": b,
                            "title": title_of.get(b, b),
                            "community_id": comm[b],
                        },
                        "shared_sources": sorted(shared),
                        "shared_source_count": len(shared),
                    }
                )
    gaps.sort(key=lambda g: (-g["shared_source_count"], g["concept_a"]["id"], g["concept_b"]["id"]))
    gaps = gaps[:top]

    return {
        "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "concept_count": len(nodes),
        "edge_count": len(weights),
        "modularity": q,
        "community_count": len(members_by_comm),
        "communities": communities,
        "bridges": bridges,
        "fragile_communities": sorted(fragile, key=lambda f: f["community_id"]),
        "gaps": gaps,
    }


def run(min_shared: int = _DEFAULT_MIN_SHARED, dry_run: bool = False) -> dict:
    from kops.vault_graph import load_graph

    report = community_audit(load_graph(), min_shared=min_shared)
    if not dry_run:
        ensure_dir(COMMUNITY_AUDIT_PATH.parent)
        save_json(COMMUNITY_AUDIT_PATH, report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Community / bridge / gap audit of the concept graph."
    )
    parser.add_argument("--min-shared", type=int, default=_DEFAULT_MIN_SHARED)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = run(min_shared=args.min_shared, dry_run=args.dry_run)
    print(
        f"community audit: {report['community_count']} communities, "
        f"modularity={report['modularity']}, {len(report['bridges'])} bridge(s), "
        f"{len(report['gaps'])} gap(s) over {report['concept_count']} concept(s)"
    )


if __name__ == "__main__":
    main()
