"""Structural invariants for the E1.1 held-out benchmark corpus.

Guards the versioned, isolated mini-vault under
``research/benchmarks/held-out/`` so it stays CI-checked and cannot silently
drift. Content is authored fixtures (expected for a benchmark); these tests
assert the corpus keeps the shape later M1 tasks depend on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "research" / "benchmarks" / "held-out"
CORPUS = BASE / "corpus"
SRC_DIR = CORPUS / "notes" / "Sources"
CON_DIR = CORPUS / "notes" / "Concepts"
REGISTRY = CORPUS / "data" / "registry.json"
QUESTIONS = BASE / "questions.jsonl"
MANIFEST = BASE / "MANIFEST.md"
SCHEMA = ROOT / "kops" / "schema.yaml"
SNAPSHOTS = BASE / "snapshots"

VERSIONED_ID = "src-fac0000002"
RETRACTED_ID = "src-5ec0000016"
SOURCE_ID_RE = re.compile(r"^src-[0-9a-f]{10}$")
QUESTION_CLASSES = {"lookup", "synthesis", "freshness", "code", "trap"}


def _parse_frontmatter(text: str) -> dict:
    assert text.startswith("---\n"), "note must start with YAML frontmatter"
    _, fm, _ = text.split("---\n", 2)
    return yaml.safe_load(fm)


def _source_files() -> list[Path]:
    return sorted(SRC_DIR.glob("src-*.md"))


def _load_questions() -> list[dict]:
    rows = []
    for line in QUESTIONS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "_comment" in obj:
            continue
        rows.append(obj)
    return rows


def _load_state(name: str) -> dict:
    return json.loads((SNAPSHOTS / name / "state.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #


def test_corpus_layout_exists():
    for path in (CORPUS, SRC_DIR, CON_DIR, REGISTRY, QUESTIONS, MANIFEST):
        assert path.exists(), f"missing corpus artifact: {path}"
    for name in ("01-initial", "02-source-update", "03-retraction"):
        assert (SNAPSHOTS / name / "state.json").exists(), f"missing snapshot: {name}"


# --------------------------------------------------------------------------- #
# Sources: count, density mix, schema-valid frontmatter
# --------------------------------------------------------------------------- #


def test_source_count_in_density_range():
    n = len(_source_files())
    assert 15 <= n <= 30, f"expected 15-30 sources, found {n}"


def test_primary_and_secondary_mix():
    tiers = [_parse_frontmatter(p.read_text(encoding="utf-8")).get("tier") for p in _source_files()]
    assert tiers.count("primary") >= 3, "need multiple primary sources"
    assert tiers.count("secondary") >= 3, "need multiple secondary sources"


def test_source_frontmatter_validates_against_schema():
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    base_required = list(schema["source_note"]["required"]) + ["content_hash"]
    kinds = schema["source_kinds"]
    for p in _source_files():
        fm = _parse_frontmatter(p.read_text(encoding="utf-8"))
        for field in base_required:
            assert field in fm, f"{p.name}: missing required field {field!r}"
        assert SOURCE_ID_RE.match(fm["source_id"]), f"{p.name}: bad source_id {fm['source_id']!r}"
        assert fm["source_id"] == p.stem, f"{p.name}: source_id != filename"
        kind = fm["source_kind"]
        assert kind in kinds, f"{p.name}: invalid source_kind {kind!r}"
        for req in kinds[kind].get("required", []):
            if req == "title":  # always present in base
                continue
            assert req in fm, f"{p.name}: source_kind {kind} requires {req!r}"


def test_registry_lists_every_source():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(registry, list)
    reg_ids = {e["id"] for e in registry}
    file_ids = {p.stem for p in _source_files()}
    assert reg_ids == file_ids, "registry.json must list exactly the source notes"


# --------------------------------------------------------------------------- #
# Acceptance-criteria content elements
# --------------------------------------------------------------------------- #


def test_contradiction_pair_present():
    # exactly-once contradiction: vendor claim vs community dispute
    vendor = (SRC_DIR / "src-fac0000001.md").read_text(encoding="utf-8").lower()
    dispute = (SRC_DIR / "src-5ec0000014.md").read_text(encoding="utf-8").lower()
    assert "exactly-once" in vendor
    assert "at-least-once" in dispute


def test_derivative_pair_shares_one_primary_origin():
    a = _parse_frontmatter((SRC_DIR / "src-5ec0000012.md").read_text(encoding="utf-8"))
    b = _parse_frontmatter((SRC_DIR / "src-5ec0000013.md").read_text(encoding="utf-8"))
    assert a.get("derived_from") == b.get("derived_from") == "src-fac0000007"


def test_concepts_have_key_claims_and_evidence_sections():
    concepts = sorted(CON_DIR.glob("*.md"))
    assert len(concepts) >= 3, "expected several concept pages"
    for c in concepts:
        text = c.read_text(encoding="utf-8")
        assert "## Key Claims" in text, f"{c.name}: missing '## Key Claims'"
        assert "## Evidence / Source Basis" in text, (
            f"{c.name}: missing '## Evidence / Source Basis'"
        )
        assert "[[Sources/src-" in text, f"{c.name}: must cite source notes via wikilink"


# --------------------------------------------------------------------------- #
# Snapshots: versioning + retraction
# --------------------------------------------------------------------------- #


def test_versioned_source_hash_changes_across_snapshots():
    s1 = _load_state("01-initial")
    s2 = _load_state("02-source-update")
    h1 = s1["sources"][VERSIONED_ID]["content_hash"]
    h2 = s2["sources"][VERSIONED_ID]["content_hash"]
    assert h1 and h2 and h1 != h2, "versioned source content_hash must change in snapshot 02"
    # the overriding note file exists and carries the new hash
    override = SNAPSHOTS / "02-source-update" / "notes" / "Sources" / f"{VERSIONED_ID}.md"
    assert override.exists()
    fm = _parse_frontmatter(override.read_text(encoding="utf-8"))
    assert fm["content_hash"] == h2


def test_retracted_source_in_snapshot_three():
    s1 = _load_state("01-initial")
    s3 = _load_state("03-retraction")
    assert s1["sources"][RETRACTED_ID]["source_status"] == "active"
    entry = s3["sources"][RETRACTED_ID]
    assert entry["source_status"] == "revoked"
    assert entry.get("retracted_at")
    assert entry.get("retraction_reason")
    override = SNAPSHOTS / "03-retraction" / "notes" / "Sources" / f"{RETRACTED_ID}.md"
    assert override.exists()
    fm = _parse_frontmatter(override.read_text(encoding="utf-8"))
    assert fm["source_status"] == "revoked"
    assert fm.get("retracted_at") and fm.get("retraction_reason")


def test_snapshots_cover_all_sources():
    file_ids = {p.stem for p in _source_files()}
    for name in ("01-initial", "02-source-update", "03-retraction"):
        state = _load_state(name)
        assert set(state["sources"]) == file_ids, f"{name}: state must cover every source"


# --------------------------------------------------------------------------- #
# Questions: parse + category coverage
# --------------------------------------------------------------------------- #


def test_questions_parse_and_have_required_fields():
    rows = _load_questions()
    assert len(rows) >= 10, "corpus should be dense with questions"
    ids = set()
    for q in rows:
        assert q["id"] not in ids, f"duplicate question id {q['id']}"
        ids.add(q["id"])
        assert q["question"]
        assert q["class"] in QUESTION_CLASSES, f"{q['id']}: bad class {q['class']}"
        assert isinstance(q["expected_answer_facts"], list)
        assert isinstance(q.get("required_source_ids", []), list)


def test_questions_cover_all_classes():
    rows = _load_questions()
    present = {q["class"] for q in rows}
    assert present == QUESTION_CLASSES, f"classes missing: {QUESTION_CLASSES - present}"


def test_questions_cover_required_categories():
    rows = _load_questions()
    assert sum(1 for q in rows if q.get("insufficient_evidence")) >= 1
    assert sum(1 for q in rows if q.get("time_sensitive")) >= 1
    assert sum(1 for q in rows if q.get("contradiction")) >= 1
    assert sum(1 for q in rows if q.get("derivative_trap")) >= 1
    assert sum(1 for q in rows if q.get("catastrophic")) >= 1


def test_required_source_ids_resolve_to_real_notes():
    file_ids = {p.stem for p in _source_files()}
    for q in _load_questions():
        for sid in q.get("required_source_ids", []):
            assert sid in file_ids, f"{q['id']}: references unknown source {sid}"


# --------------------------------------------------------------------------- #
# MANIFEST completeness
# --------------------------------------------------------------------------- #


def test_manifest_lists_everything():
    text = MANIFEST.read_text(encoding="utf-8")
    for p in _source_files():
        assert p.stem in text, f"MANIFEST does not mention {p.stem}"
    for token in ("contradiction", "retract", "derivative", "insufficient", "time-sensitive"):
        assert token.lower() in text.lower(), f"MANIFEST missing {token!r}"


@pytest.mark.parametrize("qid", ["q-trap-01", "q-trap-02"])
def test_insufficient_evidence_questions_have_no_required_sources(qid):
    rows = {q["id"]: q for q in _load_questions()}
    assert rows[qid].get("insufficient_evidence") is True
    assert rows[qid]["required_source_ids"] == [], "abstention questions cite no source"
