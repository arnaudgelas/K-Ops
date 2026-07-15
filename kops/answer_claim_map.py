"""Answer-to-claim mapping (M2 task C2.2).

A governed answer may only rest on claims that were frozen into its
:class:`~kops.evidence_model.ContextPackage`. This module validates that every
*factual* sentence of an answer cites at least one claim id that is present in
the package, and that the answer does not smuggle in claims the package never
admitted or that moved under it during generation.

The model may not self-introduce trusted claims: an answer that cites an unknown
claim, an excluded claim, or nothing at all (for a non-exploratory tier) is
refused. This is deterministic and explainable — every rejection names the
offending sentence and a reason.

Citation convention
-------------------
An answer cites a claim by writing its id inline, optionally bracketed, e.g.
``... exactly-once delivery is guaranteed [clm-1a2b3c4d5e].``. Claim ids match
``clm-[0-9a-f]{10}`` (see :func:`kops.evidence_model.stable_id`).
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from kops.evidence_model import ContextPackage

# A claim id as minted by ``stable_id("clm", ...)``.
_CLAIM_ID_RE = re.compile(r"clm-[0-9a-f]{10}")

# Sentences that assert nothing checkable — never require a citation.
_HEDGE_RE = re.compile(
    r"(could not find|couldn't find|no (?:evidence|sources?|information|data)\b"
    r"|unable to|insufficient evidence|not enough (?:evidence|information)"
    r"|cannot be (?:answered|determined)|cannot determine|no answer|unknown"
    r"|out of scope|not covered|i (?:could|can) not)",
    re.IGNORECASE,
)

# Non-exploratory tiers enforce the mapping; exploratory only advises.
_STRICT_TIERS = {"recommendation", "decision", "autonomous"}


def _answer_body(text: str) -> str:
    """Return the ``# Answer`` section, or the whole text if none is marked."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^#\s+Answer\b", line.strip(), re.IGNORECASE):
            start = i + 1
            break
    if start is None:
        return text
    body: list[str] = []
    for line in lines[start:]:
        if re.match(r"^#\s+\S", line):  # next top-level heading ends the section
            break
        body.append(line)
    return "\n".join(body)


def _segment_sentences(body: str) -> list[str]:
    """Deterministically split answer prose into candidate sentences."""
    sentences: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Strip markdown scaffolding (headings, list/quote markers).
        line = re.sub(r"^([#>\-*]+|\d+\.)\s+", "", line).strip()
        if not line:
            continue
        # Split into sentences on ., ! or ? followed by whitespace/end.
        for piece in re.split(r"(?<=[.!?])\s+", line):
            piece = piece.strip()
            if piece:
                sentences.append(piece)
    return sentences


def _is_factual(sentence: str) -> bool:
    """A factual sentence is a checkable assertion, not a hedge or a question."""
    stripped = sentence.strip()
    if not stripped or stripped.endswith("?"):
        return False
    if _HEDGE_RE.search(stripped):
        return False
    # Drop citation ids before counting words so a bare citation line is inert.
    words = _CLAIM_ID_RE.sub("", stripped)
    words = re.sub(r"\[\[[^\]]*\]\]", "", words)
    return len(re.findall(r"[A-Za-z]{2,}", words)) >= 4


def _cited_claim_ids(sentence: str) -> list[str]:
    # Order-preserving unique.
    seen: dict[str, None] = {}
    for cid in _CLAIM_ID_RE.findall(sentence):
        seen.setdefault(cid, None)
    return list(seen)


def validate_answer_claim_map(
    answer_text: str,
    package: ContextPackage,
    *,
    tier: str | None = None,
    current_source_versions: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Validate an answer's factual sentences against ``package``.

    Returns ``{"valid", "tier", "reliance", "violations", "warnings",
    "sentence_map", "factual_sentences"}``. ``violations`` invalidate the answer;
    ``warnings`` are advisory (used at the exploratory tier). Every violation and
    warning carries the offending ``sentence`` and a ``kind``.
    """
    tier = tier or package.tier
    strict = tier in _STRICT_TIERS

    allowed = set(package.claim_ids)
    excluded = {str(e.get("claim_id")) for e in package.excluded_claims if isinstance(e, dict)}

    violations: list[dict] = []
    warnings: list[dict] = []
    sentence_map: dict[str, list[str]] = {}
    reliance: dict[str, None] = {}
    factual_count = 0

    def record(bucket: list[dict], sentence: str, kind: str, detail: str) -> None:
        bucket.append({"sentence": sentence, "kind": kind, "detail": detail})

    for sentence in _segment_sentences(_answer_body(answer_text)):
        cited = _cited_claim_ids(sentence)
        if cited:
            sentence_map[sentence] = cited
        if not _is_factual(sentence):
            continue
        factual_count += 1

        for cid in cited:
            if cid in allowed:
                reliance.setdefault(cid, None)
            elif cid in excluded:
                # Citing evidence the package deliberately withheld.
                record(
                    violations if strict else warnings,
                    sentence,
                    "excluded-claim",
                    f"{cid} is in the package's excluded_claims",
                )
            else:
                # Citing a claim the package never included at all.
                record(violations, sentence, "unknown-claim", f"{cid} not in context package")

        if not cited:
            record(
                violations if strict else warnings,
                sentence,
                "uncited-factual-sentence",
                "factual sentence cites no claim id",
            )

    # Empty reliance set — a non-exploratory answer must rest on package claims.
    if strict and factual_count and not reliance:
        record(violations, "<answer>", "empty-reliance-set", "no package claim is relied upon")

    # Evidence moved under the answer: a frozen source version is no longer current.
    if current_source_versions is not None:
        current = set(current_source_versions)
        drifted = [v for v in package.source_version_ids if v not in current]
        if drifted:
            record(
                violations if strict else warnings,
                "<answer>",
                "source-version-changed",
                f"source version(s) changed during generation: {sorted(drifted)}",
            )

    return {
        "valid": not violations,
        "tier": tier,
        "reliance": sorted(reliance),
        "violations": violations,
        "warnings": warnings,
        "sentence_map": sentence_map,
        "factual_sentences": factual_count,
    }


def _main() -> None:
    import argparse
    import json
    from pathlib import Path

    from kops.evidence_store import EvidenceStore

    ap = argparse.ArgumentParser(description="Validate an answer's claim map against its package.")
    ap.add_argument("--answer", required=True, help="path to the answer memo markdown")
    ap.add_argument("--package", required=True, help="context package hash or path to its JSON")
    ap.add_argument("--tier")
    args = ap.parse_args()

    pkg_arg = args.package
    if Path(pkg_arg).exists():
        package = ContextPackage.from_dict(json.loads(Path(pkg_arg).read_text(encoding="utf-8")))
    else:
        loaded = EvidenceStore().load_context_package(pkg_arg)
        if loaded is None:
            raise SystemExit(f"context package not found: {pkg_arg}")
        package = loaded

    result = validate_answer_claim_map(
        Path(args.answer).read_text(encoding="utf-8"), package, tier=args.tier
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    _main()
