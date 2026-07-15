"""Tests for the canonical evidence objects and their store (task D1.1).

Pure and self-contained: every store test injects a tmp base dir so no real
vault is touched.
"""

from __future__ import annotations

import pytest

from kops.evidence_model import (
    EDGE_RELATIONS,
    SCHEMA_VERSION,
    AnswerMemo,
    AtomicClaim,
    ClaimEvidenceLink,
    ContextPackage,
    Source,
    SourceSpan,
    SourceVersion,
    ValidationEvent,
    content_hash,
    model_fingerprint,
    stable_id,
)
from kops.evidence_store import EvidenceStore

# --------------------------------------------------------------------------- #
# Fixtures modelled on the real registries
# --------------------------------------------------------------------------- #

SOURCE_FRONTMATTER = {
    "source_id": "src-1f2a3b4c5d",
    "title": "Agent Workflow Quick Reference Summary",
    "source_url": "notes/Runbooks/Agent_Workflow_Quick_Reference.md",
    "source_kind": "local-file",
    "evidence_strength": "strong",
    "source_status": "active",
    "ingested_at": "2026-06-14",
    "content_hash": "a" * 64,
    "tags": ["kb/source"],
}

CLAIM_REGISTRY_ENTRY = {
    "id": "clm-9548f97746",
    "claim_id": "clm-9548f97746",
    "claim_text": "The baseline workflow is ingest, compile, lint.",
    "concept": "Workflow_Pattern_Inventory",
    "claim_quality": "supported",
    "source_ids": ["src-1f2a3b4c5d"],
    "evidence_status": "direct",
    "admission_status": "admitted",
    "confidence": 0.8,
    "source_anchors": [
        {
            "source_id": "src-1f2a3b4c5d",
            "anchor": "L10-L12",
            "page": None,
            "section": "Workflow",
            "quote": "ingest then compile then lint",
            "line_start": 10,
            "line_end": 12,
            "segment_id": None,
            "commit": None,
            "extraction_confidence": 0.9,
            "path": None,
        }
    ],
}

MANIFEST_NODE = {
    "node_id": "seg-0007",
    "source_id": "src-deadbeef01",
    "title": "Methods",
    "start_char": 1200,
    "end_char": 1850,
    "page_start": 3,
    "page_end": 4,
    "anchor": "methods",
    "content_hash": "c0ffee1234",
}

ANSWER_FRONTMATTER = {
    "title": "What is the baseline workflow?",
    "asked_at": "2026-07-15T10:00:00",
    "query_class": "synthesis",
    "answer_quality": "durable",
    "scope": "private",
    "retrieval_path": ["bm25:concept"],
    "sources_consulted": ["src-1f2a3b4c5d"],
    "fetch_required": False,
}


# --------------------------------------------------------------------------- #
# schema_version present on every object
# --------------------------------------------------------------------------- #


def _all_objects() -> list:
    span = SourceSpan.from_anchor(CLAIM_REGISTRY_ENTRY["source_anchors"][0])
    return [
        Source.from_frontmatter(SOURCE_FRONTMATTER),
        SourceVersion(
            source_id="src-1f2a3b4c5d",
            content_hash="a" * 64,
            captured_at="2026-07-15T10:00:00",
            provenance="fetch",
        ),
        span,
        AtomicClaim.from_registry_dict(CLAIM_REGISTRY_ENTRY),
        ClaimEvidenceLink(claim_id="clm-9548f97746", source_id="src-1f2a3b4c5d", span=span),
        ValidationEvent(
            target_id="clm-9548f97746",
            target_type="atomic_claim",
            validator="entailment-judge",
            result="supported",
            occurred_at="2026-07-15T10:00:00",
        ),
        ContextPackage(question="q?", tier="standard"),
        AnswerMemo.from_frontmatter(ANSWER_FRONTMATTER),
    ]


def test_schema_version_present_on_all_objects():
    for obj in _all_objects():
        data = obj.to_dict()
        assert data["schema_version"] == SCHEMA_VERSION
        assert data["object_type"] == type(obj).OBJECT_TYPE


# --------------------------------------------------------------------------- #
# Round-trip serialization for each object
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("obj", _all_objects())
def test_round_trip_serialization(obj):
    cls = type(obj)
    restored = cls.from_dict(obj.to_dict())
    assert restored == obj
    # Serialization is idempotent.
    assert restored.to_dict() == obj.to_dict()


# --------------------------------------------------------------------------- #
# Building each object from its existing analog
# --------------------------------------------------------------------------- #


def test_source_from_frontmatter():
    src = Source.from_frontmatter(SOURCE_FRONTMATTER)
    assert src.source_id == "src-1f2a3b4c5d"
    assert src.tags == ("kb/source",)
    assert src.content_hash == "a" * 64


def test_source_from_registry_entry_alias():
    assert Source.from_registry_entry(SOURCE_FRONTMATTER) == Source.from_frontmatter(
        SOURCE_FRONTMATTER
    )


def test_atomic_claim_from_registry_keeps_clm_id_and_hashes_text():
    claim = AtomicClaim.from_registry_dict(CLAIM_REGISTRY_ENTRY)
    assert claim.claim_id == "clm-9548f97746"  # id format preserved
    assert claim.content_hash == content_hash(CLAIM_REGISTRY_ENTRY["claim_text"])
    assert len(claim.content_hash) == 64
    assert claim.spans[0].source_id == "src-1f2a3b4c5d"
    assert claim.spans[0].line_start == 10


def test_span_from_anchor_carries_exact_coordinates():
    span = SourceSpan.from_anchor(CLAIM_REGISTRY_ENTRY["source_anchors"][0])
    assert span.line_start == 10
    assert span.line_end == 12
    assert span.section == "Workflow"
    assert span.content_hash == content_hash("ingest then compile then lint")
    assert span.span_id.startswith("spn-")


def test_span_from_manifest_node_carries_char_and_page_coords():
    span = SourceSpan.from_manifest_node(MANIFEST_NODE)
    assert span.start_char == 1200
    assert span.end_char == 1850
    assert span.page_start == 3
    assert span.segment_id == "seg-0007"
    assert span.content_hash == "c0ffee1234"


def test_claim_evidence_link_extracted_from_claim():
    versions = {"src-1f2a3b4c5d": "srcv-abc1234567"}
    links = ClaimEvidenceLink.links_from_claim(CLAIM_REGISTRY_ENTRY, versions)
    assert len(links) == 1
    link = links[0]
    assert link.claim_id == "clm-9548f97746"
    assert link.source_id == "src-1f2a3b4c5d"
    assert link.evidence_status == "direct"
    assert link.source_version_id == "srcv-abc1234567"
    assert link.span is not None and link.span.line_start == 10
    assert link.relation == "supported_by"
    assert link.link_id.startswith("evl-")


def test_claim_evidence_link_rejects_unknown_relation():
    with pytest.raises(ValueError):
        ClaimEvidenceLink(claim_id="c", source_id="s", relation="not_a_relation")


def test_edge_vocabulary_matches_graph_relations():
    assert EDGE_RELATIONS == (
        "supported_by",
        "cites_source",
        "derived_from",
        "updates",
        "mentions",
    )


def test_answer_memo_from_frontmatter_links_context_package():
    memo = AnswerMemo.from_frontmatter(ANSWER_FRONTMATTER, context_package_hash="deadbeef")
    assert memo.title == ANSWER_FRONTMATTER["title"]
    assert memo.retrieval_path == ("bm25:concept",)
    assert memo.context_package_hash == "deadbeef"
    assert memo.memo_id.startswith("ans-")


# --------------------------------------------------------------------------- #
# Hashing convention + fingerprints
# --------------------------------------------------------------------------- #


def test_stable_id_is_deterministic_and_typed():
    a = stable_id("spn", "src-1", 10, 12)
    b = stable_id("spn", "src-1", 10, 12)
    assert a == b
    assert a.startswith("spn-")
    assert len(a.split("-", 1)[1]) == 10
    assert stable_id("spn", "src-1", 10, 13) != a


def test_content_hash_is_full_sha256():
    h = content_hash("hello")
    assert len(h) == 64
    assert h == content_hash("hello")


def test_model_fingerprint_matches_runner_algorithm():
    from kops.runners import _fingerprint

    fp = model_fingerprint("codex", ["codex", "exec"], "gpt", "prompt")
    assert fp == _fingerprint("codex", ["codex", "exec"], "gpt", "prompt")


# --------------------------------------------------------------------------- #
# ContextPackage hashing is stable / deterministic
# --------------------------------------------------------------------------- #


def test_context_package_hash_is_deterministic():
    span = SourceSpan.from_anchor(CLAIM_REGISTRY_ENTRY["source_anchors"][0])
    kwargs = dict(
        question="What is the workflow?",
        tier="standard",
        claim_ids=("clm-9548f97746",),
        spans=(span,),
        trust_states={"clm-9548f97746": "admitted"},
        source_version_ids=("srcv-abc1234567",),
        freshness={"stale": False},
        excluded_claims=({"claim_id": "clm-x", "reason": "blocked"},),
        retrieval_trace=("bm25",),
        policy_version="p1",
    )
    p1 = ContextPackage(built_at="2026-07-15T10:00:00", **kwargs)
    p2 = ContextPackage(built_at="2026-07-15T23:59:59", **kwargs)
    # built_at excluded from the hash: content-addressed, not time-addressed.
    assert p1.package_hash == p2.package_hash
    assert len(p1.package_hash) == 64


def test_context_package_hash_changes_with_content():
    base = ContextPackage(question="q", tier="standard", claim_ids=("a",))
    changed = ContextPackage(question="q", tier="standard", claim_ids=("a", "b"))
    assert base.package_hash != changed.package_hash


def test_context_package_to_dict_includes_hash():
    pkg = ContextPackage(question="q", tier="standard")
    assert pkg.to_dict()["package_hash"] == pkg.package_hash


# --------------------------------------------------------------------------- #
# SourceVersion immutability / append-only store
# --------------------------------------------------------------------------- #


def _store(tmp_path) -> EvidenceStore:
    return EvidenceStore(base_dir=tmp_path / "evidence", history_dir=tmp_path / "history")


def test_source_version_id_is_content_addressed():
    v1 = SourceVersion(
        source_id="src-1", content_hash="a" * 64, captured_at="t1", provenance="fetch"
    )
    v1b = SourceVersion(
        source_id="src-1", content_hash="a" * 64, captured_at="t2", provenance="refresh"
    )
    v2 = SourceVersion(
        source_id="src-1", content_hash="b" * 64, captured_at="t3", provenance="refresh"
    )
    assert v1.version_id == v1b.version_id  # same content -> same version id
    assert v1.version_id != v2.version_id  # changed content -> new version


def test_source_version_store_is_immutable_and_append_only(tmp_path):
    store = _store(tmp_path)
    v1 = SourceVersion(
        source_id="src-1", content_hash="a" * 64, captured_at="t1", provenance="fetch"
    )
    store.append_source_version(v1)

    # Re-appending the same content id with different metadata must NOT overwrite.
    v1_mutation = SourceVersion(
        source_id="src-1", content_hash="a" * 64, captured_at="t2", provenance="refresh"
    )
    returned = store.append_source_version(v1_mutation)
    assert returned.captured_at == "t1"  # original wins, immutable
    assert returned.provenance == "fetch"

    # A genuinely new version appends alongside the first (append-only history).
    v2 = SourceVersion(
        source_id="src-1", content_hash="b" * 64, captured_at="t3", provenance="refresh"
    )
    store.append_source_version(v2)

    history = store.source_versions("src-1")
    assert [v.content_hash for v in history] == ["a" * 64, "b" * 64]
    assert store.latest_source_version("src-1").content_hash == "b" * 64


# --------------------------------------------------------------------------- #
# ValidationEvent append-only store
# --------------------------------------------------------------------------- #


def test_validation_event_store_is_append_only(tmp_path):
    store = _store(tmp_path)
    e1 = ValidationEvent(
        target_id="clm-1",
        target_type="atomic_claim",
        validator="entailment-judge",
        result="unsupported",
        occurred_at="t1",
        prior_status=None,
        new_status="unsupported",
    )
    e2 = ValidationEvent(
        target_id="clm-1",
        target_type="atomic_claim",
        validator="entailment-judge",
        result="supported",
        occurred_at="t2",
        prior_status="unsupported",
        new_status="supported",
    )
    store.append_validation_event(e1)
    store.append_validation_event(e2)

    events = store.validation_events("clm-1")
    assert [e.result for e in events] == ["unsupported", "supported"]
    # Full audit trail retained; nothing overwritten.
    assert store.validation_events()[0].occurred_at == "t1"


def test_validation_event_carries_fingerprint_and_status_transition():
    fp = model_fingerprint("codex", ["codex"], "gpt", "judge prompt")
    event = ValidationEvent(
        target_id="clm-1",
        target_type="atomic_claim",
        target_version="v1",
        validator="entailment-judge",
        result="contradicted",
        occurred_at="t1",
        prior_status="supported",
        new_status="contradicted",
        fingerprint=fp,
        model="gpt",
        prompt_version="j1",
        policy_version="p1",
    )
    data = event.to_dict()
    assert data["fingerprint"] == fp
    assert data["prior_status"] == "supported"
    assert data["new_status"] == "contradicted"
    assert event.event_id.startswith("vev-")


# --------------------------------------------------------------------------- #
# ContextPackage store (content-addressed, idempotent)
# --------------------------------------------------------------------------- #


def test_context_package_store_round_trip(tmp_path):
    store = _store(tmp_path)
    pkg = ContextPackage(question="q", tier="standard", claim_ids=("clm-1",), policy_version="p1")
    digest = store.save_context_package(pkg)
    assert digest == pkg.package_hash
    loaded = store.load_context_package(digest)
    assert loaded == pkg
    # Idempotent re-save to the same content address.
    assert store.save_context_package(pkg) == digest
