"""Pure tests for kops.consequence_gate — the escalating evidence-bar policy."""

from __future__ import annotations

import pytest

from kops import consequence_gate as cg


def _claim(
    cid="clm-1",
    concept="C",
    admission="admitted",
    evidence="direct",
    quality="supported",
    synthetic=False,
):
    return {
        "claim_id": cid,
        "concept": concept,
        "admission_status": admission,
        "evidence_status": evidence,
        "claim_quality": quality,
        "synthetic_origin": synthetic,
    }


def _reasons(claim, tier):
    return cg._violations_for_claim(claim, tier)


# ── exploratory: no bar ──────────────────────────────────────────────────────


def test_exploratory_allows_anything():
    bad = _claim(admission="blocked", evidence="unsupported", quality="weak", synthetic=True)
    assert _reasons(bad, "exploratory") == []
    assert cg.assess_claims([bad], "exploratory")["allowed"] is True


# ── recommendation: only bars blocked sources ────────────────────────────────


def test_recommendation_bars_blocked_only():
    assert _reasons(_claim(admission="blocked"), "recommendation") == ["blocked-source"]
    # quarantined / provisional are allowed at recommendation
    assert _reasons(_claim(admission="quarantine"), "recommendation") == []
    assert _reasons(_claim(quality="provisional"), "recommendation") == []


# ── decision: admitted + non-weak/conflicting/stale/synthetic ────────────────


def test_decision_bars_quarantine_unsupported_and_weak():
    assert "admission:quarantine" in _reasons(_claim(admission="quarantine"), "decision")
    assert "unsupported-evidence" in _reasons(_claim(evidence="unsupported"), "decision")
    assert "claim-quality:conflicting" in _reasons(_claim(quality="conflicting"), "decision")
    assert "synthetic-origin" in _reasons(_claim(synthetic=True), "decision")


def test_decision_allows_provisional_and_inherited():
    # provisional quality and page-inherited evidence are acceptable for a decision
    assert _reasons(_claim(quality="provisional", evidence="inherited"), "decision") == []


# ── autonomous: strongest bar ────────────────────────────────────────────────


def test_autonomous_requires_admitted_direct_supported():
    # provisional + inherited cleared 'decision' but must fail 'autonomous'
    r = _reasons(_claim(quality="provisional", evidence="inherited"), "autonomous")
    assert "evidence-not-direct:inherited" in r
    assert "quality-not-supported:provisional" in r
    # the gold-standard claim clears autonomous
    assert _reasons(_claim(), "autonomous") == []


# ── aggregate + escalation monotonicity ──────────────────────────────────────


def test_assess_reports_usable_counts():
    claims = [_claim(cid="ok"), _claim(cid="bad", admission="blocked")]
    result = cg.assess_claims(claims, "recommendation")
    assert result["allowed"] is False
    assert result["total_claims"] == 2 and result["usable_claims"] == 1
    assert result["violations"][0]["claim_id"] == "bad"


def test_bar_is_monotonic_non_decreasing():
    # a claim that fails a lower tier must also fail every higher tier
    claim = _claim(admission="blocked")
    for lo, hi in [("recommendation", "decision"), ("decision", "autonomous")]:
        assert _reasons(claim, lo) and _reasons(claim, hi)


def test_unknown_tier_raises():
    with pytest.raises(ValueError):
        cg.assess_claims([_claim()], "yolo")
