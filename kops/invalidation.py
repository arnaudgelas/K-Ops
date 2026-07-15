"""Automatic source-change invalidation (M2 task F2.1).

When a source's raw content changes, the summaries, claims, answers and context
packages that were grounded in the *old* content are no longer trustworthy as
current, decision-grade evidence. ``content_drift`` already *detects* that a
source's ``content_hash`` diverged from its baseline; ``retract_source`` already
knows how to walk the dependency graph and flag a blast radius. This module
composes those two — plus the immutable evidence store and the claim /
contradiction registries — into a single deterministic cascade that runs on a
detected content change:

1. append a new immutable ``SourceVersion`` for the changed source (never
   overwrite a prior version);
2. find the dependent claim-evidence links (claims citing the source) and the
   spans anchored to it;
3. mark the affected validations stale by appending a ``ValidationEvent`` per
   affected claim / answer / context package (prior -> new status, with the
   old/new hash in the reason);
4. re-derive the claim registry, **then** the contradiction registry, **then**
   the claim registry again (fixed point) — closing the gap ``retract`` leaves,
   which re-runs only the claim registry and never recomputes contradictions;
5. flag the dependent concepts, answers and the source note itself
   ``revalidation_required`` (frontmatter only — reusing
   ``retract_source.flag_note_for_revalidation``);
6. write a deterministic stale-set to ``data/invalidation_queue.json`` that a
   serving gate can read to refuse a stale answer / context package as current
   at the decision or autonomous tier;
7. queue the affected outputs for regeneration / human review in that same
   artifact — it never auto-repairs.

Deliberate boundary (matches K-Ops's "fail loudly, preserve Git review"
principle, same as ``retract``): this **flags, re-derives and audits** only. It
never rewrites curated claim / concept prose and never deletes anything. Prior
answers and prior source versions stay; they are marked stale, not rewritten.
A human plus Git decides what curated prose actually changes.

Deterministic and offline: no LLM, no network. Run with

    python -m kops.invalidation [--only src-...] [--dry-run] [--flag]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from kops import content_drift
from kops.evidence_model import ClaimEvidenceLink, SourceVersion, ValidationEvent
from kops.evidence_store import EvidenceStore
from kops.retract_source import (
    _note_path_for,
    compute_blast_radius,
    flag_note_for_revalidation,
)
from kops.utils import ROOT, find_source_note, write_text

# The validator name stamped on every ValidationEvent this cascade emits, and the
# policy fingerprint identifying the invalidation rule that produced them.
VALIDATOR = "source_invalidation"
POLICY_VERSION = "m2-f2.1"
NEW_STATUS = "stale"

INVALIDATION_QUEUE_PATH = ROOT / "data" / "invalidation_queue.json"
_QUEUE_SCHEMA_VERSION = "1.0.0"


# --------------------------------------------------------------------------- #
# Dependency discovery (pure)
# --------------------------------------------------------------------------- #


def _claim_cites_source(claim: dict, source_id: str) -> bool:
    """True if ``claim`` grounds any evidence in ``source_id`` (any field)."""
    for key in ("source_ids", "inline_source_ids", "page_source_ids"):
        if source_id in (claim.get(key) or []):
            return True
    for anchor in claim.get("source_anchors") or []:
        if anchor.get("source_id") == source_id:
            return True
    return False


def dependent_claims(source_id: str, claims: list[dict]) -> list[dict]:
    """The claim registry entries that cite ``source_id`` as evidence."""
    return [c for c in claims if _claim_cites_source(c, source_id)]


def dependent_links(source_id: str, claims: list[dict]) -> list[ClaimEvidenceLink]:
    """The claim <-> source_version <-> span links pointing at ``source_id``.

    Reuses :meth:`ClaimEvidenceLink.links_from_claim` and keeps only the links
    whose evidence is the changed source.
    """
    links: list[ClaimEvidenceLink] = []
    for claim in dependent_claims(source_id, claims):
        links.extend(
            link
            for link in ClaimEvidenceLink.links_from_claim(claim)
            if link.source_id == source_id
        )
    return links


# --------------------------------------------------------------------------- #
# Stale context packages (reads the evidence store's content-addressed dir)
# --------------------------------------------------------------------------- #


def _stale_context_packages(
    store: EvidenceStore, prior_version_id: str | None, stale_claim_ids: set[str]
) -> list[str]:
    """Content-package hashes that relied on this source version or a stale claim."""
    ctx_dir = store.context_dir
    if not ctx_dir.exists():
        return []
    hits: list[str] = []
    for path in sorted(ctx_dir.glob("*.json")):
        try:
            pkg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        claim_ids = set(pkg.get("claim_ids") or [])
        version_ids = set(pkg.get("source_version_ids") or [])
        if (claim_ids & stale_claim_ids) or (prior_version_id and prior_version_id in version_ids):
            hits.append(str(pkg.get("package_hash") or path.stem))
    return sorted(set(hits))


# --------------------------------------------------------------------------- #
# Invalidation queue / stale-set artifact (owned by this module)
# --------------------------------------------------------------------------- #


def load_queue(queue_path: Path | None = None) -> dict:
    """Load the invalidation queue artifact, or an empty shell if absent."""
    path = queue_path or INVALIDATION_QUEUE_PATH
    if not path.exists():
        return {"schema_version": _QUEUE_SCHEMA_VERSION, "entries": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": _QUEUE_SCHEMA_VERSION, "entries": []}
    payload.setdefault("entries", [])
    return payload


def stale_targets(queue_path: Path | None = None) -> set[str]:
    """The set of claim / concept / answer / context-package ids currently stale.

    This is the deterministic read a serving gate consults to block a stale
    decision-grade or autonomous output: any target id in this set with an entry
    whose ``status`` is not ``resolved`` must not be served as current.
    """
    targets: set[str] = set()
    for entry in load_queue(queue_path).get("entries", []):
        if entry.get("status") == "resolved":
            continue
        for key in ("stale_claims", "stale_concepts", "stale_answers", "stale_context_packages"):
            targets.update(entry.get(key) or [])
    return targets


def _upsert_queue_entry(entry: dict, queue_path: Path | None = None) -> None:
    """Insert or replace the queue entry keyed by its source version id.

    Idempotent: re-running the same content change replaces the entry in place
    rather than appending a duplicate.
    """
    path = queue_path or INVALIDATION_QUEUE_PATH
    payload = load_queue(path)
    entries = [e for e in payload.get("entries", []) if e.get("version_id") != entry["version_id"]]
    entries.append(entry)
    entries.sort(key=lambda e: (e.get("source_id", ""), e.get("version_id", "")))
    payload["entries"] = entries
    payload["schema_version"] = _QUEUE_SCHEMA_VERSION
    payload["generated_at"] = dt.datetime.now().replace(microsecond=0).isoformat()
    write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# ValidationEvent emission (append-only, idempotent per source version)
# --------------------------------------------------------------------------- #


def _already_invalidated(store: EvidenceStore, target_id: str, version_id: str) -> bool:
    """True if this target was already invalidated for this exact source version."""
    for event in store.validation_events(target_id):
        if event.validator == VALIDATOR and event.target_version == version_id:
            return True
    return False


def _emit_event(
    store: EvidenceStore,
    *,
    target_id: str,
    target_type: str,
    prior_status: str | None,
    version_id: str,
    reason: str,
    occurred_at: str,
) -> ValidationEvent | None:
    """Append one stale ValidationEvent, unless it was already recorded."""
    if _already_invalidated(store, target_id, version_id):
        return None
    event = ValidationEvent(
        target_id=target_id,
        target_type=target_type,
        target_version=version_id,
        validator=VALIDATOR,
        result=NEW_STATUS,
        prior_status=prior_status,
        new_status=NEW_STATUS,
        reason=reason,
        policy_version=POLICY_VERSION,
        occurred_at=occurred_at,
    )
    return store.append_validation_event(event)


# --------------------------------------------------------------------------- #
# Registry re-derivation (claims -> contradictions -> claims fixed point)
# --------------------------------------------------------------------------- #


def recompute_registries() -> None:
    """Re-derive claims, then contradictions, then claims again.

    ``retract`` re-runs only the claim registry; a content change must also
    recompute contradiction state. The two registries cross-depend (claims read
    contradictions for ``conflicts_with``; contradictions read claims for
    ``claim_ids``), so we sequence claims -> contradictions -> claims to reach a
    consistent fixed point.
    """
    from kops.claim_registry import run as run_claims
    from kops.contradiction_registry import run as run_contradictions

    run_claims()
    run_contradictions()
    run_claims()


# --------------------------------------------------------------------------- #
# The cascade
# --------------------------------------------------------------------------- #


def _flag_notes(node_ids: list[str], reason: str) -> list[str]:
    """Flag each concept/answer note ``revalidation_required`` (frontmatter only)."""
    flagged: list[str] = []
    for node_id in node_ids:
        path = _note_path_for(node_id)
        if not path or not path.exists():
            continue
        updated, changed = flag_note_for_revalidation(path.read_text(encoding="utf-8"), reason)
        if changed:
            write_text(path, updated)
            flagged.append(path.relative_to(ROOT).as_posix())
    return flagged


def invalidate_on_source_change(
    source_id: str,
    *,
    old_hash: str | None = None,
    new_hash: str | None = None,
    graph: dict | None = None,
    claims: list[dict] | None = None,
    store: EvidenceStore | None = None,
    queue_path: Path | None = None,
    dry_run: bool = False,
    flag: bool = False,
    recompute: bool = True,
    provenance: str = "content-change",
    occurred_at: str | None = None,
) -> dict:
    """Propagate an invalidation for a single changed source through the graph.

    Returns a structured audit report. With ``dry_run`` nothing is written: no
    SourceVersion, no ValidationEvent, no flag, no queue entry, no registry
    re-derivation — the report shows what *would* happen.
    """
    store = store or EvidenceStore()
    occurred_at = occurred_at or dt.datetime.now().replace(microsecond=0).isoformat()

    if new_hash is None:
        new_hash = content_drift.current_raw_hash(source_id)
    if old_hash is None:
        prior = store.latest_source_version(source_id)
        old_hash = prior.content_hash if prior else None
    if not new_hash:
        raise ValueError(f"no current content hash available for {source_id!r}")

    new_version = SourceVersion(
        source_id=source_id,
        content_hash=new_hash,
        captured_at=occurred_at,
        provenance=provenance,
    )
    prior_version_id = (
        SourceVersion(
            source_id=source_id, content_hash=old_hash, captured_at="", provenance=""
        ).version_id
        if old_hash
        else None
    )

    # 2. dependent claim-evidence links + the spans anchored to this source.
    all_claims = claims if claims is not None else _load_claims()
    links = dependent_links(source_id, all_claims)
    stale_claim_ids = sorted({link.claim_id for link in links})
    stale_span_ids = sorted({link.span.span_id for link in links if link.span is not None})

    # blast radius: transitive concepts + answers (claims handled precisely above).
    radius = compute_blast_radius(graph if graph is not None else _load_graph(), source_id)
    stale_concept_ids = [c["id"] for c in radius["concepts"]]
    stale_answer_ids = [a["id"] for a in radius["answers"]]

    hash_note = f"{(old_hash or '?')[:7]}->{new_hash[:7]}"
    reason = f"source {source_id} raw content changed ({hash_note}); regrounding required"

    prior_claim_status = {
        c.get("claim_id") or c.get("id"): c.get("admission_status") for c in all_claims
    }

    stale_packages = _stale_context_packages(store, prior_version_id, set(stale_claim_ids))

    report: dict = {
        "source_id": source_id,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "version_id": new_version.version_id,
        "dry_run": dry_run,
        "stale_claims": stale_claim_ids,
        "stale_spans": stale_span_ids,
        "stale_concepts": stale_concept_ids,
        "stale_answers": stale_answer_ids,
        "stale_context_packages": stale_packages,
        "events_emitted": [],
        "flagged_notes": [],
        "source_version_appended": False,
        "registries_recomputed": False,
    }

    if dry_run:
        return report

    # 1. append the new immutable source version (first-write-wins).
    stored = store.append_source_version(new_version)
    report["source_version_appended"] = stored.content_hash == new_hash

    # 3. mark affected validations stale — one event per claim / answer / package.
    events: list[str] = []
    for claim_id in stale_claim_ids:
        ev = _emit_event(
            store,
            target_id=claim_id,
            target_type="atomic_claim",
            prior_status=prior_claim_status.get(claim_id),
            version_id=new_version.version_id,
            reason=reason,
            occurred_at=occurred_at,
        )
        if ev:
            events.append(ev.event_id)
    for answer_id in stale_answer_ids:
        ev = _emit_event(
            store,
            target_id=answer_id,
            target_type="answer_memo",
            prior_status="current",
            version_id=new_version.version_id,
            reason=reason,
            occurred_at=occurred_at,
        )
        if ev:
            events.append(ev.event_id)
    for package_hash in stale_packages:
        ev = _emit_event(
            store,
            target_id=package_hash,
            target_type="context_package",
            prior_status="current",
            version_id=new_version.version_id,
            reason=reason,
            occurred_at=occurred_at,
        )
        if ev:
            events.append(ev.event_id)
    report["events_emitted"] = events

    # 5. flag dependent concepts + answers + the source note (frontmatter only).
    if flag:
        flagged = _flag_notes(stale_concept_ids + stale_answer_ids, reason)
        source_note = find_source_note(source_id)
        if source_note and source_note.exists():
            updated, changed = flag_note_for_revalidation(
                source_note.read_text(encoding="utf-8"), reason
            )
            if changed:
                write_text(source_note, updated)
                flagged.append(source_note.relative_to(ROOT).as_posix())
        report["flagged_notes"] = flagged

    # 6 + 7. record the stale-set / regeneration worklist a serving gate reads.
    _upsert_queue_entry(
        {
            "source_id": source_id,
            "version_id": new_version.version_id,
            "old_hash": old_hash,
            "new_hash": new_hash,
            "invalidated_at": occurred_at,
            "status": "pending-review",
            "stale_claims": stale_claim_ids,
            "stale_spans": stale_span_ids,
            "stale_concepts": stale_concept_ids,
            "stale_answers": stale_answer_ids,
            "stale_context_packages": stale_packages,
            "review_action": (
                "Re-ground claims and answers cited from this source against the new "
                "content, then re-baseline the source note (backfill-content-hash --force) "
                "and clear the stale flags."
            ),
        },
        queue_path,
    )

    # 4. re-derive claims -> contradictions -> claims (close the retract gap).
    if recompute:
        recompute_registries()
        report["registries_recomputed"] = True

    return report


def run_invalidation(
    only: set[str] | None = None,
    *,
    dry_run: bool = False,
    flag: bool = False,
    store: EvidenceStore | None = None,
    queue_path: Path | None = None,
    fmt: str = "text",
) -> dict:
    """Detect content-drifted sources and invalidate each one's dependents.

    The change trigger is ``content_drift.detect`` — every source whose recorded
    baseline hash diverges from its current raw hash. Registry re-derivation is
    batched: each source is invalidated with ``recompute=False`` and the
    registries are re-derived once at the end.
    """
    store = store or EvidenceStore()
    drifted = [r for r in content_drift.detect(only) if r["status"] == "drifted"]

    reports: list[dict] = []
    for r in drifted:
        reports.append(
            invalidate_on_source_change(
                r["source_id"],
                old_hash=r["recorded"],
                new_hash=r["current"],
                store=store,
                queue_path=queue_path,
                dry_run=dry_run,
                flag=flag,
                recompute=False,
            )
        )

    if reports and not dry_run:
        recompute_registries()
        for rep in reports:
            rep["registries_recomputed"] = True

    summary = {
        "drifted_sources": [r["source_id"] for r in drifted],
        "invalidations": reports,
        "dry_run": dry_run,
    }

    if fmt == "json":
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return summary

    _print_report(summary)
    return summary


# --------------------------------------------------------------------------- #
# Helpers that touch the vault (thin wrappers, kept for monkeypatch isolation)
# --------------------------------------------------------------------------- #


def _load_claims() -> list[dict]:
    from kops.claim_registry import load_claims

    return load_claims()


def _load_graph() -> dict:
    from kops.vault_graph import load_graph

    return load_graph()


def _print_report(summary: dict) -> None:
    drifted = summary["drifted_sources"]
    tag = "[DRY-RUN] would invalidate" if summary["dry_run"] else "Invalidated"
    if not drifted:
        print("No content-drifted sources — nothing to invalidate.")
        return
    print(f"{tag} {len(drifted)} drifted source(s):")
    for rep in summary["invalidations"]:
        print(
            f"  {rep['source_id']} ({(rep['old_hash'] or '?')[:7]}->{rep['new_hash'][:7]}): "
            f"{len(rep['stale_claims'])} claim(s), {len(rep['stale_concepts'])} concept(s), "
            f"{len(rep['stale_answers'])} answer(s), "
            f"{len(rep['stale_context_packages'])} context package(s)"
        )
        if rep.get("flagged_notes"):
            print(f"    flagged {len(rep['flagged_notes'])} note(s) for revalidation")
    if not summary["dry_run"]:
        print(
            "  -> stale-set written to data/invalidation_queue.json; "
            "review with 'review-queue' and 'consequence-gate --tier decision'"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automatically invalidate on source content change."
    )
    parser.add_argument("--only", nargs="+", metavar="SRC_ID", help="Limit to these source ids.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change; write nothing."
    )
    parser.add_argument(
        "--flag",
        action="store_true",
        help="Write revalidation_required frontmatter flags on dependent notes.",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    summary = run_invalidation(
        only=set(args.only) if args.only else None,
        dry_run=args.dry_run,
        flag=args.flag,
        fmt=args.format,
    )
    # Exit 2 when there was something to invalidate (mirrors check-content-drift).
    return 2 if summary["drifted_sources"] else 0


if __name__ == "__main__":
    sys.exit(main())
