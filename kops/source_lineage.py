"""Source-independence lineage — count INDEPENDENT sources, not derivative copies.

Corroboration in the tier policy (``kops/tier_policy.py``) historically asked a
naive question: "does this claim cite at least two distinct ``source_ids``?" That
is wrong whenever two of those sources are not independent — e.g. two blogs that
both quote a single vendor benchmark, or an AI summary paired with the source it
summarizes. Counting them as two independent witnesses manufactures corroboration
that does not exist.

This module resolves declared source lineage and collapses derivative copies so
that corroboration counts genuinely independent origins. It relies ONLY on
**declared / known provenance** carried in source-note frontmatter:

- ``derived_from`` — this source's immediate upstream source_id (a copy/summary
  chain). Transitively followed to a canonical root.
- ``tier`` — ``primary`` | ``secondary`` (declared).
- ``publisher`` — declared publisher/organization, when present.
- ``evidence_strength: model-generated`` / ``source_kind: imported-model-report``
  — declared synthetic (model-generated) origin.
- ``synthetic_origin: true`` — an explicit synthetic marker, when present.

It deliberately does **not** attempt to detect undeclared AI-generated text or
infer hidden shared sources. Independence here means "no declared shared upstream
and no declared synthetic origin", not "provably distinct in reality".

Two sources are NOT independent corroboration when any of these declared
conditions hold (encoded as deterministic rules below):

- they share a canonical ``derived_from`` root (two articles repeating one press
  release; multiple pages copied from one upstream);
- one is ``derived_from`` the other (an AI summary and its source);
- the only witnesses are synthetic (model outputs with no independent primary).
"""

from __future__ import annotations

from typing import Any

# Declared synthetic-origin signals (evidence_strength / source_kind values).
_SYNTHETIC_STRENGTHS = frozenset({"model-generated"})
_SYNTHETIC_KINDS = frozenset({"imported-model-report", "imported_model_report"})

# Tier ranking for deterministic representative selection (lower = preferred).
_TIER_RANK = {"primary": 0, "secondary": 1}


def _meta_for(meta_by_id: dict[str, dict] | None) -> dict[str, dict]:
    """Resolve the source-metadata map, loading from the vault when not injected."""
    if meta_by_id is not None:
        return meta_by_id
    # Imported lazily so tests can inject ``meta_by_id`` without touching the vault
    # and so this module has no import-time dependency on registry configuration.
    from kops.claim_registry import _load_source_metadata_by_id

    return _load_source_metadata_by_id()


def _is_declared_synthetic(frontmatter: dict[str, Any]) -> bool:
    if not frontmatter:
        return False
    if frontmatter.get("synthetic_origin") is True:
        return True
    if str(frontmatter.get("evidence_strength") or "") in _SYNTHETIC_STRENGTHS:
        return True
    if str(frontmatter.get("source_kind") or "") in _SYNTHETIC_KINDS:
        return True
    return False


def _declared_tier(frontmatter: dict[str, Any]) -> str:
    """Declared tier, falling back to an evidence-strength inference."""
    tier = frontmatter.get("tier")
    if tier:
        return str(tier)
    strength = str(frontmatter.get("evidence_strength") or "")
    if strength in {"primary-doc", "official-spec", "strong", "code", "maintainer-commentary"}:
        return "primary"
    if strength in {"secondary"}:
        return "secondary"
    return "unknown"


def _chain(source_id: str, meta_by_id: dict[str, dict]) -> tuple[list[str], bool]:
    """The ``derived_from`` path from ``source_id`` up to its root, cycle-safe.

    Returns ``([source_id, parent, ..., root], cycled)``. On a ``derived_from``
    loop the walk stops at the node that would repeat, so the path is always
    finite and ``cycled`` is ``True``.
    """
    path: list[str] = []
    seen: set[str] = set()
    current = str(source_id)
    while current not in seen:
        path.append(current)
        seen.add(current)
        frontmatter = meta_by_id.get(current) or {}
        parent = frontmatter.get("derived_from")
        if parent is None:
            return path, False
        parent = str(parent)
        if parent == current:
            return path, False
        current = parent
    return path, True


def canonical_root(source_id: str, meta_by_id: dict[str, dict] | None = None) -> str:
    """Follow ``derived_from`` transitively to the upstream root source_id.

    Cycle-safe: a ``derived_from`` loop has no well-defined root, so it resolves
    deterministically to the lexicographically smallest node in the loop (making
    every member of the cycle collapse to the same origin).
    """
    meta = _meta_for(meta_by_id)
    path, cycled = _chain(source_id, meta)
    return min(path) if cycled else path[-1]


def lineage(source_id: str, meta_by_id: dict[str, dict] | None = None) -> dict[str, Any]:
    """Resolve declared lineage for a single source.

    Fields:
    - ``publisher`` — declared publisher/organization, or ``None``.
    - ``upstream`` — the ``derived_from`` ancestors (parent .. root), excluding self.
    - ``canonical_origin`` — the root source_id of the derivation chain.
    - ``transformation_lineage`` — full path ``[self, parent, ..., root]``.
    - ``synthetic`` — True if this source or any ancestor declares a synthetic
      (model-generated) origin.
    - ``tier`` — this source's declared tier (``primary`` | ``secondary`` | ...).
    """
    meta = _meta_for(meta_by_id)
    sid = str(source_id)
    frontmatter = meta.get(sid) or {}
    path, cycled = _chain(sid, meta)
    root = min(path) if cycled else path[-1]
    publisher = frontmatter.get("publisher") or frontmatter.get("organization")
    synthetic = any(_is_declared_synthetic(meta.get(node) or {}) for node in path)
    return {
        "source_id": sid,
        "publisher": str(publisher) if publisher else None,
        "upstream": path[1:],
        "canonical_origin": root,
        "transformation_lineage": path,
        "synthetic": synthetic,
        "tier": _declared_tier(frontmatter),
    }


def _rep_sort_key(source_id: str, meta_by_id: dict[str, dict]) -> tuple:
    """Deterministic preference for a group's representative source.

    Prefer the canonical root itself, then non-synthetic, then primary tier, then
    the lexicographically smallest source_id.
    """
    lin = lineage(source_id, meta_by_id)
    return (
        0 if source_id == lin["canonical_origin"] else 1,
        0 if not lin["synthetic"] else 1,
        _TIER_RANK.get(lin["tier"], 2),
        source_id,
    )


def independent_source_ids(
    source_ids: list[str], meta_by_id: dict[str, dict] | None = None
) -> list[str]:
    """Collapse a source set to one representative per independent origin.

    Sources that share a canonical ``derived_from`` root (or where one is derived
    from another) collapse to a single representative. Genuinely distinct origins
    stay distinct. The result is sorted and deterministic.
    """
    meta = _meta_for(meta_by_id)
    groups: dict[str, list[str]] = {}
    for sid in {str(s) for s in source_ids}:
        groups.setdefault(canonical_root(sid, meta), []).append(sid)
    representatives = [
        min(members, key=lambda s: _rep_sort_key(s, meta)) for members in groups.values()
    ]
    return sorted(representatives)


def independence_confidence(
    source_ids: list[str], meta_by_id: dict[str, dict] | None = None
) -> float:
    """Confidence (0..1) that a source set provides independent corroboration.

    Lower when sources share upstreams (derivative copies collapse), when the
    independent witnesses are synthetic, or when there is no independent primary
    evidence. 1.0 for two-or-more genuinely independent primaries.
    """
    meta = _meta_for(meta_by_id)
    unique = sorted({str(s) for s in source_ids})
    if not unique:
        return 0.0

    reps = independent_source_ids(unique, meta)
    n_indep = len(reps)
    n_total = len(unique)

    # 1. Collapse factor: derivative copies that fold into one origin reduce trust.
    collapse = n_indep / n_total

    # 2. Independence factor: two independent witnesses are needed for full credit.
    independence = 1.0 if n_indep >= 2 else 0.5 * n_indep

    # 3. Primary-evidence factor: fraction of independent origins backed by a
    #    non-synthetic primary source (kept above zero so a lone declared source
    #    still earns partial credit).
    primary_backed = 0
    for rep in reps:
        lin = lineage(rep, meta)
        root_fm = meta.get(lin["canonical_origin"]) or {}
        if not lin["synthetic"] and _declared_tier(root_fm) != "unknown":
            primary_backed += 1
    primary_fraction = primary_backed / n_indep if n_indep else 0.0
    primary_factor = 0.4 + 0.6 * primary_fraction

    return round(independence * collapse * primary_factor, 4)


def is_corroborated(
    source_ids: list[str],
    meta_by_id: dict[str, dict] | None = None,
    *,
    min_independent: int = 2,
) -> bool:
    """Deterministic corroboration predicate over declared provenance.

    Replaces the naive ``len(set(source_ids)) >= 2`` count. Corroboration requires
    at least ``min_independent`` independent origins that are each declared
    non-synthetic. Encodes the roadmap's "not independent corroboration" rules:

    - two articles repeating one press release / pages copied from one upstream:
      they share a canonical root, collapse to one origin, and fail the count;
    - an AI summary and its source: one is ``derived_from`` the other, they
      collapse, and fail the count;
    - model outputs with no independent primary: every independent origin is
      synthetic, so none count as independent primary evidence.
    """
    meta = _meta_for(meta_by_id)
    reps = independent_source_ids(source_ids, meta)
    independent_declared = [r for r in reps if not lineage(r, meta)["synthetic"]]
    return len(independent_declared) >= min_independent


def _main(argv: list[str] | None = None) -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Inspect declared source lineage and independence.",
    )
    parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        default=[],
        metavar="src-...",
        help="A source_id to inspect (repeatable).",
    )
    parser.add_argument(
        "--min-independent",
        type=int,
        default=2,
        help="Independent-origin threshold for corroboration (default: 2).",
    )
    args = parser.parse_args(argv)

    meta = _meta_for(None)
    sources = [str(s) for s in args.sources]
    report: dict[str, Any] = {
        "lineage": {sid: lineage(sid, meta) for sid in sources},
    }
    if sources:
        report["independent_source_ids"] = independent_source_ids(sources, meta)
        report["independence_confidence"] = independence_confidence(sources, meta)
        report["is_corroborated"] = is_corroborated(
            sources, meta, min_independent=args.min_independent
        )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    _main()
