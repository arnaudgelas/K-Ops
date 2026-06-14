from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from utils import parse_frontmatter, dump_frontmatter


ROOT = Path(__file__).resolve().parent.parent
CONCEPTS_DIR = ROOT / "notes" / "Concepts"
SOURCES_DIR = ROOT / "notes" / "Sources"

EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
SOURCE_LINK_RE = re.compile(r"\[\[Sources/(src-[0-9a-f]{10})\|")
CONTRADICTION_RE = re.compile(r"\bcontradiction\b|\bconflict(?:ing)?\b", re.IGNORECASE)

VALID_QUALITIES = {"supported", "provisional", "weak", "conflicting", "stale"}
VALID_EVIDENCE_STATUSES = {"seed", "synthesized", "verified", "contested"}


def load_source_details() -> dict[str, dict]:
    details: dict[str, dict] = {}
    for path in SOURCES_DIR.rglob("src-*.md"):
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, _ = parse_frontmatter(text)
            details[path.stem] = frontmatter
        except Exception:
            pass
    return details


def extract_evidence_source_ids(text: str) -> list[str]:
    match = EVIDENCE_SECTION_RE.search(text)
    if not match:
        return []
    return sorted(set(SOURCE_LINK_RE.findall(match.group(1))))


def classify_claim_quality(text: str, source_details: dict[str, dict]) -> str:
    evidence_source_ids = extract_evidence_source_ids(text)
    if not evidence_source_ids:
        return "weak"

    observed_strengths = []
    for source_id in evidence_source_ids:
        detail = source_details.get(source_id, {})
        strength = detail.get("evidence_strength")
        if strength:
            source_kind = detail.get("source_kind")
            source_url = str(detail.get("source_url") or "")
            is_pdf = source_kind in ("paper-pdf", "arxiv-paper") or source_url.lower().endswith(
                ".pdf"
            )
            if is_pdf and strength in {"primary-doc", "strong", "official-spec"}:
                if "extraction_coverage" not in detail or detail.get("extraction_coverage") is None:
                    # Demote effective strength
                    strength = "secondary"
            observed_strengths.append(strength)

    from lint_vault import key_claim_direct_citation_stats

    direct_claims, total_claims, _ = key_claim_direct_citation_stats(text)
    direct_rate = direct_claims / total_claims if total_claims else 0.0

    inferred = "provisional"
    if any(strength in {"primary-doc", "strong"} for strength in observed_strengths):
        inferred = "supported"
    elif all(
        strength in {"stub", "image-only"}
        for strength in observed_strengths
        if strength is not None
    ):
        inferred = "weak"
    elif CONTRADICTION_RE.search(text):
        inferred = "conflicting"

    if inferred == "supported" and direct_rate < 0.9:
        if direct_rate >= 0.7:
            inferred = "provisional"
        else:
            inferred = "weak"
    elif inferred == "provisional" and direct_rate < 0.7:
        inferred = "weak"

    return inferred


def infer_evidence_status(concept_stem: str, text: str) -> str:
    # 1. Check if contested (contradiction exists in data/contradictions.json)
    contradictions_path = ROOT / "data" / "contradictions.json"
    has_contradiction = False
    if contradictions_path.exists():
        try:
            data = json.loads(contradictions_path.read_text(encoding="utf-8"))
            conflicts = data.get("contradictions", []) if isinstance(data, dict) else data
            for conflict in conflicts:
                if conflict.get("concept") == concept_stem:
                    has_contradiction = True
                    break
        except Exception:
            pass

    if has_contradiction:
        return "contested"

    # 2. Count sources cited in ## Evidence / Source Basis
    source_ids = extract_evidence_source_ids(text)
    if len(source_ids) >= 2:
        return "synthesized"
    else:
        return "seed"


def backfill_concept_quality(all_pages: bool = False, dry_run: bool = False) -> None:
    if not all_pages:
        raise SystemExit("Pass --all to backfill all concept pages.")

    source_details = load_source_details()
    changed = 0

    for path in sorted(CONCEPTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)

        # Skip redirects
        if frontmatter.get("type") == "redirect":
            continue

        file_did_change = False

        # 1. Claim quality
        quality = classify_claim_quality(text, source_details)
        if quality not in VALID_QUALITIES:
            raise RuntimeError(f"Invalid claim quality inferred for {path}: {quality}")
        if frontmatter.get("claim_quality") != quality:
            frontmatter["claim_quality"] = quality
            file_did_change = True

        # 2. Evidence status
        current_status = frontmatter.get("evidence_status")
        if current_status == "verified":
            # Keep verified as-is
            pass
        else:
            inferred_status = infer_evidence_status(path.stem, text)
            if current_status != inferred_status:
                frontmatter["evidence_status"] = inferred_status
                file_did_change = True

        # 3. Tags check
        tags = frontmatter.get("tags")
        if not tags:
            frontmatter["tags"] = ["kb/concept"]
            file_did_change = True
        elif isinstance(tags, list):
            if "kb/concept" not in tags:
                frontmatter["tags"] = tags + ["kb/concept"]
                file_did_change = True
        else:
            frontmatter["tags"] = [tags] if "kb/concept" == tags else [tags, "kb/concept"]
            file_did_change = True

        if file_did_change:
            changed += 1
            if not dry_run:
                updated_text = dump_frontmatter(frontmatter) + body
                path.write_text(updated_text, encoding="utf-8")
            print(
                f"{'Would update' if dry_run else 'Updated'} {path.relative_to(ROOT)} -> "
                f"claim_quality: {frontmatter.get('claim_quality')}, evidence_status: {frontmatter.get('evidence_status')}"
            )

    if changed == 0:
        print("No concept claim-quality or evidence-status metadata needed backfilling")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill claim-quality, evidence-status and tags on concept pages."
    )
    parser.add_argument(
        "--all", action="store_true", help="Process every concept page in notes/Concepts/."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report planned changes without writing files."
    )
    args = parser.parse_args()
    backfill_concept_quality(all_pages=args.all, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
