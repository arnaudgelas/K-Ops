"""Tests for retract_source.py — blast radius + frontmatter mutation."""

from __future__ import annotations

from kops import retract_source as rs


def _graph() -> dict:
    """src-bad backs claim c1 (in concept A, cited by A); answer Q1 updates A.

    Concept B / answer Q2 depend on a different source and must NOT be impacted.
    """
    nodes = [
        {"id": "source:src-bad", "kind": "source", "title": "bad source"},
        {"id": "source:src-ok", "kind": "source", "title": "ok source"},
        {"id": "claim:A-1", "kind": "claim", "title": "claim c1"},
        {"id": "claim:B-1", "kind": "claim", "title": "claim b1"},
        {"id": "concept:A", "kind": "concept", "title": "Concept A"},
        {"id": "concept:B", "kind": "concept", "title": "Concept B"},
        {"id": "answer:Q1", "kind": "answer", "title": "Answer Q1"},
        {"id": "answer:Q2", "kind": "answer", "title": "Answer Q2"},
    ]
    edges = [
        {"source": "claim:A-1", "target": "source:src-bad", "relation": "supported_by"},
        {"source": "claim:A-1", "target": "concept:A", "relation": "derived_from"},
        {"source": "concept:A", "target": "source:src-bad", "relation": "cites_source"},
        {"source": "answer:Q1", "target": "concept:A", "relation": "updates"},
        # Unrelated branch, backed by src-ok
        {"source": "claim:B-1", "target": "source:src-ok", "relation": "supported_by"},
        {"source": "claim:B-1", "target": "concept:B", "relation": "derived_from"},
        {"source": "answer:Q2", "target": "concept:B", "relation": "updates"},
    ]
    return {"project": "t", "nodes": nodes, "edges": edges}


def test_blast_radius_reaches_transitive_dependents():
    radius = rs.compute_blast_radius(_graph(), "src-bad")
    assert [c["id"] for c in radius["claims"]] == ["claim:A-1"]
    assert [c["id"] for c in radius["concepts"]] == ["concept:A"]
    assert [c["id"] for c in radius["answers"]] == ["answer:Q1"]
    assert radius["source_in_graph"] is True


def test_blast_radius_excludes_unrelated_branch():
    radius = rs.compute_blast_radius(_graph(), "src-bad")
    all_ids = {n["id"] for n in radius["claims"] + radius["concepts"] + radius["answers"]}
    assert "concept:B" not in all_ids
    assert "answer:Q2" not in all_ids
    assert "claim:B-1" not in all_ids


def test_answer_directly_citing_source_is_impacted():
    graph = {
        "project": "t",
        "nodes": [
            {"id": "source:src-x", "kind": "source", "title": "x"},
            {"id": "answer:Q", "kind": "answer", "title": "Q"},
        ],
        "edges": [{"source": "answer:Q", "target": "source:src-x", "relation": "mentions"}],
    }
    radius = rs.compute_blast_radius(graph, "src-x")
    assert [a["id"] for a in radius["answers"]] == ["answer:Q"]


def test_source_absent_from_graph_yields_empty_radius():
    radius = rs.compute_blast_radius(_graph(), "src-missing")
    assert radius["source_in_graph"] is False
    assert radius["claims"] == [] and radius["concepts"] == [] and radius["answers"] == []


# ── frontmatter mutation ────────────────────────────────────────────────


SOURCE_NOTE = "---\nsource_id: src-bad\nsource_status: active\ntitle: X\n---\n\n# Body\n\ntext\n"


def test_mark_source_retracted_sets_status_and_metadata():
    out = rs.mark_source_retracted(SOURCE_NOTE, "hallucinated", "revoked", "2026-07-12")
    assert "source_status: revoked" in out
    assert "retracted_at: '2026-07-12'" in out or "retracted_at: 2026-07-12" in out
    assert "retraction_reason: hallucinated" in out
    assert out.rstrip().endswith("text")  # body preserved


CONCEPT_NOTE = "---\ntitle: Concept A\nclaim_quality: supported\n---\n\n## Key Claims\n\n- x\n"


def test_flag_note_sets_revalidation_and_reports_change():
    out, changed = rs.flag_note_for_revalidation(CONCEPT_NOTE, "source src-bad retracted")
    assert changed is True
    assert "revalidation_required: true" in out
    assert "## Key Claims" in out  # body preserved


def test_flag_note_is_idempotent():
    once, _ = rs.flag_note_for_revalidation(CONCEPT_NOTE, "r")
    twice, changed = rs.flag_note_for_revalidation(once, "r")
    assert changed is False
    assert twice == once


def test_retract_rejects_non_blocking_status():
    import pytest

    with pytest.raises(ValueError):
        rs.retract("src-bad", "reason", status="active")
