"""Deterministic context-package builder (M2 task C2.1).

Proves the builder freezes the exact evidence a governed answer may rely on:
- it captures claim ids, spans, source versions, trust states, freshness, tier
  and policy version;
- it is deterministic (same vault + question + tier -> same package_hash), and
  the tier participates in the hash;
- a flagged/barred claim is surfaced in ``excluded_claims`` with a reason and is
  never silently dropped (nor admitted); and
- the package round-trips through the EvidenceStore.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kops.context_package as context_package  # noqa: E402
from kops.evidence_store import EvidenceStore  # noqa: E402

# Ids must match the claim registry's src-[0-9a-f]{10} pattern.
CLEAN_A = "src-c1ea000001"
CLEAN_B = "src-c1ea000002"
REVOKED = "src-f1a6600001"


def _write_source(sources: Path, sid: str, body: str, **fields: object) -> None:
    sources.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"source_id: {sid}", "title: Torque source", "source_status: active"]
    for key, value in fields.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    text = "\n".join(lines) + "\n\n" + body + "\n"
    (sources / f"{sid}.md").write_text(text, encoding="utf-8")


def _write_concept(concepts: Path, name: str, body: str) -> None:
    concepts.mkdir(parents=True, exist_ok=True)
    (concepts / f"{name}.md").write_text(body, encoding="utf-8")


@pytest.fixture()
def mini_vault(tmp_path: Path) -> Path:
    """A self-contained vault: two clean sources, one revoked, one concept each."""
    vault = tmp_path / "vault"
    sources = vault / "notes" / "Sources"
    concepts = vault / "notes" / "Concepts"

    _write_source(
        sources,
        CLEAN_A,
        "Torque reached GA at v2.0.0 under Apache-2.0 licensing.",
        content_hash="aaa0000001",
    )
    _write_source(
        sources,
        CLEAN_B,
        "Torque Labs raised a Series A funding round from Northwind Ventures.",
        content_hash="bbb0000002",
    )
    _write_source(
        sources,
        REVOKED,
        "Torque throughput leaked benchmark numbers from a revoked source.",
        content_hash="ccc0000003",
        source_status="revoked",
    )

    _write_concept(
        concepts,
        "Torque_Overview",
        "---\n"
        'title: "Torque Overview"\n'
        "type: concept\n"
        "claim_quality: supported\n"
        "---\n\n"
        "# Torque Overview\n\n"
        "## Key Claims\n\n"
        f"- Torque reached GA at v2.0.0 under Apache-2.0 ([[Sources/{CLEAN_A}#page=1|src]]).\n"
        f"- Torque Labs raised a Series A round ([[Sources/{CLEAN_B}#page=2|src]]).\n\n"
        "## Evidence / Source Basis\n\n"
        f"- Release: [[Sources/{CLEAN_A}|src]].\n"
        f"- Funding: [[Sources/{CLEAN_B}|src]].\n",
    )
    _write_concept(
        concepts,
        "Torque_Throughput",
        "---\n"
        'title: "Torque Throughput"\n'
        "type: concept\n"
        "claim_quality: supported\n"
        "---\n\n"
        "# Torque Throughput\n\n"
        "## Key Claims\n\n"
        f"- Torque sustains high throughput on a single node ([[Sources/{REVOKED}#page=3|src]]).\n\n"
        "## Evidence / Source Basis\n\n"
        f"- Benchmark: [[Sources/{REVOKED}|src]].\n",
    )
    return vault


def test_package_captures_all_fields(mini_vault: Path):
    pkg = context_package.build_context_package(
        "Torque GA release and funding", "recommendation", vault=mini_vault
    )

    assert pkg.tier == "recommendation"
    assert pkg.policy_version == context_package.CONTEXT_POLICY_VERSION
    assert pkg.question == "Torque GA release and funding"
    # Admitted claims from the two clean sources are present.
    assert pkg.claim_ids
    # Exact evidence spans were captured (from the inline #page anchors).
    assert pkg.spans
    assert all(isinstance(s.source_id, str) and s.source_id for s in pkg.spans)
    # Immutable source versions were pinned.
    assert pkg.source_version_ids
    assert all(vid.startswith("srcv-") for vid in pkg.source_version_ids)
    # Trust states carry per-claim admission + per-source status.
    assert pkg.trust_states
    assert pkg.trust_states.get(CLEAN_A) == "active"
    # Freshness recorded per referenced source.
    assert set(pkg.freshness) <= set(pkg.trust_states)
    assert pkg.freshness.get(CLEAN_A) in {
        "in-sync",
        "no-baseline",
        "no-raw",
        "revalidation-required",
    }
    # Retrieval trace explains why each record was returned.
    assert pkg.retrieval_trace
    assert all("method" in t and "layer" in t for t in pkg.retrieval_trace)


def test_determinism_same_inputs_same_hash(mini_vault: Path):
    pkg1 = context_package.build_context_package(
        "Torque GA release and funding", "recommendation", vault=mini_vault
    )
    pkg2 = context_package.build_context_package(
        "Torque GA release and funding", "recommendation", vault=mini_vault
    )
    assert pkg1.package_hash == pkg2.package_hash


def test_tier_participates_in_hash(mini_vault: Path):
    rec = context_package.build_context_package(
        "Torque GA release and funding", "recommendation", vault=mini_vault
    )
    dec = context_package.build_context_package(
        "Torque GA release and funding", "decision", vault=mini_vault
    )
    # Both are valid packages, but the differing tier changes the content hash.
    assert rec.tier == "recommendation"
    assert dec.tier == "decision"
    assert rec.package_hash != dec.package_hash


def test_flagged_claim_excluded_with_reason_not_dropped(mini_vault: Path):
    # A question that retrieves the throughput concept, whose only claim is
    # grounded in a REVOKED source.
    pkg = context_package.build_context_package(
        "Torque throughput single node benchmark", "recommendation", vault=mini_vault
    )

    excluded_ids = {e["claim_id"] for e in pkg.excluded_claims}
    assert excluded_ids, "the revoked-source claim must surface as excluded"
    # The revoked-source claim is excluded with an explicit reason...
    revoked_excl = [
        e
        for e in pkg.excluded_claims
        if any("flagged-source" in r or "blocked-source" in r for r in e["reasons"])
    ]
    assert revoked_excl
    # ...and it is NOT admitted (never silently promoted).
    assert not (excluded_ids & set(pkg.claim_ids))


def test_package_round_trips_through_store(mini_vault: Path):
    store = EvidenceStore(
        base_dir=mini_vault / "data" / "evidence",
        history_dir=mini_vault / "data" / "history",
    )
    pkg = context_package.build_context_package(
        "Torque GA release and funding", "decision", vault=mini_vault, store=store
    )
    loaded = store.load_context_package(pkg.package_hash)
    assert loaded is not None
    assert loaded.package_hash == pkg.package_hash
    assert loaded.tier == pkg.tier
    assert loaded.claim_ids == pkg.claim_ids
    assert loaded.question == pkg.question
    assert [s.span_id for s in loaded.spans] == [s.span_id for s in pkg.spans]


def test_invalid_tier_rejected(mini_vault: Path):
    with pytest.raises(ValueError):
        context_package.build_context_package("q", "not-a-tier", vault=mini_vault)
