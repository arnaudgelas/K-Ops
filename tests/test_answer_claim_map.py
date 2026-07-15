"""Tests for kops.answer_claim_map (M2 C2.2)."""

from __future__ import annotations

from kops.answer_claim_map import validate_answer_claim_map
from kops.evidence_model import ContextPackage

C1 = "clm-1111111111"
C2 = "clm-2222222222"
EXCLUDED = "clm-3333333333"
UNKNOWN = "clm-4444444444"


def _package(tier: str = "decision") -> ContextPackage:
    return ContextPackage(
        question="Does Torque guarantee exactly-once delivery?",
        tier=tier,
        claim_ids=(C1, C2),
        excluded_claims=(
            {"claim_id": EXCLUDED, "concept": "X", "reasons": ["admission:quarantine"]},
        ),
        source_version_ids=("srcv-aaaaaaaaaa", "srcv-bbbbbbbbbb"),
    )


def _answer(*sentences: str) -> str:
    body = "\n".join(sentences)
    return f"# Question\nq\n\n# Answer\n{body}\n"


def test_correct_answer_is_valid():
    ans = _answer(
        f"Torque guarantees exactly-once delivery in production [{C1}].",
        f"The engine persists offsets to durable storage on commit [{C2}].",
    )
    result = validate_answer_claim_map(ans, _package("decision"))
    assert result["valid"] is True
    assert result["reliance"] == [C1, C2]
    assert result["violations"] == []


def test_unknown_claim_is_rejected():
    ans = _answer(f"Torque scales to five million events per second [{UNKNOWN}].")
    result = validate_answer_claim_map(ans, _package("decision"))
    assert result["valid"] is False
    assert any(v["kind"] == "unknown-claim" for v in result["violations"])


def test_uncited_factual_sentence_rejected_at_decision_but_advisory_at_exploratory():
    ans = _answer("Torque uses a custom columnar storage engine for durability.")
    strict = validate_answer_claim_map(ans, _package("decision"), tier="decision")
    assert strict["valid"] is False
    assert any(v["kind"] == "uncited-factual-sentence" for v in strict["violations"])

    lenient = validate_answer_claim_map(ans, _package("exploratory"), tier="exploratory")
    assert lenient["valid"] is True
    assert any(w["kind"] == "uncited-factual-sentence" for w in lenient["warnings"])


def test_empty_reliance_set_rejected_for_non_exploratory():
    # A hedge-only answer has no factual sentences -> no empty-reliance violation.
    hedge = _answer("I could not find evidence about the 2027 revenue.")
    assert validate_answer_claim_map(hedge, _package("decision"))["valid"] is True

    # A factual answer that relies on nothing in the package is refused.
    ans = _answer("Torque is written in the Rust programming language for speed.")
    result = validate_answer_claim_map(ans, _package("decision"))
    assert result["valid"] is False
    kinds = {v["kind"] for v in result["violations"]}
    assert "uncited-factual-sentence" in kinds


def test_empty_reliance_set_branch_isolated():
    # A factual sentence that DOES cite a valid package claim keeps the
    # uncited-factual branch silent, so the empty-reliance-set branch only
    # fires when the overall reliance set is empty. Here reliance is non-empty,
    # so the answer is valid — proving empty-reliance-set is not spuriously raised.
    ok = _answer(f"Torque guarantees exactly-once delivery in production [{C1}].")
    assert validate_answer_claim_map(ok, _package("decision"))["valid"] is True

    # Now an answer whose only cited id is NOT in the package: every factual
    # sentence is 'unknown-claim' AND the reliance set is empty -> both fire.
    ans = _answer(f"Torque scales to five million events per second [{UNKNOWN}].")
    result = validate_answer_claim_map(ans, _package("decision"))
    kinds = {v["kind"] for v in result["violations"]}
    assert "empty-reliance-set" in kinds
    assert "unknown-claim" in kinds


def test_citing_an_excluded_claim_is_rejected():
    ans = _answer(f"Torque throughput exceeds all competitors by a wide margin [{EXCLUDED}].")
    result = validate_answer_claim_map(ans, _package("recommendation"), tier="recommendation")
    assert result["valid"] is False
    assert any(v["kind"] == "excluded-claim" for v in result["violations"])


def test_source_version_change_is_rejected():
    ans = _answer(f"Torque guarantees exactly-once delivery in production [{C1}].")
    # The package froze srcv-aaaaaaaaaa/srcv-bbbbbbbbbb; now bbbb is superseded.
    current = ["srcv-aaaaaaaaaa", "srcv-cccccccccc"]
    result = validate_answer_claim_map(ans, _package("decision"), current_source_versions=current)
    assert result["valid"] is False
    assert any(v["kind"] == "source-version-changed" for v in result["violations"])


def test_deterministic():
    ans = _answer(f"Torque guarantees exactly-once delivery in production [{C1}].")
    pkg = _package("decision")
    assert validate_answer_claim_map(ans, pkg) == validate_answer_claim_map(ans, pkg)
