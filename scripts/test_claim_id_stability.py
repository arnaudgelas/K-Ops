"""Claim ID stability test.

Verifies that claim_stable_id() produces the same ID after common surface-level
mutations to bullet text (whitespace changes, citation reformatting, unicode
normalization).  Exit 0 if >= 99% of claims are stable, exit 1 otherwise.

Run:
    uv run python scripts/test_claim_id_stability.py
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap path so we can import claim_registry without installing the package
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from claim_registry import claim_stable_id, normalize_claim_text  # noqa: E402

CLAIMS_PATH = SCRIPTS_DIR.parent / "data" / "claims.json"

# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------

# Pattern that matches a full wikilink citation of the form
#   [[Sources/<dir>/src-<hex>|<label>]]
# We replace the whole thing with just the source ID (src-<hex>).
_WIKILINK_RE = re.compile(
    r"\[\[Sources/(?:[^/\]#|]+/)?(?P<sid>src-[0-9a-f]{10})"
    r"(?:#[^\]|)]+)?(?:\|[^\]]*)?\]\]"
)


def _strip_wikilinks_to_src_id(text: str) -> str:
    """Replace [[Sources/.../src-abc1234567|label]] with src-abc1234567."""
    return _WIKILINK_RE.sub(lambda m: m.group("sid"), text)


def apply_mutations(text: str) -> str:
    """Apply all surface-level mutations that claim IDs must survive."""
    # 1. Leading / trailing whitespace
    text = text.strip()

    # 2. Add a trailing space (common editor artefact)
    text = text + " "

    # 3. Replace wikilink citations with bare source IDs — these are then
    #    stripped away by normalize_claim_text(), so the normalized form is
    #    identical whether the citation was a wikilink or a bare src-id.
    text = _strip_wikilinks_to_src_id(text)

    # 4. Unicode NFC normalization
    text = unicodedata.normalize("NFC", text)

    # 5. Collapse multiple spaces to one (normalize_claim_text does this too,
    #    but we apply it here to simulate what a round-trip editor might produce)
    text = re.sub(r" {2,}", " ", text)

    return text


# ---------------------------------------------------------------------------
# NOTE: trailing punctuation (e.g. trailing period vs no period) is NOT
# included as a mutation because normalize_claim_text() does not strip trailing
# periods — it only fixes *preceding* whitespace before punctuation.  Adding or
# removing a trailing period would change the normalized form and therefore the
# ID.  That is a known limitation tracked separately; do not add a mutation for
# it here until claim_registry.py is updated to handle it.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Main test loop
# ---------------------------------------------------------------------------


def run_stability_test() -> None:
    if not CLAIMS_PATH.exists():
        print(f"ERROR: {CLAIMS_PATH} not found. Run 'extract-claims' first.", file=sys.stderr)
        sys.exit(1)

    payload = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    claims = payload.get("claims", [])
    total = len(claims)

    if total == 0:
        print("ERROR: no claims found in data/claims.json", file=sys.stderr)
        sys.exit(1)

    stable = 0
    unstable_diffs: list[str] = []

    for claim in claims:
        original_id = claim["id"]
        concept = claim["concept"]
        bullet_text = claim["text"]  # raw bullet, pre-normalization

        mutated = apply_mutations(bullet_text)
        recomputed_id = claim_stable_id(concept, normalize_claim_text(mutated))

        if recomputed_id == original_id:
            stable += 1
        else:
            unstable_diffs.append(
                f"  concept:     {concept}\n"
                f"  original_id: {original_id}\n"
                f"  recomp_id:   {recomputed_id}\n"
                f"  bullet:      {bullet_text!r}\n"
                f"  mutated:     {mutated!r}\n"
                f"  norm(orig):  {normalize_claim_text(bullet_text)!r}\n"
                f"  norm(mut):   {normalize_claim_text(mutated)!r}\n"
            )

    pct = 100.0 * stable / total

    if unstable_diffs:
        print(f"\nUnstable claims ({len(unstable_diffs)}):")
        for diff in unstable_diffs[:20]:  # cap output to first 20
            print(diff)
        if len(unstable_diffs) > 20:
            print(f"  ... and {len(unstable_diffs) - 20} more (suppressed)")

    print(f"\nStability: {stable}/{total} ({pct:.1f}%)")

    if pct >= 99.0:
        sys.exit(0)
    else:
        print("FAIL: stability is below 99%", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run_stability_test()
