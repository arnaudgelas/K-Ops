"""Claim registry — extract atomic claims from concept pages.

Each "Key Claims" bullet in a concept page becomes a first-class record with
a stable content-addressable ID, the originating concept, the sources cited in
that concept's Evidence section, and the current claim quality.

The registry is written to ``data/claims.json`` and is intentionally derived
from the vault (never hand-edited). Run ``extract-claims`` to rebuild it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

from kops.utils import CONFIG, ROOT, ensure_dir, parse_frontmatter

CLAIMS_PATH = ROOT / "data" / "claims.json"


class DualLinkPattern:
    def __init__(self, pattern_str: str) -> None:
        self._re = re.compile(pattern_str, re.MULTILINE if "::" in pattern_str else 0)

    def findall(self, text: str) -> list[str]:
        results = []
        for m in self._re.finditer(text):
            non_nones = [g for g in m.groups() if g is not None]
            if len(non_nones) == 1:
                results.append(non_nones[0])
            elif len(non_nones) > 1:
                results.append(tuple(non_nones))
        return results


_CLAIMS_SECTION_RE = re.compile(r"## Key Claims\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_SOURCE_ID_PATTERN = r"src-[0-9a-f]{10}"
_SOURCE_REF_RE = re.compile(
    rf"(?:\[\[Sources/(?:[^/\]#|]+/)?(?P<wiki>{_SOURCE_ID_PATTERN})"
    rf"(?P<wiki_anchor>#[^\]|)]+)?(?:\|[^\]]*)?\]\]|"
    rf"\[[^\]]*\]\((?:\.\./)*Sources/(?:[^/)]+/)?(?P<md>{_SOURCE_ID_PATTERN})\.md(?P<md_anchor>#[^)]*)?\)|"
    rf"(?P<plain>{_SOURCE_ID_PATTERN})(?P<plain_anchor>#[\w./=&:%+-]+)?)"
)
_EVIDENCE_SOURCE_RE = DualLinkPattern(
    r"(?:\[\[Sources/(?:[^/|\]#]+/)?(src-[0-9a-f]{10})(?:#[^\]|)]+)?(?:\|[^\]]*)?\]\]|"
    r"\[[^\]]*\]\((?:\.\./)*Sources/(?:[^/)]+/)?(src-[0-9a-f]{10})\.md(?:#[^)]*)?\))"
)
_EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S.*?)\s*$")
_SOURCE_CITATION_RE = re.compile(
    rf"\s*\(?(?:\[\[Sources/(?:[^/\]#|]+/)?{_SOURCE_ID_PATTERN}"
    rf"(?:#[^\]|)]+)?(?:\|[^\]]*)?\]\]|"
    rf"\[[^\]]*\]\((?:\.\./)*Sources/(?:[^/)]+/)?{_SOURCE_ID_PATTERN}\.md(?:#[^)]*)?\)|\b{_SOURCE_ID_PATTERN}"
    rf"(?:#[\w./=&:%+-]+)?\b)\)?"
)

_VALID_PREDICATES = frozenset(
    (
        "conforms_to",
        "extends",
        "derived_from",
        "contrasts_with",
        "supersedes",
        "superseded_by",
        "part_of",
    )
)
_TYPED_EDGE_RE = DualLinkPattern(
    r"^\s*-\s+`("
    + "|".join(_VALID_PREDICATES)
    + r")::`\s+(?:\[\[Concepts/([^/|\]]+?)(?:\|[^\]]+)?\]\]|"
    r"\[[^\]]*\]\((?:\.\./)*Concepts/([^)#\n]+)\.md(?:#[^)]*)?\))"
)

_BLOCKED_SOURCE_STATUSES = frozenset(
    ("revoked", "permission-revoked", "deleted-from-origin", "do-not-use")
)
_QUARANTINE_SOURCE_STRENGTHS = frozenset(("model-generated", "stub", "citation-only", "image-only"))
_QUARANTINE_SOURCE_KINDS = frozenset(
    ("imported-model-report", "imported_model_report", "citation-stub", "citation_stub")
)
_QUARANTINE_VERIFICATION_STATES = frozenset(("needs_primary_sources", "needs_fetch"))


def _load_source_metadata_by_id() -> dict[str, dict]:
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


def _classify_source(
    source_id: str, source_metadata_by_id: dict[str, dict]
) -> tuple[str, list[str]]:
    frontmatter = source_metadata_by_id.get(source_id)
    if frontmatter is None:
        return "unknown", [f"missing-source-note:{source_id}"]

    reasons: list[str] = []
    status = str(frontmatter.get("source_status") or "unknown")
    strength = str(frontmatter.get("evidence_strength") or "unknown")
    kind = str(frontmatter.get("source_kind") or "unknown")
    verification_state = str(frontmatter.get("verification_state") or "")

    if status in _BLOCKED_SOURCE_STATUSES:
        reasons.append(f"source-status:{status}")
    if frontmatter.get("adversarial_content") is True:
        reasons.append("adversarial-content")
    if reasons:
        return "blocked", reasons

    if status == "deprecated":
        reasons.append("source-status:deprecated")
    if strength in _QUARANTINE_SOURCE_STRENGTHS:
        reasons.append(f"evidence-strength:{strength}")
    if kind in _QUARANTINE_SOURCE_KINDS:
        reasons.append(f"source-kind:{kind}")
    if verification_state in _QUARANTINE_VERIFICATION_STATES:
        reasons.append(f"verification-state:{verification_state}")
    if reasons:
        return "quarantine", reasons

    return "admitted", []


def _claim_admission(
    source_ids: list[str], source_metadata_by_id: dict[str, dict]
) -> tuple[str, list[str], bool]:
    if not source_ids:
        return "unsupported", ["missing-source-evidence"], False

    statuses: list[str] = []
    reasons: list[str] = []
    synthetic_origin = False
    for source_id in source_ids:
        frontmatter = source_metadata_by_id.get(source_id, {})
        if frontmatter.get("evidence_strength") == "model-generated" or frontmatter.get(
            "source_kind"
        ) in {"imported-model-report", "imported_model_report"}:
            synthetic_origin = True
        status, source_reasons = _classify_source(source_id, source_metadata_by_id)
        statuses.append(status)
        reasons.extend(source_reasons)

    if "blocked" in statuses:
        return "blocked", sorted(set(reasons)), synthetic_origin
    if "quarantine" in statuses:
        return "quarantine", sorted(set(reasons)), synthetic_origin
    if "unknown" in statuses:
        return "unknown", sorted(set(reasons)), synthetic_origin
    return "admitted", [], synthetic_origin


def claim_stable_id(concept_stem: str, claim_text: str) -> str:
    key = f"{concept_stem}:{claim_text.strip()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"clm-{digest}"


def normalize_claim_text(claim_text: str) -> str:
    text = _SOURCE_CITATION_RE.sub("", claim_text).strip()
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


def _extract_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    for line in text.splitlines():
        match = _BULLET_RE.match(line)
        if match:
            bullets.append(" ".join(match.group(1).split()))
    return bullets


def _parse_source_anchor(source_id: str, anchor: str | None) -> dict:
    raw_anchor = (anchor or "").lstrip("#").rstrip(".,;)")
    parsed: dict = {
        "source_id": source_id,
        "anchor": raw_anchor or None,
        "page": None,
        "section": None,
        "paragraph": None,
        "quote": None,
        "path": None,
        "line_start": None,
        "line_end": None,
        "commit": None,
        "extraction_confidence": None,
        "segment_id": None,
    }
    if not raw_anchor:
        return parsed

    for part in raw_anchor.split("&"):
        if "=" not in part:
            if part.startswith("L") and part[1:].isdigit():
                parsed["line_start"] = int(part[1:])
            elif part.startswith("seg-"):
                parsed["segment_id"] = part
            continue
        key, value = part.split("=", 1)
        value = value.rstrip(".,;)")
        if key == "page" and value.isdigit():
            parsed["page"] = int(value)
        elif key == "paragraph" and value.isdigit():
            parsed["paragraph"] = int(value)
        elif key in {"line_start", "L"} and value.isdigit():
            parsed["line_start"] = int(value)
        elif key == "line_end" and value.isdigit():
            parsed["line_end"] = int(value)
        elif key in {"section", "quote", "path", "commit", "segment", "segment_id"}:
            if key in ("segment", "segment_id"):
                parsed["segment_id"] = value
            else:
                parsed[key] = value
        elif key == "extraction_confidence":
            try:
                parsed[key] = float(value)
            except ValueError:
                parsed[key] = None
        elif key.startswith("L") and key[1:].isdigit():
            parsed["line_start"] = int(key[1:])
            if value.startswith("L") and value[1:].isdigit():
                parsed["line_end"] = int(value[1:])
    return parsed


def extract_source_refs(text: str) -> list[dict]:
    refs: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    for match in _SOURCE_REF_RE.finditer(text):
        source_id = match.group("wiki") or match.group("plain") or match.group("md")
        anchor = (
            match.group("wiki_anchor") or match.group("plain_anchor") or match.group("md_anchor")
        )
        if not source_id:
            continue
        key = (source_id, anchor)
        if key in seen:
            continue
        seen.add(key)
        refs.append(_parse_source_anchor(source_id, anchor))
    return refs


def _extract_typed_edges(body: str) -> dict[str, list[str]]:
    edges: dict[str, list[str]] = {}
    for predicate, target in _TYPED_EDGE_RE.findall(body):
        edges.setdefault(predicate, []).append(target)
    return edges


def _extract_evidence_source_ids(body: str) -> list[str]:
    match = _EVIDENCE_SECTION_RE.search(body)
    if not match:
        return []
    return sorted(set(_EVIDENCE_SOURCE_RE.findall(match.group(1))))


def _status_from_quality(claim_quality: str) -> str:
    if claim_quality == "supported":
        return "active"
    if claim_quality == "conflicting":
        return "contested"
    return "provisional"


def _confidence_from_quality(claim_quality: str, source_resolution: str) -> float:
    base = {
        "supported": 0.8,
        "provisional": 0.55,
        "weak": 0.4,
        "conflicting": 0.45,
        "stale": 0.35,
    }.get(claim_quality, 0.4)
    if source_resolution == "inline":
        return base
    if source_resolution == "page-inherited":
        return max(0.0, base - 0.15)
    return max(0.0, base - 0.35)


def extract_claims_from_concept(path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)

    claims_match = _CLAIMS_SECTION_RE.search(body)
    if not claims_match:
        return []

    source_ids = _extract_evidence_source_ids(body)
    page_edges = _extract_typed_edges(body)
    bullets = _extract_bullets(claims_match.group(1))
    concept_stem = path.stem
    claim_quality = str(frontmatter.get("claim_quality") or "")
    last_updated = str(frontmatter.get("updated") or frontmatter.get("created") or "")
    source_metadata_by_id = _load_source_metadata_by_id()

    claims: list[dict] = []
    for idx, bullet in enumerate(bullets, start=1):
        inline_anchors = extract_source_refs(bullet)
        inline_source_ids = sorted({anchor["source_id"] for anchor in inline_anchors})
        if inline_source_ids:
            source_resolution = "inline"
        elif source_ids:
            source_resolution = "page-inherited"
        else:
            source_resolution = "missing"
        evidence_status = {
            "inline": "direct",
            "page-inherited": "inherited",
            "missing": "unsupported",
        }[source_resolution]
        effective_source_ids = inline_source_ids or source_ids
        admission_status, admission_reasons, synthetic_origin = _claim_admission(
            effective_source_ids, source_metadata_by_id
        )
        clean_claim = normalize_claim_text(bullet)
        claim_id = claim_stable_id(concept_stem, clean_claim)
        claims.append(
            {
                "id": claim_id,
                "claim_id": claim_id,
                "text": bullet,
                "claim_text": clean_claim,
                "concept": concept_stem,
                "concept_path": path.relative_to(ROOT).as_posix(),
                "claim_quality": claim_quality,
                "source_ids": effective_source_ids,
                "inline_source_ids": inline_source_ids,
                "page_source_ids": source_ids,
                "source_resolution": source_resolution,
                "evidence_status": evidence_status,
                "source_anchors": inline_anchors,
                "span_status": "anchored"
                if any(anchor["anchor"] for anchor in inline_anchors)
                else "missing",
                "quote_or_anchor": inline_anchors[0]["anchor"] if inline_anchors else None,
                "entities": [],
                "relations": [],
                "confidence": _confidence_from_quality(claim_quality, source_resolution),
                "status": _status_from_quality(claim_quality),
                "admission_status": admission_status,
                "admission_reasons": admission_reasons,
                "synthetic_origin": synthetic_origin,
                "extraction_method": "deterministic-key-claims",
                "last_verified": last_updated,
                "last_updated": last_updated,
                "conflicts_with": [],
                "page_edges": page_edges,
                "claim_index": idx,
            }
        )
    return claims


def _load_contradiction_conflicts() -> dict[str, set[str]]:
    """Build a claim_id -> set(other claim_ids) index from data/contradictions.json."""
    contradictions_path = ROOT / "data" / "contradictions.json"
    if not contradictions_path.exists():
        return {}
    payload = json.loads(contradictions_path.read_text(encoding="utf-8"))
    conflicts: dict[str, set[str]] = {}
    for entry in payload.get("contradictions", []):
        claim_ids = entry.get("claim_ids") or []
        if len(claim_ids) < 2:
            continue
        id_set = set(claim_ids)
        for cid in claim_ids:
            conflicts.setdefault(cid, set()).update(id_set - {cid})
    return conflicts


def extract_all_claims() -> list[dict]:
    all_claims: list[dict] = []
    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        all_claims.extend(extract_claims_from_concept(path))

    # Wire conflicts_with from contradictions.json (additive — preserves any
    # manually set entries that may already exist).
    conflicts = _load_contradiction_conflicts()
    if conflicts:
        for claim in all_claims:
            cid = claim["claim_id"]
            if cid in conflicts:
                existing = set(claim.get("conflicts_with") or [])
                claim["conflicts_with"] = sorted(existing | conflicts[cid])

    return all_claims


def search_claims(claims: list[dict], query: str, limit: int = 20) -> list[dict]:
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return claims[:limit]
    scored: list[tuple[int, dict]] = []
    for claim in claims:
        haystack = f"{claim.get('claim_text') or claim['text']} {claim['concept']}".lower()
        score = sum(haystack.count(t) for t in terms)
        if score > 0:
            scored.append((score, claim))
    scored.sort(key=lambda item: (-item[0], item[1]["concept"], item[1]["claim_index"]))
    return [claim for _, claim in scored[:limit]]


def load_claims() -> list[dict]:
    if not CLAIMS_PATH.exists():
        return extract_all_claims()
    payload = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    return payload.get("claims", [])


def run(check: bool = False, dry_run: bool = False) -> list[dict]:
    ensure_dir(CLAIMS_PATH.parent)
    claims = extract_all_claims()

    out_of_sync = True
    if CLAIMS_PATH.exists():
        try:
            existing = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
            if existing.get("claims") == claims:
                out_of_sync = False
        except Exception:
            pass

    if out_of_sync:
        if check:
            print("Claims registry is out of sync!")
            import sys

            sys.exit(1)
        elif dry_run:
            print(
                f"[DRY-RUN] Claims registry would be updated: data/claims.json ({len(claims)} claim(s))"
            )
        else:
            payload = {
                "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
                "count": len(claims),
                "claims": claims,
            }
            content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            CLAIMS_PATH.write_text(content, encoding="utf-8")
            print(f"Claims registry updated: data/claims.json ({len(claims)} claim(s))")
    else:
        print(f"Claims registry unchanged: data/claims.json ({len(claims)} claim(s))")
    return claims


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Extract atomic claims from concept pages.")
    parser.add_argument(
        "--check", action="store_true", help="Fail if data/claims.json is out of sync."
    )
    parser.add_argument("--dry-run", action="store_true", help="Run without mutating files.")
    args = parser.parse_args()
    run(check=args.check, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
