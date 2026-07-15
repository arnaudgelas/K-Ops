"""Tests for the entailment judge calibration harness (roadmap J1.2).

No real LLM is ever invoked: predictions are either an injected deterministic
stub or the sandboxed ``KB_JUDGE_CMD`` stub (the same technique the J1.1 judge
tests use). No agreement or accuracy number is fabricated by the harness.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from kops import judge_calibration as jc
from kops.entailment_judge import VERDICTS
from kops.judge_calibration import (
    ADVERSARIAL_TYPES,
    CalibrationResult,
    LabeledPair,
    cohen_kappa,
    confusion_matrix,
    detect_drift,
    false_support,
    inter_annotator_agreement,
    load_labeled_set,
    run_calibration,
    validate_coverage,
    write_report,
)

# --------------------------------------------------------------------------- #
# 1. The shipped labeled set parses and is category-complete
# --------------------------------------------------------------------------- #


def test_labeled_set_parses_and_is_category_complete():
    pairs = load_labeled_set()
    assert len(pairs) >= 50  # at least the debug slice
    # every gold verdict is in the enum
    for p in pairs:
        assert p.gold_verdict in VERDICTS
    cov = validate_coverage(pairs)
    # every adversarial failure type from the roadmap is present
    assert cov["all_adversarial_types_present"], cov["adversarial_types_missing"]
    present = {p.adversarial_type for p in pairs if p.adversarial_type}
    for adv in ADVERSARIAL_TYPES:
        assert adv in present
    # the seed set is honestly BELOW the decision-gate size
    assert not cov["meets_decision_gate_size"]
    # straightforward verdict families are all represented
    golds = {p.gold_verdict for p in pairs}
    assert {"supported", "unsupported", "contradicted", "not_evaluable", "partial"} <= golds


def test_every_pair_has_stable_id_and_claim_text():
    pairs = load_labeled_set()
    ids = [p.pair_id for p in pairs]
    assert len(ids) == len(set(ids))  # unique
    assert all(p.claim_text for p in pairs)


# --------------------------------------------------------------------------- #
# Synthetic labeled pairs + a stub predictor with KNOWN outputs
# --------------------------------------------------------------------------- #


def _pair(pid: str, gold: str, claim_type: str = "t", adv: str | None = None) -> LabeledPair:
    return LabeledPair(
        pair_id=pid,
        claim_type=claim_type,
        category="adversarial" if adv else gold,
        adversarial_type=adv,
        claim_text=f"claim {pid}",
        claim_id=f"clm-{pid}",
        span={"source_id": "src-x", "quote": f"quote {pid}", "section": "S"},
        context="",
        source_metadata={},
        gold_verdict=gold,
    )


def _synthetic_set():
    # gold / predicted pairs are chosen so every asserted cell is hand-checked.
    pairs = [
        _pair("p1", "supported"),
        _pair("p2", "unsupported"),
        _pair("p3", "contradicted"),
        _pair("p4", "not_evaluable"),
        _pair("p5", "unsupported"),
    ]
    predicted = {
        "p1": "supported",  # correct
        "p2": "supported",  # FALSE SUPPORT (gold unsupported)
        "p3": "contradicted",  # correct
        "p4": "partial",  # FALSE SUPPORT (gold not_evaluable)
        "p5": "unsupported",  # correct
    }
    return pairs, (lambda pair: predicted[pair.pair_id])


# --------------------------------------------------------------------------- #
# 2. Confusion matrix + false-support rate on a known set
# --------------------------------------------------------------------------- #


def test_confusion_matrix_exact_cells():
    pairs, predict = _synthetic_set()
    result = run_calibration(pairs, predict, judge_fingerprint="fp-test")
    cm = result.confusion_overall
    assert cm["supported"]["supported"] == 1
    assert cm["unsupported"]["supported"] == 1  # p2 false support
    assert cm["unsupported"]["unsupported"] == 1  # p5
    assert cm["contradicted"]["contradicted"] == 1
    assert cm["not_evaluable"]["partial"] == 1  # p4 false support
    # every declared cell exists (explicit zeros)
    for g in VERDICTS:
        for p in VERDICTS:
            assert isinstance(cm[g][p], int)
    # untouched cell is a real zero
    assert cm["supported"]["contradicted"] == 0


def test_false_support_rate_known_value():
    pairs, predict = _synthetic_set()
    result = run_calibration(pairs, predict, judge_fingerprint="fp-test")
    fs = result.false_support
    # 4 gold-negative cases (p2,p3,p4,p5); 2 called supportive (p2,p4)
    assert fs["n_gold_negative"] == 4
    assert fs["n_false_support"] == 2
    assert fs["false_support_rate"] == pytest.approx(0.5)
    assert set(fs["offending_pair_ids"]) == {"p2", "p4"}


def test_false_support_helper_direct():
    rows = [
        {"pair_id": "a", "gold": "unsupported", "predicted": "partial", "correct": False},
        {"pair_id": "b", "gold": "contradicted", "predicted": "contradicted", "correct": True},
        {"pair_id": "c", "gold": "supported", "predicted": "supported", "correct": True},
    ]
    fs = false_support(rows)
    assert fs["n_gold_negative"] == 2  # a, b
    assert fs["n_false_support"] == 1  # a
    assert fs["false_support_rate"] == pytest.approx(0.5)


def test_confusion_matrix_helper_zero_fill():
    cm = confusion_matrix([("supported", "supported")])
    assert cm["supported"]["supported"] == 1
    assert cm["contradicted"]["partial"] == 0


def test_agreement_overall_and_per_adversarial():
    pairs = [
        _pair("a1", "unsupported", adv="partial-quote"),
        _pair("a2", "unsupported", adv="partial-quote"),
        _pair("a3", "contradicted", adv="reversed-causality"),
    ]
    predicted = {"a1": "unsupported", "a2": "supported", "a3": "contradicted"}
    result = run_calibration(pairs, lambda p: predicted[p.pair_id], judge_fingerprint="fp")
    assert result.agreement_overall["n"] == 3
    assert result.agreement_overall["n_correct"] == 2
    pq = result.agreement_by_adversarial["partial-quote"]
    assert pq["n"] == 2 and pq["n_correct"] == 1
    rc = result.agreement_by_adversarial["reversed-causality"]
    assert rc["n"] == 1 and rc["n_correct"] == 1


# --------------------------------------------------------------------------- #
# 3. Cohen's kappa + PENDING inter-annotator handling
# --------------------------------------------------------------------------- #


def test_cohen_kappa_hand_checked():
    # Textbook 2-category example: p_o=0.75, p_e=0.5 -> kappa=0.5.
    a = ["yes", "yes", "no", "no"]
    b = ["yes", "no", "no", "no"]
    assert cohen_kappa(a, b) == pytest.approx(0.5)


def test_cohen_kappa_perfect_agreement():
    assert cohen_kappa(["x", "y", "x"], ["x", "y", "x"]) == pytest.approx(1.0)


def test_cohen_kappa_single_label_perfect():
    # Only one label used by both -> chance agreement is total; defined as 1.0.
    assert cohen_kappa(["x", "x"], ["x", "x"]) == pytest.approx(1.0)


def test_cohen_kappa_length_mismatch():
    with pytest.raises(ValueError):
        cohen_kappa(["a"], ["a", "b"])


def test_inter_annotator_pending_when_absent():
    res = inter_annotator_agreement(None)
    assert res["status"] == "PENDING"
    assert res["cohen_kappa"] is None
    assert "PENDING: 2 human annotations required" in res["message"]


def test_inter_annotator_pending_with_one_file(tmp_path):
    f = tmp_path / "ann1.jsonl"
    f.write_text(json.dumps({"pair_id": "p1", "verdict": "supported"}) + "\n", encoding="utf-8")
    res = inter_annotator_agreement([f])
    assert res["status"] == "PENDING"
    assert res["provided"] == 1


def test_inter_annotator_computed_from_two_files(tmp_path):
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    a.write_text(
        "\n".join(
            json.dumps({"pair_id": pid, "verdict": v})
            for pid, v in [("p1", "yes"), ("p2", "yes"), ("p3", "no"), ("p4", "no")]
        ),
        encoding="utf-8",
    )
    b.write_text(
        "\n".join(
            json.dumps({"pair_id": pid, "verdict": v})
            for pid, v in [("p1", "yes"), ("p2", "no"), ("p3", "no"), ("p4", "no")]
        ),
        encoding="utf-8",
    )
    res = inter_annotator_agreement([a, b])
    assert res["status"] == "computed"
    assert res["n_items"] == 4
    assert res["cohen_kappa"] == pytest.approx(0.5)
    assert res["raw_agreement"] == pytest.approx(0.75)


# --------------------------------------------------------------------------- #
# 4. Drift detection
# --------------------------------------------------------------------------- #


def test_detect_drift_flags_fingerprint_change():
    pairs, predict = _synthetic_set()
    r1 = run_calibration(pairs, predict, judge_fingerprint="fp-A")
    r2 = run_calibration(pairs, predict, judge_fingerprint="fp-B")
    drift = detect_drift(r1.run_metadata(), r2.run_metadata())
    assert drift["drifted"] is True
    fields = {c["field"] for c in drift["changes"]}
    assert "judge_fingerprint" in fields


def test_detect_drift_flags_policy_change():
    drift = detect_drift(
        {"policy_version": "1.0.0", "judge_fingerprint": "fp"},
        {"policy_version": "2.0.0", "judge_fingerprint": "fp"},
    )
    assert drift["drifted"] is True
    assert drift["changes"][0]["field"] == "policy_version"


def test_detect_drift_no_change():
    meta = {"policy_version": "1.0.0", "judge_fingerprint": "fp"}
    drift = detect_drift(meta, dict(meta))
    assert drift["drifted"] is False
    assert drift["changes"] == []


# --------------------------------------------------------------------------- #
# 5. Report artifact + end-to-end with the sandboxed stub judge (no real LLM)
# --------------------------------------------------------------------------- #


def test_write_report_creates_dated_artifacts_and_drift(tmp_path):
    pairs, predict = _synthetic_set()
    out = tmp_path / "eval_runs"
    r1 = run_calibration(pairs, predict, judge_fingerprint="fp-A", run_date="2026-07-15")
    p1 = write_report(r1, out, date="2026-07-15")
    assert p1.exists()
    assert (out / "entailment-calibration-20260715.md").exists()
    meta = json.loads(p1.read_text().splitlines()[0])
    assert meta["record_type"] == "calibration_run"
    assert meta["false_support"]["false_support_rate"] == pytest.approx(0.5)

    # a second, later run with a different fingerprint records drift vs the first
    r2 = run_calibration(pairs, predict, judge_fingerprint="fp-B", run_date="2026-07-16")
    p2 = write_report(r2, out, date="2026-07-16")
    meta2 = json.loads(p2.read_text().splitlines()[0])
    assert meta2["drift_vs_previous"]["drifted"] is True


def _write_stub(tmp_path: Path, verdict: str) -> str:
    payload = json.dumps({"verdict": verdict, "rationale": "stub", "missing_information": []})
    script = tmp_path / "stub.py"
    script.write_text(
        "#!/usr/bin/env python3\nprint(" + repr(payload) + ")\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {script}"


def test_default_runner_uses_sandboxed_stub_and_records_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_JUDGE_CMD", _write_stub(tmp_path, "supported"))
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")
    runner = jc.JudgeRunner(cache_dir=tmp_path / "cache")
    pair = _pair("s1", "supported")
    predicted = runner.predict(pair)
    assert predicted == "supported"
    assert runner.fingerprints  # a provider was invoked
    assert runner.fingerprint() != "no-provider-invoked"


def test_run_calibration_default_predictor_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_JUDGE_CMD", _write_stub(tmp_path, "unsupported"))
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")
    pairs = [_pair("s1", "unsupported"), _pair("s2", "supported")]
    result = run_calibration(pairs)  # default runner -> real judge via stub
    assert isinstance(result, CalibrationResult)
    assert result.provider_invoked is True
    assert result.judge_fingerprint != "no-provider-invoked"
    # stub always says unsupported: s1 correct, s2 wrong
    assert result.agreement_overall["n_correct"] == 1


def test_coverage_only_cli(capsys):
    rc = jc.main(["--coverage-only"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["all_adversarial_types_present"] is True
    assert out["n_pairs"] >= 50
