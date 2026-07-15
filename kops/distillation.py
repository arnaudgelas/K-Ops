#!/usr/bin/env python3
"""Supervised distillation — propose graph clean-ups; never apply them.

The claim graph accretes noise over time: two extractions phrase the same fact
slightly differently, a compound claim smuggles two facts into one bullet, a
concept gets a second near-identical name, a source is superseded by a fresher
one, and stale claims linger. K-Ops already *detects* many single-claim
problems; this module looks at the graph as a whole and asks a narrower
question: *where could the graph be distilled?*

The answer is always a **proposal**, never a mutation. Following the same idiom
as ``review_queue`` and ``retract_source``, this module is a pure, read-only
detector: it writes a derived registry (``data/distillation_proposals.json``)
and surfaces review-queue-shaped worklist items. A human — plus Git — decides
what actually changes. Nothing here merges, splits, renames, or deletes any
claim or concept prose.

Detectors (each emits ``kind`` proposals):

- ``merge``        — near-duplicate claim text (TF-IDF cosine >= threshold)
                     whose scope / time / evidence match.
- ``needs-review`` — near-duplicate claims that DIVERGE in scope, time, or
                     evidence. This is the hard guardrail: two claims that look
                     alike but rest on different sources, different temporal
                     scope, or different evidence status are NEVER silently
                     merged. They are flagged ``divergent-{scope|time|evidence}``
                     for a human instead.
- ``supersede``    — near-duplicate claims that diverge in time *only* and can
                     be temporally ordered: the newer supersedes the older. The
                     proposal carries BOTH reciprocal edges
                     (``supersedes`` / ``superseded_by``).
- ``split``        — a compound claim, detected via ``atomic_claims``, proposed
                     as its atomic fragments.
- ``rename``       — two concept names that normalise to (near-)the same form
                     (case / separator / singular-plural), proposed as a rename.
- ``archive``      — a stale claim (``claim_quality`` / ``status`` stale) or an
                     already-superseded claim, proposed for archival.

Similarity is the deterministic, dependency-free TF-IDF primitive from
``kb_suggest_links`` (``_tfidf_vectors`` + ``_cosine``). No RNG, no network.

Every proposal is content-addressed: its ``proposal_id`` is a hash of its kind,
its refs (each carrying a content-hash "version" of the claim text), its
rationale, and its guardrail — so a proposal is stable across runs and changes
only when the underlying claims change. ``created_at`` is stamped once and
preserved on re-runs, keeping each proposal an immutable record.

    python -m kops.distillation [--dry-run] [--check] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from kops import atomic_claims
from kops.claim_registry import normalize_claim_text
from kops.kb_suggest_links import _cosine, _tfidf_vectors
from kops.utils import ROOT, load_json, now_stamp, save_json, short_hash

PROPOSALS_PATH = ROOT / "data" / "distillation_proposals.json"
CLAIMS_PATH = ROOT / "data" / "claims.json"

DUP_THRESHOLD = 0.9

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_STALE_QUALITIES = {"stale", "outdated", "deprecated"}
_STALE_STATUSES = {"stale", "archived", "superseded", "retired"}


# --------------------------------------------------------------------------- #
# Claim projections (read-only — inputs are never mutated)
# --------------------------------------------------------------------------- #


def _claim_id(claim: dict) -> str:
    return claim.get("claim_id") or claim.get("id") or ""


def _claim_text(claim: dict) -> str:
    return normalize_claim_text(claim.get("claim_text") or claim.get("text") or "")


def _version(claim: dict) -> str:
    """Content-hash of a claim's normalised text — its distillation 'version'."""
    return short_hash(_claim_text(claim))


def _scope_sig(claim: dict) -> frozenset[str]:
    return frozenset(claim.get("source_ids") or [])


def _evidence_sig(claim: dict) -> str:
    return str(claim.get("evidence_status") or "")


def _years(claim: dict) -> set[int]:
    hay = _claim_text(claim) + " " + json.dumps(claim.get("source_anchors") or [])
    return {int(y) for y in _YEAR_RE.findall(hay)}


def _time_sig(claim: dict) -> tuple[int, ...]:
    return tuple(sorted(_years(claim)))


def _dominant_year(claim: dict) -> int | None:
    ys = _years(claim)
    return max(ys) if ys else None


def _divergent_dims(a: dict, b: dict) -> list[str]:
    """Which of scope / time / evidence differ between two similar claims."""
    dims = []
    if _scope_sig(a) != _scope_sig(b):
        dims.append("scope")
    if _time_sig(a) != _time_sig(b):
        dims.append("time")
    if _evidence_sig(a) != _evidence_sig(b):
        dims.append("evidence")
    return dims


def _ref(claim: dict, **extra: Any) -> dict:
    ref = {
        "claim_id": _claim_id(claim),
        "concept": claim.get("concept") or "",
        "version": _version(claim),
    }
    ref.update(extra)
    return ref


# --------------------------------------------------------------------------- #
# Proposal construction (content-addressed, deterministic)
# --------------------------------------------------------------------------- #


def _proposal(
    *,
    kind: str,
    refs: list[dict],
    rationale: str,
    guardrail: str,
    similarity: float | None = None,
    evidence: dict | None = None,
    edges: list[dict] | None = None,
    created_at: str = "",
) -> dict:
    body: dict[str, Any] = {
        "kind": kind,
        "refs": refs,
        "rationale": rationale,
        "guardrail": guardrail,
    }
    if similarity is not None:
        body["similarity"] = round(similarity, 4)
    if evidence is not None:
        body["evidence"] = evidence
    if edges is not None:
        body["edges"] = edges
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
    proposal_id = "dst-" + short_hash(canonical, length=12)
    return {
        "proposal_id": proposal_id,
        **body,
        "status": "proposed",
        "created_at": created_at,
    }


# --------------------------------------------------------------------------- #
# Detectors
# --------------------------------------------------------------------------- #


def detect_duplicates(claims: list[dict], threshold: float, now: str) -> list[dict]:
    """Near-duplicate claim pairs -> merge / needs-review / supersede proposals."""
    claims = sorted((c for c in claims if _claim_text(c)), key=_claim_id)
    if len(claims) < 2:
        return []
    vectors, _ = _tfidf_vectors([_claim_text(c) for c in claims])
    out: list[dict] = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            sim = _cosine(vectors[i], vectors[j])
            if sim < threshold:
                continue
            a, b = claims[i], claims[j]
            dims = _divergent_dims(a, b)
            if not dims:
                out.append(
                    _proposal(
                        kind="merge",
                        refs=[_ref(a), _ref(b)],
                        rationale=(
                            f"Claims {_claim_id(a)} and {_claim_id(b)} are near-duplicates "
                            f"(cosine {sim:.3f}) with identical scope, time, and evidence."
                        ),
                        guardrail=(
                            "safe: same source_ids, same temporal signature, same "
                            "evidence_status — merging loses no distinct provenance."
                        ),
                        similarity=sim,
                        created_at=now,
                    )
                )
            elif dims == ["time"] and _orderable(a, b):
                newer, older = _order_by_year(a, b)
                out.append(
                    _proposal(
                        kind="supersede",
                        refs=[
                            _ref(newer, role="superseding"),
                            _ref(older, role="superseded"),
                        ],
                        rationale=(
                            f"Claim {_claim_id(newer)} restates {_claim_id(older)} "
                            f"(cosine {sim:.3f}) with a newer temporal scope; propose the "
                            "newer supersedes the older."
                        ),
                        guardrail=(
                            "safe: divergence is temporal only and the pair is orderable "
                            "by year; both reciprocal edges are proposed, nothing is deleted."
                        ),
                        similarity=sim,
                        edges=[
                            {
                                "from": _claim_id(newer),
                                "predicate": "supersedes",
                                "to": _claim_id(older),
                            },
                            {
                                "from": _claim_id(older),
                                "predicate": "superseded_by",
                                "to": _claim_id(newer),
                            },
                        ],
                        created_at=now,
                    )
                )
            else:
                out.append(
                    _proposal(
                        kind="needs-review",
                        refs=[_ref(a), _ref(b)],
                        rationale=(
                            f"Claims {_claim_id(a)} and {_claim_id(b)} are textually similar "
                            f"(cosine {sim:.3f}) but diverge in {', '.join(dims)}; a silent "
                            "merge would erase a real distinction."
                        ),
                        guardrail="; ".join(f"divergent-{d}" for d in dims),
                        similarity=sim,
                        evidence={
                            "scope": {
                                _claim_id(a): sorted(_scope_sig(a)),
                                _claim_id(b): sorted(_scope_sig(b)),
                            },
                            "time": {
                                _claim_id(a): list(_time_sig(a)),
                                _claim_id(b): list(_time_sig(b)),
                            },
                            "evidence": {
                                _claim_id(a): _evidence_sig(a),
                                _claim_id(b): _evidence_sig(b),
                            },
                        },
                        created_at=now,
                    )
                )
    return out


def _orderable(a: dict, b: dict) -> bool:
    ya, yb = _dominant_year(a), _dominant_year(b)
    return ya is not None and yb is not None and ya != yb


def _order_by_year(a: dict, b: dict) -> tuple[dict, dict]:
    """Return (newer, older) by dominant year."""
    if (_dominant_year(a) or 0) >= (_dominant_year(b) or 0):
        return a, b
    return b, a


def detect_splits(claims: list[dict], now: str) -> list[dict]:
    """Compound claims -> split proposals (via atomic_claims)."""
    out: list[dict] = []
    for claim in sorted(claims, key=_claim_id):
        text = _claim_text(claim)
        if not text:
            continue
        reasons = atomic_claims.detect_compound(text)
        if not reasons:
            continue
        categories = {r["category"] for r in reasons}
        fragments = atomic_claims.decompose_text(text, categories)
        out.append(
            _proposal(
                kind="split",
                refs=[_ref(claim)],
                rationale=(
                    f"Claim {_claim_id(claim)} is compound "
                    f"({', '.join(sorted(categories))}); propose splitting into atomics."
                ),
                guardrail=(
                    "safe: proposes atomic fragments only; the original prose is not "
                    "rewritten — a human confirms the split."
                    if fragments
                    else "needs-review: compound but not cleanly decomposable — human split."
                ),
                evidence={
                    "reasons": reasons,
                    "fragments": fragments,
                },
                created_at=now,
            )
        )
    return out


def detect_renames(claims: list[dict], now: str) -> list[dict]:
    """Concept names that normalise together -> rename proposals."""
    concepts = sorted({str(c.get("concept") or "") for c in claims if c.get("concept")})
    out: list[dict] = []
    for i in range(len(concepts)):
        for j in range(i + 1, len(concepts)):
            a, b = concepts[i], concepts[j]
            if _concept_key(a) == _concept_key(b):
                # canonical target = the shorter/alphabetically-first spelling
                target, alias = sorted((a, b))
                out.append(
                    _proposal(
                        kind="rename",
                        refs=[
                            {"concept": alias, "role": "alias"},
                            {"concept": target, "role": "target"},
                        ],
                        rationale=(
                            f"Concepts '{alias}' and '{target}' normalise to the same form; "
                            f"propose renaming '{alias}' -> '{target}'."
                        ),
                        guardrail=(
                            "safe: differ only in case / separators / singular-plural; "
                            "a human confirms they are the same concept before any move."
                        ),
                        created_at=now,
                    )
                )
    return out


def _concept_key(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "", name.lower())
    return key[:-1] if key.endswith("s") and len(key) > 3 else key


def detect_archival(claims: list[dict], now: str) -> list[dict]:
    """Stale or already-superseded claims -> archival proposals."""
    out: list[dict] = []
    for claim in sorted(claims, key=_claim_id):
        quality = str(claim.get("claim_quality") or "").lower()
        status = str(claim.get("status") or "").lower()
        superseded_by = claim.get("superseded_by") or []
        reasons = []
        if quality in _STALE_QUALITIES:
            reasons.append(f"claim_quality={quality}")
        if status in _STALE_STATUSES:
            reasons.append(f"status={status}")
        if superseded_by:
            reasons.append(f"superseded_by={list(superseded_by)}")
        if not reasons:
            continue
        out.append(
            _proposal(
                kind="archive",
                refs=[_ref(claim)],
                rationale=(
                    f"Claim {_claim_id(claim)} is stale/superseded ({'; '.join(reasons)}); "
                    "propose archival so it stops corroborating live answers."
                ),
                guardrail=(
                    "safe: archival is a status change proposal; the claim text and its "
                    "provenance are preserved for the record — a human approves."
                ),
                evidence={"reasons": reasons},
                created_at=now,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def build_proposals(
    claims: list[dict],
    *,
    threshold: float = DUP_THRESHOLD,
    now: str = "",
) -> list[dict]:
    """Pure aggregator: claims in, proposals out. Never mutates ``claims``."""
    proposals: list[dict] = []
    proposals += detect_duplicates(claims, threshold, now)
    proposals += detect_splits(claims, now)
    proposals += detect_renames(claims, now)
    proposals += detect_archival(claims, now)
    proposals.sort(key=lambda p: (p["kind"], p["proposal_id"]))
    return proposals


_REVIEW_SEVERITY = {
    "merge": "info",
    "supersede": "info",
    "split": "info",
    "rename": "info",
    "archive": "info",
    "needs-review": "warning",
}

_REVIEW_ACTION = {
    "merge": "Confirm the claims are identical, then approve the merge (or reject).",
    "supersede": "Confirm the ordering, then approve both supersedes/superseded_by edges.",
    "split": "Confirm the atomic fragments, then approve the split into separate claims.",
    "rename": "Confirm the concepts are the same, then approve the rename/move.",
    "archive": "Confirm the claim is stale/superseded, then approve archival.",
    "needs-review": "Adjudicate the divergence — do NOT merge unless it is spurious.",
}


def distillation_review_items(proposals: list[dict]) -> list[dict]:
    """Project proposals into review-queue-shaped worklist items.

    Returns ``{category, severity, ref, detail, action}`` records so a human
    worklist can surface distillation proposals alongside every other signal.
    Does not touch ``review_queue`` — that module stays untouched.
    """
    items: list[dict] = []
    for p in proposals:
        kind = p["kind"]
        items.append(
            {
                "category": f"distillation-{kind}",
                "severity": _REVIEW_SEVERITY.get(kind, "info"),
                "ref": p["proposal_id"],
                "detail": p["rationale"],
                "action": _REVIEW_ACTION.get(kind, "Review the distillation proposal."),
            }
        )
    items.sort(key=lambda it: (it["severity"], it["category"], it["ref"]))
    return items


# --------------------------------------------------------------------------- #
# Registry I/O + CLI
# --------------------------------------------------------------------------- #


def load_claims(path: Path | None = None) -> list[dict]:
    data = load_json(path or CLAIMS_PATH, {"claims": []})
    if isinstance(data, dict):
        return list(data.get("claims", []))
    return list(data or [])


def _reconcile_created_at(proposals: list[dict], existing: list[dict]) -> list[dict]:
    """Preserve the original ``created_at`` for proposals that already exist.

    Keeps each proposal an immutable record: a proposal's timestamp is stamped
    once (when first seen) and never rewritten, so re-runs are stable.
    """
    prior = {p.get("proposal_id"): p.get("created_at", "") for p in existing}
    for p in proposals:
        if p["proposal_id"] in prior and prior[p["proposal_id"]]:
            p["created_at"] = prior[p["proposal_id"]]
    return proposals


def _comparable(proposals: list[dict]) -> list[dict]:
    """Strip ``created_at`` so drift checks ignore first-seen timestamps."""
    return [{k: v for k, v in p.items() if k != "created_at"} for p in proposals]


def run(*, dry_run: bool = False, check: bool = False) -> tuple[list[dict], int]:
    claims = load_claims()
    existing = []
    prev = load_json(PROPOSALS_PATH, None)
    if isinstance(prev, dict):
        existing = list(prev.get("proposals", []))

    stamp = "" if (check or dry_run) else now_stamp()
    proposals = build_proposals(claims, now=stamp)
    proposals = _reconcile_created_at(proposals, existing)

    if check:
        drifted = _comparable(proposals) != _comparable(existing)
        return proposals, (1 if drifted else 0)

    if not dry_run:
        save_json(
            PROPOSALS_PATH,
            {
                "generated_at": now_stamp(),
                "count": len(proposals),
                "threshold": DUP_THRESHOLD,
                "proposals": proposals,
            },
        )
    return proposals, 0


def _print_summary(proposals: list[dict], *, wrote: bool) -> None:
    from collections import Counter

    counts = Counter(p["kind"] for p in proposals)
    if not proposals:
        print("No distillation proposals — the claim graph looks clean.")
        return
    print(f"{len(proposals)} distillation proposal(s):")
    for kind in sorted(counts):
        print(f"  {kind:<12} {counts[kind]}")
    for p in proposals:
        print(f"  [{p['kind']}] {p['proposal_id']}: {p['rationale']}")
        print(f"      guardrail: {p['guardrail']}")
    if wrote:
        print(f"\nWrote {PROPOSALS_PATH}")
    print("\nProposals only — nothing was merged, split, renamed, or archived.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run", action="store_true", help="Compute proposals but do not write the registry."
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the on-disk registry is stale (CI drift gate).",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    args = ap.parse_args(argv)

    proposals, exit_code = run(dry_run=args.dry_run, check=args.check)

    if args.json:
        print(
            json.dumps(
                {"count": len(proposals), "proposals": proposals},
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.check:
        if exit_code:
            print("Distillation proposals are STALE — run 'python -m kops.distillation'.")
        else:
            print("Distillation proposals are up to date.")
    else:
        _print_summary(proposals, wrote=not args.dry_run)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
