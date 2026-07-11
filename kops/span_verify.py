"""Quote-span verification — prove a claim's cited quote actually exists in its source.

The claim registry (``kops/claim_registry.py``) already parses source-span anchors
off each Key-Claims bullet: ``[[Sources/src-…#page=12&quote=…]]`` becomes a
structured anchor with ``source_id``, ``page``, ``line_start``, ``quote`` and so on.
But parsing an anchor only proves an anchor *string* was written. It does **not**
prove the quoted text is really in the source. ``span_status: anchored`` therefore
means "someone typed a quote", not "the quote checks out".

This module closes that gap with a **deterministic** check: for every claim anchor
that carries a ``quote=…``, resolve the cited source's text and verify the quote is
actually present (verbatim, or modulo whitespace/Unicode punctuation, or across an
ellipsis bridge). The per-claim verdict is written to a versioned audit artifact,
``data/span_verification.json``.

Scope boundary — read this before trusting the output:

- This verifies **existence** (the quote is in the source), not **entailment**
  (the quote supports the claim). Entailment needs an LLM judge and is a separate,
  lower-trust layer. A ``verified`` result means the text is really there; it does
  not certify that the source *substantiates* the claim.
- Locator-only anchors (``#page=12`` with no ``quote=``) are not quote-verifiable
  and are reported as ``absent`` for that anchor.

Verdicts (per claim, aggregated over its quote anchors):

- ``verified``     — every quote anchor was found in its source
- ``failed``       — at least one quote anchor was NOT found in its source (the
                     source contradicts the citation; this is the fail-closed case)
- ``unverifiable`` — a cited source's text could not be resolved on disk
- ``absent``       — the claim carries no quote anchor to check

Run ``kops verify-spans`` to rebuild the artifact, ``--check`` to exit non-zero when
any claim is ``failed``.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Callable

from kops.claim_registry import load_claims
from kops.utils import (
    CONFIG,
    ROOT,
    ensure_dir,
    parse_frontmatter,
    resolve_content_path,
    save_json,
)

SPAN_VERIFICATION_PATH = ROOT / "data" / "span_verification.json"

# A resolver maps a source_id to its full text (or None if it cannot be found).
Resolver = Callable[[str], "str | None"]

# Minimum length of a quote fragment we are willing to treat as meaningful.
# Very short fragments ("the", "AI") match everything and prove nothing.
_MIN_QUOTE_LEN = 8

_SMART_MAP = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "–": "-",  # en dash
    "—": "-",  # em dash
    "−": "-",  # minus sign
    " ": " ",  # non-breaking space
}

_ELLIPSIS_MARKERS = ("…", "...")


def normalize_text(text: str) -> str:
    """Fold text for tolerant matching: NFC, straighten punctuation, collapse whitespace.

    Whitespace-insensitive on purpose — Markdown normalization and PDF extraction
    routinely rewrap lines, so requiring byte-identical whitespace would produce
    false ``failed`` verdicts. Case is preserved.
    """
    text = unicodedata.normalize("NFC", text)
    text = "".join(_SMART_MAP.get(ch, ch) for ch in text)
    return " ".join(text.split())


def _split_ellipsis(quote: str) -> list[str]:
    """Split a quote on ellipsis markers into its non-empty fragments."""
    fragments = [quote]
    for marker in _ELLIPSIS_MARKERS:
        fragments = [seg for frag in fragments for seg in frag.split(marker)]
    return [f.strip() for f in fragments if f.strip()]


def match_quote(quote: str, source_text: str) -> str | None:
    """Return the match kind if ``quote`` is present in ``source_text``, else None.

    Match kinds, tried in order of strength:
      ``exact``      — verbatim substring
      ``normalized`` — substring after whitespace/punctuation folding
      ``ellipsis``   — every fragment either side of a ``…`` is present, in order
    """
    if not quote or not source_text:
        return None
    if quote in source_text:
        return "exact"

    nq = normalize_text(quote)
    ns = normalize_text(source_text)
    if len(nq) < _MIN_QUOTE_LEN:
        # Too short to be evidence; only accept a verbatim hit (handled above).
        return None
    if nq in ns:
        return "normalized"

    fragments = _split_ellipsis(quote)
    if len(fragments) >= 2:
        cursor = 0
        for frag in fragments:
            nf = normalize_text(frag)
            if len(nf) < _MIN_QUOTE_LEN:
                return None
            idx = ns.find(nf, cursor)
            if idx < 0:
                return None
            cursor = idx + len(nf)
        return "ellipsis"

    return None


def _quote_anchors(claim: dict) -> list[dict]:
    """Anchors on a claim that carry a non-empty quote."""
    return [a for a in claim.get("source_anchors", []) if (a.get("quote") or "").strip()]


def verify_claim(claim: dict, resolver: Resolver) -> dict:
    """Verify one claim's quote anchors. Returns a per-claim result record."""
    anchors = _quote_anchors(claim)
    anchor_results: list[dict] = []
    saw_failure = False
    saw_unverifiable = False

    for anchor in anchors:
        source_id = anchor.get("source_id")
        quote = (anchor.get("quote") or "").strip()
        source_text = resolver(source_id) if source_id else None
        if source_text is None:
            status, match_kind = "unverifiable", None
            saw_unverifiable = True
        else:
            match_kind = match_quote(quote, source_text)
            if match_kind is None:
                status = "failed"
                saw_failure = True
            else:
                status = "verified"
        anchor_results.append(
            {
                "source_id": source_id,
                "quote": quote,
                "status": status,
                "match_kind": match_kind,
            }
        )

    if not anchors:
        verdict = "absent"
    elif saw_failure:
        verdict = "failed"
    elif saw_unverifiable:
        verdict = "unverifiable"
    else:
        verdict = "verified"

    return {
        "claim_id": claim.get("claim_id") or claim.get("id"),
        "concept": claim.get("concept"),
        "span_verification": verdict,
        "quote_anchor_count": len(anchors),
        "anchors": anchor_results,
    }


def verify_claims(claims: list[dict], resolver: Resolver) -> list[dict]:
    return [verify_claim(claim, resolver) for claim in claims]


# ---------------------------------------------------------------------------
# Default vault-backed resolver
# ---------------------------------------------------------------------------


def _load_source_frontmatter_by_id() -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    summaries_dir = getattr(CONFIG, "summaries_dir", None)
    if not summaries_dir or not summaries_dir.exists():
        return metadata
    for path in sorted(summaries_dir.rglob("src-*.md")):
        try:
            frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        source_id = str(frontmatter.get("source_id") or path.stem)
        metadata[source_id] = frontmatter
    return metadata


def _resolve_source_text(source_id: str, meta_by_id: dict[str, dict]) -> str | None:
    """Best-effort resolution of a source's raw/normalized text on disk.

    Reuses the canonical ``resolve_content_path`` (normalized_path/original_path)
    and adds a fallback for local-file sources whose ``source_url`` points at a
    file inside the repo.
    """
    meta = meta_by_id.get(source_id)
    if not meta:
        return None

    candidates: list[Path] = []
    try:
        candidates.append(Path(resolve_content_path({**meta, "id": source_id})))
    except (FileNotFoundError, KeyError):
        pass

    source_url = str(meta.get("source_url") or "")
    if source_url and not source_url.startswith(("http://", "https://")):
        candidates.append(ROOT / source_url)

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None


def default_resolver() -> Resolver:
    """A caching resolver backed by the on-disk vault."""
    meta_by_id = _load_source_frontmatter_by_id()
    cache: dict[str, str | None] = {}

    def resolve(source_id: str) -> str | None:
        if source_id not in cache:
            cache[source_id] = _resolve_source_text(source_id, meta_by_id)
        return cache[source_id]

    return resolve


def build_report(results: list[dict]) -> dict:
    summary = Counter(r["span_verification"] for r in results)
    verifiable = summary["verified"] + summary["failed"]
    return {
        "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "count": len(results),
        "summary": {
            "verified": summary["verified"],
            "failed": summary["failed"],
            "unverifiable": summary["unverifiable"],
            "absent": summary["absent"],
        },
        # Of the claims whose quotes we could actually resolve, what fraction checked out.
        "quote_verification_rate": (
            round(summary["verified"] / verifiable, 3) if verifiable else None
        ),
        "results": results,
    }


def run(check: bool = False, dry_run: bool = False) -> dict:
    """Verify every claim's quote anchors and write data/span_verification.json."""
    claims = load_claims()
    results = verify_claims(claims, default_resolver())
    report = build_report(results)
    s = report["summary"]

    msg = (
        f"span verification: {s['verified']} verified, {s['failed']} failed, "
        f"{s['unverifiable']} unverifiable, {s['absent']} without quote anchors "
        f"({report['count']} claim(s))"
    )

    if dry_run:
        print(f"[DRY-RUN] {msg}")
    else:
        ensure_dir(SPAN_VERIFICATION_PATH.parent)
        save_json(SPAN_VERIFICATION_PATH, report)
        print(msg)
        print("Span verification written: data/span_verification.json")

    if check and s["failed"] > 0:
        failed_ids = [r["claim_id"] for r in results if r["span_verification"] == "failed"]
        print(f"FAIL: {s['failed']} claim(s) cite a quote absent from their source:")
        for cid in failed_ids:
            print(f"  - {cid}")
        import sys

        sys.exit(1)

    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify that each claim's cited quote exists in its source."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any claim cites a quote absent from its source.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run without writing the artifact.")
    args = parser.parse_args()
    run(check=args.check, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
