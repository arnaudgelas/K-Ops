"""Tests for kops.distillation — proposal-only claim-graph distillation."""

from __future__ import annotations

import copy

from kops import distillation as dist


def _claim(cid, text, *, sources=("src-1",), evidence="direct", **extra):
    claim = {
        "claim_id": cid,
        "claim_text": text,
        "concept": "Workflow_Pattern_Inventory",
        "source_ids": list(sources),
        "evidence_status": evidence,
        "claim_quality": "supported",
        "status": "active",
    }
    claim.update(extra)
    return claim


def _by_kind(proposals, kind):
    return [p for p in proposals if p["kind"] == kind]


# --------------------------------------------------------------------------- #
# Near-duplicate -> merge
# --------------------------------------------------------------------------- #


def test_near_duplicate_same_scope_evidence_yields_merge():
    claims = [
        _claim("clm-a", "The compile step writes source summaries and concept pages to the vault."),
        _claim("clm-b", "The compile step writes concept pages and source summaries to the vault."),
    ]
    proposals = dist.build_proposals(claims)
    merges = _by_kind(proposals, "merge")
    assert len(merges) == 1
    merge = merges[0]
    refs = {r["claim_id"] for r in merge["refs"]}
    assert refs == {"clm-a", "clm-b"}
    assert "safe" in merge["guardrail"]
    assert merge["status"] == "proposed"
    # every ref carries a content-hash version
    assert all(r["version"] for r in merge["refs"])


# --------------------------------------------------------------------------- #
# The guardrail: divergent scope/time/evidence -> needs-review, NEVER merge
# --------------------------------------------------------------------------- #


def test_divergent_scope_time_evidence_blocks_merge():
    claims = [
        _claim(
            "clm-a",
            "In 2021 the compile step wrote source summaries and concept pages to the vault.",
            sources=("src-1",),
            evidence="direct",
        ),
        _claim(
            "clm-b",
            "In 2024 the compile step wrote concept pages and source summaries to the vault.",
            sources=("src-2",),
            evidence="page",
        ),
    ]
    proposals = dist.build_proposals(claims)
    assert _by_kind(proposals, "merge") == []
    review = _by_kind(proposals, "needs-review")
    assert len(review) == 1
    guardrail = review[0]["guardrail"]
    assert "divergent-scope" in guardrail
    assert "divergent-time" in guardrail
    assert "divergent-evidence" in guardrail


def test_divergent_scope_only_blocks_merge():
    text = "The lint command checks structural consistency across the vault notes."
    claims = [
        _claim("clm-a", text, sources=("src-1",)),
        _claim("clm-b", text, sources=("src-2",)),
    ]
    proposals = dist.build_proposals(claims)
    assert _by_kind(proposals, "merge") == []
    review = _by_kind(proposals, "needs-review")
    assert len(review) == 1
    assert review[0]["guardrail"] == "divergent-scope"


# --------------------------------------------------------------------------- #
# Divergent time only + orderable -> supersede with reciprocal edges
# --------------------------------------------------------------------------- #


def test_time_only_divergence_yields_supersede_with_reciprocal_edges():
    claims = [
        _claim("clm-old", "As of 2019 the vault indexed 12 concept pages and 8 source summaries."),
        _claim("clm-new", "As of 2025 the vault indexed 12 concept pages and 8 source summaries."),
    ]
    proposals = dist.build_proposals(claims)
    assert _by_kind(proposals, "merge") == []
    sup = _by_kind(proposals, "supersede")
    assert len(sup) == 1
    edges = sup[0]["edges"]
    predicates = {(e["predicate"], e["from"], e["to"]) for e in edges}
    assert ("supersedes", "clm-new", "clm-old") in predicates
    assert ("superseded_by", "clm-old", "clm-new") in predicates


# --------------------------------------------------------------------------- #
# Compound claim -> split (via atomic_claims)
# --------------------------------------------------------------------------- #


def test_compound_claim_yields_split_proposal():
    claims = [
        _claim(
            "clm-compound",
            "The ingest step writes raw evidence and the compile step writes concept pages.",
        )
    ]
    proposals = dist.build_proposals(claims)
    splits = _by_kind(proposals, "split")
    assert len(splits) == 1
    assert splits[0]["refs"][0]["claim_id"] == "clm-compound"
    assert splits[0]["evidence"]["reasons"]  # the compound reasons are recorded


# --------------------------------------------------------------------------- #
# Stale / superseded -> archive
# --------------------------------------------------------------------------- #


def test_stale_claim_yields_archive_proposal():
    claims = [_claim("clm-stale", "An outdated fact about the vault.", claim_quality="stale")]
    proposals = dist.build_proposals(claims)
    arch = _by_kind(proposals, "archive")
    assert len(arch) == 1
    assert arch[0]["refs"][0]["claim_id"] == "clm-stale"


def test_superseded_claim_yields_archive_proposal():
    claims = [
        _claim("clm-x", "A superseded fact.", superseded_by=["clm-y"]),
    ]
    proposals = dist.build_proposals(claims)
    arch = _by_kind(proposals, "archive")
    assert len(arch) == 1
    assert "superseded_by" in "; ".join(arch[0]["evidence"]["reasons"])


# --------------------------------------------------------------------------- #
# Concept rename
# --------------------------------------------------------------------------- #


def test_near_identical_concept_names_yield_rename_proposal():
    claims = [
        _claim("clm-a", "First fact.", concept="Workflow_Pattern"),
        _claim("clm-b", "Second fact.", concept="Workflow_Patterns"),
    ]
    proposals = dist.build_proposals(claims)
    renames = _by_kind(proposals, "rename")
    assert len(renames) == 1
    roles = {r["role"]: r["concept"] for r in renames[0]["refs"]}
    assert roles["target"] == "Workflow_Pattern"
    assert roles["alias"] == "Workflow_Patterns"


# --------------------------------------------------------------------------- #
# Determinism + no mutation + proposal-only
# --------------------------------------------------------------------------- #


def test_proposals_are_deterministic_and_never_mutate_input():
    claims = [
        _claim("clm-a", "The compile step writes source summaries and concept pages."),
        _claim("clm-b", "The compile step writes concept pages and source summaries."),
        _claim("clm-stale", "An outdated fact.", claim_quality="stale"),
    ]
    snapshot = copy.deepcopy(claims)

    first = dist.build_proposals(claims)
    second = dist.build_proposals(claims)

    # inputs untouched
    assert claims == snapshot
    # identical output across runs (content-addressed ids, sorted)
    assert first == second
    assert [p["proposal_id"] for p in first] == [p["proposal_id"] for p in second]
    # nothing carries an "applied"/mutation flag — everything is still a proposal
    assert all(p["status"] == "proposed" for p in first)


def test_review_items_are_review_queue_shaped():
    claims = [
        _claim("clm-a", "The compile step writes source summaries and concept pages."),
        _claim("clm-b", "The compile step writes concept pages and source summaries."),
    ]
    proposals = dist.build_proposals(claims)
    items = dist.distillation_review_items(proposals)
    assert items
    for it in items:
        assert set(it) == {"category", "severity", "ref", "detail", "action"}
        assert it["severity"] in {"error", "warning", "info"}
        assert it["category"].startswith("distillation-")


def test_run_writes_registry_and_check_detects_drift(tmp_path, monkeypatch):
    claims_path = tmp_path / "claims.json"
    proposals_path = tmp_path / "distillation_proposals.json"
    import json as _json

    claims = [
        _claim("clm-a", "The compile step writes source summaries and concept pages."),
        _claim("clm-b", "The compile step writes concept pages and source summaries."),
    ]
    claims_path.write_text(_json.dumps({"claims": claims}), encoding="utf-8")
    monkeypatch.setattr(dist, "CLAIMS_PATH", claims_path)
    monkeypatch.setattr(dist, "PROPOSALS_PATH", proposals_path)

    # dry-run writes nothing
    dist.run(dry_run=True)
    assert not proposals_path.exists()

    # a real run writes the registry
    proposals, code = dist.run()
    assert code == 0
    assert proposals_path.exists()
    assert proposals

    # check is clean immediately after a write
    _, code = dist.run(check=True)
    assert code == 0

    # mutating a claim changes content-hash versions -> check reports drift
    claims[0]["claim_text"] = "A completely different unrelated statement about lint checks."
    claims_path.write_text(_json.dumps({"claims": claims}), encoding="utf-8")
    _, code = dist.run(check=True)
    assert code == 1
