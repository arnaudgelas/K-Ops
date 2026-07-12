"""Pure tests for kops.inner_loop.assess_write (the inner-loop verify core)."""

from __future__ import annotations

from kops import inner_loop as il

_AVAIL = {"span_verification": True, "claims": True, "contradictions": True}


def _snap(signals, availability=None):
    return {"signals": signals, "availability": availability or dict(_AVAIL)}


def test_clean_write_does_not_regress():
    before = _snap({"failed_quote_spans": 0, "blocked_claims": 0})
    after = _snap({"failed_quote_spans": 0, "blocked_claims": 0})
    r = il.assess_write(before, after)
    assert r["regressed"] is False
    assert r["reasons"] == []


def test_new_failed_span_is_a_regression():
    before = _snap({"failed_quote_spans": 0, "blocked_claims": 0})
    after = _snap({"failed_quote_spans": 1, "blocked_claims": 0})
    r = il.assess_write(before, after)
    assert r["regressed"] is True
    assert any("failed_quote_spans" in reason for reason in r["reasons"])


def test_new_blocked_claim_is_a_regression():
    before = _snap({"failed_quote_spans": 0, "blocked_claims": 0})
    after = _snap({"failed_quote_spans": 0, "blocked_claims": 2})
    r = il.assess_write(before, after)
    assert r["regressed"] is True


def test_warning_only_change_is_not_a_regression():
    before = _snap({"failed_quote_spans": 0, "unsupported_claims": 0})
    after = _snap({"failed_quote_spans": 0, "unsupported_claims": 4})
    r = il.assess_write(before, after)
    # unsupported_claims is a warning-class signal — reported in delta, not a regression
    assert r["regressed"] is False
    assert r["delta"]["unsupported_claims"]["change"] == 4


def test_artifact_disappearing_during_write_is_a_regression():
    before = _snap({"blocked_claims": 3}, {**_AVAIL, "claims": True})
    after = _snap({"blocked_claims": 0}, {**_AVAIL, "claims": False})  # claims.json vanished
    r = il.assess_write(before, after)
    # blocked_claims went DOWN (looks like improvement) but the artifact vanished -> regression
    assert r["regressed"] is True
    assert any("claims" in reason for reason in r["reasons"])
