"""Claim registry — extract atomic claims from concept pages.

Each "Key Claims" bullet in a concept page becomes a first-class record with
a stable content-addressable ID, the originating concept, the sources cited in
that concept's Evidence section, and the current claim quality.

The registry is written to ``data/claims.json`` and is intentionally derived
from the vault (never hand-edited).  Run ``extract-claims`` to rebuild it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from utils import CONFIG, ROOT, ensure_dir, parse_frontmatter

CLAIMS_PATH = ROOT / "data" / "claims.json"

_CLAIMS_SECTION_RE = re.compile(r"## Key Claims\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_EVIDENCE_SOURCE_RE = re.compile(r"\[\[Sources/(src-[0-9a-f]{10})\|")
_EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S.*?)\s*$")


def claim_stable_id(concept_stem: str, claim_text: str) -> str:
    """Return a stable, content-addressable ID for one claim."""
    key = f"{concept_stem}:{claim_text.strip()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"clm-{digest}"


def _extract_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    for line in text.splitlines():
        m = _BULLET_RE.match(line)
        if m:
            bullets.append(" ".join(m.group(1).split()))
    return bullets


def _extract_evidence_source_ids(body: str) -> list[str]:
    m = _EVIDENCE_SECTION_RE.search(body)
    if not m:
        return []
    return sorted(set(_EVIDENCE_SOURCE_RE.findall(m.group(1))))


def extract_claims_from_concept(path: Path) -> list[dict]:
    """Parse one concept page and return its atomic claim records."""
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)

    claims_match = _CLAIMS_SECTION_RE.search(body)
    if not claims_match:
        return []

    source_ids = _extract_evidence_source_ids(body)
    bullets = _extract_bullets(claims_match.group(1))

    concept_stem = path.stem
    claim_quality = str(frontmatter.get("claim_quality") or "")
    last_updated = str(frontmatter.get("updated") or frontmatter.get("created") or "")

    return [
        {
            "id": claim_stable_id(concept_stem, bullet),
            "text": bullet,
            "concept": concept_stem,
            "concept_path": path.relative_to(ROOT).as_posix(),
            "claim_quality": claim_quality,
            "source_ids": source_ids,
            "claim_index": idx,
            "last_updated": last_updated,
        }
        for idx, bullet in enumerate(bullets, start=1)
    ]


def extract_all_claims() -> list[dict]:
    """Extract claims from every concept page in the vault."""
    all_claims: list[dict] = []
    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        all_claims.extend(extract_claims_from_concept(path))
    return all_claims


def search_claims(claims: list[dict], query: str, limit: int = 20) -> list[dict]:
    """Case-insensitive full-text search over claim records."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return claims[:limit]
    scored: list[tuple[int, dict]] = []
    for claim in claims:
        haystack = f"{claim['text']} {claim['concept']}".lower()
        score = sum(haystack.count(t) for t in terms)
        if score > 0:
            scored.append((score, claim))
    scored.sort(key=lambda item: (-item[0], item[1]["concept"], item[1]["claim_index"]))
    return [claim for _, claim in scored[:limit]]


def load_claims() -> list[dict]:
    """Load the current claims registry; rebuild from vault if file is absent."""
    if not CLAIMS_PATH.exists():
        return extract_all_claims()
    payload = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    return payload.get("claims", [])


def run() -> list[dict]:
    """Extract claims from all concepts and write ``data/claims.json``.

    Returns the full claim list.
    """
    ensure_dir(CLAIMS_PATH.parent)
    claims = extract_all_claims()
    payload = {
        "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "count": len(claims),
        "claims": claims,
    }
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    changed = not CLAIMS_PATH.exists() or CLAIMS_PATH.read_text(encoding="utf-8") != content
    if changed:
        CLAIMS_PATH.write_text(content, encoding="utf-8")
    print(f"Claims registry {'updated' if changed else 'unchanged'}: data/claims.json ({len(claims)} claim(s))")
    return claims
