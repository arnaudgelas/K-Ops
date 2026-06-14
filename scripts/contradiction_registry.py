"""Contradiction registry — extract structured conflict records from concept pages.

Every concept page with ``claim_quality: conflicting`` contributes at least one
contradiction record. If the page has an ``## Open Questions`` section, each
bullet in that section becomes its own record. If there are no Open Questions
bullets, the concept gets a single undocumented record so the gap is visible in
the registry.

Records are written to ``data/contradictions.json`` and are derived from the
vault (never hand-edited). Claim IDs from ``data/claims.json`` are linked when
the file exists.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

from utils import CONFIG, ROOT, ensure_dir, parse_frontmatter

CONTRADICTIONS_PATH = ROOT / "data" / "contradictions.json"
_CLAIMS_PATH = ROOT / "data" / "claims.json"
_MAINTENANCE_CONTRADICTIONS_PATH = ROOT / "notes" / "Maintenance" / "Contradictions.md"

_OQ_SECTION_RE = re.compile(r"## Open Questions\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_MAINT_OPEN_SECTION_RE = re.compile(r"## Contradictions — Open\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_EVIDENCE_SOURCE_RE = re.compile(r"\[\[Sources/(?:[^/|]+/)?(src-[0-9a-f]{10})\|")
_EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S.*?)\s*$")


def contradiction_stable_id(concept_stem: str, oq_text: str) -> str:
    key = f"{concept_stem}:{oq_text.strip()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"ctr-{digest}"


def _extract_bullets(section_text: str) -> list[str]:
    bullets: list[str] = []
    for line in section_text.splitlines():
        match = _BULLET_RE.match(line)
        if match:
            bullets.append(" ".join(match.group(1).split()))
    return bullets


def _extract_evidence_source_ids(body: str) -> list[str]:
    match = _EVIDENCE_SECTION_RE.search(body)
    if not match:
        return []
    return sorted(set(_EVIDENCE_SOURCE_RE.findall(match.group(1))))


def _load_claims_by_concept() -> dict[str, list[str]]:
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
    path, claims_by_concept: dict[str, list[str]] | None = None
) -> list[dict]:
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


def _extract_maintenance_contradictions() -> list[dict]:
    """Extract open contradictions documented in notes/Maintenance/Contradictions.md."""
    maint_path = ROOT / "notes" / "Maintenance" / "Contradictions.md"
    if not maint_path.exists():
        return []
    text = maint_path.read_text(encoding="utf-8")
    section_match = _MAINT_OPEN_SECTION_RE.search(text)
    if not section_match:
        return []

    section = section_match.group(1)
    # Split on bullet boundaries (lines starting with "- ")
    raw_bullets = re.split(r"\n(?=\s*[-*]\s+\*\*)", "\n" + section.strip())
    records: list[dict] = []
    for raw in raw_bullets:
        raw = raw.strip()
        if not raw:
            continue
        title_match = re.match(r"[-*]\s+\*\*(.*?)\*\*", raw)
        if not title_match:
            continue
        title = title_match.group(1).strip()
        full_text = " ".join(line.strip() for line in raw.splitlines()).strip()
        source_ids = sorted(set(re.findall(r"src-[0-9a-f]{10}", full_text)))
        records.append(
            {
                "id": contradiction_stable_id("maintenance", title),
                "concept": "maintenance",
                "concept_path": maint_path.relative_to(ROOT).as_posix(),
                "open_question": full_text,
                "documented": True,
                "claim_ids": [],
                "source_ids": source_ids,
                "created_at": "",
                "source": "maintenance/contradictions",
            }
        )
    return records


def extract_all_contradictions() -> list[dict]:
    claims_by_concept = _load_claims_by_concept()
    all_contradictions: list[dict] = []
    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        all_contradictions.extend(extract_contradictions_from_concept(path, claims_by_concept))
    all_contradictions.extend(_extract_maintenance_contradictions())
    return all_contradictions


def load_contradictions() -> list[dict]:
    if not CONTRADICTIONS_PATH.exists():
        return extract_all_contradictions()
    payload = json.loads(CONTRADICTIONS_PATH.read_text(encoding="utf-8"))
    return payload.get("contradictions", [])


def search_contradictions(contradictions: list[dict], query: str, limit: int = 20) -> list[dict]:
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


def run(check: bool = False, dry_run: bool = False) -> list[dict]:
    ensure_dir(CONTRADICTIONS_PATH.parent)
    contradictions = extract_all_contradictions()
    documented = sum(1 for c in contradictions if c["documented"])

    out_of_sync = True
    if CONTRADICTIONS_PATH.exists():
        try:
            existing = json.loads(CONTRADICTIONS_PATH.read_text(encoding="utf-8"))
            if existing.get("contradictions") == contradictions:
                out_of_sync = False
        except Exception:
            pass

    if out_of_sync:
        if check:
            print("Contradictions registry is out of sync!")
            import sys

            sys.exit(1)
        elif dry_run:
            print(
                f"[DRY-RUN] Contradictions registry would be updated: "
                f"data/contradictions.json ({len(contradictions)} record(s), {documented} documented, "
                f"{len(contradictions) - documented} undocumented)"
            )
        else:
            payload = {
                "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
                "count": len(contradictions),
                "documented": documented,
                "undocumented": len(contradictions) - documented,
                "contradictions": contradictions,
            }
            content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            CONTRADICTIONS_PATH.write_text(content, encoding="utf-8")
            print(
                f"Contradictions registry updated: "
                f"data/contradictions.json ({len(contradictions)} record(s), {documented} documented, "
                f"{len(contradictions) - documented} undocumented)"
            )
    else:
        print(
            f"Contradictions registry unchanged: "
            f"data/contradictions.json ({len(contradictions)} record(s), {documented} documented, "
            f"{len(contradictions) - documented} undocumented)"
        )
    return contradictions


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract contradiction records from concept pages."
    )
    parser.add_argument(
        "--check", action="store_true", help="Fail if data/contradictions.json is out of sync."
    )
    parser.add_argument("--dry-run", action="store_true", help="Run without mutating files.")
    args = parser.parse_args()
    run(check=args.check, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
