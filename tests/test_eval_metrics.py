"""Tests for the end-to-end M1 benchmark metrics harness (roadmap task E1.4).

Two layers:

* A fast **tmp mini-vault** (clean + revoked-on-snapshot source, 2 questions) that
  the whole pipeline runs over with an injected deterministic provider — proving
  the four metric families, ContextPackage linkage, deterministic governance
  advantage, failure attribution, determinism, and the stubbed entailment judge.
* A couple of **real E1.1 corpus** checks: the governance headline over the
  ``03-retraction`` snapshot and the one-command ``kops benchmark`` subcommand.

No real LLM or network is ever touched (deterministic provider; stub judge via
``KB_JUDGE_CMD``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from kops import baselines, eval_metrics
from kops.evidence_store import EvidenceStore

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Fast tmp mini-vault + mini golden set + mini snapshot
# --------------------------------------------------------------------------- #

VENDOR_ID = "src-ven0000001"  # clean: vendor throughput + license
BLOG_ID = "src-blg0000001"  # clean in base, REVOKED in the snapshot overlay


def _write_source(sources: Path, sid: str, body: str, *, status: str = "active", **fm: object):
    lines = ["---", f"source_id: {sid}", "title: Test Source", f"source_status: {status}"]
    for key, value in fm.items():
        lines.append(f"{key}: {json.dumps(value)}")
    lines += ["---", "", body, ""]
    (sources / f"{sid}.md").write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture()
def mini(tmp_path):
    """Build a mini corpus + snapshot + golden set. Returns paths + a store."""
    corpus = tmp_path / "corpus"
    sources = corpus / "notes" / "Sources"
    concepts = corpus / "notes" / "Concepts"
    sources.mkdir(parents=True)
    concepts.mkdir(parents=True)
    (corpus / "config").mkdir()
    (corpus / "config" / "kb_config.yaml").write_text(
        "summaries_dir: notes/Sources\nconcepts_dir: notes/Concepts\n", encoding="utf-8"
    )
    (corpus / "data").mkdir()
    (corpus / "data" / "registry.json").write_text(
        json.dumps([{"id": VENDOR_ID}, {"id": BLOG_ID}]), encoding="utf-8"
    )

    _write_source(
        sources,
        VENDOR_ID,
        "Torque official benchmark: 1.2M events per second throughput. "
        "Torque is licensed under Apache-2.0.",
        content_hash="ven0000001",
    )
    _write_source(
        sources,
        BLOG_ID,
        "Torque hits 5M events per second throughput in my tests.",
        content_hash="blg0000001",
    )

    # Snapshot overlay: the blog is retracted (source_status: revoked).
    snap = tmp_path / "snapshot" / "notes" / "Sources"
    snap.mkdir(parents=True)
    _write_source(
        snap,
        BLOG_ID,
        "RETRACTED. Torque hits 5M events per second throughput in my tests.",
        status="revoked",
        content_hash="blg0000002",
        retracted_at="2026-04-05",
    )

    golden = tmp_path / "golden.yaml"
    golden.write_text(
        json.dumps(
            {
                "version": "1.0",
                "questions": [
                    {
                        "id": "q-thru",
                        "category": "freshness-sensitive",
                        "question": "What throughput events per second does Torque achieve?",
                        "expected_answer_elements": ["1.2M events per second"],
                        "forbidden_conclusions": ["5M events per second"],
                        "relevant_claim_refs": [],
                        "relevant_source_spans": [
                            {"src": VENDOR_ID, "quote": "1.2M events per second throughput."}
                        ],
                        "expected_contradictions": [],
                        "required_uncertainty": False,
                        "expected_behavior": "answer",
                        "consequence_tier": "decision",
                    },
                    {
                        "id": "q-lic",
                        "category": "direct-factual",
                        "question": "What license is Torque under?",
                        "expected_answer_elements": ["Apache-2.0"],
                        "forbidden_conclusions": ["proprietary"],
                        "relevant_claim_refs": [],
                        "relevant_source_spans": [
                            {"src": VENDOR_ID, "quote": "licensed under Apache-2.0"}
                        ],
                        "expected_contradictions": [],
                        "required_uncertainty": False,
                        "expected_behavior": "answer",
                        "consequence_tier": "exploratory",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    store = EvidenceStore(base_dir=tmp_path / "ev", history_dir=tmp_path / "hist")
    return {
        "corpus": corpus,
        "snapshot": tmp_path / "snapshot",
        "golden": golden,
        "store": store,
        "tmp": tmp_path,
    }


def _run_mini(mini, *, store=None, **kw):
    return eval_metrics.run_benchmark(
        corpus_dir=mini["corpus"],
        golden_set_path=mini["golden"],
        snapshot_dir=mini["snapshot"],
        provider=baselines.DeterministicProvider(),
        store=store if store is not None else mini["store"],
        work_dir=mini["tmp"] / "work",
        **kw,
    )


# --------------------------------------------------------------------------- #
# Four metric families
# --------------------------------------------------------------------------- #


def test_pipeline_produces_four_metric_families(mini):
    report = _run_mini(mini)
    metrics = report["metrics"]
    assert set(metrics) == {"retrieval", "answer_quality", "governance", "operations"}
    for family in metrics.values():
        for name in baselines.BASELINE_NAMES:
            assert name in family
    # Answer quality is honestly labelled as demo/plumbing.
    assert metrics["answer_quality"]["_status"] == "demo-plumbing-pending-real-llm"
    assert metrics["governance"]["_status"] == "real-deterministic"


def test_retrieval_family_has_recall_and_coverage(mini):
    retr = _run_mini(mini)["metrics"]["retrieval"]
    for name in baselines.BASELINE_NAMES:
        assert set(retr[name]) == {
            "recall_at_k",
            "evidence_coverage",
            "irrelevant_context_rate",
        }
    # raw-agent retrieves nothing => zero coverage; kops grounds the questions.
    assert retr["raw-agent"]["evidence_coverage"] == 0.0
    assert retr["current-kops"]["evidence_coverage"] > 0.0


# --------------------------------------------------------------------------- #
# ContextPackage linkage (exit-gate requirement)
# --------------------------------------------------------------------------- #


def test_every_answer_linked_to_resolvable_context_package(mini):
    store = mini["store"]
    report = _run_mini(mini, store=store)
    assert report["context_packages"]["all_answers_linked"] is True
    assert report["graded_answers"], "expected graded answers"
    for rec in report["graded_answers"]:
        h = rec["context_package_hash"]
        assert h, "each answer must carry a package hash"
        pkg = store.load_context_package(h)
        assert pkg is not None and pkg.package_hash == h
        assert pkg.policy_version == eval_metrics.HARNESS_POLICY_VERSION


def test_governed_package_is_versioned_and_records_exclusions(mini):
    store = mini["store"]
    report = _run_mini(mini, store=store)
    # A governed answer that actually retrieved sources: versioned + excludes the
    # revoked blog with a reason.
    rec = next(
        r
        for r in report["graded_answers"]
        if r["baseline"] == "current-kops" and r["retrieved_source_ids"]
    )
    pkg = store.load_context_package(rec["context_package_hash"])
    assert pkg.tier in {"decision", "exploratory"}
    assert pkg.source_version_ids, "governed package should pin source versions"
    assert pkg.spans, "governed package should carry evidence spans"
    excluded_ids = {e["source_id"] for e in pkg.excluded_claims}
    assert BLOG_ID in excluded_ids
    # Source versions are persisted and resolvable.
    assert store.source_versions(), "source versions should be persisted"


# --------------------------------------------------------------------------- #
# Governance advantage (real, deterministic)
# --------------------------------------------------------------------------- #


def test_governance_leakage_advantage_is_deterministic(mini):
    gov = _run_mini(mini)["metrics"]["governance"]
    # The core, non-fabricated M1 win: governed K-Ops leaks 0 revoked sources
    # while the ungoverned BM25 baseline leaks them.
    assert gov["current-kops"]["revoked_source_leakage"] == 0
    assert gov["improved-kops"]["revoked_source_leakage"] == 0
    assert gov["bm25-agent"]["revoked_source_leakage"] > 0


def test_safe_grounded_rate_kops_beats_raw_and_bm25(mini):
    report = _run_mini(mini)
    sg = report["safe_grounded_rate"]
    assert sg["current-kops"] > sg["raw-agent"]
    assert sg["current-kops"] > sg["bm25-agent"]
    adv = report["comparison"]["demonstrated_advantage"]
    assert adv["metric"] == "safe_grounded_rate"
    assert adv["kops_beats_raw_and_bm25"] is True
    # Answer-accuracy wins are explicitly NOT claimed here.
    assert report["comparison"]["answer_quality_advantage"]["_status"] == "PENDING"


# --------------------------------------------------------------------------- #
# Failure attribution (exit-gate requirement)
# --------------------------------------------------------------------------- #


def test_failure_attribution_present_and_in_taxonomy(mini):
    report = _run_mini(mini)
    allowed = {
        eval_metrics.ATTR_RETRIEVAL,
        eval_metrics.ATTR_EVIDENCE,
        eval_metrics.ATTR_GENERATION,
        eval_metrics.ATTR_POLICY,
        eval_metrics.ATTR_NONE,
    }
    for rec in report["graded_answers"]:
        assert rec["failure_attribution"] in allowed
    # A leaked flagged source must be attributed to policy.
    leaked = [r for r in report["graded_answers"] if r["leaked_flagged"]]
    assert leaked, "the mini snapshot should produce at least one leak (bm25-agent)"
    assert all(r["failure_attribution"] == eval_metrics.ATTR_POLICY for r in leaked)


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_two_runs_are_identical_under_deterministic_view(mini):
    a = _run_mini(mini)
    b = _run_mini(mini)
    va = eval_metrics.deterministic_view(a)
    vb = eval_metrics.deterministic_view(b)
    assert json.dumps(va, sort_keys=True) == json.dumps(vb, sort_keys=True)


# --------------------------------------------------------------------------- #
# Entailment via a stub judge (calibrated, not assumed)
# --------------------------------------------------------------------------- #


def test_entailment_runs_and_calibrates_with_stub_judge(tmp_path, monkeypatch):
    stub = tmp_path / "judge.py"
    stub.write_text(
        "import json\n"
        'print(json.dumps({"verdict": "supported", "rationale": "ok", '
        '"missing_information": []}))\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("KB_JUDGE_CMD", f"{sys.executable} {stub}")
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")

    store = EvidenceStore(base_dir=tmp_path / "ev", history_dir=tmp_path / "hist")
    report = eval_metrics.run_benchmark(
        provider=baselines.DeterministicProvider(),
        store=store,
        work_dir=tmp_path / "work",
        run_entailment_judge=True,
    )
    ent = report["entailment"]
    assert ent["_status"] == "real"
    assert ent["cited_span_pairs_judged"] > 0
    assert ent["calibration"] is not None
    assert 0.0 <= ent["calibration"]["accuracy_vs_gold"] <= 1.0
    assert report["exit_gate"]["entailment_calibrated"] == "met"


def test_entailment_pending_without_judge(mini, monkeypatch):
    monkeypatch.delenv("KB_JUDGE_CMD", raising=False)
    monkeypatch.delenv("KB_JUDGE_AGENT", raising=False)
    report = _run_mini(mini, run_entailment_judge=None)
    assert report["entailment"]["_status"] == "pending-real-judge"
    assert report["exit_gate"]["entailment_calibrated"] == "pending-real-judge"


# --------------------------------------------------------------------------- #
# Real E1.1 corpus: governance headline + one-command subcommand
# --------------------------------------------------------------------------- #


def test_real_corpus_governance_headline(tmp_path):
    """Over the real 03-retraction snapshot: bm25 leaks the revoked source, kops doesn't."""
    store = EvidenceStore(base_dir=tmp_path / "ev", history_dir=tmp_path / "hist")
    report = eval_metrics.run_benchmark(
        provider=baselines.DeterministicProvider(),
        store=store,
        work_dir=tmp_path / "work",
    )
    gov = report["metrics"]["governance"]
    assert gov["current-kops"]["revoked_source_leakage"] == 0
    assert gov["bm25-agent"]["revoked_source_leakage"] > 0
    assert report["comparison"]["demonstrated_advantage"]["kops_beats_raw_and_bm25"] is True
    assert report["question_count"] == 84


def test_kb_benchmark_subcommand_writes_dated_report(tmp_path):
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "kops.kb", "benchmark", "--out-dir", str(out_dir)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Demonstrated advantage" in result.stdout
    reports = list(out_dir.glob("benchmark-*.json"))
    jsonls = list(out_dir.glob("benchmark-*.jsonl"))
    assert reports and jsonls
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["exit_gate"]["kops_advantage_over_raw_and_bm25"] is True
    assert report["context_packages"]["all_answers_linked"] is True
