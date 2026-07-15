"""Tests for kops.invalidation — automatic source-change invalidation (F2.1).

Builds a tmp mini-vault (one source, a dependent claim, a dependent answer),
changes the source's content hash, runs the cascade and asserts the full
contract: a new immutable SourceVersion is appended (the prior one survives),
dependent claim / answer targets get a stale ValidationEvent, both the claim and
contradiction registries are re-derived, the stale-set queue is written, and
curated prose is never rewritten.
"""

from __future__ import annotations

import json

import pytest

from kops import (
    claim_registry,
    contradiction_registry,
    content_drift,
    invalidation,
    retract_source,
)
from kops.evidence_model import SourceVersion
from kops.evidence_store import EvidenceStore
from kops.utils import parse_frontmatter

SOURCE_ID = "src-aaa0000001"
OLD_HASH = "0000000000oldbaseline"
NEW_HASH = "1111111111newcontent"

CONCEPT_STEM = "Widget_Perf"
ANSWER_STEM = "ans-widget"

_KEY_CLAIM = f"- Widget X sustains 2M ops/sec ([[Sources/{SOURCE_ID}|{SOURCE_ID}]])."

CONCEPT_NOTE = f"""---
title: Widget Performance
type: concept
claim_quality: conflicting
evidence_status: contested
created: '2026-01-01'
---

# Widget Performance

## Key Claims

{_KEY_CLAIM}

## Evidence / Source Basis

- Primary: [[Sources/{SOURCE_ID}|{SOURCE_ID}]].

## Related Concepts

## Open Questions

- Is the 2M ops/sec figure independently corroborated, or vendor-only?
"""

SOURCE_NOTE = f"""---
title: Widget benchmark
type: source-summary
source_id: {SOURCE_ID}
source_status: active
source_kind: official-doc
evidence_strength: primary-doc
content_hash: {OLD_HASH}
---

# Source Summary

## Summary

body
"""

ANSWER_NOTE = f"""---
title: How fast is Widget X?
type: answer
answer_quality: durable
asked_at: '2026-02-01'
---

# How fast is Widget X?

## Answer

Widget X sustains 2M ops/sec.

## Vault Updates

- [[Concepts/{CONCEPT_STEM}]]
"""


class _Cfg:
    def __init__(self, **kw: object) -> None:
        self.__dict__.update(kw)


def _graph() -> dict:
    """source -> claim -> concept -> answer dependency chain."""
    return {
        "project": "t",
        "nodes": [
            {"id": f"source:{SOURCE_ID}", "kind": "source", "title": "Widget benchmark"},
            {"id": f"claim:{CONCEPT_STEM}-01", "kind": "claim", "title": "Widget X 2M ops/sec"},
            {"id": f"concept:{CONCEPT_STEM}", "kind": "concept", "title": "Widget Performance"},
            {"id": f"answer:{ANSWER_STEM}", "kind": "answer", "title": "How fast is Widget X?"},
        ],
        "edges": [
            {
                "source": f"claim:{CONCEPT_STEM}-01",
                "target": f"source:{SOURCE_ID}",
                "relation": "supported_by",
            },
            {
                "source": f"claim:{CONCEPT_STEM}-01",
                "target": f"concept:{CONCEPT_STEM}",
                "relation": "derived_from",
            },
            {
                "source": f"concept:{CONCEPT_STEM}",
                "target": f"source:{SOURCE_ID}",
                "relation": "cites_source",
            },
            {
                "source": f"answer:{ANSWER_STEM}",
                "target": f"concept:{CONCEPT_STEM}",
                "relation": "updates",
            },
        ],
    }


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    """A tmp mini-vault with the registries + evidence store isolated to it."""
    concepts = tmp_path / "notes" / "Concepts"
    sources = tmp_path / "notes" / "Sources"
    answers = tmp_path / "notes" / "Answers"
    data = tmp_path / "data"
    for d in (concepts, sources, answers, data):
        d.mkdir(parents=True, exist_ok=True)

    (concepts / f"{CONCEPT_STEM}.md").write_text(CONCEPT_NOTE, encoding="utf-8")
    (sources / f"{SOURCE_ID}.md").write_text(SOURCE_NOTE, encoding="utf-8")
    (answers / f"{ANSWER_STEM}.md").write_text(ANSWER_NOTE, encoding="utf-8")

    cfg = _Cfg(
        project_name="t",
        concepts_dir=concepts,
        summaries_dir=sources,
        answers_dir=answers,
        indexes_dir=tmp_path / "notes" / "Indexes",
        outputs_dir=tmp_path / "outputs",
        raw_dir=tmp_path / "data" / "raw",
    )

    # Isolate every module that reads vault paths at module import time.
    monkeypatch.setattr(claim_registry, "CONFIG", cfg)
    monkeypatch.setattr(claim_registry, "ROOT", tmp_path)
    monkeypatch.setattr(claim_registry, "CLAIMS_PATH", data / "claims.json")
    monkeypatch.setattr(contradiction_registry, "CONFIG", cfg)
    monkeypatch.setattr(contradiction_registry, "ROOT", tmp_path)
    monkeypatch.setattr(contradiction_registry, "CONTRADICTIONS_PATH", data / "contradictions.json")
    monkeypatch.setattr(contradiction_registry, "_CLAIMS_PATH", data / "claims.json")
    monkeypatch.setattr(
        contradiction_registry,
        "_MAINTENANCE_CONTRADICTIONS_PATH",
        tmp_path / "notes" / "Maintenance" / "Contradictions.md",
    )
    monkeypatch.setattr(retract_source, "CONFIG", cfg)
    monkeypatch.setattr(retract_source, "ROOT", tmp_path)
    monkeypatch.setattr(invalidation, "ROOT", tmp_path)
    monkeypatch.setattr(invalidation, "INVALIDATION_QUEUE_PATH", data / "invalidation_queue.json")
    monkeypatch.setattr(invalidation, "find_source_note", lambda sid: sources / f"{sid}.md")

    store = EvidenceStore(base_dir=data / "evidence", history_dir=data / "history")
    # Seed the prior (old-hash) source version so we can prove it survives.
    store.append_source_version(
        SourceVersion(
            source_id=SOURCE_ID,
            content_hash=OLD_HASH,
            captured_at="2026-01-01",
            provenance="ingest",
        )
    )
    # Build the initial claims registry so dependent_claims can find the claim.
    claim_registry.run()

    return _Cfg(root=tmp_path, cfg=cfg, store=store, data=data, concepts=concepts)


def _invalidate(vault, **kw):
    return invalidation.invalidate_on_source_change(
        SOURCE_ID,
        old_hash=OLD_HASH,
        new_hash=NEW_HASH,
        graph=_graph(),
        store=vault.store,
        queue_path=vault.data / "invalidation_queue.json",
        flag=True,
        **kw,
    )


# --------------------------------------------------------------------------- #
# Dependency discovery (pure)
# --------------------------------------------------------------------------- #


def test_dependent_links_target_only_the_changed_source(vault):
    claims = claim_registry.load_claims()
    links = invalidation.dependent_links(SOURCE_ID, claims)
    assert links, "expected the widget claim to cite the source"
    assert all(link.source_id == SOURCE_ID for link in links)
    assert all(link.claim_id.startswith("clm-") for link in links)


# --------------------------------------------------------------------------- #
# Full cascade
# --------------------------------------------------------------------------- #


def test_new_source_version_appended_and_prior_survives(vault):
    _invalidate(vault)
    versions = vault.store.source_versions(SOURCE_ID)
    hashes = [v.content_hash for v in versions]
    assert OLD_HASH in hashes and NEW_HASH in hashes
    assert len(versions) == 2  # prior version was not overwritten


def test_dependent_claim_and_answer_flagged_for_revalidation(vault):
    report = _invalidate(vault)
    assert report["stale_claims"], "a dependent claim should be stale"
    assert f"answer:{ANSWER_STEM}" in report["stale_answers"]

    concept_fm, _ = parse_frontmatter(
        (vault.concepts / f"{CONCEPT_STEM}.md").read_text(encoding="utf-8")
    )
    answer_fm, _ = parse_frontmatter(
        (vault.root / "notes" / "Answers" / f"{ANSWER_STEM}.md").read_text(encoding="utf-8")
    )
    assert concept_fm.get("revalidation_required") is True
    assert answer_fm.get("revalidation_required") is True


def test_validation_event_emitted_per_target(vault):
    report = _invalidate(vault)
    version_id = report["version_id"]

    claim_id = report["stale_claims"][0]
    claim_events = [
        e for e in vault.store.validation_events(claim_id) if e.validator == "source_invalidation"
    ]
    assert claim_events, "expected a stale event on the dependent claim"
    ev = claim_events[0]
    assert ev.new_status == "stale"
    assert ev.target_version == version_id
    assert NEW_HASH[:7] in (ev.reason or "")
    assert ev.prior_status == "admitted"  # prior admission recorded on the event

    answer_events = [
        e
        for e in vault.store.validation_events(f"answer:{ANSWER_STEM}")
        if e.validator == "source_invalidation"
    ]
    assert answer_events and answer_events[0].new_status == "stale"


def test_claims_and_contradictions_both_rederived(vault):
    # Remove both registries so re-derivation must recreate them.
    (vault.data / "claims.json").unlink()
    (vault.data / "contradictions.json").unlink(missing_ok=True)

    _invalidate(vault)

    claims_payload = json.loads((vault.data / "claims.json").read_text(encoding="utf-8"))
    contra_payload = json.loads((vault.data / "contradictions.json").read_text(encoding="utf-8"))
    assert claims_payload["claims"], "claim registry should be re-derived"
    # The conflicting concept with an Open Questions bullet yields a documented record.
    assert contra_payload["contradictions"], "contradiction registry should be re-derived"
    assert any(c["documented"] for c in contra_payload["contradictions"])


def test_stale_set_queue_written_and_readable_by_serving_gate(vault):
    report = _invalidate(vault)
    queue_path = vault.data / "invalidation_queue.json"
    payload = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(payload["entries"]) == 1
    entry = payload["entries"][0]
    assert entry["source_id"] == SOURCE_ID
    assert entry["new_hash"] == NEW_HASH
    assert entry["status"] == "pending-review"

    # The deterministic read a serving gate uses to block stale outputs.
    targets = invalidation.stale_targets(queue_path)
    assert f"answer:{ANSWER_STEM}" in targets
    assert set(report["stale_claims"]).issubset(targets)


# --------------------------------------------------------------------------- #
# Dry run, idempotency, boundary
# --------------------------------------------------------------------------- #


def test_dry_run_writes_nothing(vault):
    report = _invalidate(vault, dry_run=True)
    assert report["dry_run"] is True
    assert report["source_version_appended"] is False
    # Only the seeded prior version exists; nothing new appended.
    assert [v.content_hash for v in vault.store.source_versions(SOURCE_ID)] == [OLD_HASH]
    assert not (vault.data / "invalidation_queue.json").exists()
    assert not vault.store.validation_events()


def test_idempotent_second_run_does_not_double_append(vault):
    _invalidate(vault)
    versions_after_first = len(vault.store.source_versions(SOURCE_ID))
    events_after_first = len(vault.store.validation_events())

    _invalidate(vault)  # second run, same content change
    assert len(vault.store.source_versions(SOURCE_ID)) == versions_after_first
    assert len(vault.store.validation_events()) == events_after_first  # no duplicate events

    payload = json.loads((vault.data / "invalidation_queue.json").read_text(encoding="utf-8"))
    assert len(payload["entries"]) == 1  # entry replaced in place, not duplicated


def test_curated_claim_prose_is_not_rewritten(vault):
    _, before_body = parse_frontmatter(
        (vault.concepts / f"{CONCEPT_STEM}.md").read_text(encoding="utf-8")
    )
    _invalidate(vault)
    _, after_body = parse_frontmatter(
        (vault.concepts / f"{CONCEPT_STEM}.md").read_text(encoding="utf-8")
    )
    assert before_body == after_body  # only frontmatter changed; Key Claims prose intact
    assert _KEY_CLAIM in after_body


# --------------------------------------------------------------------------- #
# run_invalidation trigger via content_drift
# --------------------------------------------------------------------------- #


def test_run_invalidation_detects_drift_and_cascades(vault, monkeypatch):
    monkeypatch.setattr(content_drift, "SOURCES_DIR", vault.root / "notes" / "Sources")
    monkeypatch.setattr(content_drift, "current_raw_hash", lambda sid: NEW_HASH)
    monkeypatch.setattr(invalidation, "_load_graph", _graph)

    summary = invalidation.run_invalidation(
        store=vault.store,
        queue_path=vault.data / "invalidation_queue.json",
        flag=True,
        fmt="json",
    )
    assert summary["drifted_sources"] == [SOURCE_ID]
    assert summary["invalidations"][0]["registries_recomputed"] is True
    assert NEW_HASH in [v.content_hash for v in vault.store.source_versions(SOURCE_ID)]
