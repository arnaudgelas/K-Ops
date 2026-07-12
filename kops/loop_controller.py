"""Loop controller — the single next action + a convergence verdict.

`signal-log` measures the loop and gates on regressions; `review-queue` lists everything
that needs a human. This is the missing **controller**: given the current deterministic
signals, it emits ONE next action (the highest-leverage minimal repair) and a convergence
verdict against explicit stop criteria — the "what do I do next, and am I done?" layer that
an agent-driven or human-run repair loop needs on each iteration (see design.md Loop
Engineering).

Deterministic and non-gameable by construction: it consumes `review-queue` items (all
derived from committed artifacts) and the `signal-log` vector. It *recommends*; it never
acts. Actuation stays human-gated (design principle 7).

Stop criteria — three states, from the deterministic signals only:

- ``blocking``   — at least one error-severity review-queue item, OR an error-class signal
                   (failed_quote_spans / blocked_claims) > 0, OR a derived artifact missing.
                   The loop MUST continue; the vault is not safe for consequential use.
- ``cleanup``    — no blocking condition, but warning/info items remain. Safe to stop the
                   mandatory loop; optional cleanup is left. This is "converged enough".
- ``converged``  — no items at all and no blocking condition. Fully clean; stop.

The next action is the single highest-severity review-queue item (they are already ranked
error -> warning -> info); ``converged`` has no next action.
"""

from __future__ import annotations

from kops.signal_history import ERROR_SIGNALS, compute_availability, compute_signal_vector
from kops.review_queue import build_queue

# Per-category concrete command hint appended to the review-queue's own action text.
_COMMAND_HINT = {
    "failed-quote-span": "fix or remove the quote anchor, then `kops verify-spans`",
    "unverifiable-quote-span": "restore the source content or correct the source_id",
    "blocked-claim": "`kops retract` the source or re-source the claim, then `kops extract-claims`",
    "quarantined-claim": "verify against a primary source, then `kops extract-claims`",
    "unsupported-claim": "add an inline source citation or move the claim to Open Questions",
    "undocumented-contradiction": "add an `## Open Questions` section, then `kops extract-contradictions`",
    "adversarial-source": "review the raw content before any compile uses it",
    "source-needs-verification": "fetch primary sources or verify the lead",
    "unreviewed-probe": "run the Probe Review checklist",
    "knowledge-gap": "add a Related Concepts link, or file a research question (`kops community-audit`)",
    "fragile-cluster": "add cross-links so the cluster is not a single point of failure",
}


def assess(items: list[dict], signals: dict, availability: dict) -> dict:
    """Pure controller policy. Returns the loop verdict and the single next action.

    ``items`` are review-queue records (severity-sorted error -> warning -> info).
    """
    from collections import Counter

    by_sev = Counter(it["severity"] for it in items)
    error_signals_up = sorted(k for k in ERROR_SIGNALS if signals.get(k, 0) > 0)
    missing_artifacts = sorted(k for k, present in availability.items() if not present)

    blocking = bool(by_sev.get("error", 0) or error_signals_up or missing_artifacts)

    if blocking:
        status = "blocking"
    elif items:
        status = "cleanup"
    else:
        status = "converged"

    next_item = items[0] if items else None
    next_action = None
    if next_item is not None:
        next_action = {
            "category": next_item["category"],
            "severity": next_item["severity"],
            "ref": next_item["ref"],
            "detail": next_item["detail"],
            "action": next_item["action"],
            "command_hint": _COMMAND_HINT.get(next_item["category"]),
        }

    blocking_reasons: list[str] = []
    if by_sev.get("error", 0):
        blocking_reasons.append(f"{by_sev['error']} error-severity review item(s)")
    if error_signals_up:
        blocking_reasons.append(f"error-class signal(s) > 0: {', '.join(error_signals_up)}")
    if missing_artifacts:
        blocking_reasons.append(f"missing derived artifact(s): {', '.join(missing_artifacts)}")

    return {
        "status": status,
        "converged": status == "converged",
        "safe_to_stop": status in ("cleanup", "converged"),
        "blocking_reasons": blocking_reasons,
        "remaining": {
            "error": by_sev.get("error", 0),
            "warning": by_sev.get("warning", 0),
            "info": by_sev.get("info", 0),
        },
        "next_action": next_action,
    }


def compute_verdict() -> dict:
    """Vault-backed controller: gather signals + review queue, apply the policy."""
    return assess(build_queue(), compute_signal_vector(), compute_availability())


def run(fmt: str = "text") -> dict:
    verdict = compute_verdict()

    if fmt == "json":
        import json

        print(json.dumps(verdict, indent=2, ensure_ascii=False))
        return verdict

    status = verdict["status"]
    rem = verdict["remaining"]
    banner = {
        "blocking": "ACTION REQUIRED — the vault is not safe for consequential use",
        "cleanup": "SAFE TO STOP — no blocking issues; optional cleanup remains",
        "converged": "CONVERGED — nothing left in the loop",
    }[status]
    print(f"Loop status: {status.upper()} — {banner}")
    print(f"  remaining: {rem['error']} error, {rem['warning']} warning, {rem['info']} info")
    for reason in verdict["blocking_reasons"]:
        print(f"  blocking: {reason}")

    na = verdict["next_action"]
    if na is not None:
        print("\nNext action (highest-leverage single step):")
        print(f"  [{na['severity']}] {na['category']} — {na['ref']}")
        print(f"    {na['detail']}")
        print(f"    -> {na['action']}")
        if na["command_hint"]:
            print(f"    hint: {na['command_hint']}")
    else:
        print("\nNo action needed.")
    return verdict


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Recommend the single next loop action and a convergence verdict."
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    run(fmt=args.format)


if __name__ == "__main__":
    main()
