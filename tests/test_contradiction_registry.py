"""Tests for contradiction_registry.py."""
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
    concepts.mkdir(parents=True)
    return {"concepts": concepts, "root": tmp_path}


def _write_concept(
    dirs: dict,
    stem: str,
    claim_quality: str = "supported",
    body: str = "",
) -> None:
    text = (
        f"---\ntitle: \"{stem}\"\ntype: concept\nclaim_quality: {claim_quality}\n"
        "tags:\n  - kb/concept\n---\n"
        + (body or "## What It Is\n\nSomething.\n")
    )
    (dirs["concepts"] / f"{stem}.md").write_text(text, encoding="utf-8")


def _write_claims_json(dirs: dict, claims: list[dict]) -> None:
    path = dirs["root"] / "data" / "claims.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": "2026-01-01T00:00:00", "count": len(claims), "claims": claims}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _patch_cr(cr_mod, dirs: dict) -> None:
    cr_mod.CONFIG = type("C", (), {"concepts_dir": dirs["concepts"]})()
    cr_mod.ROOT = dirs["root"]
    cr_mod.CONTRADICTIONS_PATH = dirs["root"] / "data" / "contradictions.json"
    cr_mod._CLAIMS_PATH = dirs["root"] / "data" / "claims.json"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_vault_returns_empty(tmp_path):
    import contradiction_registry as cr
    dirs = _make_dirs(tmp_path)
    _patch_cr(cr, dirs)
    result = cr.extract_all_contradictions()
    assert result == []


def test_non_conflicting_concept_excluded(tmp_path):
    import contradiction_registry as cr
    dirs = _make_dirs(tmp_path)
    _patch_cr(cr, dirs)
    _write_concept(dirs, "SupportedPage", "supported")
    result = cr.extract_all_contradictions()
    assert result == []


def test_conflicting_with_oq_produces_one_record_per_bullet(tmp_path):
    import contradiction_registry as cr
    dirs = _make_dirs(tmp_path)
    _patch_cr(cr, dirs)
    body = (
        "## Key Claims\n\n- A claim.\n\n"
        "## Open Questions\n\n"
        "- Source A says X while Source B says Y.\n"
        "- The timeline is disputed.\n"
    )
    _write_concept(dirs, "Conflict", "conflicting", body=body)
    result = cr.extract_all_contradictions()
    assert len(result) == 2
    assert result[0]["documented"] is True
    assert result[1]["documented"] is True
    assert "Source A says X" in result[0]["open_question"]
    assert "timeline is disputed" in result[1]["open_question"]


def test_conflicting_without_oq_produces_undocumented_record(tmp_path):
    import contradiction_registry as cr
    dirs = _make_dirs(tmp_path)
    _patch_cr(cr, dirs)
    body = "## Key Claims\n\n- A claim.\n"
    _write_concept(dirs, "NakedConflict", "conflicting", body=body)
    result = cr.extract_all_contradictions()
    assert len(result) == 1
    assert result[0]["documented"] is False
    assert result[0]["open_question"] is None


def test_stable_id_is_deterministic(tmp_path):
    import contradiction_registry as cr
    id1 = cr.contradiction_stable_id("ConceptA", "Source X disagrees with Y")
    id2 = cr.contradiction_stable_id("ConceptA", "Source X disagrees with Y")
    assert id1 == id2
    assert id1.startswith("ctr-")
    assert len(id1) == 14  # "ctr-" + 10 hex chars


def test_different_oq_bullets_produce_different_ids(tmp_path):
    import contradiction_registry as cr
    id1 = cr.contradiction_stable_id("Concept", "Bullet one")
    id2 = cr.contradiction_stable_id("Concept", "Bullet two")
    assert id1 != id2


def test_source_ids_linked_from_evidence_section(tmp_path):
    import contradiction_registry as cr
    dirs = _make_dirs(tmp_path)
    _patch_cr(cr, dirs)
    body = (
        "## Key Claims\n\n- A claim.\n\n"
        "## Open Questions\n\n- A vs B.\n\n"
        "## Evidence / Source Basis\n\n"
        "- [[Sources/src-aabbccdd11|source-aabbccdd11]]: something.\n"
    )
    _write_concept(dirs, "WithSrc", "conflicting", body=body)
    result = cr.extract_all_contradictions()
    assert result[0]["source_ids"] == ["src-aabbccdd11"]


def test_claim_ids_linked_from_claims_json(tmp_path):
    import contradiction_registry as cr
    dirs = _make_dirs(tmp_path)
    _patch_cr(cr, dirs)
    _write_claims_json(dirs, [
        {"id": "clm-abc1234567", "concept": "ClaimConcept", "text": "A claim.", "claim_quality": "conflicting",
         "source_ids": [], "claim_index": 1, "last_updated": ""},
    ])
    body = "## Key Claims\n\n- A claim.\n\n## Open Questions\n\n- Disagreement here.\n"
    _write_concept(dirs, "ClaimConcept", "conflicting", body=body)
    result = cr.extract_all_contradictions()
    assert "clm-abc1234567" in result[0]["claim_ids"]


def test_run_writes_contradictions_json(tmp_path):
    import contradiction_registry as cr
    dirs = _make_dirs(tmp_path)
    _patch_cr(cr, dirs)
    body = "## Key Claims\n\n- A claim.\n\n## Open Questions\n\n- A disputes B.\n"
    _write_concept(dirs, "DocConflict", "conflicting", body=body)
    cr.run()
    assert cr.CONTRADICTIONS_PATH.exists()
    payload = json.loads(cr.CONTRADICTIONS_PATH.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["documented"] == 1
    assert payload["undocumented"] == 0


def test_run_is_idempotent(tmp_path):
    import contradiction_registry as cr
    dirs = _make_dirs(tmp_path)
    _patch_cr(cr, dirs)
    _write_concept(dirs, "C", "conflicting", body="## Open Questions\n\n- A vs B.\n")
    cr.run()
    mtime1 = cr.CONTRADICTIONS_PATH.stat().st_mtime
    cr.run()
    mtime2 = cr.CONTRADICTIONS_PATH.stat().st_mtime
    assert mtime1 == mtime2


def test_load_contradictions_falls_back_to_extract(tmp_path):
    import contradiction_registry as cr
    dirs = _make_dirs(tmp_path)
    _patch_cr(cr, dirs)
    _write_concept(dirs, "D", "conflicting", body="## Open Questions\n\n- Something.\n")
    # No JSON file — should extract on the fly
    result = cr.load_contradictions()
    assert len(result) == 1


def test_search_matches_by_keyword(tmp_path):
    import contradiction_registry as cr
    recs = [
        {"id": "ctr-a", "concept": "FooBar", "open_question": "Source A and B disagree on timelines", "documented": True},
        {"id": "ctr-b", "concept": "BazQux", "open_question": "Methodology differs", "documented": True},
    ]
    results = cr.search_contradictions(recs, "timeline")
    assert len(results) == 1
    assert results[0]["id"] == "ctr-a"


def test_search_empty_query_returns_all(tmp_path):
    import contradiction_registry as cr
    recs = [
        {"id": "ctr-a", "concept": "X", "open_question": "something", "documented": True},
        {"id": "ctr-b", "concept": "Y", "open_question": "other", "documented": True},
    ]
    results = cr.search_contradictions(recs, "", limit=10)
    assert len(results) == 2


def test_undocumented_count_in_run_output(tmp_path):
    import contradiction_registry as cr
    dirs = _make_dirs(tmp_path)
    _patch_cr(cr, dirs)
    # One documented, one undocumented
    _write_concept(dirs, "DocOne", "conflicting", body="## Open Questions\n\n- A vs B.\n")
    _write_concept(dirs, "NoOQ", "conflicting", body="## Key Claims\n\n- A claim.\n")
    cr.run()
    payload = json.loads(cr.CONTRADICTIONS_PATH.read_text(encoding="utf-8"))
    assert payload["documented"] == 1
    assert payload["undocumented"] == 1
    assert payload["count"] == 2
