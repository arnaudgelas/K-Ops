"""Consequence gating — is this evidence strong enough to act on at a given stakes level?

K-Ops accumulates governance metadata on every claim (`admission_status`, `evidence_status`,
`claim_quality`, `synthetic_origin`) but never *enforced* it at the output boundary. A claim
backed by a quarantined source, or one that is merely provisional, could still silently
support a high-stakes recommendation.

This gate makes the evidence bar explicit and checkable. Consequence tiers escalate:

- `exploratory`   — brainstorming / orientation. No bar; anything goes.
- `recommendation`— advice a human will weigh. Bars blocked (revoked / adversarial) sources.
- `decision`      — a choice will be made on this. Additionally bars quarantined / unknown /
                    unsupported evidence and weak / conflicting / stale / synthetic claims.
- `autonomous`    — an agent may act without review. Strongest: every claim must be admitted,
                    directly cited, and `supported` (no inherited evidence, no provisional).

Deterministic and non-gameable: it reads the claim registry only; no LLM judgment. It
*reports and gates*; it never rewrites claims (design principle 7, human-gated).

Run `kops consequence-gate --tier decision [--concept X]`; `--check` exits non-zero when the
evidence does not clear the bar.
"""

from __future__ import annotations

from kops.claim_registry import load_claims

TIERS = ("exploratory", "recommendation", "decision", "autonomous")


def _violations_for_claim(claim: dict, tier: str) -> list[str]:
    """Reasons this claim fails the evidence bar for ``tier`` (empty = clears it)."""
    if tier == "exploratory":
        return []

    adm = str(claim.get("admission_status") or "unknown")
    ev = str(claim.get("evidence_status") or "unsupported")
    quality = str(claim.get("claim_quality") or "")
    synthetic = claim.get("synthetic_origin") is True
    reasons: list[str] = []

    # recommendation and up: never rest on a blocked (revoked / do-not-use / adversarial) source.
    if adm == "blocked":
        reasons.append("blocked-source")
    if tier == "recommendation":
        return reasons

    # decision and up: admitted evidence only, and no weak/conflicting/stale/synthetic claims.
    if adm in {"quarantine", "unknown", "unsupported"}:
        reasons.append(f"admission:{adm}")
    if ev == "unsupported":
        reasons.append("unsupported-evidence")
    if quality in {"weak", "conflicting", "stale"}:
        reasons.append(f"claim-quality:{quality}")
    if synthetic:
        reasons.append("synthetic-origin")
    if tier == "decision":
        return sorted(set(reasons))

    # autonomous: strongest — must be exactly admitted + direct + supported.
    if adm != "admitted":
        reasons.append(f"not-admitted:{adm}")
    if ev != "direct":
        reasons.append(f"evidence-not-direct:{ev}")
    if quality != "supported":
        reasons.append(f"quality-not-supported:{quality or 'unknown'}")
    return sorted(set(reasons))


def assess_claims(claims: list[dict], tier: str) -> dict:
    """PURE — does this set of claims clear the evidence bar for ``tier``?"""
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")
    violations: list[dict] = []
    for claim in claims:
        reasons = _violations_for_claim(claim, tier)
        if reasons:
            violations.append(
                {
                    "claim_id": claim.get("claim_id") or claim.get("id"),
                    "concept": claim.get("concept"),
                    "reasons": reasons,
                }
            )
    return {
        "tier": tier,
        "allowed": not violations,
        "total_claims": len(claims),
        "usable_claims": len(claims) - len(violations),
        "violations": violations,
    }


def compute_gate(tier: str, concept: str | None = None) -> dict:
    """Vault-backed gate: load claims (optionally for one concept) and assess them."""
    claims = load_claims()
    if concept:
        claims = [c for c in claims if c.get("concept") == concept]
    result = assess_claims(claims, tier)
    result["concept"] = concept
    return result


def run(tier: str, concept: str | None = None, fmt: str = "text", check: bool = False) -> dict:
    result = compute_gate(tier, concept)

    if fmt == "json":
        import json

        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        scope = f"concept '{concept}'" if concept else "the whole vault"
        verdict = "CLEARS" if result["allowed"] else "DOES NOT CLEAR"
        print(f"Consequence gate [{tier}] over {scope}: {verdict} the bar")
        print(f"  {result['usable_claims']}/{result['total_claims']} claim(s) usable at this tier")
        for v in result["violations"]:
            print(f"  - {v['claim_id']} ({v['concept']}): {', '.join(v['reasons'])}")

    if check and not result["allowed"]:
        import sys

        sys.exit(1)
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Gate whether evidence clears the bar for a consequence tier."
    )
    parser.add_argument("--tier", required=True, choices=list(TIERS))
    parser.add_argument("--concept", help="Limit the gate to one concept stem.")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--check", action="store_true", help="Exit non-zero if the evidence does not clear the bar."
    )
    args = parser.parse_args()
    run(tier=args.tier, concept=args.concept, fmt=args.format, check=args.check)


if __name__ == "__main__":
    main()
