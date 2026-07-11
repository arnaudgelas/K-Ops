"""Tests for span_verify.py — deterministic quote-span verification."""

from __future__ import annotations

from kops import span_verify


# ---------------------------------------------------------------------------
# match_quote — the deterministic core
# ---------------------------------------------------------------------------

SOURCE = (
    "The baseline repository workflow is ingest or refresh, then compile, then "
    "extract-claims, extract-contradictions, heal, lint, and scorecard."
)


def test_exact_substring_matches():
    assert span_verify.match_quote("then compile, then", SOURCE) == "exact"


def test_whitespace_is_normalized():
    # Source has been re-wrapped: newlines/extra spaces should not break the match.
    quote = "ingest or refresh,\n   then    compile"
    assert span_verify.match_quote(quote, SOURCE) == "normalized"


def test_smart_punctuation_is_folded():
    source = "The model is “grounded” and well—tested."
    quote = 'The model is "grounded" and well-tested.'
    assert span_verify.match_quote(quote, source) == "normalized"


def test_ellipsis_bridge_matches_when_both_fragments_present_in_order():
    quote = "baseline repository workflow … heal, lint, and scorecard"
    assert span_verify.match_quote(quote, SOURCE) == "ellipsis"


def test_ellipsis_fragments_out_of_order_fail():
    quote = "heal, lint, and scorecard … baseline repository workflow"
    assert span_verify.match_quote(quote, SOURCE) is None


def test_absent_quote_fails():
    assert span_verify.match_quote("this phrase is nowhere in the source", SOURCE) is None


def test_too_short_normalized_quote_is_rejected():
    # A fragment shorter than the min length must not count as evidence unless verbatim.
    # "compile" is < _MIN_QUOTE_LEN and appears verbatim -> exact still allowed.
    assert span_verify.match_quote("compile", SOURCE) == "exact"
    # But a short quote that only matches after normalization must be rejected.
    assert span_verify.match_quote("the AI", "the  AI wins") is None


def test_empty_inputs_fail():
    assert span_verify.match_quote("", SOURCE) is None
    assert span_verify.match_quote("something", "") is None


# ---------------------------------------------------------------------------
# verify_claim — aggregation over a claim's anchors
# ---------------------------------------------------------------------------


def _claim(claim_id: str, anchors: list[dict]) -> dict:
    return {"claim_id": claim_id, "concept": "Test_Concept", "source_anchors": anchors}


def test_claim_with_matching_quote_is_verified():
    claim = _claim("clm-1", [{"source_id": "src-a", "quote": "then compile, then"}])
    result = span_verify.verify_claim(claim, lambda sid: SOURCE)
    assert result["span_verification"] == "verified"
    assert result["anchors"][0]["match_kind"] == "exact"


def test_claim_with_absent_quote_fails_closed():
    claim = _claim("clm-2", [{"source_id": "src-a", "quote": "fabricated supporting text"}])
    result = span_verify.verify_claim(claim, lambda sid: SOURCE)
    assert result["span_verification"] == "failed"
    assert result["anchors"][0]["status"] == "failed"


def test_claim_without_quote_anchor_is_absent():
    claim = _claim("clm-3", [{"source_id": "src-a", "quote": None, "page": 12}])
    result = span_verify.verify_claim(claim, lambda sid: SOURCE)
    assert result["span_verification"] == "absent"
    assert result["quote_anchor_count"] == 0


def test_claim_with_unresolvable_source_is_unverifiable():
    claim = _claim("clm-4", [{"source_id": "src-missing", "quote": "then compile, then"}])
    result = span_verify.verify_claim(claim, lambda sid: None)
    assert result["span_verification"] == "unverifiable"


def test_failure_dominates_unverifiable():
    # One anchor fails, one is unresolvable -> the claim must surface as failed.
    def resolver(source_id: str):
        return SOURCE if source_id == "src-a" else None

    claim = _claim(
        "clm-5",
        [
            {"source_id": "src-a", "quote": "not in the source at all"},
            {"source_id": "src-missing", "quote": "then compile, then"},
        ],
    )
    result = span_verify.verify_claim(claim, resolver)
    assert result["span_verification"] == "failed"


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


def test_build_report_summarizes_and_rates():
    results = [
        {"span_verification": "verified"},
        {"span_verification": "verified"},
        {"span_verification": "failed"},
        {"span_verification": "absent"},
        {"span_verification": "unverifiable"},
    ]
    report = span_verify.build_report(results)
    assert report["summary"] == {
        "verified": 2,
        "failed": 1,
        "unverifiable": 1,
        "absent": 1,
    }
    # rate is over resolvable (verified + failed) = 2/3
    assert report["quote_verification_rate"] == 0.667


def test_build_report_rate_none_when_nothing_verifiable():
    report = span_verify.build_report([{"span_verification": "absent"}])
    assert report["quote_verification_rate"] is None
