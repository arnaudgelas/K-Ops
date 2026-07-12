"""Pure tests for kops.loop_controller — the loop controller policy."""

from __future__ import annotations

from kops import loop_controller as lc

_ALL_PRESENT = {"span_verification": True, "claims": True, "contradictions": True}
_ZERO_SIGNALS = {"failed_quote_spans": 0, "blocked_claims": 0}


def _item(severity, category="x", ref="r", detail="d", action="a"):
    return {
        "severity": severity,
        "category": category,
        "ref": ref,
        "detail": detail,
        "action": action,
    }


def test_converged_when_nothing_open():
    v = lc.assess([], _ZERO_SIGNALS, _ALL_PRESENT)
    assert v["status"] == "converged"
    assert v["converged"] is True
    assert v["safe_to_stop"] is True
    assert v["next_action"] is None


def test_cleanup_when_only_warnings():
    items = [_item("warning", "unsupported-claim"), _item("info", "knowledge-gap")]
    v = lc.assess(items, _ZERO_SIGNALS, _ALL_PRESENT)
    assert v["status"] == "cleanup"
    assert v["converged"] is False
    assert v["safe_to_stop"] is True  # warnings do not block
    assert v["next_action"]["category"] == "unsupported-claim"


def test_blocking_on_error_item():
    items = [_item("error", "failed-quote-span"), _item("warning", "unsupported-claim")]
    v = lc.assess(items, _ZERO_SIGNALS, _ALL_PRESENT)
    assert v["status"] == "blocking"
    assert v["safe_to_stop"] is False
    # next action is the highest-severity item (error, listed first)
    assert v["next_action"]["category"] == "failed-quote-span"
    assert any("error-severity" in r for r in v["blocking_reasons"])


def test_blocking_on_error_signal_even_without_error_items():
    # No error items, but the signal vector shows a failed span => still blocking.
    v = lc.assess([_item("warning")], {"failed_quote_spans": 1, "blocked_claims": 0}, _ALL_PRESENT)
    assert v["status"] == "blocking"
    assert any("failed_quote_spans" in r for r in v["blocking_reasons"])


def test_blocking_on_missing_artifact():
    v = lc.assess([], _ZERO_SIGNALS, {**_ALL_PRESENT, "claims": False})
    assert v["status"] == "blocking"
    assert any("claims" in r for r in v["blocking_reasons"])
    # no items, so no next action, but still not safe to stop
    assert v["next_action"] is None
    assert v["safe_to_stop"] is False


def test_next_action_carries_command_hint():
    v = lc.assess([_item("error", "blocked-claim")], _ZERO_SIGNALS, _ALL_PRESENT)
    assert v["next_action"]["command_hint"] is not None
    assert "retract" in v["next_action"]["command_hint"]


def test_remaining_counts_by_severity():
    items = [_item("error"), _item("warning"), _item("warning"), _item("info")]
    v = lc.assess(items, _ZERO_SIGNALS, _ALL_PRESENT)
    assert v["remaining"] == {"error": 1, "warning": 2, "info": 1}
