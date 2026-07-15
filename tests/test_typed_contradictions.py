"""Tests for typed contradiction records (M4 task L4.1)."""

from __future__ import annotations

import json
from pathlib import Path

from kops.typed_contradictions import (
    CONTRADICTION_TYPES,
    Contradiction,
    classify_contradiction,
    material_contradiction_ids,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(open_question: str | None, **overrides) -> dict:
    rec = {
        "id": "ctr-0000000000",
        "concept": "Some_Concept",
        "concept_path": "notes/Concepts/Some_Concept.md",
        "open_question": open_question,
        "documented": open_question is not None,
        "claim_ids": [],
        "source_ids": [],
        "created_at": "",
    }
    rec.update(overrides)
    return rec


def _classify_type(open_question, **kw) -> str:
    claims_by_id = kw.pop("claims_by_id", None)
    sources_by_id = kw.pop("sources_by_id", None)
    return classify_contradiction(
        _record(open_question, **kw), claims_by_id=claims_by_id, sources_by_id=sources_by_id
    ).contradiction_type


# ---------------------------------------------------------------------------
# The 9 types are each producible
# ---------------------------------------------------------------------------


def test_direct_conflict_default():
    assert _classify_type("Source A says the value is 5 and Source B says it is 9.") == (
        "direct-conflict"
    )


def test_temporal_supersession():
    assert _classify_type("The 2019 figure was superseded by the 2023 revision.") == (
        "temporal-supersession"
    )


def test_scope_mismatch():
    assert _classify_type("This only applies to the special case of streaming inputs.") == (
        "scope-mismatch"
    )


def test_terminology_mismatch():
    assert _classify_type("The two notes use a different term for the same definition.") == (
        "terminology-mismatch"
    )


def test_methodological_disagreement():
    assert _classify_type("They disagree on the benchmark methodology used to measure it.") == (
        "methodological-disagreement"
    )


def test_evidence_quality_disagreement():
    assert _classify_type("One relies on a weak evidence base with an unreliable source.") == (
        "evidence-quality-disagreement"
    )


def test_interpretation_disagreement():
    assert _classify_type("Reviewers interpret the same result differently.") == (
        "interpretation-disagreement"
    )


def test_synthetic_from_source_metadata():
    rec = _record("A plain disagreement.", source_ids=["src-aaaaaaaaaa"])
    sources = {"src-aaaaaaaaaa": {"source_id": "src-aaaaaaaaaa", "synthetic_origin": True}}
    con = classify_contradiction(rec, sources_by_id=sources)
    assert con.contradiction_type == "synthetic-or-derivative-contamination"


def test_synthetic_from_evidence_strength_model_generated():
    rec = _record("A plain disagreement.", source_ids=["src-bbbbbbbbbb"])
    sources = {
        "src-bbbbbbbbbb": {"source_id": "src-bbbbbbbbbb", "evidence_strength": "model-generated"}
    }
    assert (
        classify_contradiction(rec, sources_by_id=sources).contradiction_type
        == "synthetic-or-derivative-contamination"
    )


def test_synthetic_from_claim_flag():
    rec = _record("A plain disagreement.", claim_ids=["clm-aaaaaaaaaa"])
    claims = {"clm-aaaaaaaaaa": {"claim_id": "clm-aaaaaaaaaa", "synthetic_origin": True}}
    assert (
        classify_contradiction(rec, claims_by_id=claims).contradiction_type
        == "synthetic-or-derivative-contamination"
    )


def test_extraction_error():
    assert _classify_type(
        "The quote does not appear in the source — likely an extraction error."
    ) == ("extraction-error")


def test_all_nine_types_covered():
    produced = {
        _classify_type("Source A says 5 and Source B says 9."),
        _classify_type("The 2019 figure was superseded by the 2023 revision."),
        _classify_type("This only applies to the special case of streaming."),
        _classify_type("They use a different term for the same definition."),
        _classify_type("They disagree on the benchmark methodology."),
        _classify_type("One relies on a weak evidence base, unreliable source."),
        _classify_type("Reviewers interpret the same result differently."),
        classify_contradiction(
            _record("plain", source_ids=["src-x"]),
            sources_by_id={"src-x": {"source_id": "src-x", "synthetic_origin": True}},
        ).contradiction_type,
        _classify_type("The quote does not appear — extraction error."),
    }
    assert produced == set(CONTRADICTION_TYPES)
    assert len(CONTRADICTION_TYPES) == 9


# ---------------------------------------------------------------------------
# Materiality rule
# ---------------------------------------------------------------------------


def test_immaterial_type_not_in_material_ids():
    # terminology-mismatch is immaterial -> its claims must NOT be flagged.
    rec = _record(
        "They use a different term for the same definition.",
        claim_ids=["clm-term00001", "clm-term00002"],
    )
    con = classify_contradiction(rec)
    assert con.materiality == "immaterial"
    claims = [{"claim_id": "clm-term00001"}, {"claim_id": "clm-term00002"}]
    assert material_contradiction_ids(claims, [rec]) == set()


def test_material_type_in_material_ids():
    rec = _record(
        "Source A says the value is 5 and Source B says it is 9.",
        claim_ids=["clm-dc000001", "clm-dc000002"],
    )
    con = classify_contradiction(rec)
    assert con.materiality == "material"
    assert con.resolution_state == "unresolved"
    claims = [{"claim_id": "clm-dc000001"}, {"claim_id": "clm-dc000002"}]
    assert material_contradiction_ids(claims, [rec]) == {"clm-dc000001", "clm-dc000002"}


def test_material_type_without_evidence_is_immaterial():
    # A material-type record with no claims/sources cannot gate a decision.
    con = classify_contradiction(_record("Source A says 5 and B says 9."))
    assert con.materiality == "immaterial"


def test_material_ids_scoped_to_known_claims():
    rec = _record(
        "Source A says 5 and B says 9.",
        claim_ids=["clm-known0001", "clm-unknown01"],
    )
    claims = [{"claim_id": "clm-known0001"}]
    assert material_contradiction_ids(claims, [rec]) == {"clm-known0001"}


def test_superseded_excluded_from_material_ids():
    rec = _record(
        "The 2019 result was superseded by the 2023 revision.",
        claim_ids=["clm-sup00001", "clm-sup00002"],
    )
    con = classify_contradiction(rec)
    assert con.resolution_state == "superseded"
    claims = [{"claim_id": "clm-sup00001"}, {"claim_id": "clm-sup00002"}]
    # superseded => resolved-enough => not an unresolved material contradiction.
    assert material_contradiction_ids(claims, [rec]) == set()


# ---------------------------------------------------------------------------
# Typed field extraction
# ---------------------------------------------------------------------------


def test_time_interval_extracted():
    con = classify_contradiction(_record("Disputed between 2019 and 2023."))
    assert con.time_interval == {"start": "2019", "end": "2023"}


def test_scope_extracted():
    con = classify_contradiction(_record("The claim only applies to batch inference on GPUs."))
    assert con.scope is not None and "batch inference" in con.scope


def test_supporting_evidence_shape():
    con = classify_contradiction(
        _record("A vs B.", claim_ids=["clm-e0000001"], source_ids=["src-e0000001"])
    )
    assert {"ref_type": "claim", "id": "clm-e0000001", "version": "clm-e0000001"} in (
        con.supporting_evidence
    )
    assert {"ref_type": "source", "id": "src-e0000001"} in con.supporting_evidence


def test_reviewer_decision_null_by_default():
    con = classify_contradiction(_record("A vs B.", claim_ids=["clm-x", "clm-y"]))
    assert con.reviewer_decision is None


def test_severity_levels():
    high = classify_contradiction(_record("A says 5, B says 9.", claim_ids=["clm-a", "clm-b"]))
    assert high.severity == "high"
    low = classify_contradiction(_record("Different term, same definition.", claim_ids=["clm-a"]))
    assert low.severity == "low"


# ---------------------------------------------------------------------------
# Round-trip and backward compatibility
# ---------------------------------------------------------------------------


def test_to_dict_from_dict_roundtrip():
    con = classify_contradiction(
        _record("A vs B.", claim_ids=["clm-a", "clm-b"], source_ids=["src-a"])
    )
    restored = Contradiction.from_dict(con.to_dict())
    assert restored.to_dict() == con.to_dict()


def test_maintenance_source_key_preserved():
    rec = _record("A vs B.", source="maintenance/contradictions")
    data = classify_contradiction(rec).to_dict()
    assert data["source"] == "maintenance/contradictions"


def test_concept_record_has_no_source_key():
    data = classify_contradiction(_record("A vs B.")).to_dict()
    assert "source" not in data


def test_original_eight_keys_and_display_keys_intact():
    data = classify_contradiction(
        _record("A vs B.", claim_ids=["clm-a"], source_ids=["src-a"])
    ).to_dict()
    for key in (
        "id",
        "concept",
        "concept_path",
        "open_question",
        "documented",
        "claim_ids",
        "source_ids",
        "created_at",
    ):
        assert key in data
    # The 5 CLI display keys the formatter reads.
    for key in ("documented", "open_question", "concept", "source_ids", "claim_ids"):
        assert key in data


def test_claim_ids_semantics_unchanged():
    rec = _record("A vs B.", claim_ids=["clm-1", "clm-2"])
    data = classify_contradiction(rec).to_dict()
    assert data["claim_ids"] == ["clm-1", "clm-2"]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_classify_is_deterministic():
    rec = _record("They disagree on the benchmark methodology in 2020.")
    a = classify_contradiction(rec).to_dict()
    b = classify_contradiction(rec).to_dict()
    assert a == b


def _make_conflicting_vault(tmp_path: Path):
    concepts = tmp_path / "notes" / "Concepts"
    concepts.mkdir(parents=True)
    body = (
        "## Key Claims\n\n- A claim.\n\n"
        "## Open Questions\n\n"
        "- Source A says X while the 2019 figure was superseded by 2023 data.\n"
        "- They use a different term for the same definition.\n"
    )
    text = (
        '---\ntitle: "Conflict"\ntype: concept\nclaim_quality: conflicting\n'
        "tags:\n  - kb/concept\n---\n" + body
    )
    (concepts / "Conflict.md").write_text(text, encoding="utf-8")
    return concepts


def test_run_check_is_stable(tmp_path, monkeypatch):
    import kops.contradiction_registry as cr

    concepts = _make_conflicting_vault(tmp_path)
    monkeypatch.setattr(cr, "CONFIG", type("C", (), {"concepts_dir": concepts})())
    monkeypatch.setattr(cr, "ROOT", tmp_path)
    monkeypatch.setattr(cr, "CONTRADICTIONS_PATH", tmp_path / "data" / "contradictions.json")
    monkeypatch.setattr(cr, "_CLAIMS_PATH", tmp_path / "data" / "claims.json")

    cr.run()
    payload = json.loads(cr.CONTRADICTIONS_PATH.read_text(encoding="utf-8"))
    assert payload["count"] == 2
    types = {c["contradiction_type"] for c in payload["contradictions"]}
    assert "temporal-supersession" in types
    assert "terminology-mismatch" in types
    # Second run must not report drift (deterministic).
    mtime1 = cr.CONTRADICTIONS_PATH.stat().st_mtime
    cr.run()
    mtime2 = cr.CONTRADICTIONS_PATH.stat().st_mtime
    assert mtime1 == mtime2
