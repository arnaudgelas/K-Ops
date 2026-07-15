"""Consequence-tier policy matrix (M2 task C2.3).

Encodes how each consequence tier treats a set of served claims, composing the
deterministic admission gate in :mod:`kops.consequence_gate` with the extra
dimensions the tier matrix requires: entailment treatment, freshness/staleness,
unresolved material contradictions, and (for the autonomous tier) independent
corroboration and fail-closed behaviour.

Everything here is a PURE function of its inputs. Entailment verdicts, freshness
states, and contradiction membership are passed in (the LLM judge is never
called from this module), so a decision is reproducible from its inputs.

Tiers (see also ``docs/TRUST_CONTRACT.md`` §5):

- **exploratory** — permit; unsupported material is allowed but labelled;
  entailment is advisory; the answer never claims decision-suitability.
- **recommendation** — blocked/revoked evidence is barred (gate); partial or
  unsupported entailment and stale sources become warnings; human stays in loop.
- **decision** — unsupported/contradicted/not_evaluable claims are barred (gate
  + entailment); stale evidence is barred; an unresolved material contradiction
  forces *qualify* or *abstain*; a barred claim can only enter via an audited
  human override.
- **autonomous** — only directly-supported, current, admitted, corroborated
  claims pass; any unresolved contradiction or residual uncertainty fails
  closed (refuse).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from kops import consequence_gate

TIERS = consequence_gate.TIERS

# Entailment verdicts that count as "not adequately supported".
_ENTAILMENT_BAR = {"unsupported", "contradicted", "not_evaluable"}
# content_drift / context-package freshness values that mean "stale".
_STALE_FRESHNESS = {"drifted", "revalidation-required"}

# How each tier treats entailment verdicts.
_ENTAILMENT_TREATMENT = {
    "exploratory": "advisory",
    "recommendation": "warn",
    "decision": "gate",
    "autonomous": "gate",
}


def _claim_id(claim: Mapping[str, Any]) -> str:
    return str(claim.get("claim_id") or claim.get("id"))


def _claim_sources(claim: Mapping[str, Any]) -> list[str]:
    return [str(s) for s in (claim.get("source_ids") or [])]


def _is_stale(claim: Mapping[str, Any], freshness: Mapping[str, str]) -> list[str]:
    """Freshness reasons a claim is stale (empty = fresh)."""
    return [
        f"stale-source:{sid}"
        for sid in _claim_sources(claim)
        if freshness.get(sid) in _STALE_FRESHNESS
    ]


def evaluate_tier_policy(
    claims: list[dict],
    tier: str,
    *,
    entailment: Mapping[str, str] | None = None,
    freshness: Mapping[str, str] | None = None,
    contradictions: Iterable[str] | None = None,
    package: Any | None = None,
) -> dict[str, Any]:
    """Evaluate the tier policy over ``claims``.

    ``entailment`` maps claim_id -> verdict; ``freshness`` maps source_id ->
    status; ``contradictions`` is the set of claim_ids in unresolved material
    contradictions (defaults to claims whose ``conflicts_with`` is non-empty).
    ``package`` may supply ``freshness`` when not given explicitly.

    Returns ``{"tier", "decision", "allowed_claim_ids", "barred", "warnings",
    "requires_human_override", "entailment_treatment"}`` where ``decision`` is
    one of ``permit | qualify | abstain | refuse``.
    """
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")

    entailment = dict(entailment or {})
    if freshness is None:
        freshness = dict(getattr(package, "freshness", {}) or {})
    if contradictions is None:
        contradictions = {_claim_id(c) for c in claims if c.get("conflicts_with")}
    contradicted = set(contradictions)
    treatment = _ENTAILMENT_TREATMENT[tier]

    # 1. Admission backbone — reuse the deterministic gate, don't fork it.
    gate = consequence_gate.assess_claims(claims, tier)
    gate_bars = {str(v["claim_id"]): list(v["reasons"]) for v in gate["violations"]}

    barred: list[dict] = []
    warnings: list[dict] = []
    allowed_ids: list[str] = []
    unresolved_contradiction = False

    for claim in claims:
        cid = _claim_id(claim)
        reasons: list[str] = list(gate_bars.get(cid, []))

        verdict = entailment.get(cid)
        stale = _is_stale(claim, freshness)
        in_contradiction = cid in contradicted

        # 2. Entailment: advisory / warn / gate by tier.
        if verdict in _ENTAILMENT_BAR:
            if treatment == "gate":
                reasons.append(f"entailment:{verdict}")
            elif treatment == "warn":
                warnings.append({"claim_id": cid, "kind": "entailment", "detail": verdict})
        elif verdict == "partial":
            if tier == "autonomous":
                reasons.append("entailment:partial")
            elif tier in {"recommendation", "decision"}:
                warnings.append({"claim_id": cid, "kind": "entailment", "detail": "partial"})

        # 3. Freshness: stale evidence barred at decision+, warned at recommendation.
        if stale:
            if tier in {"decision", "autonomous"}:
                reasons.extend(stale)
            elif tier == "recommendation":
                warnings.append({"claim_id": cid, "kind": "stale", "detail": ",".join(stale)})

        # 4. Autonomous: independent corroboration required, fail closed.
        if tier == "autonomous":
            if len(set(_claim_sources(claim))) < 2:
                reasons.append("needs-corroboration")
            if in_contradiction:
                reasons.append("unresolved-contradiction")

        # 5. Contradictions: at decision they force qualify/abstain, not a hard bar.
        if in_contradiction:
            unresolved_contradiction = True
            if tier in {"exploratory", "recommendation"}:
                warnings.append({"claim_id": cid, "kind": "contradiction", "detail": "unresolved"})

        if reasons:
            barred.append({"claim_id": cid, "reasons": sorted(set(reasons))})
        else:
            allowed_ids.append(cid)

    decision, requires_override = _decide(tier, allowed_ids, barred, unresolved_contradiction)

    return {
        "tier": tier,
        "decision": decision,
        "allowed_claim_ids": sorted(allowed_ids),
        "barred": barred,
        "warnings": warnings,
        "requires_human_override": requires_override,
        "entailment_treatment": treatment,
    }


def _decide(
    tier: str,
    allowed_ids: list[str],
    barred: list[dict],
    unresolved_contradiction: bool,
) -> tuple[str, bool]:
    """Resolve the tier-level serving decision and human-override requirement."""
    if tier == "exploratory":
        # Everything is visible and labelled; exploration never fails closed.
        return "permit", False

    if tier == "recommendation":
        if not allowed_ids:
            return "abstain", False
        # Human stays in the loop for a recommendation; barred claims need review.
        return "permit", bool(barred)

    if tier == "decision":
        if not allowed_ids:
            return "abstain", bool(barred)
        if unresolved_contradiction:
            return "qualify", bool(barred)
        # Barred claims may only enter via an explicit, audited human override.
        return "permit", bool(barred)

    # autonomous — fail closed: any residual uncertainty refuses.
    if not allowed_ids or barred or unresolved_contradiction:
        return "refuse", False
    return "permit", False


def _main() -> None:  # pragma: no cover - thin CLI
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Evaluate the consequence-tier policy over claims.")
    ap.add_argument("--claims", required=True, help="path to a claims JSON list")
    ap.add_argument("--tier", required=True, choices=list(TIERS))
    args = ap.parse_args()

    data = json.loads(Path(args.claims).read_text(encoding="utf-8"))
    claims = data["claims"] if isinstance(data, dict) else data
    result = evaluate_tier_policy(claims, args.tier)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["decision"] in {"permit", "qualify"} else 1)


if __name__ == "__main__":
    _main()
