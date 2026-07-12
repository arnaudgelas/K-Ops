"""Tests for review_queue.py — the aggregated human-review worklist."""

from __future__ import annotations

from kops import review_queue as rq


def test_failed_span_is_error_priority():
    spans = {"results": [{"claim_id": "clm-1", "concept": "C", "span_verification": "failed"}]}
    items = rq.assemble(spans, None, None, None, None, None)
    assert len(items) == 1
    assert items[0]["category"] == "failed-quote-span"
    assert items[0]["severity"] == "error"


def test_claim_admission_states_map_to_categories():
    claims = {
        "claims": [
            {
                "claim_id": "clm-b",
                "concept": "C",
                "admission_status": "blocked",
                "admission_reasons": ["source-status:revoked"],
            },
            {
                "claim_id": "clm-q",
                "concept": "C",
                "admission_status": "quarantine",
                "admission_reasons": ["evidence-strength:stub"],
            },
            {
                "claim_id": "clm-u",
                "concept": "C",
                "admission_status": "admitted",
                "evidence_status": "unsupported",
            },
        ]
    }
    items = rq.assemble(None, claims, None, None, None, None)
    cats = {it["category"] for it in items}
    assert cats == {"blocked-claim", "quarantined-claim", "unsupported-claim"}


def test_undocumented_contradiction_included():
    contradictions = {"contradictions": [{"id": "con-1", "concept": "C", "documented": False}]}
    items = rq.assemble(None, None, contradictions, None, None, None)
    assert items[0]["category"] == "undocumented-contradiction"


def test_documented_contradiction_excluded():
    contradictions = {"contradictions": [{"id": "con-1", "concept": "C", "documented": True}]}
    assert rq.assemble(None, None, contradictions, None, None, None) == []


def test_source_verification_and_adversarial_flags():
    sources = [
        {"source_id": "src-1", "verification_state": "needs_primary_sources"},
        {"source_id": "src-2", "adversarial_content": True},
        {"source_id": "src-3", "source_status": "active"},  # nothing to review
    ]
    items = rq.assemble(None, None, None, sources, None, None)
    cats = {it["category"] for it in items}
    assert cats == {"source-needs-verification", "adversarial-source"}


def test_unreviewed_probe_is_info():
    probes = [
        {"id": "p1", "concept": "C", "review_status": "unreviewed"},
        {"id": "p2", "concept": "C", "review_status": "approved"},
    ]
    items = rq.assemble(None, None, None, None, probes, None)
    assert len(items) == 1
    assert items[0]["severity"] == "info"


def test_community_gaps_and_fragile_clusters_surface():
    community = {
        "gaps": [
            {
                "concept_a": {"id": "concept:A", "title": "A"},
                "concept_b": {"id": "concept:B", "title": "B"},
                "shared_source_count": 2,
            }
        ],
        "fragile_communities": [
            {"community_id": 1, "size": 4, "sole_connector": {"id": "concept:H", "title": "H"}}
        ],
    }
    items = rq.assemble(None, None, None, None, None, community)
    cats = {it["category"] for it in items}
    assert cats == {"knowledge-gap", "fragile-cluster"}


def test_items_sorted_error_first():
    spans = {"results": [{"claim_id": "clm-1", "concept": "C", "span_verification": "failed"}]}
    probes = [{"id": "p1", "concept": "C", "review_status": "unreviewed"}]
    items = rq.assemble(spans, None, None, None, probes, None)
    assert [it["severity"] for it in items] == ["error", "info"]
