"""Tests for graph_community.py — community / bridge / gap audit."""

from __future__ import annotations

from kops import graph_community as gc


def _concept(cid: str) -> dict:
    return {"id": f"concept:{cid}", "kind": "concept", "title": cid}


def _related(a: str, b: str) -> list[dict]:
    # Related-Concepts links are bidirectional in the real graph.
    return [
        {"source": f"concept:{a}", "target": f"concept:{b}", "relation": "related_to"},
        {"source": f"concept:{b}", "target": f"concept:{a}", "relation": "related_to"},
    ]


def _cites(concept: str, src: str) -> dict:
    return {"source": f"concept:{concept}", "target": f"source:{src}", "relation": "cites_source"}


def _two_cluster_graph() -> dict:
    """Two triangles (A1-A2-A3, B1-B2-B3) joined by a single bridge edge A3-B1.

    A1 and B3 share source src-x but have no direct link (a gap across clusters).
    """
    nodes = [_concept(c) for c in ("A1", "A2", "A3", "B1", "B2", "B3")]
    nodes += [
        {"id": "source:src-x", "kind": "source", "title": "x"},
    ]
    edges: list[dict] = []
    for a, b in [("A1", "A2"), ("A2", "A3"), ("A1", "A3")]:
        edges += _related(a, b)
    for a, b in [("B1", "B2"), ("B2", "B3"), ("B1", "B3")]:
        edges += _related(a, b)
    edges += _related("A3", "B1")  # the bridge
    edges += [_cites("A1", "src-x"), _cites("B3", "src-x")]  # the gap-inducing shared source
    return {"project": "test", "nodes": nodes, "edges": edges}


def test_detects_two_communities():
    report = gc.community_audit(_two_cluster_graph())
    assert report["community_count"] == 2
    # each community should hold exactly one triangle
    sizes = sorted(c["size"] for c in report["communities"])
    assert sizes == [3, 3]


def test_modularity_positive_for_clustered_graph():
    report = gc.community_audit(_two_cluster_graph())
    assert report["modularity"] > 0.2


def test_bridge_nodes_are_the_connectors():
    # Two cross-cluster edges exist: A3-B1 (related link) and A1-B3 (shared source).
    # All four endpoints are bridges; the pure-internal nodes A2/B2 are not.
    report = gc.community_audit(_two_cluster_graph())
    bridge_ids = {b["id"] for b in report["bridges"]}
    assert bridge_ids == {"concept:A1", "concept:A3", "concept:B1", "concept:B3"}
    for b in report["bridges"]:
        assert b["cross_community_edges"] >= 1
    assert "concept:A2" not in bridge_ids
    assert "concept:B2" not in bridge_ids


def test_gap_detected_between_clusters_sharing_a_source():
    report = gc.community_audit(_two_cluster_graph())
    pairs = {frozenset((g["concept_a"]["id"], g["concept_b"]["id"])) for g in report["gaps"]}
    assert frozenset(("concept:A1", "concept:B3")) in pairs


def test_explicitly_linked_pair_is_not_a_gap():
    # A3 and B1 share no source but are linked; must never be reported as a gap.
    report = gc.community_audit(_two_cluster_graph())
    pairs = {frozenset((g["concept_a"]["id"], g["concept_b"]["id"])) for g in report["gaps"]}
    assert frozenset(("concept:A3", "concept:B1")) not in pairs


def test_empty_graph_is_safe():
    report = gc.community_audit({"project": "t", "nodes": [], "edges": []})
    assert report["concept_count"] == 0
    assert report["community_count"] == 0
    assert report["modularity"] == 0.0
    assert report["gaps"] == []


def test_disconnected_concepts_are_singleton_communities():
    nodes = [_concept("X"), _concept("Y")]
    report = gc.community_audit({"project": "t", "nodes": nodes, "edges": []})
    assert report["community_count"] == 2
