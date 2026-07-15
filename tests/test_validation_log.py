"""Tests for the immutable validation-event ledger (F2.2)."""

from __future__ import annotations

import pytest

from kops.evidence_store import EvidenceStore
from kops.validation_log import (
    CONSEQUENCE_GATE,
    ENTAILMENT_JUDGE,
    TARGET_ANSWER,
    TARGET_CLAIM,
    VocabularyError,
    events_for,
    latest_status,
    record_event,
    serving_audit,
)


@pytest.fixture
def store(tmp_path):
    """An EvidenceStore isolated to a temp dir so tests never touch data/history/."""
    return EvidenceStore(base_dir=tmp_path / "evidence", history_dir=tmp_path / "history")


def test_record_event_appends_immutable_event(store):
    event = record_event(
        store,
        target_id="claim-1",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="supported",
        reason="span fully supports claim",
    )
    assert event.validator == ENTAILMENT_JUDGE
    assert event.result == "supported"
    assert event.occurred_at  # stamped
    assert event.event_id.startswith("vev-")

    stored = store.validation_events(target_id="claim-1")
    assert len(stored) == 1
    assert stored[0].to_dict() == event.to_dict()


def test_identical_logical_event_still_appends_with_deterministic_id(store):
    kwargs = dict(
        target_id="claim-1",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="supported",
        target_version="hash-abc",
        fingerprint="fp-1",
    )
    first = record_event(store, **kwargs)
    # Force identical occurred_at so the two events are logically identical.
    kwargs_same = dict(kwargs)
    second = store.append_validation_event(
        first.__class__(occurred_at=first.occurred_at, **kwargs_same)
    )

    events = store.validation_events(target_id="claim-1")
    assert len(events) == 2  # append-only, not dedup
    assert first.event_id == second.event_id  # deterministic id for identical content


def test_unknown_validator_raises(store):
    with pytest.raises(VocabularyError):
        record_event(
            store,
            target_id="x",
            target_type=TARGET_CLAIM,
            validator="made_up_validator",
            result="supported",
        )


def test_unknown_result_raises(store):
    with pytest.raises(VocabularyError):
        record_event(
            store,
            target_id="x",
            target_type=TARGET_CLAIM,
            validator=ENTAILMENT_JUDGE,
            result="totally_fine",  # not in the entailment vocabulary
        )


def test_events_for_is_ordered(store):
    record_event(
        store,
        target_id="claim-1",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="partial",
    )
    record_event(
        store,
        target_id="other",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="supported",
    )
    record_event(
        store,
        target_id="claim-1",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="supported",
    )

    trail = events_for(store, "claim-1")
    assert [e.result for e in trail] == ["partial", "supported"]  # append order preserved
    assert all(e.target_id == "claim-1" for e in trail)


def test_latest_status(store):
    record_event(
        store,
        target_id="claim-1",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="partial",
    )
    record_event(
        store,
        target_id="claim-1",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="supported",
    )
    record_event(
        store,
        target_id="claim-1",
        target_type=TARGET_ANSWER,
        validator=CONSEQUENCE_GATE,
        result="allowed",
    )

    assert latest_status(store, "claim-1") == "allowed"
    assert latest_status(store, "claim-1", validator=ENTAILMENT_JUDGE) == "supported"
    assert latest_status(store, "claim-1", validator=CONSEQUENCE_GATE) == "allowed"
    assert latest_status(store, "missing") is None


def test_serving_audit_reconstructs_answer_record(store):
    # Two supporting claims judged.
    record_event(
        store,
        target_id="claim-a",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="supported",
    )
    record_event(
        store,
        target_id="claim-b",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="partial",
    )
    # The answer-level consequence-gate ruling.
    record_event(
        store,
        target_id="answer-1",
        target_type=TARGET_ANSWER,
        validator=CONSEQUENCE_GATE,
        result="qualified",
        reason="partial claim requires qualification",
    )

    audit = serving_audit(store, "answer-1", claim_ids=["claim-a", "claim-b"])
    assert audit["answer_id"] == "answer-1"
    assert audit["decision"] == "qualified"
    assert [e.validator for e in audit["events"]] == [CONSEQUENCE_GATE]
    assert audit["claims"]["claim-a"][0].result == "supported"
    assert audit["claims"]["claim-b"][0].result == "partial"


def test_ledger_is_append_only_never_rewritten(store):
    record_event(
        store,
        target_id="claim-1",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="unsupported",
    )
    path = store.validation_events_path
    first_bytes = path.read_bytes()

    record_event(
        store,
        target_id="claim-1",
        target_type=TARGET_CLAIM,
        validator=ENTAILMENT_JUDGE,
        result="supported",
    )
    second_bytes = path.read_bytes()

    # The file only ever grew; the original bytes are still a prefix.
    assert second_bytes.startswith(first_bytes)
    assert len(second_bytes) > len(first_bytes)
    assert len(second_bytes.splitlines()) == 2
