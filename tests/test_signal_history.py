"""Pure, no-vault tests for kops.signal_history."""

from __future__ import annotations

import kops.signal_history as sh


# ── signal_vector_from_artifacts ─────────────────────────────────────────────


def test_vector_from_synthetic_artifacts():
    span = {"summary": {"failed": 2, "unverifiable": 3}}
    claims = {
        "claims": [
            {"admission_status": "blocked"},
            {"admission_status": "blocked"},
            {"admission_status": "quarantine"},
            {"admission_status": "admitted", "evidence_status": "unsupported"},
            {"admission_status": "admitted", "evidence_status": "direct"},
        ]
    }
    contradictions = {
        "contradictions": [
            {"documented": False},
            {"documented": True},
            {"documented": False},
        ]
    }
    vector = sh.signal_vector_from_artifacts(span, claims, contradictions)
    assert vector == {
        "failed_quote_spans": 2,
        "unverifiable_quote_spans": 3,
        "blocked_claims": 2,
        "quarantined_claims": 1,
        "unsupported_claims": 1,
        "undocumented_contradictions": 2,
    }


def test_vector_none_artifacts_all_zero():
    vector = sh.signal_vector_from_artifacts(None, None, None)
    assert set(vector) == set(sh.SIGNAL_KEYS)
    assert all(v == 0 for v in vector.values())


def test_vector_missing_keys_default_zero():
    # Present-but-empty artifacts still yield zeros.
    vector = sh.signal_vector_from_artifacts({}, {}, {})
    assert all(v == 0 for v in vector.values())


def test_undocumented_counts_absent_and_null_documented():
    # Match review_queue.py: absent / null / falsy `documented` all count as undocumented.
    contradictions = {
        "contradictions": [
            {"documented": False},
            {},  # absent
            {"documented": None},  # null
            {"documented": True},  # documented => not counted
        ]
    }
    vector = sh.signal_vector_from_artifacts(None, None, contradictions)
    assert vector["undocumented_contradictions"] == 3


# ── delta ────────────────────────────────────────────────────────────────────


def test_delta_prev_curr_change_and_new_signal():
    prev = {"failed_quote_spans": 1, "removed_signal": 4}
    curr = {"failed_quote_spans": 3, "new_signal": 2}
    d = sh.delta(prev, curr)
    # keys are the sorted union
    assert list(d) == sorted(["failed_quote_spans", "removed_signal", "new_signal"])
    # changed signal
    assert d["failed_quote_spans"] == {"prev": 1, "curr": 3, "change": 2}
    # a signal present only in curr (prev None => change None) = "new"
    assert d["new_signal"] == {"prev": None, "curr": 2, "change": None}
    # a signal present only in prev (removed) => curr defaults to 0
    assert d["removed_signal"] == {"prev": 4, "curr": 0, "change": -4}


def test_delta_prev_none_all_new():
    curr = {"failed_quote_spans": 1, "blocked_claims": 0}
    d = sh.delta(None, curr)
    assert d["failed_quote_spans"] == {"prev": None, "curr": 1, "change": None}
    assert d["blocked_claims"] == {"prev": None, "curr": 0, "change": None}


# ── detect_regression ────────────────────────────────────────────────────────


def test_regression_error_signal_increase_is_hard():
    prev = {"failed_quote_spans": 0, "blocked_claims": 0}
    curr = {"failed_quote_spans": 1, "blocked_claims": 0}
    is_reg, reasons = sh.detect_regression(prev, curr)
    assert is_reg is True
    assert any("failed_quote_spans" in r for r in reasons)


def test_regression_warning_only_increase_is_not_hard():
    prev = {"unsupported_claims": 0, "quarantined_claims": 0}
    curr = {"unsupported_claims": 5, "quarantined_claims": 3}
    is_reg, reasons = sh.detect_regression(prev, curr)
    assert is_reg is False
    assert reasons == []


def test_regression_all_equal_is_false():
    prev = {"failed_quote_spans": 2, "blocked_claims": 1}
    curr = {"failed_quote_spans": 2, "blocked_claims": 1}
    assert sh.detect_regression(prev, curr) == (False, [])


def test_regression_decrease_is_false():
    prev = {"failed_quote_spans": 3, "blocked_claims": 2}
    curr = {"failed_quote_spans": 1, "blocked_claims": 0}
    assert sh.detect_regression(prev, curr) == (False, [])


def test_regression_prev_none_is_false():
    curr = {"failed_quote_spans": 9, "blocked_claims": 9}
    assert sh.detect_regression(None, curr) == (False, [])


# ── availability regression (anti-gaming guardrail) ──────────────────────────


def test_availability_regression_present_to_absent_is_hard():
    prev = {"span_verification": True, "claims": True, "contradictions": True}
    curr = {"span_verification": True, "claims": False, "contradictions": True}
    is_reg, reasons = sh.detect_availability_regression(prev, curr)
    assert is_reg is True
    assert any("claims" in r for r in reasons)


def test_availability_regression_absent_to_present_is_false():
    assert sh.detect_availability_regression({"claims": False}, {"claims": True}) == (False, [])


def test_availability_regression_stays_absent_is_false():
    assert sh.detect_availability_regression({"claims": False}, {"claims": False}) == (False, [])


def test_availability_regression_prev_none_is_false():
    # A fresh vault with no prior record cannot regress on availability.
    assert sh.detect_availability_regression(None, {"claims": False}) == (False, [])


# ── build_record ─────────────────────────────────────────────────────────────


def test_build_record_shape():
    vector = {k: i for i, k in enumerate(sh.SIGNAL_KEYS)}
    record = sh.build_record(vector, availability={"claims": True})
    assert record["recorded_at"]
    assert "git_commit" in record
    assert record["signals"] == vector
    assert record["availability"] == {"claims": True}
    assert record["total"] == sum(vector.values())


# ── record_signals / load_history roundtrip ──────────────────────────────────


def test_record_and_load_roundtrip(tmp_path, monkeypatch):
    hist = tmp_path / "signals.jsonl"
    monkeypatch.setattr(sh, "HISTORY_PATH", hist)

    assert sh.load_history() == []
    assert sh.load_last() is None

    v1 = {k: 0 for k in sh.SIGNAL_KEYS}
    v2 = {**v1, "failed_quote_spans": 1}
    r1 = sh.record_signals(v1)
    r2 = sh.record_signals(v2)

    history = sh.load_history()
    assert len(history) == 2
    assert history[0]["signals"] == v1
    assert history[1]["signals"] == v2
    assert history[0] == r1
    assert history[1] == r2
    assert sh.load_last()["signals"] == v2


def test_load_history_skips_blank_and_corrupt(tmp_path, monkeypatch):
    hist = tmp_path / "signals.jsonl"
    hist.write_text(
        '{"signals": {"failed_quote_spans": 1}}\n'
        "\n"
        "not json at all\n"
        '{"signals": {"failed_quote_spans": 2}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(sh, "HISTORY_PATH", hist)
    history = sh.load_history()
    assert len(history) == 2
    assert history[0]["signals"]["failed_quote_spans"] == 1
    assert history[1]["signals"]["failed_quote_spans"] == 2
