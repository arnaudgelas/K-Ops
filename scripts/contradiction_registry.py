"""Contradiction registry — extract structured conflict records from concept pages.

Every concept page with ``claim_quality: conflicting`` contributes at least one
contradiction record.  If the page has an ``## Open Questions`` section, each
bullet in that section becomes its own record (documenting *why* the conflict
exists).  If there are no Open Questions bullets the concept gets a single
*undocumented* record so that the gap is visible in the registry.

Records are written to ``data/contradictions.json`` and are derived from the
vault (never hand-edited).  Claim IDs from ``data/claims.json`` are linked when
the file exists.

Run ``extract-contradictions`` to rebuild the registry.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from utils import CONFIG, ROOT, ensure_dir, parse_frontmatter

CONTRADICTIONS_PATH = ROOT / "data" / "contradictions.json"

_CLAIMS_PATH = ROOT / "data" / "claims.json"

_OQ_SECTION_RE = re.compile(r"## Open Questions\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_EVIDENCE_SOURCE_RE = re.compile(r"\[\[Sources/(src-[0-9a-f]{10})\|")
_EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S.*?)\s*$")


def contradiction_stable_id(concept_stem: str, oq_text: str) -> str:
    """Return a stable, content-addressable ID for one contradiction record."""
    key = f"{concept_stem}:{oq_text.strip()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"ctr-{digest}"


def _extract_bullets(section_text: str) -> list[str]:
    bullets: list[str] = []
    for line in section_text.splitlines():
        m = _BULLET_RE.match(line)
        if m:
            bullets.append(" ".join(m.group(1).split()))
    return bullets


def _extract_evidence_source_ids(body: str) -> list[str]:
    m = _EVIDENCE_SECTION_RE.search(body)
    if not m:
        return []
    return sorted(set(_EVIDENCE_SOURCE_RE.findall(m.group(1))))


def _load_claims_by_concept() -> dict[str, list[str]]:
    """Return a mapping of concept_stem → list of claim IDs from data/claims.json."""
    if not _CLAIMS_PATH.exists():
        return {}
    try:
        payload = json.loads(_CLAIMS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    result: dict[str, list[str]] = {}
    for claim in payload.get("claims", []):
        stem = str(claim.get("concept") or "")
        cid = str(claim.get("id") or "")
        if stem and cid:
            result.setdefault(stem, []).append(cid)
    return result


def extract_contradictions_from_concept(
    path: Path,
    claims_by_concept: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Parse one concept page and return its contradiction records.

    Returns an empty list if the page does not have ``claim_quality: conflicting``.
    Returns one record per Open Questions bullet, or one undocumented record if
    the section is absent or empty.
    """
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)

    if str(frontmatter.get("claim_quality") or "") != "conflicting":
        return []

    concept_stem = path.stem
    source_ids = _extract_evidence_source_ids(body)
    claim_ids = list((claims_by_concept or {}).get(concept_stem, []))
    created_at = str(frontmatter.get("updated") or frontmatter.get("created") or "")

    oq_match = _OQ_SECTION_RE.search(body)
    oq_bullets: list[str] = _extract_bullets(oq_match.group(1)) if oq_match else []

    if oq_bullets:
        return [
            {
                "id": contradiction_stable_id(concept_stem, bullet),
                "concept": concept_stem,
                "concept_path": path.relative_to(ROOT).as_posix(),
                "open_question": bullet,
                "documented": True,
                "claim_ids": claim_ids,
                "source_ids": source_ids,
                "created_at": created_at,
            }
            for bullet in oq_bullets
        ]

    # No Open Questions bullets — undocumented contradiction
    return [
        {
            "id": contradiction_stable_id(concept_stem, "__undocumented__"),
            "concept": concept_stem,
            "concept_path": path.relative_to(ROOT).as_posix(),
            "open_question": None,
            "documented": False,
            "claim_ids": claim_ids,
            "source_ids": source_ids,
            "created_at": created_at,
        }
    ]


def extract_all_contradictions() -> list[dict]:
    """Extract contradiction records from every concept page in the vault."""
    claims_by_concept = _load_claims_by_concept()
    all_contradictions: list[dict] = []
    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        all_contradictions.extend(extract_contradictions_from_concept(path, claims_by_concept))
    return all_contradictions


def load_contradictions() -> list[dict]:
    """Load the current contradictions registry; rebuild if the file is absent."""
    if not CONTRADICTIONS_PATH.exists():
        return extract_all_contradictions()
    payload = json.loads(CONTRADICTIONS_PATH.read_text(encoding="utf-8"))
    return payload.get("contradictions", [])


def search_contradictions(
    contradictions: list[dict], query: str, limit: int = 20
) -> list[dict]:
    """Case-insensitive keyword search over contradiction records."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return contradictions[:limit]
    scored: list[tuple[int, dict]] = []
    for rec in contradictions:
        haystack = " ".join(
            filter(None, [rec.get("open_question") or "", rec.get("concept") or ""])
        ).lower()
        score = sum(haystack.count(t) for t in terms)
        if score > 0:
            scored.append((score, rec))
    scored.sort(key=lambda item: (-item[0], item[1]["concept"]))
    return [rec for _, rec in scored[:limit]]


def run() -> list[dict]:
    """Extract contradiction records and write ``data/contradictions.json``.

    Returns the full contradiction list.
    """
    ensure_dir(CONTRADICTIONS_PATH.parent)
    contradictions = extract_all_contradictions()
    documented = sum(1 for c in contradictions if c["documented"])
    payload = {
        "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "count": len(contradictions),
        "documented": documented,
        "undocumented": len(contradictions) - documented,
        "contradictions": contradictions,
    }
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    changed = (
        not CONTRADICTIONS_PATH.exists()
        or CONTRADICTIONS_PATH.read_text(encoding="utf-8") != content
    )
    if changed:
        CONTRADICTIONS_PATH.write_text(content, encoding="utf-8")
    print(
        f"Contradictions registry {'updated' if changed else 'unchanged'}: "
        f"data/contradictions.json "
        f"({len(contradictions)} record(s), {documented} documented, "
        f"{len(contradictions) - documented} undocumented)"
    )
    return contradictions
