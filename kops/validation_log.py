"""Immutable validation-event ledger (M2 task F2.2).

Every governance decision — an entailment verdict, a consequence-gate ruling, a
source invalidation, a human review — must leave a durable, tamper-evident
record. This module is the *canonical* way to record and read those records.

It is a thin, opinionated layer over the M1 primitives, not a new store:

* ``evidence_model.ValidationEvent`` is the frozen event record.
* ``evidence_store.EvidenceStore`` is the append-only JSONL persistence
  (``data/history/validation_events.jsonl``). Events are only ever appended;
  nothing is rewritten in place. The reader tolerates blank/corrupt lines.

Two things this module adds on top of the raw store:

1. **A small, documented vocabulary** (``VALIDATORS``) of validator names and
   their allowed ``result`` values. ``record_event`` validates against it and
   raises on anything unknown, so a caller (F2.1 invalidation, C2.4 serving
   gate) cannot silently record garbage into the audit trail.
2. **A query/audit API** — the ordered trail for one target, the latest status,
   and ``serving_audit`` which reconstructs the full decision record behind one
   served answer. The M2 exit gate ("every serving decision has a reproducible
   audit record") is exactly this reconstruction.

Git review is the tamper backstop (see ``signal_history`` design principle 7):
the durable ledger at ``data/history/validation_events.jsonl`` is deliberately
**tracked** in git (see ``.gitignore``) so every appended decision shows up in a
reviewable diff. An adversary with write access can still rewrite the file, and
there the backstop is the commit history, not this module.

Run ``python -m kops.validation_log --target <id>`` to print a target's trail,
or ``--answer <id>`` to print a served answer's full decision record.
"""

from __future__ import annotations

import datetime as dt

from kops.evidence_model import ValidationEvent
from kops.evidence_store import EvidenceStore

# --------------------------------------------------------------------------- #
# Canonical vocabulary
# --------------------------------------------------------------------------- #
#
# Keep this small and documented. Other tasks emit events with these validators;
# adding a validator or result here is a deliberate, reviewable vocabulary change.
#
#   entailment_judge     — sentence/claim support verdict (kops.entailment_judge).
#   consequence_gate     — tier-policy ruling on a served answer (C2.4).
#   source_invalidation  — a source version change made a prior judgement stale (F2.1).
#   human_review         — an explicit human approval/rejection (override trail).

ENTAILMENT_JUDGE = "entailment_judge"
CONSEQUENCE_GATE = "consequence_gate"
SOURCE_INVALIDATION = "source_invalidation"
HUMAN_REVIEW = "human_review"

VALIDATORS: dict[str, tuple[str, ...]] = {
    ENTAILMENT_JUDGE: ("supported", "partial", "unsupported", "contradicted", "not_evaluable"),
    CONSEQUENCE_GATE: ("allowed", "refused", "qualified"),
    SOURCE_INVALIDATION: ("stale", "superseded"),
    HUMAN_REVIEW: ("approved", "rejected"),
}

# Common target types (free-form, but these keep call sites consistent).
TARGET_ANSWER = "answer"
TARGET_CLAIM = "atomic_claim"
TARGET_SOURCE = "source"


class VocabularyError(ValueError):
    """Raised when a validator name or result is not in the canonical vocabulary."""


def _now_iso() -> str:
    """Second-resolution local ISO timestamp (mirrors signal_history)."""
    return dt.datetime.now().replace(microsecond=0).isoformat()


def _validate_vocabulary(validator: str, result: str) -> None:
    if validator not in VALIDATORS:
        known = ", ".join(sorted(VALIDATORS))
        raise VocabularyError(f"unknown validator {validator!r}; known validators: {known}")
    allowed = VALIDATORS[validator]
    if result not in allowed:
        raise VocabularyError(
            f"unknown result {result!r} for validator {validator!r}; allowed: {', '.join(allowed)}"
        )


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #


def record_event(
    store: EvidenceStore,
    *,
    target_id: str,
    target_type: str,
    validator: str,
    result: str,
    prior_status: str | None = None,
    new_status: str | None = None,
    reason: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    policy_version: str | None = None,
    target_version: str | None = None,
    fingerprint: str | None = None,
) -> ValidationEvent:
    """Construct and append one immutable validation event.

    ``occurred_at`` is stamped here. ``validator``/``result`` are checked against
    the canonical vocabulary and raise :class:`VocabularyError` on anything
    unknown, so garbage can never enter the audit trail.

    The ledger is append-only and does **not** deduplicate: a second logically
    identical event still appends a second line. Its ``event_id`` is
    deterministic for identical content (see ``ValidationEvent.event_id``), so
    the two lines are recognisably the same decision recorded twice.
    """
    _validate_vocabulary(validator, result)
    event = ValidationEvent(
        target_id=target_id,
        target_type=target_type,
        validator=validator,
        result=result,
        occurred_at=_now_iso(),
        target_version=target_version,
        prior_status=prior_status,
        new_status=new_status,
        reason=reason,
        fingerprint=fingerprint,
        model=model,
        prompt_version=prompt_version,
        policy_version=policy_version,
    )
    store.append_validation_event(event)
    return event


# --------------------------------------------------------------------------- #
# Reading / query
# --------------------------------------------------------------------------- #


def _ordered(events: list[ValidationEvent]) -> list[ValidationEvent]:
    """Chronological order. A stable sort preserves append order for ties, so
    events recorded within the same second keep the order they were written."""
    return sorted(events, key=lambda e: e.occurred_at)


def events_for(store: EvidenceStore, target_id: str) -> list[ValidationEvent]:
    """The full audit trail for one target, oldest first."""
    return _ordered(store.validation_events(target_id=target_id))


def latest_status(store: EvidenceStore, target_id: str, validator: str | None = None) -> str | None:
    """The ``result`` of the most recent event for ``target_id``.

    With ``validator`` set, only that validator's events are considered. Returns
    ``None`` when there is no matching event.
    """
    events = events_for(store, target_id)
    if validator is not None:
        events = [e for e in events if e.validator == validator]
    return events[-1].result if events else None


def serving_audit(
    store: EvidenceStore,
    answer_id: str,
    claim_ids: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """Reconstruct the full decision record behind one served answer.

    Returns the answer-level trail (consequence-gate rulings, human reviews,
    invalidations targeting the answer itself), the current ``decision`` (the
    latest ``consequence_gate`` result, if any), and — for each supporting claim
    in ``claim_ids`` — that claim's ordered validation trail. Together these are
    the events that justified permit/refuse/qualify, i.e. the reproducible audit
    record the M2 exit gate depends on.
    """
    answer_events = events_for(store, answer_id)
    claims: dict[str, list[ValidationEvent]] = {}
    for claim_id in claim_ids or ():
        claims[claim_id] = events_for(store, claim_id)
    return {
        "answer_id": answer_id,
        "decision": latest_status(store, answer_id, validator=CONSEQUENCE_GATE),
        "events": answer_events,
        "claims": claims,
    }


# --------------------------------------------------------------------------- #
# CLI (module entrypoint only — a later task owns kb.py)
# --------------------------------------------------------------------------- #


def _fmt_event(event: ValidationEvent) -> str:
    bits = f"{event.occurred_at}  {event.validator} -> {event.result}"
    if event.target_version:
        bits += f"  (v={event.target_version})"
    if event.reason:
        bits += f"  reason: {event.reason}"
    return bits


def _print_target(store: EvidenceStore, target_id: str) -> None:
    events = events_for(store, target_id)
    print(f"Audit trail for target {target_id} ({len(events)} event(s)):")
    for event in events:
        print(f"  {_fmt_event(event)}")
    if not events:
        print("  (no events recorded)")


def _print_answer(store: EvidenceStore, answer_id: str) -> None:
    audit = serving_audit(store, answer_id)
    print(f"Serving audit for answer {answer_id}")
    print(f"  decision (consequence_gate): {audit['decision'] or '(none)'}")
    print(f"  answer-level events ({len(audit['events'])}):")
    for event in audit["events"]:
        print(f"    {_fmt_event(event)}")
    if not audit["events"]:
        print("    (no answer-level events recorded)")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Print an immutable validation-event audit trail.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--target", help="Print the ordered trail for one target id.")
    group.add_argument("--answer", help="Print the full serving decision record for one answer.")
    args = parser.parse_args()

    store = EvidenceStore()
    if args.answer:
        _print_answer(store, args.answer)
    else:
        _print_target(store, args.target)


if __name__ == "__main__":
    main()
