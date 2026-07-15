"""Tests for the published benchmark report renderer (roadmap task L4.4).

Covers:
* the Wilson score CI against a hand-checked reference value;
* that every required section heading and the governance headline numbers render;
* that the two M4 differentiation demonstrations show REAL decision flips computed
  from the live modules (not hardcoded prose);
* determinism (same report -> byte-identical Markdown, no timestamps);
* that answer-quality numbers are labelled pending-real-llm, not a proven win.

No real LLM or network is touched; the sample report is a hand-built dict and the
M4 demos run over the real held-out corpus / M4 modules (all deterministic).
"""

from __future__ import annotations

import math

from kops import benchmark_report

BASELINES = ["raw-agent", "bm25-agent", "current-kops", "improved-kops"]


def _sample_report() -> dict:
    """A compact but structurally complete benchmark report dict."""

    def gov(revoked, flagged, fa, fr):
        return {
            "_status": "real-deterministic",
            "revoked_source_leakage": revoked,
            "flagged_source_leakage": flagged,
            "decision_gate_false_accept": fa,
            "decision_gate_false_reject": fr,
            "stale_answer_leakage": 0,
            "time_to_invalidate": "immediate",
        }

    def retr(recall, cov, irr):
        return {
            "recall_at_k": recall,
            "evidence_coverage": cov,
            "irrelevant_context_rate": irr,
        }

    def ops(review):
        return {
            "latency_ms": 123.4,  # volatile — must not appear in the body
            "token_usage": None,
            "model_cost_usd": 0.0,
            "review_minutes_per_accepted_answer": review,
        }

    return {
        "schema_version": "1.0.0",
        "harness_policy_version": "1.0.0",
        "generated_at": "2026-07-15T10:42:00",  # volatile — must not appear
        "corpus": "corpus",
        "snapshot": "03-retraction",
        "provider": {"name": "deterministic", "fingerprint": "det-abc123"},
        "question_count": 84,
        "baselines": list(BASELINES),
        "top_k": 8,
        "metrics": {
            "retrieval": {
                "raw-agent": retr(0.0, 0.0, 0.0),
                "bm25-agent": retr(0.5, 0.6, 0.4),
                "current-kops": retr(0.7, 0.8, 0.1),
                "improved-kops": retr(0.7, 0.8, 0.1),
            },
            "answer_quality": {
                "_status": "demo-plumbing-pending-real-llm",
                "_note": "canned answers",
                "raw-agent": {"factual_correctness": 0.0},
                "bm25-agent": {"factual_correctness": 0.3},
                "current-kops": {"factual_correctness": 0.4},
                "improved-kops": {"factual_correctness": 0.4},
            },
            "governance": {
                "raw-agent": gov(0, 0, 0, 66),
                "bm25-agent": gov(43, 43, 39, 0),
                "current-kops": gov(0, 0, 0, 0),
                "improved-kops": gov(0, 0, 0, 0),
            },
            "operations": {
                "raw-agent": ops(4.695),
                "bm25-agent": ops(4.695),
                "current-kops": ops(4.695),
                "improved-kops": ops(4.695),
            },
        },
        "safe_grounded_rate": {
            "raw-agent": 0.0,
            "bm25-agent": 0.4524,
            "current-kops": 0.7857,
            "improved-kops": 0.7857,
        },
        "comparison": {
            "demonstrated_advantage": {"kops_beats_raw_and_bm25": True},
            "answer_quality_advantage": {"_status": "PENDING"},
        },
        "entailment": {"_status": "pending-real-judge"},
        "context_packages": {"count": 336, "all_answers_linked": True},
        "graded_answers": [],
    }


# --------------------------------------------------------------------------- #
# Wilson score confidence interval
# --------------------------------------------------------------------------- #


def test_wilson_interval_hand_checked():
    """50/100 has a Wilson 95% CI of ~[0.4038, 0.5962] (standard reference)."""
    lo, hi = benchmark_report.wilson_interval(50, 100)
    assert math.isclose(lo, 0.4038, abs_tol=1e-3)
    assert math.isclose(hi, 0.5962, abs_tol=1e-3)


def test_wilson_interval_zero_successes_lower_bound_is_zero():
    """0/10 has a Wilson 95% CI of ~[0.0, 0.2775] (reference value)."""
    lo, hi = benchmark_report.wilson_interval(0, 10)
    assert lo == 0.0
    assert math.isclose(hi, 0.2775, abs_tol=1e-3)


def test_wilson_interval_empty_sample():
    assert benchmark_report.wilson_interval(0, 0) == (0.0, 0.0)


def test_wilson_interval_clamped_to_unit_interval():
    lo, hi = benchmark_report.wilson_interval(84, 84)
    assert 0.0 <= lo <= hi <= 1.0
    assert hi == 1.0


# --------------------------------------------------------------------------- #
# Required sections + headline numbers
# --------------------------------------------------------------------------- #

REQUIRED_HEADINGS = [
    "## Headline",
    "## Corpus version and snapshot",
    "## Models, prompts, and provider",
    "## Baseline configurations",
    "## Retrieval performance",
    "## Citation support",
    "## Stale and retracted source leakage",
    "## Contradiction handling",
    "## Decision-gate accuracy",
    "## Review burden",
    "## Latency and cost",
    "## M4 differentiation",
    "## Failures and limitations",
]


def test_render_report_contains_every_required_section():
    md = benchmark_report.render_report(_sample_report())
    for heading in REQUIRED_HEADINGS:
        assert heading in md, f"missing section: {heading}"


def test_render_report_shows_governance_headline_numbers():
    md = benchmark_report.render_report(_sample_report())
    # 0 revoked leaks for K-Ops vs 43 for BM25, over 84 questions.
    assert "84" in md
    assert "43" in md
    # The composite safe-grounded rate for K-Ops.
    assert "0.786" in md
    # Wilson CI notation appears on a rate.
    assert "95% CI" in md


def test_render_report_review_minutes_present():
    md = benchmark_report.render_report(_sample_report())
    assert "review_minutes_per_accepted_answer" in md
    assert "4.695" in md


# --------------------------------------------------------------------------- #
# M4 differentiation — real flips, not hardcoded prose
# --------------------------------------------------------------------------- #


def test_independence_flip_is_a_real_decision_change():
    flip = benchmark_report.compute_independence_flip()
    assert flip["flipped"] is True
    assert flip["naive_decision"] == "permit"
    assert flip["lineage_decision"] == "refuse"
    # Lineage collapses the derivative pair to a single independent origin.
    assert len(flip["naive_independent_ids"]) == 2
    assert len(flip["lineage_independent_ids"]) == 1
    assert flip["naive_corroborated"] is True
    assert flip["lineage_corroborated"] is False
    assert "needs-corroboration" in flip["lineage_barred_reasons"]


def test_materiality_flip_is_a_real_decision_change():
    flip = benchmark_report.compute_materiality_flip()
    assert flip["flipped"] is True
    assert flip["material_type"] == "direct-conflict"
    assert flip["material_materiality"] == "material"
    assert flip["material_decision"] == "qualify"
    assert flip["immaterial_type"] == "terminology-mismatch"
    assert flip["immaterial_materiality"] == "immaterial"
    assert flip["immaterial_decision"] == "permit"


def test_m4_section_embeds_both_flips():
    md = benchmark_report.render_report(_sample_report())
    m4 = md.split("## M4 differentiation", 1)[1]
    # Independence flip rendered with real decisions.
    assert "`permit` → `refuse`" in m4
    assert "src-5ec0000012" in m4
    assert "src-fac0000007" in m4
    # Materiality flip rendered with real classifier types.
    assert "`qualify` → `permit`" in m4
    assert "direct-conflict" in m4
    assert "terminology-mismatch" in m4


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_render_is_deterministic():
    report = _sample_report()
    assert benchmark_report.render_report(report) == benchmark_report.render_report(report)


def test_no_volatile_fields_leak_into_body():
    md = benchmark_report.render_report(_sample_report())
    assert "2026-07-15T10:42:00" not in md  # generated_at timestamp
    assert "123.4" not in md  # volatile latency_ms


# --------------------------------------------------------------------------- #
# Honesty: answer quality is pending, not a proven win
# --------------------------------------------------------------------------- #


def test_answer_quality_labelled_pending():
    md = benchmark_report.render_report(_sample_report())
    assert "demo-plumbing-pending-real-llm" in md
    # The headline explicitly disclaims an answer-quality win.
    headline = md.split("## Headline", 1)[1].split("##", 1)[0]
    assert "PENDING" in headline
    assert "REAL" in headline


# --------------------------------------------------------------------------- #
# generate() writes a file
# --------------------------------------------------------------------------- #


def test_generate_writes_report(tmp_path):
    out = tmp_path / "REPORT.md"
    written = benchmark_report.generate(out_path=out, report=_sample_report())
    assert written == out
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# K-Ops Benchmark Report")
    assert text.endswith("\n")
