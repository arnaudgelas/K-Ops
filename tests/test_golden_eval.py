"""Tests for the rich golden evaluation set and its deterministic grader."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from kops.golden_eval import (
    CATEGORIES,
    REQUIRED_FIELDS,
    RESULT_CATASTROPHIC,
    RESULT_FAIL,
    RESULT_PASS,
    grade_all,
    grade_answer,
    load_golden_set,
    load_registry_ids,
    summarize,
    validate_golden_set,
    verify_source_spans,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SET = ROOT / "research" / "benchmarks" / "held-out" / "golden_set.yaml"
CORPUS = ROOT / "research" / "benchmarks" / "held-out" / "corpus"


@pytest.fixture(scope="module")
def golden():
    return load_golden_set(GOLDEN_SET)


@pytest.fixture(scope="module")
def by_id(golden):
    return {q["id"]: q for q in golden["questions"]}


# ---------------------------------------------------------------------------
# Golden-set structure
# ---------------------------------------------------------------------------


def test_golden_set_parses_and_is_valid(golden):
    assert isinstance(golden.get("questions"), list)
    assert len(golden["questions"]) >= 75
    assert validate_golden_set(golden) == []


def test_all_eight_categories_present(golden):
    present = {q["category"] for q in golden["questions"]}
    assert present == set(CATEGORIES), f"missing/extra: {present ^ set(CATEGORIES)}"


def test_every_question_has_full_schema(golden):
    for q in golden["questions"]:
        for field in REQUIRED_FIELDS:
            assert field in q, f"{q.get('id')} missing {field}"
        assert q["expected_behavior"] in {"answer", "abstain", "qualify"}
        assert q["consequence_tier"] in {
            "exploratory",
            "recommendation",
            "decision",
            "autonomous",
        }


def test_source_spans_are_verbatim_in_corpus(golden):
    # Deterministic spot-check across the whole set (whitespace-normalized).
    errors = verify_source_spans(golden, CORPUS)
    assert errors == [], errors


def test_categories_each_have_multiple_questions(golden):
    from collections import Counter

    counts = Counter(q["category"] for q in golden["questions"])
    for cat in CATEGORIES:
        assert counts[cat] >= 5, f"{cat} only has {counts[cat]} questions"


# ---------------------------------------------------------------------------
# Grader behaviour
# ---------------------------------------------------------------------------


def test_correct_answer_passes(by_id):
    q = by_id["gq-fact-01"]
    answer = "Torque v2.0.0 was the first general availability release, shipped on 2026-01-15."
    result = grade_answer(q, answer)
    assert result["result"] == RESULT_PASS, result


def test_forbidden_conclusion_is_catastrophic(by_id):
    q = by_id["gq-insuf-01"]  # forbidden includes "annual recurring revenue of"
    answer = "Torque Labs' projected annual recurring revenue of $50M ARR for 2027."
    result = grade_answer(q, answer)
    assert result["result"] == RESULT_CATASTROPHIC
    assert "forbidden-conclusion" in result["failures"]
    assert result["dimensions"]["forbidden_violated"]


def test_failure_to_abstain_on_insufficient_evidence_fails(by_id):
    q = by_id["gq-insuf-02"]  # expected_behavior == abstain
    assert q["expected_behavior"] == "abstain"
    answer = "Torque Labs runs its managed service in a major public cloud region."
    result = grade_answer(q, answer)
    assert result["result"] == RESULT_FAIL
    assert "missing-abstention" in result["failures"]


def test_correct_abstention_passes(by_id):
    q = by_id["gq-insuf-02"]
    answer = (
        "This is not answerable from the corpus; there is insufficient evidence "
        "and no cloud provider is named in any source."
    )
    result = grade_answer(q, answer)
    assert result["result"] == RESULT_PASS, result
    assert result["dimensions"]["abstention_detected"] is True


def test_fabricated_citation_is_catastrophic(by_id):
    registry_ids = load_registry_ids(CORPUS)
    assert registry_ids  # sanity
    q = by_id["gq-fact-03"]
    answer = {
        "text": "Torque Labs raised an $18M Series A led by Northwind Ventures.",
        "cited_source_ids": ["src-fac9999999"],  # not in registry
    }
    result = grade_answer(q, answer, registry_ids)
    assert result["result"] == RESULT_CATASTROPHIC
    assert "fabricated-citation" in result["failures"]


def test_contradiction_question_requires_awareness(by_id):
    q = by_id["gq-contra-01"]
    # A confident single-sided answer that ignores the dispute should not pass.
    blind = "Torque definitively provides exactly-once processing semantics."
    result = grade_answer(q, blind)
    assert result["result"] == RESULT_CATASTROPHIC  # hits a forbidden conclusion


def test_grade_all_and_summary_breakdown(golden):
    # Feed a correct abstention for abstain questions and empty otherwise;
    # exercise the aggregation path.
    answers = {}
    for q in golden["questions"]:
        if q["expected_behavior"] == "abstain":
            answers[q["id"]] = {"text": "not answerable — insufficient evidence in the corpus"}
    records = grade_all(golden, answers, load_registry_ids(CORPUS))
    assert len(records) == len(golden["questions"])
    summary = summarize(records)
    assert summary["total"] == len(records)
    assert set(summary["by_category"]) <= set(CATEGORIES)
    assert set(summary["by_tier"])  # non-empty tier breakdown


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_eval_check_validates_golden_set():
    result = subprocess.run(
        [sys.executable, "-m", "kops.kb", "eval-check"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Eval check OK" in result.stdout
    assert "golden_set.yaml" in result.stdout


def test_eval_setup_is_idempotent():
    result = subprocess.run(
        [sys.executable, "-m", "kops.kb", "eval-setup"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "already exists" in result.stdout


def test_golden_eval_module_validation_mode():
    result = subprocess.run(
        [sys.executable, "-m", "kops.golden_eval"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Golden set OK" in result.stdout


# ---------------------------------------------------------------------------
# Regression: `evaluate` dispatch must not crash on its flags
# ---------------------------------------------------------------------------


def test_evaluate_compilation_accepts_dispatch_flags():
    # kb.py's `evaluate` handler forwards --limit/--probe-id/--workers/--verbose
    # to kops.evaluate_compilation; its argparse must accept them (previously
    # only --all was defined, so this raised SystemExit(2)).
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kops.evaluate_compilation",
            "--limit",
            "1",
            "--probe-id",
            "does-not-exist",
            "--workers",
            "3",
            "--verbose",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" not in result.stderr.lower()
