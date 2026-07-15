"""Consequence-gated answer serving (M2 task C2.4).

These tests demonstrate the five M2 exit-gate criteria against the real
governance stack (context package -> tier policy -> claim map -> invalidation ->
validation ledger), driving generation through an injected deterministic
generator (no LLM):

1. a decision-grade answer relying on a quarantined/unsupported claim is refused;
2. a decision-grade answer with no claim map is refused;
3. a source update makes a dependent decision answer stale (serving reads the
   invalidation stale-set) -> abstain/refuse;
4. a revoked source cannot appear in a current decision answer -> refused;
5. every serving decision leaves a reproducible audit record.

Plus: an exploratory serve permits and stamps the memo, and serving is
deterministic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kops import claim_registry  # noqa: E402
from kops import context_package as context_package  # noqa: E402
from kops import invalidation, output_gate  # noqa: E402
from kops.evidence_store import EvidenceStore  # noqa: E402
from kops.utils import parse_frontmatter  # noqa: E402
from kops.validation_log import serving_audit  # noqa: E402

CLEAN_A = "src-c1ea000001"
CLEAN_B = "src-c1ea000002"
REVOKED = "src-f1a6600001"
QUARANTINE = "src-9aa4000001"


# --------------------------------------------------------------------------- #
# Vault + generator helpers
# --------------------------------------------------------------------------- #


def _write_source(sources: Path, sid: str, body: str, **fields: object) -> None:
    sources.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"source_id: {sid}", "title: Torque source", "source_status: active"]
    for key, value in fields.items():
        rendered = str(value).lower() if isinstance(value, bool) else value
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    (sources / f"{sid}.md").write_text("\n".join(lines) + "\n\n" + body + "\n", encoding="utf-8")


def _write_concept(concepts: Path, name: str, key_claims: str, evidence: str) -> None:
    concepts.mkdir(parents=True, exist_ok=True)
    (concepts / f"{name}.md").write_text(
        "---\n"
        f'title: "{name}"\n'
        "type: concept\n"
        "claim_quality: supported\n"
        "---\n\n"
        f"# {name}\n\n## Key Claims\n\n{key_claims}\n\n## Evidence / Source Basis\n\n{evidence}\n",
        encoding="utf-8",
    )


def _store_for(vault: Path) -> EvidenceStore:
    return EvidenceStore(
        base_dir=vault / "data" / "evidence", history_dir=vault / "data" / "history"
    )


@pytest.fixture()
def full_vault(tmp_path: Path) -> Path:
    """Two clean claims (admitted), one revoked-source claim, one synthetic claim."""
    vault = tmp_path / "vault"
    sources = vault / "notes" / "Sources"
    concepts = vault / "notes" / "Concepts"

    _write_source(sources, CLEAN_A, "Torque reached GA at v2.0.0.", content_hash="aaa0000001")
    _write_source(sources, CLEAN_B, "Torque raised a Series A round.", content_hash="bbb0000002")
    _write_source(
        sources,
        REVOKED,
        "Torque leaked benchmark numbers.",
        content_hash="ccc0000003",
        source_status="revoked",
    )
    _write_source(
        sources,
        QUARANTINE,
        "Torque latency, model-generated.",
        content_hash="ddd0000004",
        evidence_strength="model-generated",
    )

    _write_concept(
        concepts,
        "Torque_Overview",
        f"- Torque reached GA at v2.0.0 ([[Sources/{CLEAN_A}#page=1|s]]).\n"
        f"- Torque raised a Series A round ([[Sources/{CLEAN_B}#page=2|s]]).",
        f"- [[Sources/{CLEAN_A}|s]].\n- [[Sources/{CLEAN_B}|s]].",
    )
    _write_concept(
        concepts,
        "Torque_Throughput",
        f"- Torque sustains high throughput on a single node ([[Sources/{REVOKED}#page=3|s]]).",
        f"- [[Sources/{REVOKED}|s]].",
    )
    _write_concept(
        concepts,
        "Torque_Latency",
        f"- Torque tail latency is 5ms at p99 ([[Sources/{QUARANTINE}#page=4|s]]).",
        f"- [[Sources/{QUARANTINE}|s]].",
    )
    return vault


@pytest.fixture()
def single_clean_vault(tmp_path: Path) -> Path:
    """One clean source + one clean claim — so staling it empties the admitted set."""
    vault = tmp_path / "solo"
    sources = vault / "notes" / "Sources"
    concepts = vault / "notes" / "Concepts"
    _write_source(sources, CLEAN_A, "Torque reached GA at v2.0.0.", content_hash="aaa0000001")
    _write_concept(
        concepts,
        "Torque_Overview",
        f"- Torque reached GA at v2.0.0 ([[Sources/{CLEAN_A}#page=1|s]]).",
        f"- [[Sources/{CLEAN_A}|s]].",
    )
    return vault


def _scaffold(path: Path) -> Path:
    path.write_text(
        "---\ntitle: Torque question\nasked_at: '2026-07-15T00:00:00'\n---\n\n"
        "# Question\n\nq\n\n# Answer\n\n__ANSWER_PENDING__\n",
        encoding="utf-8",
    )
    return path


def _generator_citing(claim_ids: list[str]):
    """A deterministic generator whose answer cites exactly ``claim_ids``."""

    def generate(prompt: str, answer_path: Path | None) -> str:
        body = "\n".join(
            f"The Torque system is proven reliable in production [{cid}]." for cid in claim_ids
        )
        text = (
            "---\ntitle: Torque question\nasked_at: '2026-07-15T00:00:00'\n---\n\n"
            f"# Answer\n\n{body or 'The Torque system is fast and reliable in production.'}\n"
        )
        if answer_path is not None:
            Path(answer_path).write_text(text, encoding="utf-8")
        return text

    return generate


def _excluded_id(package, reason_substr: str) -> str:
    for exc in package.excluded_claims:
        if any(reason_substr in r for r in exc["reasons"]):
            return str(exc["claim_id"])
    raise AssertionError(f"no excluded claim with reason ~{reason_substr!r}")


# --------------------------------------------------------------------------- #
# Exit-gate criterion 1 — quarantined / unsupported claim -> refused
# --------------------------------------------------------------------------- #


def test_decision_answer_relying_on_quarantined_claim_is_refused(full_vault: Path):
    store = _store_for(full_vault)
    package = context_package.build_context_package(
        "Torque overview", "decision", vault=full_vault, store=store
    )
    quarantined = _excluded_id(package, "admission:quarantine")

    result = output_gate.serve_ask(
        "Torque overview",
        "decision",
        generate=_generator_citing([quarantined]),
        store=store,
        vault=full_vault,
    )
    assert result["decision"] in {"refuse", "abstain"}
    assert quarantined not in result["reliance"]
    # The refusal is explained: the answer cited an excluded (quarantined) claim.
    assert any(v.get("kind") == "excluded-claim" for v in result["violations"])


# --------------------------------------------------------------------------- #
# Exit-gate criterion 2 — no claim map -> refused
# --------------------------------------------------------------------------- #


def test_decision_answer_with_no_claim_map_is_refused(full_vault: Path):
    store = _store_for(full_vault)
    result = output_gate.serve_ask(
        "Torque overview",
        "decision",
        generate=_generator_citing([]),  # factual prose, cites nothing
        store=store,
        vault=full_vault,
    )
    assert result["decision"] == "refuse"
    assert result["reliance"] == []
    kinds = {v.get("kind") for v in result["violations"]}
    assert "empty-reliance-set" in kinds or "uncited-factual-sentence" in kinds


# --------------------------------------------------------------------------- #
# Exit-gate criterion 3 — source update makes a dependent answer stale
# --------------------------------------------------------------------------- #


def test_source_update_makes_dependent_decision_answer_stale(single_clean_vault: Path):
    store = _store_for(single_clean_vault)
    package = context_package.build_context_package(
        "Torque overview", "decision", vault=single_clean_vault, store=store
    )
    assert package.claim_ids, "the clean claim must be admitted before invalidation"

    # Run the real F2.1 invalidation for the changed source -> writes the stale-set.
    with context_package._redirect_vault(single_clean_vault):
        claims = claim_registry.load_claims()
    queue_path = single_clean_vault / "data" / "invalidation_queue.json"
    report = invalidation.invalidate_on_source_change(
        CLEAN_A,
        old_hash="aaa0000001",
        new_hash="eee0000009",
        graph={"project": "t", "nodes": [], "edges": []},
        claims=claims,
        store=store,
        queue_path=queue_path,
        recompute=False,
        flag=False,
    )
    assert set(package.claim_ids).issubset(invalidation.stale_targets(queue_path))
    assert report["stale_claims"]

    # A decision serve that relies on the now-stale claim must refuse/abstain,
    # and must not generate (the stale-set is consulted BEFORE generation).
    result = output_gate.serve_ask(
        "Torque overview",
        "decision",
        generate=_generator_citing(list(package.claim_ids)),
        store=store,
        vault=single_clean_vault,
        queue_path=queue_path,
    )
    assert result["decision"] in {"refuse", "abstain"}
    assert result["generated"] is False


# --------------------------------------------------------------------------- #
# Exit-gate criterion 4 — a revoked source cannot appear in a current decision
# --------------------------------------------------------------------------- #


def test_revoked_source_cannot_appear_in_decision_answer(full_vault: Path):
    store = _store_for(full_vault)
    package = context_package.build_context_package(
        "Torque throughput", "decision", vault=full_vault, store=store
    )
    revoked_claim = _excluded_id(package, "revoked")
    # The revoked-source claim is excluded from the package, never admitted.
    assert revoked_claim not in package.claim_ids

    result = output_gate.serve_ask(
        "Torque throughput",
        "decision",
        generate=_generator_citing([revoked_claim]),
        store=store,
        vault=full_vault,
    )
    assert result["decision"] == "refuse"
    assert revoked_claim not in result["reliance"]
    assert any(v.get("kind") == "excluded-claim" for v in result["violations"])


# --------------------------------------------------------------------------- #
# Exit-gate criterion 5 — every serving decision has a reproducible audit record
# --------------------------------------------------------------------------- #


def test_every_serving_decision_has_reproducible_audit_record(full_vault: Path):
    store = _store_for(full_vault)
    package = context_package.build_context_package(
        "Torque overview", "decision", vault=full_vault, store=store
    )
    result = output_gate.serve_ask(
        "Torque overview",
        "decision",
        generate=_generator_citing(list(package.claim_ids)),
        store=store,
        vault=full_vault,
    )
    assert result["decision"] == "permit"

    audit = serving_audit(store, result["answer_id"])
    assert audit["decision"] in {"allowed", "qualified", "refused"}
    assert audit["events"], "the serving decision must leave a validation event"
    gate_events = [e for e in audit["events"] if e.validator == "consequence_gate"]
    assert gate_events
    # The audit event pins the exact context package the decision was made against.
    assert gate_events[-1].target_version == result["package_hash"]


# --------------------------------------------------------------------------- #
# Exploratory permit + memo stamping + determinism
# --------------------------------------------------------------------------- #


def test_exploratory_serve_permits_and_stamps_memo(full_vault: Path, tmp_path: Path):
    store = _store_for(full_vault)
    answer_path = _scaffold(tmp_path / "answer.md")
    result = output_gate.serve_ask(
        "Torque overview",
        "exploratory",
        generate=_generator_citing([]),
        store=store,
        vault=full_vault,
        answer_path=answer_path,
    )
    assert result["decision"] == "permit"

    fm, _ = parse_frontmatter(answer_path.read_text(encoding="utf-8"))
    assert fm.get("consequence_tier") == "exploratory"
    assert fm.get("context_package_hash") == result["package_hash"]


def test_serving_is_deterministic(full_vault: Path):
    store = _store_for(full_vault)
    r1 = output_gate.serve_ask(
        "Torque overview", "decision", generate=_generator_citing([]), store=store, vault=full_vault
    )
    r2 = output_gate.serve_ask(
        "Torque overview", "decision", generate=_generator_citing([]), store=store, vault=full_vault
    )
    assert r1["package_hash"] == r2["package_hash"]
    assert r1["decision"] == r2["decision"]


# --------------------------------------------------------------------------- #
# Render gate (lighter): permits clean, refuses on stale
# --------------------------------------------------------------------------- #


def test_gate_render_permits_clean_and_audits(full_vault: Path):
    store = _store_for(full_vault)
    gate = output_gate.gate_render("Torque overview", "decision", store=store, vault=full_vault)
    assert gate["decision"] == "permit"
    assert gate["allowed"]
    audit = serving_audit(store, gate["render_id"])
    assert audit["events"] and audit["decision"] == "allowed"


def test_gate_render_refuses_on_stale_evidence(single_clean_vault: Path):
    store = _store_for(single_clean_vault)
    package = context_package.build_context_package(
        "Torque overview", "decision", vault=single_clean_vault, store=store
    )
    with context_package._redirect_vault(single_clean_vault):
        claims = claim_registry.load_claims()
    queue_path = single_clean_vault / "data" / "invalidation_queue.json"
    invalidation.invalidate_on_source_change(
        CLEAN_A,
        old_hash="aaa0000001",
        new_hash="eee0000009",
        graph={"project": "t", "nodes": [], "edges": []},
        claims=claims,
        store=store,
        queue_path=queue_path,
        recompute=False,
        flag=False,
    )
    assert package.claim_ids
    gate = output_gate.gate_render(
        "Torque overview", "decision", store=store, vault=single_clean_vault, queue_path=queue_path
    )
    assert gate["decision"] in {"refuse", "abstain"}
    assert gate["allowed"] == []


def test_invalid_tier_rejected(full_vault: Path):
    with pytest.raises(ValueError):
        output_gate.serve_ask("q", "not-a-tier", generate=_generator_citing([]), vault=full_vault)
