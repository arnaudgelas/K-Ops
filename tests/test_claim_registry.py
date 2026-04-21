"""Tests for claim_registry.py."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def _make_concept(tmp_path: Path, stem: str, body: str, claim_quality: str = "supported") -> Path:
    """Write a minimal concept page and return its path."""
    concepts = tmp_path / "notes" / "Concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    path = concepts / f"{stem}.md"
    text = (
        f"---\ntitle: \"{stem}\"\ntype: concept\nclaim_quality: {claim_quality}\ntags:\n  - kb/concept\n---\n"
        + body
    )
    path.write_text(text, encoding="utf-8")
    return path


def _patch_cr(cr_mod, tmp_path: Path) -> None:
    """Point claim_registry at the tmp vault."""
    import utils
    cr_mod.CONFIG = type("C", (), {"concepts_dir": tmp_path / "notes" / "Concepts"})()
    cr_mod.ROOT = tmp_path


def test_no_claims_section_returns_empty(tmp_path):
    import claim_registry as cr
    path = _make_concept(tmp_path, "Empty", "## What It Is\n\nNothing yet.\n")
    _patch_cr(cr, tmp_path)
    claims = cr.extract_claims_from_concept(path)
    assert claims == []


def test_extracts_bullets_from_key_claims(tmp_path):
    import claim_registry as cr
    body = (
        "## Key Claims\n\n"
        "- First claim about X.\n"
        "- Second claim about Y.\n\n"
        "## Evidence / Source Basis\n\n"
        "- [[Sources/src-aabbccdd11|source-aabbccdd11]]: Some source.\n"
    )
    path = _make_concept(tmp_path, "Concept_A", body)
    _patch_cr(cr, tmp_path)
    claims = cr.extract_claims_from_concept(path)
    assert len(claims) == 2
    assert claims[0]["text"] == "First claim about X."
    assert claims[1]["text"] == "Second claim about Y."
    assert claims[0]["claim_index"] == 1
    assert claims[1]["claim_index"] == 2


def test_claim_ids_are_stable(tmp_path):
    import claim_registry as cr
    body = "## Key Claims\n\n- Stable claim.\n"
    path = _make_concept(tmp_path, "Stable", body)
    _patch_cr(cr, tmp_path)
    claims1 = cr.extract_claims_from_concept(path)
    claims2 = cr.extract_claims_from_concept(path)
    assert claims1[0]["id"] == claims2[0]["id"]
    assert claims1[0]["id"].startswith("clm-")


def test_claim_ids_differ_for_different_text(tmp_path):
    import claim_registry as cr
    id_a = cr.claim_stable_id("Concept", "Claim A.")
    id_b = cr.claim_stable_id("Concept", "Claim B.")
    assert id_a != id_b


def test_claim_ids_differ_for_same_text_different_concept(tmp_path):
    import claim_registry as cr
    id_a = cr.claim_stable_id("Concept_A", "Same text.")
    id_b = cr.claim_stable_id("Concept_B", "Same text.")
    assert id_a != id_b


def test_extracts_source_ids_from_evidence_section(tmp_path):
    import claim_registry as cr
    body = (
        "## Key Claims\n\n- A claim.\n\n"
        "## Evidence / Source Basis\n\n"
        "- [[Sources/src-1122334455|source-1122334455]]: First.\n"
        "- [[Sources/src-aabbccdd11|source-aabbccdd11]]: Second.\n"
    )
    path = _make_concept(tmp_path, "With_Sources", body)
    _patch_cr(cr, tmp_path)
    claims = cr.extract_claims_from_concept(path)
    assert len(claims) == 1
    assert sorted(claims[0]["source_ids"]) == ["src-1122334455", "src-aabbccdd11"]


def test_search_claims_finds_match(tmp_path):
    import claim_registry as cr
    claims = [
        {"id": "clm-001", "text": "Rust is memory safe.", "concept": "Rust", "claim_quality": "supported", "source_ids": [], "claim_index": 1, "last_updated": ""},
        {"id": "clm-002", "text": "Python is dynamically typed.", "concept": "Python", "claim_quality": "supported", "source_ids": [], "claim_index": 1, "last_updated": ""},
    ]
    results = cr.search_claims(claims, "rust memory")
    assert len(results) == 1
    assert results[0]["id"] == "clm-001"


def test_search_claims_no_match_returns_empty(tmp_path):
    import claim_registry as cr
    claims = [
        {"id": "clm-001", "text": "Rust is memory safe.", "concept": "Rust", "claim_quality": "supported", "source_ids": [], "claim_index": 1, "last_updated": ""},
    ]
    results = cr.search_claims(claims, "javascript")
    assert results == []


def test_search_claims_empty_query_returns_all(tmp_path):
    import claim_registry as cr
    claims = [{"id": f"clm-{i:03d}", "text": f"Claim {i}.", "concept": "C", "claim_quality": "supported", "source_ids": [], "claim_index": i, "last_updated": ""} for i in range(5)]
    results = cr.search_claims(claims, "")
    assert len(results) == 5


def test_extract_all_claims_multiple_concepts(tmp_path):
    import claim_registry as cr
    body_a = "## Key Claims\n\n- A1.\n- A2.\n"
    body_b = "## Key Claims\n\n- B1.\n"
    _make_concept(tmp_path, "Concept_A", body_a)
    _make_concept(tmp_path, "Concept_B", body_b)
    _patch_cr(cr, tmp_path)
    all_claims = cr.extract_all_claims()
    texts = [c["text"] for c in all_claims]
    assert "A1." in texts
    assert "A2." in texts
    assert "B1." in texts
    assert len(all_claims) == 3


def test_run_writes_claims_json(tmp_path):
    import claim_registry as cr
    body = "## Key Claims\n\n- Written claim.\n"
    _make_concept(tmp_path, "Written", body)
    _patch_cr(cr, tmp_path)
    cr.CLAIMS_PATH = tmp_path / "data" / "claims.json"
    cr.run()
    assert cr.CLAIMS_PATH.exists()
    payload = json.loads(cr.CLAIMS_PATH.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["claims"][0]["text"] == "Written claim."


def test_run_is_idempotent(tmp_path):
    import claim_registry as cr
    body = "## Key Claims\n\n- Idempotent claim.\n"
    _make_concept(tmp_path, "Idem", body)
    _patch_cr(cr, tmp_path)
    cr.CLAIMS_PATH = tmp_path / "data" / "claims.json"
    cr.run()
    mtime1 = cr.CLAIMS_PATH.stat().st_mtime
    cr.run()
    # Content unchanged so file should not be rewritten (same mtime)
    mtime2 = cr.CLAIMS_PATH.stat().st_mtime
    assert mtime1 == mtime2
