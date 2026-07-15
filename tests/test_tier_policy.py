"""Tests for kops.tier_policy (M2 C2.3)."""

from __future__ import annotations

from kops.tier_policy import evaluate_tier_policy


def _claim(
    cid, adm="admitted", ev="direct", quality="supported", sources=("src-a", "src-b"), conflicts=()
):
    return {
        "claim_id": cid,
        "admission_status": adm,
        "evidence_status": ev,
        "claim_quality": quality,
        "source_ids": list(sources),
        "conflicts_with": list(conflicts),
        "synthetic_origin": False,
    }


def test_exploratory_permits_everything():
    claims = [_claim("c1", adm="quarantine", ev="unsupported", quality="weak")]
    result = evaluate_tier_policy(claims, "exploratory")
    assert result["decision"] == "permit"
    assert result["entailment_treatment"] == "advisory"
    assert result["barred"] == []


def test_decision_permits_clean_claim():
    result = evaluate_tier_policy([_claim("c1")], "decision")
    assert result["decision"] == "permit"
    assert result["allowed_claim_ids"] == ["c1"]


def test_entailment_gates_at_decision_but_warns_at_recommendation():
    claims = [_claim("c1")]
    ent = {"c1": "unsupported"}

    decision = evaluate_tier_policy(claims, "decision", entailment=ent)
    assert decision["decision"] == "abstain"  # only claim barred -> nothing allowed
    assert any("entailment:unsupported" in b["reasons"] for b in decision["barred"])

    rec = evaluate_tier_policy(claims, "recommendation", entailment=ent)
    assert rec["decision"] == "permit"  # entailment is a warning, not a bar
    assert rec["allowed_claim_ids"] == ["c1"]
    assert any(w["kind"] == "entailment" for w in rec["warnings"])


def test_stale_source_barred_at_decision_not_exploratory():
    claims = [_claim("fresh"), _claim("stale", sources=("src-x", "src-b"))]
    fresh = {"src-x": "drifted"}  # 'stale' claim rests on a drifted source

    dec = evaluate_tier_policy(claims, "decision", freshness=fresh)
    assert dec["decision"] == "permit"  # 'fresh' still usable
    assert dec["requires_human_override"] is True
    barred_ids = {b["claim_id"] for b in dec["barred"]}
    assert "stale" in barred_ids
    assert any(
        "stale-source:src-x" in b["reasons"] for b in dec["barred"] if b["claim_id"] == "stale"
    )

    exp = evaluate_tier_policy(claims, "exploratory", freshness=fresh)
    assert exp["barred"] == []


def test_unresolved_contradiction_forces_qualify_at_decision():
    claims = [_claim("c1", conflicts=("c9",))]
    result = evaluate_tier_policy(claims, "decision")
    assert result["decision"] == "qualify"
    assert result["allowed_claim_ids"] == ["c1"]


def test_autonomous_fails_closed_without_corroboration():
    # A perfect claim but backed by a single source -> needs corroboration -> refuse.
    result = evaluate_tier_policy([_claim("c1", sources=("src-a",))], "autonomous")
    assert result["decision"] == "refuse"
    assert any("needs-corroboration" in b["reasons"] for b in result["barred"])


def test_autonomous_permits_corroborated_supported_claim():
    result = evaluate_tier_policy(
        [_claim("c1", sources=("src-a", "src-b"))], "autonomous", entailment={"c1": "supported"}
    )
    assert result["decision"] == "permit"
    assert result["allowed_claim_ids"] == ["c1"]


def test_autonomous_refuses_on_contradiction():
    result = evaluate_tier_policy([_claim("c1", conflicts=("c9",))], "autonomous")
    assert result["decision"] == "refuse"


def test_invalid_tier_raises():
    import pytest

    with pytest.raises(ValueError):
        evaluate_tier_policy([], "bogus")


def test_deterministic():
    claims = [_claim("c1"), _claim("c2", adm="quarantine")]
    assert evaluate_tier_policy(claims, "decision") == evaluate_tier_policy(claims, "decision")
