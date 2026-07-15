"""Tests for source-independence lineage (kops/source_lineage.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kops.source_lineage import (
    canonical_root,
    independence_confidence,
    independent_source_ids,
    is_corroborated,
    lineage,
)
from kops.utils import parse_frontmatter

CORPUS_SOURCES = (
    Path(__file__).resolve().parents[1]
    / "research"
    / "benchmarks"
    / "held-out"
    / "corpus"
    / "notes"
    / "Sources"
)


def _corpus_meta() -> dict[str, dict]:
    """Build a ``meta_by_id`` map from the held-out corpus source notes."""
    meta: dict[str, dict] = {}
    if not CORPUS_SOURCES.exists():
        pytest.skip("held-out corpus not present")
    for path in sorted(CORPUS_SOURCES.glob("src-*.md")):
        frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        sid = str(frontmatter.get("source_id") or path.stem)
        meta[sid] = frontmatter
    return meta


# --- Synthetic fixtures (declared provenance only) -------------------------


def _two_independent_primaries() -> dict[str, dict]:
    return {
        "src-aaaaaaaa01": {"source_id": "src-aaaaaaaa01", "tier": "primary"},
        "src-bbbbbbbb02": {"source_id": "src-bbbbbbbb02", "tier": "primary"},
    }


def _chain_abc() -> dict[str, dict]:
    # A derives from B derives from C (root).
    return {
        "src-cccccccc03": {"source_id": "src-cccccccc03", "tier": "primary"},
        "src-bbbbbbbb02": {
            "source_id": "src-bbbbbbbb02",
            "tier": "secondary",
            "derived_from": "src-cccccccc03",
        },
        "src-aaaaaaaa01": {
            "source_id": "src-aaaaaaaa01",
            "tier": "secondary",
            "derived_from": "src-bbbbbbbb02",
        },
    }


def _cycle() -> dict[str, dict]:
    return {
        "src-1111111101": {"source_id": "src-1111111101", "derived_from": "src-2222222202"},
        "src-2222222202": {"source_id": "src-2222222202", "derived_from": "src-1111111101"},
    }


def _synthetic_pair() -> dict[str, dict]:
    # Two model outputs with no independent primary.
    return {
        "src-dddddddd04": {
            "source_id": "src-dddddddd04",
            "evidence_strength": "model-generated",
        },
        "src-eeeeeeee05": {
            "source_id": "src-eeeeeeee05",
            "source_kind": "imported-model-report",
        },
    }


# --- Exit-gate case: the corpus derivative pair ----------------------------


def test_corpus_derivative_pair_collapses_to_one():
    meta = _corpus_meta()
    reps = independent_source_ids(["src-5ec0000012", "src-5ec0000013"], meta)
    assert len(reps) == 1  # both derive from src-fac0000007


def test_corpus_derivative_pair_not_corroborated():
    meta = _corpus_meta()
    assert is_corroborated(["src-5ec0000012", "src-5ec0000013"], meta) is False


def test_corpus_root_resolution():
    meta = _corpus_meta()
    assert canonical_root("src-5ec0000012", meta) == "src-fac0000007"
    assert canonical_root("src-5ec0000013", meta) == "src-fac0000007"
    assert canonical_root("src-fac0000007", meta) == "src-fac0000007"


def test_corpus_lineage_fields():
    meta = _corpus_meta()
    lin = lineage("src-5ec0000012", meta)
    assert lin["canonical_origin"] == "src-fac0000007"
    assert lin["upstream"] == ["src-fac0000007"]
    assert lin["transformation_lineage"] == ["src-5ec0000012", "src-fac0000007"]
    assert lin["synthetic"] is False
    assert lin["tier"] == "secondary"


# --- Independence & corroboration ------------------------------------------


def test_two_independent_primaries_are_corroborated():
    meta = _two_independent_primaries()
    reps = independent_source_ids(["src-aaaaaaaa01", "src-bbbbbbbb02"], meta)
    assert reps == ["src-aaaaaaaa01", "src-bbbbbbbb02"]
    assert is_corroborated(["src-aaaaaaaa01", "src-bbbbbbbb02"], meta) is True


def test_synthetic_pair_not_corroborated():
    meta = _synthetic_pair()
    # Distinct roots, but every witness is declared synthetic -> no independent primary.
    assert is_corroborated(["src-dddddddd04", "src-eeeeeeee05"], meta) is False


def test_summary_and_its_source_not_corroborated():
    # An AI summary derived_from its source collapses to one origin.
    meta = {
        "src-ffffffff06": {"source_id": "src-ffffffff06", "tier": "primary"},
        "src-9999999907": {
            "source_id": "src-9999999907",
            "evidence_strength": "model-generated",
            "derived_from": "src-ffffffff06",
        },
    }
    reps = independent_source_ids(["src-ffffffff06", "src-9999999907"], meta)
    assert len(reps) == 1
    assert is_corroborated(["src-ffffffff06", "src-9999999907"], meta) is False


# --- Chain & cycle safety ---------------------------------------------------


def test_chain_resolves_to_root():
    meta = _chain_abc()
    for sid in ("src-aaaaaaaa01", "src-bbbbbbbb02", "src-cccccccc03"):
        assert canonical_root(sid, meta) == "src-cccccccc03"
    lin = lineage("src-aaaaaaaa01", meta)
    assert lin["transformation_lineage"] == [
        "src-aaaaaaaa01",
        "src-bbbbbbbb02",
        "src-cccccccc03",
    ]
    # Whole A/B/C set collapses to a single independent origin.
    assert len(independent_source_ids(list(meta), meta)) == 1


def test_cycle_is_safe():
    meta = _cycle()
    # Must terminate and return a stable node from the cycle.
    root = canonical_root("src-1111111101", meta)
    assert root in {"src-1111111101", "src-2222222202"}
    # Both members collapse together (never infinite-loop).
    assert len(independent_source_ids(["src-1111111101", "src-2222222202"], meta)) == 1


# --- Confidence -------------------------------------------------------------


def test_confidence_full_for_independent_primaries():
    meta = _two_independent_primaries()
    assert independence_confidence(["src-aaaaaaaa01", "src-bbbbbbbb02"], meta) == 1.0


def test_confidence_lower_for_derivative_and_synthetic():
    corpus = _corpus_meta()
    primaries = _two_independent_primaries()
    synth = _synthetic_pair()

    full = independence_confidence(["src-aaaaaaaa01", "src-bbbbbbbb02"], primaries)
    derivative = independence_confidence(["src-5ec0000012", "src-5ec0000013"], corpus)
    synthetic = independence_confidence(["src-dddddddd04", "src-eeeeeeee05"], synth)

    assert derivative < full
    assert synthetic < full


def test_empty_and_single():
    meta = _two_independent_primaries()
    assert independence_confidence([], meta) == 0.0
    assert is_corroborated([], meta) is False
    assert is_corroborated(["src-aaaaaaaa01"], meta) is False


# --- Determinism ------------------------------------------------------------


def test_determinism():
    meta = _corpus_meta()
    ids = ["src-5ec0000013", "src-5ec0000012", "src-fac0000007"]
    first = independent_source_ids(ids, meta)
    for _ in range(5):
        assert independent_source_ids(list(reversed(ids)), meta) == first
        assert independence_confidence(ids, meta) == independence_confidence(ids, meta)
