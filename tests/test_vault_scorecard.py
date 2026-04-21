"""Tests for vault_scorecard.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dirs(tmp_path: Path) -> dict[str, Path]:
    concepts = tmp_path / "notes" / "Concepts"
    sources = tmp_path / "notes" / "Sources"
    answers = tmp_path / "notes" / "Answers"
    for d in (concepts, sources, answers):
        d.mkdir(parents=True)
    return {"concepts": concepts, "sources": sources, "answers": answers, "root": tmp_path}


def _write_concept(dirs: dict, stem: str, claim_quality: str = "supported", body: str = "") -> None:
    text = (
        f"---\ntitle: \"{stem}\"\ntype: concept\nclaim_quality: {claim_quality}\ntags:\n  - kb/concept\n---\n"
        + (body or "## What It Is\n\nSomething.\n")
    )
    (dirs["concepts"] / f"{stem}.md").write_text(text, encoding="utf-8")


def _write_source(dirs: dict, source_id: str, strength: str = "secondary", kind: str = "web-page") -> None:
    text = (
        f"---\ntitle: \"Source\"\ntype: source\nsource_id: {source_id}\n"
        f"evidence_strength: {strength}\nsource_kind: {kind}\ntags:\n  - kb/source\n---\n\n## Summary\n\nContent.\n"
    )
    (dirs["sources"] / f"{source_id}.md").write_text(text, encoding="utf-8")


def _write_answer(dirs: dict, stem: str, quality: str = "memo-only", sources_consulted: list | None = None) -> None:
    sc_line = f"sources_consulted: {json.dumps(sources_consulted or [])}\n"
    text = (
        f"---\ntitle: \"Q\"\ntype: answer\nasked_at: \"2026-01-01T00:00:00\"\n"
        f"answer_quality: {quality}\nscope: private\n{sc_line}tags:\n  - kb/answer\n---\n\n# Question\n\nQ.\n\n---\n\n# Answer\n\nA.\n\n## Vault Updates\n\n- None.\n"
    )
    (dirs["answers"] / f"{stem}.md").write_text(text, encoding="utf-8")


def _patch_vs(vs_mod, dirs: dict) -> None:
    vs_mod.CONFIG = type("C", (), {
        "project_name": "Test",
        "concepts_dir": dirs["concepts"],
        "summaries_dir": dirs["sources"],
        "answers_dir": dirs["answers"],
        "research_dir": dirs["root"] / "research",
    })()
    vs_mod.ROOT = dirs["root"]
    vs_mod._CLAIMS_PATH = dirs["root"] / "data" / "claims.json"
    vs_mod._CONTRADICTIONS_PATH = dirs["root"] / "data" / "contradictions.json"
    vs_mod._RESEARCH_DIR = dirs["root"] / "research"
    vs_mod.SCORECARD_PATH = dirs["root"] / "data" / "scorecard.json"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_vault_returns_zeros(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    sc = vs.compute_scorecard()
    assert sc["concepts"]["total"] == 0
    assert sc["sources"]["total"] == 0
    assert sc["answers"]["total"] == 0
    assert sc["claims"]["total"] == 0
    assert sc["contradictions"]["total"] == 0


def test_scorecard_includes_contradictions_domain(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    # Write a contradictions.json with one documented record
    contradictions_path = dirs["root"] / "data" / "contradictions.json"
    contradictions_path.parent.mkdir(parents=True, exist_ok=True)
    contradictions_path.write_text(
        json.dumps({
            "generated_at": "2026-01-01T00:00:00",
            "count": 1,
            "documented": 1,
            "undocumented": 0,
            "contradictions": [
                {"id": "ctr-abc1234567", "concept": "Foo", "open_question": "A vs B",
                 "documented": True, "claim_ids": [], "source_ids": [], "created_at": ""}
            ],
        }),
        encoding="utf-8",
    )
    sc = vs.compute_scorecard()
    assert sc["contradictions"]["total"] == 1
    assert sc["contradictions"]["documented"] == 1
    assert sc["contradictions"]["undocumented"] == 0
    assert sc["contradictions"]["concepts_affected"] == 1


def test_undocumented_contradiction_triggers_health_signal(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    contradictions_path = dirs["root"] / "data" / "contradictions.json"
    contradictions_path.parent.mkdir(parents=True, exist_ok=True)
    contradictions_path.write_text(
        json.dumps({
            "generated_at": "2026-01-01T00:00:00",
            "count": 1,
            "documented": 0,
            "undocumented": 1,
            "contradictions": [
                {"id": "ctr-xyz9876543", "concept": "Bar", "open_question": None,
                 "documented": False, "claim_ids": [], "source_ids": [], "created_at": ""}
            ],
        }),
        encoding="utf-8",
    )
    sc = vs.compute_scorecard()
    codes = {s["code"] for s in sc["health_signals"]}
    assert "undocumented-contradictions" in codes


def test_concept_quality_counts(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    _write_concept(dirs, "A", "supported")
    _write_concept(dirs, "B", "provisional")
    _write_concept(dirs, "C", "supported")
    sc = vs.compute_scorecard()
    assert sc["concepts"]["total"] == 3
    assert sc["concepts"]["by_claim_quality"].get("supported") == 2
    assert sc["concepts"]["by_claim_quality"].get("provisional") == 1


def test_unsupported_concept_detected(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    _write_concept(dirs, "NoSources", "supported", body="## Key Claims\n\n- A claim.\n")
    sc = vs.compute_scorecard()
    assert sc["concepts"]["unsupported"] == 1


def test_supported_concept_with_evidence(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    body = (
        "## Key Claims\n\n- A claim.\n\n"
        "## Evidence / Source Basis\n\n"
        "- [[Sources/src-aabbccdd11|source-aabbccdd11]]: X.\n"
    )
    _write_concept(dirs, "WithSources", "supported", body=body)
    sc = vs.compute_scorecard()
    assert sc["concepts"]["unsupported"] == 0


def test_source_strength_distribution(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    _write_source(dirs, "src-0000000001", "primary-doc")
    _write_source(dirs, "src-0000000002", "secondary")
    _write_source(dirs, "src-0000000003", "stub")
    sc = vs.compute_scorecard()
    assert sc["sources"]["total"] == 3
    assert sc["sources"]["by_evidence_strength"].get("primary-doc") == 1
    assert sc["sources"]["stub_count"] == 1
    assert sc["sources"]["primary_count"] == 1


def test_stub_fraction_computed(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    _write_source(dirs, "src-0000000001", "stub")
    _write_source(dirs, "src-0000000002", "stub")
    _write_source(dirs, "src-0000000003", "primary-doc")
    sc = vs.compute_scorecard()
    assert abs(sc["sources"]["stub_fraction"] - 2 / 3) < 0.01


def test_answer_provenance_counted(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    _write_answer(dirs, "ans1", sources_consulted=["src-abc123def0"])
    _write_answer(dirs, "ans2", sources_consulted=[])
    sc = vs.compute_scorecard()
    assert sc["answers"]["total"] == 2
    assert sc["answers"]["with_provenance"] == 1


def test_inline_citation_rate(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    body = (
        "## Key Claims\n\n"
        "- Claim with cite ([[Sources/src-aabbccdd11|source]]).\n"
        "- Claim without cite.\n"
    )
    _write_concept(dirs, "Mixed", "supported", body=body)
    sc = vs.compute_scorecard()
    assert sc["concepts"]["claim_bullets_total"] == 2
    assert sc["concepts"]["claim_bullets_with_inline_citation"] == 1
    assert sc["concepts"]["inline_citation_rate"] == 0.5


def test_conflicting_no_oq_detected(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    _write_concept(dirs, "Conflict", "conflicting", body="## Key Claims\n\n- A claim.\n")
    sc = vs.compute_scorecard()
    assert sc["concepts"]["conflicting_without_open_questions"] == 1


def test_conflicting_with_oq_not_flagged(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    body = "## Key Claims\n\n- A claim.\n\n## Open Questions\n\n- Source A vs B disagrees.\n"
    _write_concept(dirs, "ConflictOQ", "conflicting", body=body)
    sc = vs.compute_scorecard()
    assert sc["concepts"]["conflicting_without_open_questions"] == 0


def test_health_signal_high_stub_fraction(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    for i in range(4):
        _write_source(dirs, f"src-stub000000{i}", "stub")
    _write_source(dirs, "src-primary0001", "primary-doc")
    sc = vs.compute_scorecard()
    codes = {s["code"] for s in sc["health_signals"]}
    assert "high-stub-fraction" in codes


def test_run_writes_scorecard_json(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    vs.SCORECARD_PATH = dirs["root"] / "data" / "scorecard.json"
    _write_concept(dirs, "A", "supported")
    vs.run()
    assert vs.SCORECARD_PATH.exists()
    payload = json.loads(vs.SCORECARD_PATH.read_text(encoding="utf-8"))
    assert payload["concepts"]["total"] == 1


def test_run_is_idempotent(tmp_path):
    import vault_scorecard as vs
    dirs = _make_dirs(tmp_path)
    _patch_vs(vs, dirs)
    vs.SCORECARD_PATH = dirs["root"] / "data" / "scorecard.json"
    vs.run()
    mtime1 = vs.SCORECARD_PATH.stat().st_mtime
    vs.run()
    mtime2 = vs.SCORECARD_PATH.stat().st_mtime
    assert mtime1 == mtime2
