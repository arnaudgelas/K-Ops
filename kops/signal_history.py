"""Signal history — turn the open quality loop into a measurable, gated one.

K-Ops already *computes* every "needs-a-human" signal (failed quote spans, blocked
claims, undocumented contradictions, …) but only ever reports the *current* state.
Nothing records whether the vault is getting better or worse over time, and nothing
fails closed when a regression sneaks in.

This module records a small, **deterministic** signal vector — six integer counts,
lower is better, 0 is ideal — to an append-only history (``data/history/signals.jsonl``),
reports the delta against the previous datapoint, and offers a fail-closed regression
gate for CI.

Non-gameable by construction: every signal is a plain count read off an already-derived
artifact (``data/span_verification.json``, ``data/claims.json``, ``data/contradictions.json``).
We never recompute the registries here — we only read what they last produced.

A deleted artifact must not look like an improvement. Each record therefore also stores
per-artifact **availability**, and an artifact going present->absent between records is
itself a HARD regression (you cannot certify "no regression" from data you can no longer
read; see design principle 5, fail loudly on missing provenance). Absolute absence with
no prior record is tolerated (a fresh vault before its first `extract-claims`). This closes
the naive/accidental deletion vector and makes deliberate deletion visible as
``availability`` in the committed JSONL; an adversarial agent with write access can still
rewrite history, and there the backstop is Git review (design principle 7), not this gate.

Signal classes:

- ERROR_SIGNALS  — a strict increase is a HARD regression (fail closed).
- everything else — WARNING class; tracked and reported, but never fails the gate.
- artifact disappearance (present->absent vs the last record) — HARD regression.

Run ``kops signal-log`` to report, ``--record`` to append a datapoint, ``--check`` to
exit non-zero on a hard regression.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess

from kops.utils import ROOT, ensure_dir, load_json

HISTORY_PATH = ROOT / "data" / "history" / "signals.jsonl"

# All signals: deterministic integer counts, lower is better, 0 is ideal.
SIGNAL_KEYS = (
    "failed_quote_spans",
    "unverifiable_quote_spans",
    "blocked_claims",
    "quarantined_claims",
    "unsupported_claims",
    "undocumented_contradictions",
)

# Hard-fail class: a strict increase in any of these is a regression.
ERROR_SIGNALS = {"failed_quote_spans", "blocked_claims"}

# The derived artifacts the signal vector is read from. A required artifact
# disappearing between records is a hard regression (see module docstring).
ARTIFACT_PATHS = {
    "span_verification": ROOT / "data" / "span_verification.json",
    "claims": ROOT / "data" / "claims.json",
    "contradictions": ROOT / "data" / "contradictions.json",
}


def signal_vector_from_artifacts(
    span_report: dict | None,
    claims: dict | None,
    contradictions: dict | None,
) -> dict[str, int]:
    """Compute the six-key signal vector from already-loaded artifact dicts.

    PURE — no I/O. A missing artifact (``None``) contributes 0 to its signals.
    """
    span_summary = (span_report or {}).get("summary", {})
    claim_list = (claims or {}).get("claims", [])
    contradiction_list = (contradictions or {}).get("contradictions", [])

    return {
        "failed_quote_spans": int(span_summary.get("failed", 0) or 0),
        "unverifiable_quote_spans": int(span_summary.get("unverifiable", 0) or 0),
        "blocked_claims": sum(1 for c in claim_list if c.get("admission_status") == "blocked"),
        "quarantined_claims": sum(
            1 for c in claim_list if c.get("admission_status") == "quarantine"
        ),
        "unsupported_claims": sum(
            1 for c in claim_list if c.get("evidence_status") == "unsupported"
        ),
        # Match review_queue.py: absent/null/falsy `documented` counts as undocumented.
        "undocumented_contradictions": sum(
            1 for r in contradiction_list if not r.get("documented", False)
        ),
    }


def compute_signal_vector() -> dict[str, int]:
    """Vault loader — read the three derived artifacts and build the vector."""
    span_report = load_json(ARTIFACT_PATHS["span_verification"], None)
    claims = load_json(ARTIFACT_PATHS["claims"], None)
    contradictions = load_json(ARTIFACT_PATHS["contradictions"], None)
    return signal_vector_from_artifacts(span_report, claims, contradictions)


def compute_availability() -> dict[str, bool]:
    """Which derived artifacts exist right now (present == readable, not deleted)."""
    return {name: path.exists() for name, path in ARTIFACT_PATHS.items()}


def detect_availability_regression(
    prev_availability: dict | None, curr_availability: dict
) -> tuple[bool, list[str]]:
    """Hard regression iff a required artifact went present -> absent vs the last record.

    No prior record (``prev_availability is None``) is tolerated: a fresh vault has no
    artifacts yet and cannot regress.
    """
    if not prev_availability:
        return False, []
    reasons: list[str] = []
    for name in ARTIFACT_PATHS:
        if prev_availability.get(name) is True and not curr_availability.get(name, False):
            reasons.append(
                f"artifact {name} disappeared (present -> absent); signals not trustworthy"
            )
    return (bool(reasons), reasons)


def _git_commit() -> str | None:
    """Best-effort short commit sha; None if git is unavailable or fails."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha or None


def build_record(vector: dict, availability: dict | None = None) -> dict:
    """Wrap a signal vector in a timestamped, commit-stamped history record."""
    return {
        "recorded_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "git_commit": _git_commit(),
        "signals": vector,
        "availability": availability if availability is not None else compute_availability(),
        "total": sum(vector.values()),
    }


def record_signals(vector: dict, availability: dict | None = None) -> dict:
    """Append one datapoint to the JSON Lines history and return the record."""
    record = build_record(vector, availability)
    ensure_dir(HISTORY_PATH.parent)
    line = json.dumps(record, ensure_ascii=False)
    with HISTORY_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return record


def load_history() -> list[dict]:
    """Parse the history file; [] if missing. Blank/corrupt lines are skipped."""
    if not HISTORY_PATH.exists():
        return []
    records: list[dict] = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def load_last() -> dict | None:
    """The most recent history record, or None if the history is empty."""
    history = load_history()
    return history[-1] if history else None


def delta(prev_signals: dict | None, curr_signals: dict) -> dict:
    """Per-signal prev/curr/change over the union of keys, sorted by key.

    ``prev`` and ``change`` are None for a signal absent from the prior record.
    """
    prev = prev_signals or {}
    keys = sorted(set(prev) | set(curr_signals))
    out: dict = {}
    for key in keys:
        curr = int(curr_signals.get(key, 0))
        if key in prev:
            p = int(prev[key])
            out[key] = {"prev": p, "curr": curr, "change": curr - p}
        else:
            out[key] = {"prev": None, "curr": curr, "change": None}
    return out


def detect_regression(prev_signals: dict | None, curr_signals: dict) -> tuple[bool, list[str]]:
    """Hard regression iff any ERROR_SIGNAL strictly increased vs prev.

    The first record can never regress: ``prev_signals is None`` => ``(False, [])``.
    """
    if prev_signals is None:
        return False, []
    reasons: list[str] = []
    for key in sorted(ERROR_SIGNALS):
        prev = int(prev_signals.get(key, 0))
        curr = int(curr_signals.get(key, 0))
        if curr > prev:
            reasons.append(f"{key}: {prev} -> {curr} (+{curr - prev})")
    return (bool(reasons), reasons)


def _change_str(entry: dict) -> str:
    change = entry["change"]
    if change is None:
        return "new"
    if change > 0:
        return f"+{change}"
    if change < 0:
        return str(change)
    return "0"


def run(record: bool = False, check: bool = False, fmt: str = "text") -> dict:
    """Report the signal vector, its delta, and (optionally) record / gate on it."""
    curr = compute_signal_vector()
    curr_avail = compute_availability()
    last = load_last()
    prev = last.get("signals") if last else None
    prev_avail = last.get("availability") if last else None

    # COMPARE against the prior last record BEFORE recording this run's datapoint.
    d = delta(prev, curr)
    sig_reg, sig_reasons = detect_regression(prev, curr)
    avail_reg, avail_reasons = detect_availability_regression(prev_avail, curr_avail)
    is_reg = sig_reg or avail_reg
    reasons = sig_reasons + avail_reasons

    if record:
        record_signals(curr, curr_avail)

    total = sum(curr.values())
    result = {
        "signals": curr,
        "availability": curr_avail,
        "total": total,
        "delta": d,
        "regression": {"hard": is_reg, "reasons": reasons},
        "recorded": record,
    }

    if fmt == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Signal history — total {total} (lower is better, 0 is ideal)")
        for key in SIGNAL_KEYS:
            entry = d.get(key, {"curr": curr.get(key, 0), "change": None})
            cls = "error" if key in ERROR_SIGNALS else "warning"
            print(f"  {key:<28} {entry['curr']:>4}  ({_change_str(entry)}) [{cls}]")
        print(f"  {'total':<28} {total:>4}")
        missing = [name for name, present in curr_avail.items() if not present]
        if missing:
            print(f"  artifacts missing: {', '.join(sorted(missing))}")
        if is_reg:
            print("REGRESSION (hard): " + "; ".join(reasons))
        if record:
            print("Datapoint recorded: data/history/signals.jsonl")

    if check and is_reg:
        print("FAIL: hard regression in error-class signals:")
        for reason in reasons:
            print(f"  - {reason}")
        import sys

        sys.exit(1)

    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Record and report the deterministic vault signal vector over time."
    )
    parser.add_argument(
        "--record", action="store_true", help="Append this run's datapoint to the history."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if an error-class signal strictly increased vs the last record.",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    run(record=args.record, check=args.check, fmt=args.format)


if __name__ == "__main__":
    main()
