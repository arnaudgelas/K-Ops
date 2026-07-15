"""Source-exclusion invariants (roadmap task S0.1).

Proves that a source flagged as prompt-injection / adversarial / revoked /
permission-revoked / do-not-use / deleted-from-origin / unresolved-fetch-warning
cannot enter any serving surface by default:

  (a) compilation (``_build_compile_plan`` ``to_summarize``)
  (b) retrieval / search results
  (c) the ``ask`` answer-context package (agent prompt)
  (d) rendering / export
  (e) a decision-grade answer (consequence gate)

Plus the audited override object: an explicit, scoped, unexpired override lets a
source through for its named command only; expired / out-of-scope does not; and
the override is recorded/auditable.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kops.claim_registry as claim_registry  # noqa: E402
import kops.consequence_gate as consequence_gate  # noqa: E402
import kops.export_obsidian_vault as export_mod  # noqa: E402
import kops.kb_runtime as kb_runtime  # noqa: E402
import kops.render_manifest as render_mod  # noqa: E402
import kops.retrieval as retrieval  # noqa: E402
import kops.source_override as source_override  # noqa: E402


# Every flag that must gate a source out of the serving surfaces.
# (name, frontmatter/registry fields that raise the flag)
FLAG_CASES: list[tuple[str, dict]] = [
    ("prompt_injection", {"prompt_injection_detected": True}),
    ("adversarial", {"adversarial_content": True}),
    ("revoked", {"source_status": "revoked"}),
    ("permission_revoked", {"source_status": "permission-revoked"}),
    ("do_not_use", {"source_status": "do-not-use"}),
    ("deleted_from_origin", {"source_status": "deleted-from-origin"}),
    ("fetch_warning", {"fetch_warning": "429 rate limited"}),
]

# The subset the claim registry classifies as *blocked* (decision-grade gate).
# prompt-injection / fetch-warning are stopped upstream (compile + retrieval),
# so they never form a claim that could reach the consequence gate.
CLAIM_BLOCKING_CASES: list[tuple[str, dict]] = [
    ("adversarial", {"adversarial_content": True}),
    ("revoked", {"source_status": "revoked"}),
    ("permission_revoked", {"source_status": "permission-revoked"}),
    ("do_not_use", {"source_status": "do-not-use"}),
    ("deleted_from_origin", {"source_status": "deleted-from-origin"}),
]

FLAG_IDS = [name for name, _ in FLAG_CASES]
CLAIM_BLOCKING_IDS = [name for name, _ in CLAIM_BLOCKING_CASES]

# IDs must match the claim registry's src-[0-9a-f]{10} pattern.
CLEAN_ID = "src-c1ea000000"
FLAGGED_ID = "src-f1a6600000"


def _fm_lines(source_id: str, fields: dict) -> list[str]:
    lines = ["---", f"source_id: {source_id}", "title: Test Source", "source_status: active"]
    for key, value in fields.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        else:
            lines.append(f"{key}: {json.dumps(value)}")
    lines.append("---")
    return lines


def _write_source(sources_dir: Path, source_id: str, body: str, **fields: object) -> Path:
    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / f"{source_id}.md"
    text = "\n".join(_fm_lines(source_id, fields)) + "\n\n" + body + "\n"
    path.write_text(text, encoding="utf-8")
    return path


class _Cfg:
    def __init__(self, **kw: object) -> None:
        self.__dict__.update(kw)


@pytest.fixture()
def isolated_overrides(tmp_path, monkeypatch):
    """Point the override store at an (initially empty) tmp file."""
    store = tmp_path / "data" / "source_overrides.json"
    monkeypatch.setattr(source_override, "OVERRIDES_PATH", store)
    return store


def _patch_retrieval(tmp_path, monkeypatch) -> Path:
    sources = tmp_path / "notes" / "Sources"
    concepts = tmp_path / "notes" / "Concepts"
    sources.mkdir(parents=True, exist_ok=True)
    concepts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(retrieval, "CONFIG", _Cfg(summaries_dir=sources, concepts_dir=concepts))
    monkeypatch.setattr(retrieval, "ROOT", tmp_path)
    return sources


# ---------------------------------------------------------------------------
# (b) retrieval / search
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fields", [c[1] for c in FLAG_CASES], ids=FLAG_IDS)
def test_flagged_source_excluded_from_retrieval(tmp_path, monkeypatch, isolated_overrides, fields):
    sources = _patch_retrieval(tmp_path, monkeypatch)
    _write_source(sources, CLEAN_ID, "kubernetes networking overview.")
    _write_source(sources, FLAGGED_ID, "kubernetes secret poisonpayload steps.", **fields)

    index = retrieval.VaultIndex()
    index.build()

    results = index.search("kubernetes")
    ids = {r["id"] for r in results}
    assert CLEAN_ID in ids
    assert FLAGGED_ID not in ids
    # Exact lookup by id must also refuse to surface the flagged source.
    assert index.exact(FLAGGED_ID) == []
    # But an explicit admin opt-in can see it.
    assert FLAGGED_ID in {r["id"] for r in index.search("kubernetes", include_flagged=True)}


# ---------------------------------------------------------------------------
# (c) ask answer-context package — the agent prompt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fields", [c[1] for c in FLAG_CASES], ids=FLAG_IDS)
def test_flagged_source_never_reaches_agent_prompt(
    tmp_path, monkeypatch, isolated_overrides, fields
):
    sources = _patch_retrieval(tmp_path, monkeypatch)
    _write_source(sources, CLEAN_ID, "kubernetes networking overview.")
    _write_source(sources, FLAGGED_ID, "kubernetes secret poisonpayload steps.", **fields)

    context = kb_runtime.build_ask_retrieval_context("kubernetes")

    assert CLEAN_ID in context
    assert FLAGGED_ID not in context
    assert "poisonpayload" not in context


# ---------------------------------------------------------------------------
# (a) compilation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fields", [c[1] for c in FLAG_CASES], ids=FLAG_IDS)
def test_flagged_source_excluded_from_compile_plan(
    tmp_path, monkeypatch, isolated_overrides, fields
):
    registry_path = tmp_path / "data" / "registry.json"
    summaries_dir = tmp_path / "notes" / "Sources"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps([{"id": CLEAN_ID}, {"id": FLAGGED_ID, **fields}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        kb_runtime, "CONFIG", _Cfg(registry_path=registry_path, summaries_dir=summaries_dir)
    )
    monkeypatch.setattr(kb_runtime, "ROOT", tmp_path)

    plan = kb_runtime._build_compile_plan()

    assert CLEAN_ID in plan["to_summarize"]
    assert FLAGGED_ID not in plan["to_summarize"]
    assert FLAGGED_ID in {entry["id"] for entry in plan["flag_for_review"]}


def test_compile_plan_flags_deleted_from_origin(tmp_path, monkeypatch, isolated_overrides):
    """Regression: the inline compile status set once omitted deleted-from-origin."""
    registry_path = tmp_path / "data" / "registry.json"
    summaries_dir = tmp_path / "notes" / "Sources"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps([{"id": FLAGGED_ID, "source_status": "deleted-from-origin"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        kb_runtime, "CONFIG", _Cfg(registry_path=registry_path, summaries_dir=summaries_dir)
    )
    monkeypatch.setattr(kb_runtime, "ROOT", tmp_path)

    plan = kb_runtime._build_compile_plan()
    assert plan["to_summarize"] == []
    reasons = plan["flag_for_review"][0]["reasons"]
    assert reasons == ["source_status:deleted-from-origin"]


# ---------------------------------------------------------------------------
# (d) rendering / export
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fields", [c[1] for c in FLAG_CASES], ids=FLAG_IDS)
def test_flagged_source_excluded_from_render_manifest(
    tmp_path, monkeypatch, isolated_overrides, fields
):
    registry_path = tmp_path / "data" / "registry.json"
    vault_dir = tmp_path / "notes"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    vault_dir.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps([{"id": CLEAN_ID}, {"id": FLAGGED_ID, **fields}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        render_mod, "CONFIG", _Cfg(registry_path=registry_path, vault_dir=vault_dir)
    )
    monkeypatch.setattr(render_mod, "ROOT", tmp_path)

    manifest = render_mod.build_manifest()
    served_ids = {s["id"] for s in manifest["sources"]}
    excluded_ids = {s["id"] for s in manifest["excluded_sources"]}
    assert CLEAN_ID in served_ids
    assert FLAGGED_ID not in served_ids
    assert FLAGGED_ID in excluded_ids
    # admin opt-in restores it
    admin = render_mod.build_manifest(include_flagged=True)
    assert FLAGGED_ID in {s["id"] for s in admin["sources"]}


@pytest.mark.parametrize("fields", [c[1] for c in FLAG_CASES], ids=FLAG_IDS)
def test_flagged_source_note_excluded_from_export(
    tmp_path, monkeypatch, isolated_overrides, fields
):
    vault_dir = tmp_path / "notes"
    sources_dir = vault_dir / "Sources"
    _write_source(sources_dir, CLEAN_ID, "clean body.")
    _write_source(sources_dir, FLAGGED_ID, "poisonpayload body.", **fields)
    (tmp_path / ".obsidian").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(export_mod, "CONFIG", _Cfg(vault_dir=vault_dir))
    monkeypatch.setattr(export_mod, "ROOT", tmp_path)

    staging = tmp_path / "staging"
    vault_root = export_mod.build_export_staging(staging)
    exported = {p.name for p in vault_root.rglob("*.md")}
    assert f"{CLEAN_ID}.md" in exported
    assert f"{FLAGGED_ID}.md" not in exported


# ---------------------------------------------------------------------------
# (e) decision-grade answer (consequence gate)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fields", [c[1] for c in CLAIM_BLOCKING_CASES], ids=CLAIM_BLOCKING_IDS)
def test_flagged_source_barred_from_decision_grade_answer(tmp_path, monkeypatch, fields):
    sources = tmp_path / "notes" / "Sources"
    concepts = tmp_path / "notes" / "Concepts"
    sources.mkdir(parents=True, exist_ok=True)
    concepts.mkdir(parents=True, exist_ok=True)
    _write_source(sources, FLAGGED_ID, "content.", **fields)
    concept = concepts / "Topic.md"
    concept.write_text(
        '---\ntitle: "Topic"\ntype: concept\nclaim_quality: supported\n---\n\n'
        "## Key Claims\n\n"
        f"- A strong claim ([[Sources/{FLAGGED_ID}|source]]).\n\n"
        "## Evidence / Source Basis\n\n"
        f"- [[Sources/{FLAGGED_ID}|source]]: cited.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        claim_registry, "CONFIG", _Cfg(concepts_dir=concepts, summaries_dir=sources)
    )
    monkeypatch.setattr(claim_registry, "ROOT", tmp_path)

    claim = claim_registry.extract_claims_from_concept(concept)[0]
    assert claim["admission_status"] == "blocked"

    # The consequence gate bars a blocked-source claim from recommendation up.
    for tier in ("recommendation", "decision", "autonomous"):
        result = consequence_gate.assess_claims([claim], tier)
        assert result["allowed"] is False
        assert "blocked-source" in result["violations"][0]["reasons"]


# ---------------------------------------------------------------------------
# Newly-revoked source: its summary + derived content leave the serving surfaces
# ---------------------------------------------------------------------------


def test_retracted_source_summary_and_derived_content_excluded(tmp_path, monkeypatch):
    import kops.retract_source as retract_source

    sources = _patch_retrieval(tmp_path, monkeypatch)
    concepts = tmp_path / "notes" / "Concepts"
    isolated = tmp_path / "data" / "source_overrides.json"
    monkeypatch.setattr(source_override, "OVERRIDES_PATH", isolated)

    note = _write_source(sources, FLAGGED_ID, "kubernetes networking overview.")

    # While active, the summary is served by retrieval.
    idx = retrieval.VaultIndex()
    idx.build()
    assert FLAGGED_ID in {r["id"] for r in idx.search("kubernetes")}

    # And a claim derived from it clears the recommendation bar.
    concept = concepts / "Topic.md"
    concept.write_text(
        '---\ntitle: "Topic"\ntype: concept\nclaim_quality: supported\n---\n\n'
        "## Key Claims\n\n"
        f"- Derived claim ([[Sources/{FLAGGED_ID}|source]]).\n\n"
        "## Evidence / Source Basis\n\n"
        f"- [[Sources/{FLAGGED_ID}|source]]: cited.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        claim_registry, "CONFIG", _Cfg(concepts_dir=concepts, summaries_dir=sources)
    )
    monkeypatch.setattr(claim_registry, "ROOT", tmp_path)
    claim_active = claim_registry.extract_claims_from_concept(concept)[0]
    assert consequence_gate.assess_claims([claim_active], "recommendation")["allowed"] is True

    # Retract the source (real frontmatter mutation) and rebuild.
    note.write_text(
        retract_source.mark_source_retracted(
            note.read_text(encoding="utf-8"), "hallucinated", "revoked", "2026-07-15"
        ),
        encoding="utf-8",
    )

    idx2 = retrieval.VaultIndex()
    idx2.build()
    assert FLAGGED_ID not in {r["id"] for r in idx2.search("kubernetes")}
    assert FLAGGED_ID not in kb_runtime.build_ask_retrieval_context("kubernetes")

    # Derived claim is now blocked from a decision-grade answer.
    claim_after = claim_registry.extract_claims_from_concept(concept)[0]
    assert claim_after["admission_status"] == "blocked"
    assert consequence_gate.assess_claims([claim_after], "recommendation")["allowed"] is False


# ---------------------------------------------------------------------------
# Audited override object
# ---------------------------------------------------------------------------


def _add_override(store: Path, **kw: object) -> source_override.SourceOverride:
    defaults = dict(
        source_id=FLAGGED_ID,
        operator="alice",
        reason="reviewed benign false-positive",
        scope="single incident triage",
        expiry="2999-01-01",
        commands=["ask"],
        path=store,
    )
    defaults.update(kw)
    return source_override.add_override(**defaults)


def test_scoped_unexpired_override_admits_only_its_command(tmp_path, monkeypatch):
    store = tmp_path / "data" / "source_overrides.json"
    monkeypatch.setattr(source_override, "OVERRIDES_PATH", store)
    sources = _patch_retrieval(tmp_path, monkeypatch)
    _write_source(sources, FLAGGED_ID, "kubernetes secret data.", source_status="revoked")

    _add_override(store, commands=["ask"])

    # In scope: ask re-admits the source.
    assert FLAGGED_ID in kb_runtime.build_ask_retrieval_context("kubernetes")
    # Out of scope: default search command still excludes it.
    idx = retrieval.VaultIndex()
    idx.build()
    assert FLAGGED_ID not in {r["id"] for r in idx.search("kubernetes")}
    assert FLAGGED_ID in {r["id"] for r in idx.search("kubernetes", command="ask")}


def test_expired_override_does_not_admit(tmp_path, monkeypatch):
    store = tmp_path / "data" / "source_overrides.json"
    monkeypatch.setattr(source_override, "OVERRIDES_PATH", store)
    sources = _patch_retrieval(tmp_path, monkeypatch)
    _write_source(sources, FLAGGED_ID, "kubernetes secret data.", source_status="revoked")

    _add_override(store, commands=["ask"], expiry="2000-01-01")

    assert FLAGGED_ID not in kb_runtime.build_ask_retrieval_context("kubernetes")


def test_wildcard_override_applies_to_all_commands(tmp_path, monkeypatch):
    store = tmp_path / "data" / "source_overrides.json"
    monkeypatch.setattr(source_override, "OVERRIDES_PATH", store)
    sources = _patch_retrieval(tmp_path, monkeypatch)
    _write_source(sources, FLAGGED_ID, "kubernetes secret data.", source_status="revoked")

    _add_override(store, commands=["*"])
    idx = retrieval.VaultIndex()
    idx.build()
    assert FLAGGED_ID in {r["id"] for r in idx.search("kubernetes")}


def test_override_is_recorded_and_auditable(tmp_path, monkeypatch):
    store = tmp_path / "data" / "source_overrides.json"
    monkeypatch.setattr(source_override, "OVERRIDES_PATH", store)

    _add_override(store, operator="bob", reason="manual review passed", commands=["render"])

    loaded = source_override.load_overrides(store)
    assert len(loaded) == 1
    ov = loaded[0]
    assert ov.operator == "bob"
    assert ov.reason == "manual review passed"
    assert ov.scope
    assert ov.commands == ("render",)
    assert ov.created_at  # who/why/when captured
    # Persisted on disk as an auditable record.
    on_disk = json.loads(store.read_text(encoding="utf-8"))
    assert on_disk[0]["operator"] == "bob"
    assert on_disk[0]["created_at"]


def test_override_requires_audit_fields(tmp_path, monkeypatch):
    store = tmp_path / "data" / "source_overrides.json"
    monkeypatch.setattr(source_override, "OVERRIDES_PATH", store)
    for missing in ("operator", "reason", "scope"):
        kwargs = dict(
            source_id=FLAGGED_ID,
            operator="a",
            reason="r",
            scope="s",
            expiry="2999-01-01",
            commands=["ask"],
            path=store,
        )
        kwargs[missing] = ""
        with pytest.raises(ValueError):
            source_override.add_override(**kwargs)
    # An unparseable expiry is also rejected (must be time-bounded).
    with pytest.raises(ValueError):
        source_override.add_override(
            source_id=FLAGGED_ID,
            operator="a",
            reason="r",
            scope="s",
            expiry="not-a-date",
            commands=["ask"],
            path=store,
        )


def test_version_pinned_override_only_matches_that_version(tmp_path, monkeypatch):
    store = tmp_path / "data" / "source_overrides.json"
    monkeypatch.setattr(source_override, "OVERRIDES_PATH", store)
    _add_override(store, commands=["ask"], version="v1")
    overrides = source_override.load_overrides(store)

    now = dt.datetime(2026, 1, 1)
    assert source_override.active_override_for(
        FLAGGED_ID, "ask", "v1", now=now, overrides=overrides
    )
    assert (
        source_override.active_override_for(FLAGGED_ID, "ask", "v2", now=now, overrides=overrides)
        is None
    )
