"""Deterministic context-package builder (M2 task C2.1).

Before a governed answer is generated, this module freezes the *exact* evidence
that answer is permitted to rely on into an immutable
:class:`kops.evidence_model.ContextPackage`, and persists it (content-addressed)
via :class:`kops.evidence_store.EvidenceStore`. The model then receives this
package instead of unrestricted vault access — it is the single source of truth
for what a governed answer may cite.

Design ethos (matches ``consequence_gate`` / ``source_override``): deterministic,
non-gameable, report-and-gate. No LLM, no RNG, no timestamps in the hash. The
same vault state + question + tier always produces the same ``package_hash``.

What each package field records and where it comes from
------------------------------------------------------
* ``question`` / ``tier``               — the caller's inputs.
* ``claim_ids``                         — served claims that *clear* every bar
                                          (retrieval + consequence gate + not
                                          flagged/stale), sorted.
* ``spans``                             — exact evidence coordinates, unified
                                          from each admitted claim's
                                          ``source_anchors`` and from retrieved
                                          source-section records (SourceSpan).
* ``trust_states``                      — per-claim ``admission_status`` and
                                          per-source ``source_status``.
* ``source_version_ids``                — immutable SourceVersion ids for every
                                          referenced source (content-addressed).
* ``freshness``                         — per-source drift / revalidation status
                                          from ``content_drift`` + frontmatter.
* ``excluded_claims``                   — every served claim that was barred,
                                          each with explicit reasons. Nothing is
                                          silently dropped.
* ``retrieval_trace``                   — id / kind / method / layer / score for
                                          every retrieved record.
* ``policy_version``                    — :data:`CONTEXT_POLICY_VERSION`.

This is additive: it does not modify retrieval, the claim registry, or any
serving surface — it composes them.

Ad-hoc build:
    python -m kops.context_package --vault <dir> --question "..." --tier decision
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from kops import (
    claim_registry,
    consequence_gate,
    content_drift,
    retrieval,
    source_override,
)
from kops.evidence_model import (
    ClaimEvidenceLink,
    ContextPackage,
    SourceSpan,
    SourceVersion,
)
from kops.evidence_store import EvidenceStore
from kops.utils import now_stamp, parse_frontmatter

# The governance policy this builder encodes. Bump when the packaging rules
# (what is admitted, what is excluded, how spans/versions are resolved) change.
CONTEXT_POLICY_VERSION = "1.0.0"

# The retrieval-command scope. ``ask`` makes retrieval exclusion-aware so
# flagged/revoked/adversarial sources are already barred from the surface.
_COMMAND = "ask"


# --------------------------------------------------------------------------- #
# Vault redirection (so ``vault=`` and the CLI target an arbitrary vault)
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def redirect_vault(vault: Path | None):
    """Point every collaborating module at ``vault`` for the duration.

    The collaborators bind ``ROOT`` / ``CONFIG`` (and a couple of derived path
    constants) at import time, so redirecting to a non-default vault means
    swapping those module globals and restoring them afterwards. When ``vault``
    is ``None`` this is a no-op and the ambient configured vault is used.
    """
    if vault is None:
        yield
        return
    vault = Path(vault).expanduser().resolve()
    cfg = SimpleNamespace(
        summaries_dir=vault / "notes" / "Sources",
        concepts_dir=vault / "notes" / "Concepts",
        raw_dir=vault / "data" / "raw",
        registry_path=vault / "data" / "registry.json",
        vault_dir=vault / "notes",
    )
    patches: list[tuple[Any, str, Any]] = [
        (retrieval, "CONFIG", cfg),
        (retrieval, "ROOT", vault),
        (claim_registry, "CONFIG", cfg),
        (claim_registry, "ROOT", vault),
        (claim_registry, "CLAIMS_PATH", vault / "data" / "claims.json"),
        (content_drift, "CONFIG", cfg),
        (content_drift, "ROOT", vault),
        (content_drift, "SOURCES_DIR", vault / "notes" / "Sources"),
        (source_override, "OVERRIDES_PATH", vault / "data" / "source_overrides.json"),
    ]
    saved = [(mod, attr, getattr(mod, attr)) for mod, attr, _ in patches]
    try:
        for mod, attr, value in patches:
            setattr(mod, attr, value)
        yield
    finally:
        for mod, attr, value in saved:
            setattr(mod, attr, value)


# Backward-compatible private alias (kept so existing callers keep working).
_redirect_vault = redirect_vault


# --------------------------------------------------------------------------- #
# Small readers over the (possibly redirected) vault
# --------------------------------------------------------------------------- #


def _source_frontmatter_by_id() -> dict[str, dict]:
    """Map every source note's ``source_id`` to its frontmatter."""
    meta: dict[str, dict] = {}
    summaries_dir = getattr(claim_registry.CONFIG, "summaries_dir", None)
    if not summaries_dir or not Path(summaries_dir).exists():
        return meta
    for path in sorted(Path(summaries_dir).rglob("src-*.md")):
        try:
            fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        sid = str(fm.get("source_id") or path.stem)
        meta[sid] = fm
    return meta


def _content_hash_for(sid: str, fm_by_id: dict[str, dict]) -> str:
    """Current content hash for a source: frontmatter, then raw, else 'unknown'."""
    fm = fm_by_id.get(sid) or {}
    if fm.get("content_hash"):
        return str(fm["content_hash"])
    raw = content_drift.current_raw_hash(sid)
    return str(raw) if raw else "unknown"


def _retrieved_source_ids(results: list[dict]) -> set[str]:
    ids: set[str] = set()
    for r in results:
        kind = r.get("kind")
        if kind == "source":
            ids.add(r["id"])
        elif kind == "source-section" and r.get("source_id"):
            ids.add(str(r["source_id"]))
    return ids


def _retrieval_layer(method: str) -> str:
    if method.startswith("exact"):
        return "exact"
    if method.startswith("bm25"):
        return "bm25"
    return method or "unknown"


# --------------------------------------------------------------------------- #
# Served-claim resolution
# --------------------------------------------------------------------------- #


def _served_claims(results: list[dict], claims: list[dict]) -> list[dict]:
    """Claims made servable by this retrieval, deterministically ordered.

    A claim is served if it was retrieved directly (``kind == claim``), belongs
    to a retrieved concept page, or is grounded in a retrieved source. Ordered
    by ``(concept, claim_index)`` so the package is reproducible.
    """
    retrieved_claim_ids = {str(r["id"]) for r in results if r.get("kind") == "claim"}
    retrieved_concepts = {str(r["id"]) for r in results if r.get("kind") == "concept"}
    retrieved_sources = _retrieved_source_ids(results)

    served: dict[str, dict] = {}
    for claim in claims:
        cid = str(claim.get("claim_id") or claim.get("id") or "")
        if not cid:
            continue
        source_ids = {str(s) for s in (claim.get("source_ids") or [])}
        if (
            cid in retrieved_claim_ids
            or str(claim.get("concept") or "") in retrieved_concepts
            or (source_ids & retrieved_sources)
        ):
            served[cid] = claim
    return sorted(
        served.values(),
        key=lambda c: (
            str(c.get("concept") or ""),
            int(c.get("claim_index") or 0),
            str(c["claim_id"]),
        ),
    )


def _exclusion_reasons(
    claim: dict,
    tier: str,
    gate_violations: dict[str, list[str]],
    fm_by_id: dict[str, dict],
    freshness: dict[str, str],
) -> list[str]:
    """Every reason this served claim may not back a governed answer (empty = admitted)."""
    reasons: list[str] = []
    cid = str(claim.get("claim_id") or claim.get("id") or "")

    # (1) consequence-gate bar for this tier (blocked/quarantine/weak/synthetic/...).
    reasons.extend(gate_violations.get(cid, []))

    for sid in (str(s) for s in (claim.get("source_ids") or [])):
        # (2) a flagged/revoked/adversarial grounding source (tier-independent).
        for flag in source_override.frontmatter_flag_reasons(fm_by_id.get(sid) or {}):
            reasons.append(f"flagged-source:{sid}:{flag}")
        # (3) a stale grounding source (drifted raw content or revalidation needed).
        fresh = freshness.get(sid)
        if fresh in {"drifted", "revalidation-required"}:
            reasons.append(f"stale-source:{sid}:{fresh}")

    # De-duplicate while preserving a stable, sorted order.
    return sorted(set(reasons))


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #


def build_context_package(
    question: str,
    tier: str,
    *,
    index: retrieval.VaultIndex | None = None,
    vault: Path | None = None,
    store: EvidenceStore | None = None,
    top_k: int = 8,
    policy_version: str = CONTEXT_POLICY_VERSION,
) -> ContextPackage:
    """Freeze and persist the exact evidence a governed answer may rely on.

    Deterministic: same vault state + ``question`` + ``tier`` yields the same
    ``package_hash`` (``built_at`` is provenance only and is excluded from the
    hash). Every served claim ends up either in ``claim_ids`` (admitted) or in
    ``excluded_claims`` (with explicit reasons) — nothing is silently dropped.

    Returns the persisted :class:`ContextPackage`; ``pkg.package_hash`` resolves
    it back out of ``store``.
    """
    if tier not in consequence_gate.TIERS:
        raise ValueError(f"tier must be one of {consequence_gate.TIERS}, got {tier!r}")

    with redirect_vault(vault):
        if store is None:
            if vault is not None:
                v = Path(vault).expanduser().resolve()
                store = EvidenceStore(
                    base_dir=v / "data" / "evidence", history_dir=v / "data" / "history"
                )
            else:
                store = EvidenceStore()

        if index is None:
            index = retrieval.VaultIndex()
            index.build()

        results = index.search(question, top_k=top_k, command=_COMMAND, include_flagged=False)

        claims = claim_registry.load_claims()
        fm_by_id = _source_frontmatter_by_id()

        # Freshness per source (drift status + revalidation frontmatter flag).
        drift_status = {r["source_id"]: r["status"] for r in content_drift.detect()}
        served = _served_claims(results, claims)

        # Source universe: everything a served claim cites, plus retrieved sources.
        referenced_sources: set[str] = set(_retrieved_source_ids(results))
        for claim in served:
            referenced_sources.update(str(s) for s in (claim.get("source_ids") or []))

        freshness: dict[str, str] = {}
        for sid in referenced_sources:
            fm = fm_by_id.get(sid) or {}
            if fm.get("revalidation_required") is True:
                freshness[sid] = "revalidation-required"
            else:
                freshness[sid] = drift_status.get(sid, "no-baseline")

        # Consequence-gate assessment (pure) → per-claim tier violations.
        gate = consequence_gate.assess_claims(served, tier)
        gate_violations = {str(v["claim_id"]): list(v["reasons"]) for v in gate["violations"]}

        # Immutable SourceVersion per referenced source (content-addressed).
        version_by_source: dict[str, str] = {}
        version_ids: list[str] = []
        for sid in sorted(referenced_sources):
            fm = fm_by_id.get(sid) or {}
            version = SourceVersion(
                source_id=sid,
                content_hash=_content_hash_for(sid, fm_by_id),
                captured_at="",  # empty → deterministic; version_id is content-derived
                provenance="context-package",
                git_commit=(str(fm["git_commit"]) if fm.get("git_commit") else None),
            )
            stored = store.append_source_version(version)
            version_by_source[sid] = stored.version_id
            version_ids.append(stored.version_id)

        # Partition served claims into admitted vs excluded (with reasons).
        admitted: list[dict] = []
        excluded_claims: list[dict[str, Any]] = []
        trust_states: dict[str, str] = {}
        for claim in served:
            cid = str(claim["claim_id"])
            trust_states[cid] = str(claim.get("admission_status") or "unknown")
            reasons = _exclusion_reasons(claim, tier, gate_violations, fm_by_id, freshness)
            if reasons:
                excluded_claims.append(
                    {
                        "claim_id": cid,
                        "concept": claim.get("concept"),
                        "reasons": reasons,
                    }
                )
            else:
                admitted.append(claim)

        # Per-source trust (source_status) for every referenced source.
        for sid in referenced_sources:
            trust_states[sid] = str((fm_by_id.get(sid) or {}).get("source_status") or "unknown")

        # Spans: admitted-claim anchors + retrieved source-section coordinates.
        spans_by_id: dict[str, SourceSpan] = {}
        for claim in admitted:
            for link in ClaimEvidenceLink.links_from_claim(claim, version_by_source):
                if link.span is not None:
                    spans_by_id[link.span.span_id] = link.span
        for r in results:
            if r.get("kind") == "source-section":
                span = SourceSpan(
                    source_id=str(r.get("source_id") or ""),
                    anchor=r.get("anchor") or None,
                    quote=r.get("snippet") or None,
                    content_hash=r.get("content_hash") or None,
                )
                spans_by_id[span.span_id] = span
        spans = tuple(spans_by_id[k] for k in sorted(spans_by_id))

        # Retrieval trace: why each record was returned.
        trace = tuple(
            {
                "id": str(r["id"]),
                "kind": r.get("kind"),
                "method": r.get("retrieval_method"),
                "layer": _retrieval_layer(str(r.get("retrieval_method") or "")),
                "score": r.get("score"),
                "source_id": r.get("source_id") or None,
                "anchor": r.get("anchor") or None,
            }
            for r in results
        )

        package = ContextPackage(
            question=question,
            tier=tier,
            claim_ids=tuple(sorted(str(c["claim_id"]) for c in admitted)),
            spans=spans,
            trust_states=trust_states,
            source_version_ids=tuple(sorted(set(version_ids))),
            freshness=freshness,
            excluded_claims=tuple(sorted(excluded_claims, key=lambda e: str(e["claim_id"]))),
            retrieval_trace=trace,
            policy_version=policy_version,
            built_at=now_stamp(),
        )
        store.save_context_package(package)
        return package


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic, frozen context package for one question."
    )
    parser.add_argument("--vault", help="Vault root directory (defaults to the configured vault).")
    parser.add_argument("--question", required=True, help="The question to package evidence for.")
    parser.add_argument(
        "--tier",
        default="recommendation",
        choices=list(consequence_gate.TIERS),
        help="Consequence tier (governs the evidence bar).",
    )
    parser.add_argument("--top-k", type=int, default=8, help="Retrieval breadth.")
    args = parser.parse_args(argv)

    pkg = build_context_package(
        args.question,
        args.tier,
        vault=Path(args.vault) if args.vault else None,
        top_k=args.top_k,
    )
    print(f"package_hash: {pkg.package_hash}")
    print(f"tier: {pkg.tier}")
    print(f"admitted claims: {len(pkg.claim_ids)}")
    print(f"excluded claims: {len(pkg.excluded_claims)}")
    print(f"spans: {len(pkg.spans)}")
    print(f"source versions: {len(pkg.source_version_ids)}")
    for exc in pkg.excluded_claims:
        print(f"  excluded {exc['claim_id']} ({exc.get('concept')}): {', '.join(exc['reasons'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
