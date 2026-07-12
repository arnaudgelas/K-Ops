"""Inner-loop verification — check an agent's compile/heal write before trusting it.

The outer loop (`signal-log` / `next-action`) measures the vault across invocations.
The INNER loop is one agent invocation: observe -> act -> verify -> recover. `ask`
already closes its inner loop (the answer provenance gate rejects malformed memos).
`compile` and `heal` did not: the agent wrote concept pages and nothing re-checked them,
so the derived registries were left stale and a bad write went unnoticed until the next
manual audit.

This runs the deterministic **verify** step after `compile`/`heal`:

1. snapshot the signal vector *before* the agent runs,
2. after the agent writes, rebuild the registries the write invalidated (claims,
   contradictions, quote-spans),
3. snapshot *after*, and check whether the write **regressed** the deterministic signal
   vector — a new failed span / blocked claim, or a vanished artifact.

Boundary (deliberate): this VERIFIES and REPORTS; it does not **recover** (re-invoke the
agent to repair). Auto-recovery needs a live agent and stays human-gated (design
principle 7). A regression is surfaced loudly for a human — or a follow-up agent pass —
to fix or revert. The regression check itself is deterministic and non-gameable (it reuses
the `signal-log` signal vector), so this half is fully testable without an agent.
"""

from __future__ import annotations

from kops.signal_history import (
    compute_availability,
    compute_signal_vector,
    delta,
    detect_availability_regression,
    detect_regression,
)


def snapshot() -> dict:
    """Current deterministic signal vector + artifact availability."""
    return {"signals": compute_signal_vector(), "availability": compute_availability()}


def rebuild_derived() -> None:
    """Regenerate the derived registries a concept-page write invalidates."""
    from kops.claim_registry import run as run_claims
    from kops.contradiction_registry import run as run_contradictions
    from kops.span_verify import run as run_spans

    run_claims()
    run_contradictions()
    run_spans()


def assess_write(before: dict, after: dict) -> dict:
    """PURE — did the write regress the signal vector (signals or availability)?"""
    sig_reg, sig_reasons = detect_regression(before["signals"], after["signals"])
    avail_reg, avail_reasons = detect_availability_regression(
        before["availability"], after["availability"]
    )
    return {
        "regressed": sig_reg or avail_reg,
        "reasons": sig_reasons + avail_reasons,
        "delta": delta(before["signals"], after["signals"]),
    }


def verify_agent_write(before: dict, rebuild: bool = True) -> dict:
    """Rebuild derived state, then assess whether the agent write regressed the vault."""
    if rebuild:
        rebuild_derived()
    after = snapshot()
    result = assess_write(before, after)
    result["after"] = after
    return result


def report(result: dict) -> None:
    """Print the inner-loop verdict. Loud on regression, quiet on a clean write."""
    if result["regressed"]:
        print("\n[!] INNER-LOOP VERIFY: this agent write REGRESSED the vault:")
        for reason in result["reasons"]:
            print(f"  - {reason}")
        print("  Review with `kops next-action`; repair or revert before trusting this write.")
    else:
        print("\nInner-loop verify: no deterministic regression from this write.")
