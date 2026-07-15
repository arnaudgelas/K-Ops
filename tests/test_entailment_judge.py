"""Tests for the pure entailment judge (roadmap J1.1).

The provider is always a stubbed CLI pointed at by ``KB_JUDGE_CMD`` (the same
technique ``tests/test_runners.py`` uses); no real LLM is ever invoked.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from kops import entailment_judge as ej
from kops.entailment_judge import (
    ENTAILMENT_POLICY_VERSION,
    NOT_EVALUABLE,
    EntailmentCache,
    judge,
    judge_batch,
)
from kops.evidence_model import AtomicClaim, SourceSpan
from kops.evidence_store import EvidenceStore
from kops.runners import JudgeError

# --------------------------------------------------------------------------- #
# Stub provider helpers
# --------------------------------------------------------------------------- #


def _write_stub(tmp_path: Path, name: str, body: str) -> str:
    script = tmp_path / name
    script.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    return f"{sys.executable} {script}"


# A stub that returns a fixed verdict AND appends to a counter file every call,
# so a test can assert exactly how many times the provider was invoked.
def _counting_stub_body(counter_path: Path, verdict: str = "supported") -> str:
    return f"""
import json
with open({str(counter_path)!r}, "a") as fh:
    fh.write("x")
print(json.dumps({{
    "verdict": {verdict!r},
    "rationale": "the span states the claim verbatim",
    "missing_information": [],
}}))
"""


def _use_stub(monkeypatch, cmd: str) -> None:
    monkeypatch.setenv("KB_JUDGE_CMD", cmd)
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")


def _claim(text: str = "K-Ops caches entailment verdicts.") -> AtomicClaim:
    return AtomicClaim(claim_id="clm-test01", claim_text=text, concept="Entailment")


def _span(quote: str = "K-Ops caches entailment verdicts by content hash.") -> SourceSpan:
    return SourceSpan(source_id="src-1", quote=quote, section="Design")


def _call_count(counter_path: Path) -> int:
    return len(counter_path.read_text()) if counter_path.exists() else 0


# --------------------------------------------------------------------------- #
# Happy path: full structured result
# --------------------------------------------------------------------------- #


def test_judge_returns_full_structured_result(tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _use_stub(monkeypatch, _write_stub(tmp_path, "ok.py", _counting_stub_body(counter)))
    cache = EntailmentCache(tmp_path / "cache")

    result = judge(_claim(), _span(), cache=cache)

    assert result.verdict == "supported"
    assert result.rationale
    assert result.claim_hash and len(result.claim_hash) == 64
    assert result.span_hash and len(result.span_hash) == 64
    assert result.claim_hash != result.span_hash
    assert len(result.judge_prompt_fingerprint) == 64
    assert result.policy_version == ENTAILMENT_POLICY_VERSION
    assert result.cached is False
    # to_dict carries the full roadmap shape.
    d = result.to_dict()
    for key in (
        "verdict",
        "rationale",
        "missing_information",
        "judge_model",
        "judge_prompt_fingerprint",
        "claim_hash",
        "span_hash",
        "policy_version",
    ):
        assert key in d
    assert _call_count(counter) == 1


# --------------------------------------------------------------------------- #
# not_evaluable stays first-class and visible
# --------------------------------------------------------------------------- #


def test_missing_span_is_not_evaluable_without_provider(tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _use_stub(monkeypatch, _write_stub(tmp_path, "ok.py", _counting_stub_body(counter)))
    cache = EntailmentCache(tmp_path / "cache")

    result = judge(_claim(), None, cache=cache)

    assert result.verdict == NOT_EVALUABLE
    assert result.claim_id == "clm-test01"
    assert result.span_hash == ""
    assert "exact evidence span" in result.missing_information
    # Provider never invoked for a not_evaluable determination.
    assert _call_count(counter) == 0


def test_span_without_quote_is_not_evaluable(tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _use_stub(monkeypatch, _write_stub(tmp_path, "ok.py", _counting_stub_body(counter)))
    cache = EntailmentCache(tmp_path / "cache")

    empty = SourceSpan(source_id="src-1", quote="   ", section="Design")
    result = judge(_claim(), empty, cache=cache)

    assert result.verdict == NOT_EVALUABLE
    assert _call_count(counter) == 0


def test_compound_claim_is_not_evaluable(tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _use_stub(monkeypatch, _write_stub(tmp_path, "ok.py", _counting_stub_body(counter)))
    cache = EntailmentCache(tmp_path / "cache")

    compound = AtomicClaim(
        claim_id="clm-cmp",
        claim_text="Caching improves latency and the judge writes verdicts to disk.",
        concept="Entailment",
    )
    result = judge(compound, _span(), cache=cache)

    assert result.verdict == NOT_EVALUABLE
    assert "not atomic" in result.rationale
    assert _call_count(counter) == 0


def test_not_evaluable_stays_visible_in_batch(tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _use_stub(monkeypatch, _write_stub(tmp_path, "ok.py", _counting_stub_body(counter)))
    cache = EntailmentCache(tmp_path / "cache")

    pairs = [
        (_claim("K-Ops caches entailment verdicts."), _span()),
        (_claim("A claim with no span."), None),
    ]
    results = judge_batch(pairs, cache=cache)

    assert len(results) == 2  # every input yields exactly one verdict
    verdicts = [r.verdict for r in results]
    assert "supported" in verdicts
    assert NOT_EVALUABLE in verdicts


# --------------------------------------------------------------------------- #
# Caching semantics
# --------------------------------------------------------------------------- #


def test_second_identical_judgement_hits_cache(tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _use_stub(monkeypatch, _write_stub(tmp_path, "ok.py", _counting_stub_body(counter)))
    cache = EntailmentCache(tmp_path / "cache")

    first = judge(_claim(), _span(), cache=cache)
    second = judge(_claim(), _span(), cache=cache)

    assert first.verdict == second.verdict == "supported"
    assert first.cached is False
    assert second.cached is True
    # Provider invoked exactly once despite two judgements.
    assert _call_count(counter) == 1


def test_changing_span_reinvokes_provider(tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _use_stub(monkeypatch, _write_stub(tmp_path, "ok.py", _counting_stub_body(counter)))
    cache = EntailmentCache(tmp_path / "cache")

    judge(_claim(), _span("quote A about caching verdicts by content hash."), cache=cache)
    judge(_claim(), _span("quote B is a completely different sentence."), cache=cache)

    assert _call_count(counter) == 2  # different span_hash -> fresh judgement


def test_changing_policy_version_reinvokes_provider(tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _use_stub(monkeypatch, _write_stub(tmp_path, "ok.py", _counting_stub_body(counter)))
    cache = EntailmentCache(tmp_path / "cache")

    judge(_claim(), _span(), cache=cache)
    assert _call_count(counter) == 1

    # A policy bump must invalidate the prior verdict.
    monkeypatch.setattr(ej, "ENTAILMENT_POLICY_VERSION", "9.9.9")
    judge(_claim(), _span(), cache=cache)
    assert _call_count(counter) == 2


# --------------------------------------------------------------------------- #
# Schema-invalid provider output propagates as JudgeError
# --------------------------------------------------------------------------- #


def test_schema_invalid_output_raises(tmp_path, monkeypatch):
    body = "import json\nprint(json.dumps({'verdict': 'maybe-ish'}))\n"
    _use_stub(monkeypatch, _write_stub(tmp_path, "bad.py", body))
    cache = EntailmentCache(tmp_path / "cache")

    with pytest.raises(JudgeError):
        judge(_claim(), _span(), cache=cache)


def test_non_json_output_raises(tmp_path, monkeypatch):
    _use_stub(monkeypatch, _write_stub(tmp_path, "junk.py", "print('not json')\n"))
    cache = EntailmentCache(tmp_path / "cache")

    with pytest.raises(JudgeError):
        judge(_claim(), _span(), cache=cache)


# --------------------------------------------------------------------------- #
# The judge cannot write to the repo
# --------------------------------------------------------------------------- #


def test_judge_does_not_touch_the_repo(tmp_path, monkeypatch):
    # A stub that tries to write a marker into its cwd; judge_run confines it to
    # a throwaway temp dir, so the repo working tree must be unchanged.
    body = """
import json, os
open("JUDGE_TRIED_TO_WRITE", "w").write("marker")
print(json.dumps({"verdict": "supported", "rationale": "ok", "missing_information": []}))
"""
    _use_stub(monkeypatch, _write_stub(tmp_path, "writer.py", body))
    cache = EntailmentCache(tmp_path / "cache")

    repo_root = Path(__file__).resolve().parents[1]
    before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    ).stdout

    judge(_claim(), _span(), cache=cache)

    after = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    ).stdout
    assert before == after
    assert not (repo_root / "JUDGE_TRIED_TO_WRITE").exists()


# --------------------------------------------------------------------------- #
# Optional ValidationEvent recording ties into the audit trail
# --------------------------------------------------------------------------- #


def test_records_validation_event_when_store_given(tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _use_stub(monkeypatch, _write_stub(tmp_path, "ok.py", _counting_stub_body(counter)))
    cache = EntailmentCache(tmp_path / "cache")
    store = EvidenceStore(base_dir=tmp_path / "evidence", history_dir=tmp_path / "history")

    result = judge(_claim(), _span(), cache=cache, store=store)

    events = store.validation_events(target_id="clm-test01")
    assert len(events) == 1
    event = events[0]
    assert event.validator == "entailment_judge"
    assert event.result == result.verdict
    assert event.policy_version == ENTAILMENT_POLICY_VERSION
    assert event.model == result.judge_model


# --------------------------------------------------------------------------- #
# Cache is content-addressed and reloadable across cache instances
# --------------------------------------------------------------------------- #


def test_cache_persists_across_instances(tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _use_stub(monkeypatch, _write_stub(tmp_path, "ok.py", _counting_stub_body(counter)))

    cache_dir = tmp_path / "cache"
    judge(_claim(), _span(), cache=EntailmentCache(cache_dir))
    # A fresh cache object over the same directory still hits.
    judge(_claim(), _span(), cache=EntailmentCache(cache_dir))

    assert _call_count(counter) == 1
    files = list(cache_dir.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["cached"] is True
