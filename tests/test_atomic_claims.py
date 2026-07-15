"""Tests for compound-claim detection and decomposition (task D1.2).

Pure and self-contained: no real vault is read; ``--check`` is driven against a
tmp claims file.
"""

from __future__ import annotations

import json

import pytest

from kops.atomic_claims import (
    COMPARISON_CAUSAL,
    MIXED_TEMPORAL,
    MULTI_PREDICATE,
    PARENT_CHILD_RELATION,
    RECOMMENDATION_FACT,
    analyze_claim,
    detect_compound,
    run,
    to_atomic_claim,
)
from kops.evidence_model import AtomicClaim


def _categories(text: str) -> set[str]:
    return {r["category"] for r in detect_compound(text)}


# --------------------------------------------------------------------------- #
# Detection: one category per compound kind
# --------------------------------------------------------------------------- #


def test_detects_multiple_predicates():
    text = "The compiler writes concept pages and the linter checks structural consistency."
    assert MULTI_PREDICATE in _categories(text)


def test_detects_multiple_predicates_semicolon():
    text = "Ingest writes raw evidence; compile writes source summaries."
    assert MULTI_PREDICATE in _categories(text)


def test_detects_mixed_temporal():
    text = "Revenue reached $1M in 2020 and $5M in 2023."
    cats = _categories(text)
    assert MIXED_TEMPORAL in cats
    # The "$5M in 2023" tail is not an independent clause, so it must NOT also
    # be mis-detected as multi-predicate.
    assert MULTI_PREDICATE not in cats


def test_detects_comparison_plus_causal():
    text = "Method A is faster than Method B because it caches results."
    assert _categories(text) == {COMPARISON_CAUSAL}


def test_detects_recommendation_plus_fact():
    text = "Teams should adopt the linter because it catches 90% of contradictions."
    assert RECOMMENDATION_FACT in _categories(text)
    assert COMPARISON_CAUSAL not in _categories(text)


# --------------------------------------------------------------------------- #
# False-positive guardrails: genuinely atomic claims are NOT flagged
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "The baseline workflow is ingest, compile, lint.",
        # Noun-list conjunction, not two clauses.
        "Compile writes source summaries and concept pages.",
        "The linter checks structural consistency.",
        # Comma list with a trailing "and" that is still a noun phrase.
        "The research workflow is multi-phase, with collect, review, report, and archive steps.",
        # Bare recommendation with no supporting fact.
        "Teams should run lint after structural edits.",
        # A single temporal reference is fine.
        "Adoption reached 60% by 2024.",
        "Method A caches results.",
    ],
)
def test_atomic_claims_not_flagged(text):
    result = analyze_claim({"claim_id": "clm-x", "claim_text": text, "concept": "C"})
    assert result["atomic"] is True, result["reasons"]
    assert result["reasons"] == []
    assert result["sub_claims"] == []
    assert result["needs_review"] is False


# --------------------------------------------------------------------------- #
# Decomposition with parent provenance
# --------------------------------------------------------------------------- #


def test_decomposes_multiple_predicates_with_provenance():
    claim = {
        "claim_id": "clm-parent",
        "claim_text": (
            "The compiler writes concept pages and the linter checks structural consistency."
        ),
        "concept": "Workflow_Pattern_Inventory",
        "source_ids": ["src-1f2a3b4c5d"],
        "source_anchors": [{"source_id": "src-1f2a3b4c5d", "anchor": "L1"}],
        "evidence_status": "direct",
        "admission_status": "admitted",
    }
    result = analyze_claim(claim)
    assert result["atomic"] is False
    assert result["needs_review"] is False

    subs = result["sub_claims"]
    assert [s["claim_text"] for s in subs] == [
        "The compiler writes concept pages.",
        "The linter checks structural consistency.",
    ]
    for sub in subs:
        # Provenance back to the parent via the evidence-model edge vocabulary.
        assert sub["parent_claim_id"] == "clm-parent"
        assert sub["derived_from"] == "clm-parent"
        assert sub["relation"] == PARENT_CHILD_RELATION
        # Sub-claims keep the parent's source provenance and are AtomicClaim-shaped.
        assert sub["source_ids"] == ["src-1f2a3b4c5d"]
        assert sub["claim_id"].startswith("clm-")
        assert sub["claim_id"] != "clm-parent"
        atomic = to_atomic_claim(sub)
        assert isinstance(atomic, AtomicClaim)
        assert atomic.claim_text == sub["claim_text"]
        assert atomic.source_ids == ("src-1f2a3b4c5d",)


def test_decomposes_comparison_plus_causal():
    claim = {
        "claim_id": "clm-cc",
        "claim_text": "Method A is faster than Method B because it caches results.",
        "concept": "C",
    }
    result = analyze_claim(claim)
    assert result["atomic"] is False
    assert [s["claim_text"] for s in result["sub_claims"]] == [
        "Method A is faster than Method B.",
        "It caches results.",
    ]


def test_decomposes_recommendation_plus_fact():
    claim = {
        "claim_id": "clm-rf",
        "claim_text": "Teams should adopt the linter because it catches 90% of contradictions.",
        "concept": "C",
    }
    result = analyze_claim(claim)
    assert result["atomic"] is False
    assert [s["claim_text"] for s in result["sub_claims"]] == [
        "Teams should adopt the linter.",
        "It catches 90% of contradictions.",
    ]


# --------------------------------------------------------------------------- #
# Conservative behavior: ambiguous compound -> flag-for-review, not mis-split
# --------------------------------------------------------------------------- #


def test_ambiguous_mixed_temporal_is_flagged_for_review():
    # Two temporal scopes but a single clause with no clean split boundary.
    claim = {
        "claim_id": "clm-amb",
        "claim_text": "The metric improved from 2019 through 2024.",
        "concept": "C",
    }
    result = analyze_claim(claim)
    assert result["atomic"] is False
    assert MIXED_TEMPORAL in {r["category"] for r in result["reasons"]}
    # Conservative: no mangled sub-claims, hand it to review instead.
    assert result["sub_claims"] == []
    assert result["needs_review"] is True


# --------------------------------------------------------------------------- #
# Typed AtomicClaim input works too
# --------------------------------------------------------------------------- #


def test_accepts_atomic_claim_instances():
    claim = AtomicClaim.from_registry_dict(
        {
            "claim_id": "clm-typed",
            "claim_text": "The linter checks consistency and the compiler writes pages.",
            "concept": "C",
            "source_ids": ["src-aaaaaaaaaa"],
        }
    )
    result = analyze_claim(claim)
    assert result["atomic"] is False
    assert result["sub_claims"]
    assert all(s["parent_claim_id"] == "clm-typed" for s in result["sub_claims"])


# --------------------------------------------------------------------------- #
# --check mode
# --------------------------------------------------------------------------- #


def test_check_exits_nonzero_when_compound_present(tmp_path, capsys):
    payload = {
        "count": 2,
        "claims": [
            {"claim_id": "clm-ok", "claim_text": "The linter checks consistency.", "concept": "C"},
            {
                "claim_id": "clm-bad",
                "claim_text": ("The compiler writes pages and the linter checks consistency."),
                "concept": "C",
            },
        ],
    }
    path = tmp_path / "claims.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        run(check=True, claims_path=path)
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "clm-bad" in out


def test_check_passes_when_all_atomic(tmp_path):
    payload = {
        "claims": [
            {"claim_id": "clm-ok", "claim_text": "The linter checks consistency.", "concept": "C"},
        ]
    }
    path = tmp_path / "claims.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    # Should not raise.
    results = run(check=True, claims_path=path)
    assert all(r["atomic"] for r in results)
