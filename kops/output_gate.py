"""Consequence-gated answer serving (M2 task C2.4).

This module is the *serving-path integration* that ties M2 together. It does not
re-implement any governance primitive — it composes the ones the earlier M2
tasks already shipped into the exact process the roadmap prescribes for a
governed answer:

1. build (and persist) an immutable :class:`~kops.evidence_model.ContextPackage`
   (C2.1) — the frozen evidence the answer may rely on;
2. **pre-gate** the package's admitted claims with the consequence-tier policy
   (C2.3), consulting the source-invalidation stale-set (F2.1) and the package's
   own freshness/exclusions. If nothing survives, we *do not generate*;
3. **generate** the answer through an injected generator (in production this
   wraps ``readonly_agent_run``; in tests it returns a canned memo). The prompt
   carries the tier, the admitted claim ids, and a claim-citation instruction;
4. **validate the claim map** (C2.2): every factual sentence must rest on an
   admitted claim id, nothing excluded/unknown/uncited may be smuggled in, and
   no frozen source version may have moved under the answer;
5. **finalize** the decision — ``permit | qualify | abstain | refuse``;
6. **record an immutable ValidationEvent** (F2.2, validator ``consequence_gate``)
   against the answer id — the reproducible audit record the M2 exit gate wants;
7. **stamp** ``consequence_tier`` + ``context_package_hash`` into the memo.

Everything here is deterministic given its inputs: the generator is injected (no
LLM call lives in this module), and every gate it consults is a pure function of
the frozen package + the stale-set artifact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from kops import context_package as _context_package
from kops import invalidation, tier_policy
from kops.answer_claim_map import validate_answer_claim_map
from kops.consequence_gate import TIERS
from kops.evidence_model import AnswerMemo, ContextPackage, stable_id
from kops.evidence_store import EvidenceStore
from kops.utils import parse_frontmatter
from kops.validation_log import CONSEQUENCE_GATE, TARGET_ANSWER, record_event

# The serving-policy fingerprint stamped on every audit event this module emits.
POLICY_VERSION = "m2-c2.4"

# Module-level indirections so tests can inject a canned package/store without a
# real vault. Rebinding ``output_gate.build_context_package`` / ``EvidenceStore``
# is enough to isolate a unit test from retrieval and from the real ledger.
build_context_package = _context_package.build_context_package

# A serving decision (permit|qualify|abstain|refuse) mapped to the canonical
# consequence_gate result vocabulary (allowed|qualified|refused) for the ledger.
_DECISION_TO_RESULT = {
    "permit": "allowed",
    "qualify": "qualified",
    "abstain": "refused",
    "refuse": "refused",
}

# Tiers whose claim map is enforced (a bad map refuses/qualifies rather than warns).
_STRICT_TIERS = {"recommendation", "decision", "autonomous"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _answer_id(question: str, tier: str, package_hash: str, answer_path: Path | None) -> str:
    """The stable audit target id for this served answer.

    Prefer the answer memo's own ``memo_id`` (so the audit trail keys off the
    persisted note). Fall back to a content-derived id when no memo exists yet
    (e.g. a pre-gate abstention that never generated a memo) so *every* serving
    decision still has a reproducible target.
    """
    if answer_path is not None and Path(answer_path).exists():
        try:
            fm, _ = parse_frontmatter(Path(answer_path).read_text(encoding="utf-8"))
        except OSError:
            fm = {}
        if fm.get("title") or fm.get("asked_at"):
            return AnswerMemo.from_frontmatter(fm).memo_id
    return stable_id("ans", question, tier, package_hash)


def _admitted_claim_dicts(package: ContextPackage, vault: Path | None) -> list[dict]:
    """Full claim-registry dicts for the package's admitted claim ids.

    The tier policy needs real claim metadata (source ids, admission status,
    ``conflicts_with``) — not just ids — to re-check corroboration, contradiction
    and freshness. We load them through the same vault redirection the package
    was built under, so the dicts match exactly what the package froze.
    """
    if not package.claim_ids:
        return []
    from kops import claim_registry

    with _context_package.redirect_vault(vault):
        all_claims = claim_registry.load_claims()
    wanted = set(package.claim_ids)
    return [c for c in all_claims if str(c.get("claim_id") or c.get("id") or "") in wanted]


def _gate_prompt(tier: str, allowed_ids: list[str]) -> str:
    """The claim-citation guidance injected into the generator prompt."""
    lines = [f"Consequence tier: {tier}."]
    if allowed_ids:
        lines.append("You may cite ONLY these admitted claim ids as governed evidence:")
        lines.extend(f"- {cid}" for cid in allowed_ids)
    else:
        lines.append("No governed claims are available for citation at this tier.")
    if tier in _STRICT_TIERS:
        lines.append(
            "Every factual sentence MUST cite at least one of the claim ids above, "
            "written inline (e.g. `... is guaranteed [clm-xxxxxxxxxx].`). Do not cite "
            "any claim id that is not listed above."
        )
    else:
        lines.append(
            "Cite the claim ids above wherever they support a sentence. Unsupported "
            "material is permitted at this tier but must be explicitly labelled."
        )
    return "\n".join(lines)


def _stamp_memo(answer_path: Path | None, tier: str, package_hash: str) -> None:
    """Write ``consequence_tier`` + ``context_package_hash`` into the memo frontmatter.

    A targeted line upsert (rather than a YAML re-dump) so the rest of the memo's
    formatting is preserved untouched.
    """
    if answer_path is None:
        return
    path = Path(answer_path)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text:
        return
    head, rest = text.split("\n---\n", 1)
    lines = head[4:].splitlines()

    def upsert(key: str, value: str) -> None:
        newline = f"{key}: {value}"
        for i, line in enumerate(lines):
            if line.startswith(f"{key}:"):
                lines[i] = newline
                return
        lines.append(newline)

    upsert("consequence_tier", tier)
    upsert("context_package_hash", package_hash)
    path.write_text("---\n" + "\n".join(lines) + "\n---\n" + rest, encoding="utf-8")


def _record(
    store: EvidenceStore,
    *,
    answer_id: str,
    decision: str,
    package_hash: str,
    reason: str,
    policy_version: str,
):
    """Append the immutable consequence-gate ValidationEvent for this decision."""
    return record_event(
        store,
        target_id=answer_id,
        target_type=TARGET_ANSWER,
        validator=CONSEQUENCE_GATE,
        result=_DECISION_TO_RESULT[decision],
        new_status=decision,
        reason=reason,
        policy_version=policy_version,
        target_version=package_hash,
    )


# --------------------------------------------------------------------------- #
# Serve
# --------------------------------------------------------------------------- #


def serve_ask(
    question: str,
    tier: str,
    *,
    generate: Callable[[str, Path | None], str | None],
    store: EvidenceStore | None = None,
    vault: Path | None = None,
    index: Any | None = None,
    answer_path: Path | str | None = None,
    queue_path: Path | None = None,
    current_source_versions: list[str] | tuple[str, ...] | None = None,
    entailment: dict[str, str] | None = None,
    contradictions: list[str] | None = None,
    policy_version: str = POLICY_VERSION,
) -> dict:
    """Serve one consequence-gated answer and return its decision record.

    ``generate(prompt, answer_path) -> str`` produces the answer text (and, in
    production, writes it to ``answer_path`` via the agent). It is only invoked
    when the pre-gate admits something to answer from.

    Returns ``{decision, tier, answer_path, package_hash, audit_event_id,
    answer_id, reliance, violations, generated}`` where ``decision`` is one of
    ``permit | qualify | abstain | refuse``.
    """
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")

    store = store or EvidenceStore()
    apath = Path(answer_path) if answer_path is not None else None

    # 1. Freeze the exact evidence this answer may rely on.
    package = build_context_package(question, tier, index=index, vault=vault, store=store)
    package_hash = package.package_hash
    answer_id = _answer_id(question, tier, package_hash, apath)

    # 2. Pre-gate the admitted claims through the tier policy, then subtract any
    #    claim (or the whole package) that the source-invalidation stale-set has
    #    marked stale — a stale claim may not be served as current at decision+.
    admitted = _admitted_claim_dicts(package, vault)
    stale = invalidation.stale_targets(queue_path)
    pre = tier_policy.evaluate_tier_policy(
        admitted,
        tier,
        entailment=entailment,
        freshness=package.freshness,
        contradictions=contradictions,
        package=package,
    )
    package_stale = package_hash in stale
    stale_claim_hits = sorted(set(pre["allowed_claim_ids"]) & stale)
    allowed_ids = [
        cid for cid in pre["allowed_claim_ids"] if cid not in stale and not package_stale
    ]

    stale_reasons: list[str] = []
    if package_stale:
        stale_reasons.append(f"context-package-stale:{package_hash}")
    stale_reasons.extend(f"stale-claim:{cid}" for cid in stale_claim_hits)

    pre_decision = pre["decision"]
    # Staleness can empty an otherwise-permitted decision -> fail closed by tier.
    if tier != "exploratory" and not allowed_ids and pre_decision in {"permit", "qualify"}:
        pre_decision = "refuse" if tier == "autonomous" else "abstain"

    # Pre-gate refusal / abstention: never generate; record the decision anyway.
    if pre_decision in {"abstain", "refuse"}:
        violations = list(pre["barred"]) + [
            {"claim_id": None, "reasons": [r]} for r in stale_reasons
        ]
        reason = _pre_reason(tier, pre_decision, pre, stale_reasons)
        event = _record(
            store,
            answer_id=answer_id,
            decision=pre_decision,
            package_hash=package_hash,
            reason=reason,
            policy_version=policy_version,
        )
        _stamp_memo(apath, tier, package_hash)
        return _result(
            pre_decision,
            tier,
            apath,
            package_hash,
            event.event_id,
            answer_id,
            [],
            violations,
            False,
        )

    # 3. Generate against the frozen package (tier + admitted ids + citation rule).
    prompt = _gate_prompt(tier, allowed_ids)
    answer_text = generate(prompt, apath)
    if not answer_text and apath is not None and apath.exists():
        answer_text = apath.read_text(encoding="utf-8")
    answer_text = answer_text or ""

    # 4. Validate the answer-to-claim map against the package at this tier.
    cmap = validate_answer_claim_map(
        answer_text, package, tier=tier, current_source_versions=current_source_versions
    )
    reliance = cmap["reliance"]
    violations = cmap["violations"]

    # 5. Finalize: a bad map refuses (decision/autonomous) or qualifies
    #    (recommendation); otherwise the tier-policy verdict stands.
    if not cmap["valid"]:
        decision = "refuse" if tier in {"decision", "autonomous"} else "qualify"
    else:
        decision = pre_decision

    reason = _post_reason(tier, decision, cmap, reliance)
    event = _record(
        store,
        answer_id=answer_id,
        decision=decision,
        package_hash=package_hash,
        reason=reason,
        policy_version=policy_version,
    )
    _stamp_memo(apath, tier, package_hash)
    return _result(
        decision, tier, apath, package_hash, event.event_id, answer_id, reliance, violations, True
    )


def gate_render(
    brief: str,
    tier: str,
    *,
    store: EvidenceStore | None = None,
    vault: Path | None = None,
    index: Any | None = None,
    queue_path: Path | None = None,
    policy_version: str = POLICY_VERSION,
) -> dict:
    """Gate the claims a render would rely on at ``tier`` and audit the decision.

    Deliberately lighter than :func:`serve_ask` (render has no claim map to
    validate before it runs): build the package, pre-gate the admitted claims,
    refuse on stale/blocked evidence, and record the immutable audit event.
    Returns ``{decision, tier, package_hash, audit_event_id, render_id, allowed}``.
    """
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")

    store = store or EvidenceStore()
    package = build_context_package(brief, tier, index=index, vault=vault, store=store)
    package_hash = package.package_hash

    admitted = _admitted_claim_dicts(package, vault)
    stale = invalidation.stale_targets(queue_path)
    pre = tier_policy.evaluate_tier_policy(
        admitted, tier, freshness=package.freshness, package=package
    )
    package_stale = package_hash in stale
    allowed = [cid for cid in pre["allowed_claim_ids"] if cid not in stale and not package_stale]

    decision = pre["decision"]
    if tier != "exploratory" and not allowed and decision in {"permit", "qualify"}:
        decision = "refuse" if tier == "autonomous" else "abstain"

    render_id = stable_id("ren", brief, tier, package_hash)
    reason = f"render gate [{tier}] -> {decision}; {len(allowed)} admitted claim(s)"
    if package_stale:
        reason += "; context package is stale"
    event = _record(
        store,
        answer_id=render_id,
        decision=decision,
        package_hash=package_hash,
        reason=reason,
        policy_version=policy_version,
    )
    return {
        "decision": decision,
        "tier": tier,
        "package_hash": package_hash,
        "audit_event_id": event.event_id,
        "render_id": render_id,
        "allowed": allowed,
    }


# --------------------------------------------------------------------------- #
# Reason / result formatting
# --------------------------------------------------------------------------- #


def _pre_reason(tier: str, decision: str, pre: dict, stale_reasons: list[str]) -> str:
    bits = [f"pre-gate [{tier}] -> {decision}"]
    if not pre["allowed_claim_ids"] and not stale_reasons:
        bits.append("no admitted claim cleared the evidence bar")
    if pre["barred"]:
        bits.append(f"{len(pre['barred'])} barred claim(s)")
    if stale_reasons:
        bits.append("stale: " + ", ".join(stale_reasons))
    return "; ".join(bits)


def _post_reason(tier: str, decision: str, cmap: dict, reliance: list[str]) -> str:
    bits = [f"post-gate [{tier}] -> {decision}"]
    if cmap["valid"]:
        bits.append(f"relies on {len(reliance)} admitted claim(s)")
    else:
        kinds = sorted({v.get("kind", "violation") for v in cmap["violations"]})
        bits.append("claim-map violations: " + ", ".join(kinds))
    return "; ".join(bits)


def _result(
    decision: str,
    tier: str,
    answer_path: Path | None,
    package_hash: str,
    audit_event_id: str,
    answer_id: str,
    reliance: list[str],
    violations: list[dict],
    generated: bool,
) -> dict:
    return {
        "decision": decision,
        "tier": tier,
        "answer_path": str(answer_path) if answer_path is not None else None,
        "package_hash": package_hash,
        "audit_event_id": audit_event_id,
        "answer_id": answer_id,
        "reliance": reliance,
        "violations": violations,
        "generated": generated,
    }


__all__ = ["serve_ask", "gate_render", "POLICY_VERSION"]
