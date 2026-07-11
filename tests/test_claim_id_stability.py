"""Claim ID stability tests for the generated claim registry."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kops.claim_registry import claim_stable_id, normalize_claim_text  # noqa: E402

CLAIMS_PATH = ROOT / "data" / "claims.json"
_WIKILINK_RE = re.compile(
    r"\[\[Sources/(?:[^/\]#|]+/)?(?P<sid>src-[0-9a-f]{10})"
    r"(?:#[^\]|)]+)?(?:\|[^\]]*)?\]\]"
)


def _strip_wikilinks_to_src_id(text: str) -> str:
    return _WIKILINK_RE.sub(lambda match: match.group("sid"), text)


def _apply_surface_mutations(text: str) -> str:
    text = text.strip()
    text = f"{text} "
    text = _strip_wikilinks_to_src_id(text)
    text = unicodedata.normalize("NFC", text)
    return re.sub(r" {2,}", " ", text)


def test_claim_ids_survive_common_surface_mutations():
    assert CLAIMS_PATH.exists(), "Run `uv run python scripts/kb.py extract-claims` first."

    payload = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    claims = payload.get("claims", [])
    assert claims, "No claims found in data/claims.json."

    unstable: list[str] = []
    for claim in claims:
        mutated = _apply_surface_mutations(claim["text"])
        recomputed_id = claim_stable_id(claim["concept"], normalize_claim_text(mutated))
        if recomputed_id != claim["id"]:
            unstable.append(
                f"{claim['concept']}: {claim['id']} != {recomputed_id} for {claim['text']!r}"
            )

    stable_fraction = (len(claims) - len(unstable)) / len(claims)
    assert stable_fraction >= 0.99, "\n".join(unstable[:20])
