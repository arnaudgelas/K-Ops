from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from utils import CONFIG, ROOT, find_source_note, parse_frontmatter

REGISTRY_PATH = CONFIG.registry_path
RAW_DIR = CONFIG.raw_dir
SOURCES_DIR = CONFIG.summaries_dir
ANSWERS_DIR = CONFIG.answers_dir
CONCEPTS_DIR = CONFIG.concepts_dir
INDEXES_DIR = CONFIG.indexes_dir
HOME_PATH = CONFIG.home_note
RESEARCH_DIR = CONFIG.research_dir
RESEARCH_NOTES_DIR = RESEARCH_DIR / "notes"
RESEARCH_BRIEFS_DIR = RESEARCH_DIR / "briefs"
RESEARCH_FINDINGS_DIR = RESEARCH_DIR / "findings"
RESEARCH_REPORTS_DIR = RESEARCH_DIR / "reports"
RESEARCH_IMPORTS_DIR = RESEARCH_DIR / "imports"
RESEARCH_ARCHIVE_DIR = RESEARCH_DIR / "archive"

SOURCE_REF_RE = re.compile(r"\[\[Sources/(?:[^/]+/)?(src-[0-9a-f]{10})\|")
INLINE_SOURCE_REF_RE = re.compile(
    r"(?:\[\[Sources/(?:[^/\]#|]+/)?(src-[0-9a-f]{10})(?:#[^\]|)]+)?(?:\|[^\]]*)?\]\]|"
    r"(src-[0-9a-f]{10})(?:#[\w./=&:%+-]+)?)"
)
RELATED_CONCEPT_RE = re.compile(r"\[\[(Concepts/[^|\]]+)")
SOURCE_ID_RE = re.compile(r"^source_id:\s*(src-[0-9a-f]{10})\s*$", re.MULTILINE)
TITLE_RE = re.compile(r'^title:\s*"([^"]+)"\s*$', re.MULTILINE)
SUMMARY_SECTION_RE = re.compile(r"## Summary\s+(.+?)(?:\n## |\Z)", re.DOTALL)
RELATED_SECTION_RE = re.compile(r"## Related Concepts\s+(.*?)(?:\n## |\Z)", re.DOTALL)
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
_TYPED_EDGE_RE = re.compile(
    r"^\s*-\s+`("
    + "|".join(_VALID_PREDICATES)
    + r")::`\s+\[\[Concepts/([^/|\]]+?)(?:\|[^\]]+)?\]\]",
    re.MULTILINE,
)
EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
KEY_CLAIMS_SECTION_RE = re.compile(r"(?mi)^##\s+Key Claims\s*\n+(.*?)(?:\n##\s|\Z)", re.DOTALL)
OPEN_QUESTIONS_SECTION_RE = re.compile(
    r"(?mi)^##\s+.*Open Questions\b.*\n+(.*?)(?:\n##\s|\Z)", re.DOTALL
)
CONCEPT_LINK_IN_SECTION_RE = re.compile(r"\[\[Concepts/([^|\]]+)")
EVIDENCE_STRENGTH_RE = re.compile(r"^evidence_strength:\s*(\S+)\s*$", re.MULTILINE)
ANSWER_HEADING_RE = re.compile(r"^#\s+", re.MULTILINE)
ANSWER_SUBHEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
ANSWER_VAULT_UPDATES_RE = re.compile(r"## Vault Updates\s+(.*?)(?:\n## |\Z)", re.DOTALL)
ANSWER_PLACEHOLDER = "__ANSWER_PENDING__"
VALID_EVIDENCE_STRENGTHS = {
    "primary-doc",
    "primary-doc-partial",
    "official-spec",
    "strong",
    "code",
    "maintainer-commentary",
    "changelog",
    "pr-issue",
    "secondary",
    "model-generated",
    "adversarial",
    "stub",
    "citation-only",
    "image-only",
}
VALID_CLAIM_QUALITIES = {"supported", "provisional", "weak", "conflicting", "stale"}
VALID_ANSWER_QUALITIES = {"memo-only", "durable"}
VALID_SOURCE_STATUSES = {
    "active",
    "stale",
    "permission-revoked",
    "deleted-from-origin",
    "archived",
    "do-not-use",
}
REVOKED_SOURCE_STATUSES = {"permission-revoked", "deleted-from-origin", "do-not-use"}
VALID_ANSWER_SCOPES = {"private", "shared"}
VALID_RESEARCH_TIERS = {"fast", "standard", "deep"}
VALID_RESEARCH_PHASES = {
    "briefing",
    "source-collection",
    "findings",
    "contrarian-review",
    "report-drafting",
    "done",
    "blocked",
}
VALID_RESEARCH_KINDS = {
    "research-status",
    "research-progress",
    "research-findings",
    "research-review",
    "research-report",
    "research-archive-manifest",
}


@dataclass
class Finding:
    severity: str
    code: str
    message: str


def section_body(text: str, heading: str) -> tuple[str, str, str] | None:
    header = f"{heading}\n\n"
    if header not in text:
        return None
    start = text.index(header) + len(header)
    remainder = text[start:]
    next_heading = remainder.find("\n## ")
    if next_heading == -1:
        body = remainder
        tail = ""
    else:
        body = remainder[:next_heading]
        tail = remainder[next_heading:]
    return text[:start], body, tail


def has_markdown_heading(text: str, heading: str) -> bool:
    return bool(re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", text))


def has_any_markdown_heading(text: str, headings: tuple[str, ...]) -> bool:
    return any(has_markdown_heading(text, heading) for heading in headings)


def has_open_questions_heading(text: str) -> bool:
    return bool(re.search(r"(?mi)^##\s+.*Open Questions\b.*$", text))


def insert_section_bullets(
    text: str, heading: str, bullets: list[str], markers: list[str]
) -> tuple[str, int]:
    parts = section_body(text, heading)
    if not parts:
        return text, 0
    prefix, body, tail = parts
    existing_body = body.rstrip("\n")
    new_lines: list[str] = []
    for bullet, marker in zip(bullets, markers, strict=False):
        if marker in existing_body:
            continue
        new_lines.append(bullet)
    if not new_lines:
        return text, 0

    if existing_body:
        updated_body = existing_body + "\n" + "\n".join(new_lines) + "\n"
    else:
        updated_body = "\n".join(new_lines) + "\n"
    return prefix + updated_body + tail, len(new_lines)


def home_recent_answers_bullet(answer_path: Path) -> str:
    text = answer_path.read_text(encoding="utf-8")
    frontmatter, _ = parse_frontmatter(text)
    title = str(frontmatter.get("title") or answer_path.stem)
    asked_at = str(frontmatter.get("asked_at") or "")
    date_label = asked_at.split("T", 1)[0] if asked_at else answer_path.stem[:10]
    answer_target = answer_path.relative_to(CONFIG.vault_dir).with_suffix("").as_posix()
    return f"- [[{answer_target}|{date_label}: {title}]]"


@dataclass
class BacklinkFix:
    target_path: Path
    heading: str
    bullet: str
    marker: str


def load_registry() -> list[dict]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def source_note_ids() -> set[str]:
    return {path.stem for path in SOURCES_DIR.rglob("src-*.md")}


def source_note_id_paths() -> dict[str, list[Path]]:
    """Return a mapping of canonical source_id stem to all paths that claim it."""
    mapping: dict[str, list[Path]] = {}
    for path in sorted(SOURCES_DIR.rglob("src-*.md")):
        mapping.setdefault(path.stem, []).append(path)
    return mapping


def source_note_frontmatters() -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    for path in sorted(SOURCES_DIR.rglob("src-*.md")):
        frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        metadata[path.stem] = frontmatter
    return metadata


def raw_dir_ids() -> set[str]:
    return {path.name for path in RAW_DIR.iterdir() if path.is_dir()}


def concept_paths() -> list[Path]:
    return sorted(CONCEPTS_DIR.glob("*.md")) + [HOME_PATH]


def index_paths() -> list[Path]:
    return sorted(INDEXES_DIR.glob("*.md"))


def research_paths(pattern: str) -> list[Path]:
    if not RESEARCH_DIR.exists():
        return []
    return sorted(RESEARCH_DIR.rglob(pattern))


def research_source_kind(source_id: str) -> str | None:
    note_path = find_source_note(source_id)
    if not note_path or not note_path.exists():
        return None
    frontmatter, _ = parse_frontmatter(note_path.read_text(encoding="utf-8"))
    kind = frontmatter.get("source_kind")
    return str(kind) if kind else None


def extract_related_concept_names(text: str) -> set[str]:
    """Extract concept page stems from the Related Concepts section of a concept page."""
    section_match = RELATED_SECTION_RE.search(text)
    if not section_match:
        return set()
    return set(CONCEPT_LINK_IN_SECTION_RE.findall(section_match.group(1)))


def _extract_typed_edges(text: str) -> dict[str, list[str]]:
    """Extract dict of predicate -> list of target stems from the Related Concepts section."""
    edges: dict[str, list[str]] = {}
    section_match = RELATED_SECTION_RE.search(text)
    if section_match:
        for predicate, target in _TYPED_EDGE_RE.findall(section_match.group(1)):
            edges.setdefault(predicate, []).append(target)
    return edges


def extract_title(note_text: str, fallback: str) -> str:
    match = TITLE_RE.search(note_text)
    return match.group(1).strip() if match else fallback


def extract_summary_sentence(note_text: str) -> str | None:
    match = SUMMARY_SECTION_RE.search(note_text)
    if not match:
        return None
    paragraph = " ".join(
        line.strip() for line in match.group(1).strip().splitlines() if line.strip()
    )
    if not paragraph:
        return None
    sentence_match = re.match(r"(.+?[.!?])(?:\s|$)", paragraph)
    sentence = sentence_match.group(1).strip() if sentence_match else paragraph.strip()
    return " ".join(sentence.split())


def extract_evidence_source_ids(text: str) -> set[str]:
    match = EVIDENCE_SECTION_RE.search(text)
    if not match:
        return set()
    return set(SOURCE_REF_RE.findall(match.group(1)))


def extract_inline_source_ids(text: str) -> set[str]:
    source_ids: set[str] = set()
    for match in INLINE_SOURCE_REF_RE.finditer(text):
        source_id = match.group(1) or match.group(2)
        if source_id:
            source_ids.add(source_id)
    return source_ids


def key_claim_direct_citation_stats(text: str) -> tuple[int, int, set[str]]:
    match = KEY_CLAIMS_SECTION_RE.search(text)
    if not match:
        return 0, 0, set()
    total = 0
    direct = 0
    source_ids: set[str] = set()
    for line in match.group(1).splitlines():
        if not re.match(r"^\s*[-*]\s+", line):
            continue
        total += 1
        ids = extract_inline_source_ids(line)
        if ids:
            direct += 1
            source_ids.update(ids)
    return direct, total, source_ids


def open_question_inline_source_ids(text: str) -> set[str]:
    source_ids: set[str] = set()
    for match in OPEN_QUESTIONS_SECTION_RE.finditer(text):
        source_ids.update(extract_inline_source_ids(match.group(1)))
    return source_ids


def build_backlink_bullet(source_id: str, note_path: Path) -> str:
    text = note_path.read_text(encoding="utf-8")
    summary_sentence = extract_summary_sentence(text)
    if summary_sentence:
        return f"- [[Sources/{source_id}|source-{source_id}]]: {summary_sentence}"
    title = extract_title(text, source_id)
    return f"- [[Sources/{source_id}|source-{source_id}]]: {title}."


def collect_backlink_fixes(strict: bool = False) -> list[BacklinkFix]:
    fixes: list[BacklinkFix] = []
    for note_path in sorted(SOURCES_DIR.rglob("src-*.md")):
        text = note_path.read_text(encoding="utf-8")
        related_concepts = sorted(set(RELATED_CONCEPT_RE.findall(text)))
        for concept_ref in related_concepts:
            concept_path = ROOT / "notes" / f"{concept_ref}.md"
            if not concept_path.exists():
                continue
            concept_text = concept_path.read_text(encoding="utf-8")
            if note_path.stem in concept_text:
                continue
            fixes.append(
                BacklinkFix(
                    target_path=concept_path,
                    heading="## Evidence / Source Basis",
                    bullet=build_backlink_bullet(note_path.stem, note_path),
                    marker=note_path.stem,
                )
            )

    concept_texts: dict[str, str] = {}
    for page_path in sorted(CONCEPTS_DIR.glob("*.md")):
        concept_texts[page_path.stem] = page_path.read_text(encoding="utf-8")

    for concept_name, text in sorted(concept_texts.items()):
        edges_A = _extract_typed_edges(text)
        directional_targets = set()
        for pred in ("conforms_to", "extends", "derived_from"):
            directional_targets.update(edges_A.get(pred, []))

        for related_name in sorted(extract_related_concept_names(text)):
            if related_name not in concept_texts:
                continue
            if related_name in directional_targets:
                continue  # conforms_to, extends, derived_from are directional; no reciprocal link needed

            related_text = concept_texts[related_name]
            edges_B = _extract_typed_edges(related_text)

            # Determine desired reciprocal predicate
            desired_pred = None
            if related_name in edges_A.get("contrasts_with", []):
                desired_pred = "contrasts_with"
            elif related_name in edges_A.get("supersedes", []):
                desired_pred = "superseded_by"
            elif related_name in edges_A.get("superseded_by", []):
                desired_pred = "supersedes"

            has_link = concept_name in extract_related_concept_names(related_text)
            has_typed_link = desired_pred is not None and concept_name in edges_B.get(
                desired_pred, []
            )

            related_path = ROOT / "notes" / "Concepts" / f"{related_name}.md"
            if desired_pred:
                if not has_typed_link:
                    # We need a typed reciprocal link
                    fixes.append(
                        BacklinkFix(
                            target_path=related_path,
                            heading="## Related Concepts",
                            bullet=f"- `{desired_pred}::` [[Concepts/{concept_name}|{concept_name}]]",
                            marker=f"`{desired_pred}::` [[Concepts/{concept_name}",
                        )
                    )
            else:
                # part_of or generic link. B needs a link back to A.
                if not has_link:
                    fixes.append(
                        BacklinkFix(
                            target_path=related_path,
                            heading="## Related Concepts",
                            bullet=f"- [[Concepts/{concept_name}|{concept_name}]]",
                            marker=concept_name,
                        )
                    )

    home_text = HOME_PATH.read_text(encoding="utf-8")
    for answer_path in sorted(ANSWERS_DIR.glob("*.md")):
        bullet = home_recent_answers_bullet(answer_path)
        answer_target = answer_path.relative_to(CONFIG.vault_dir).with_suffix("").as_posix()
        if answer_target in home_text:
            continue
        fixes.append(
            BacklinkFix(
                target_path=HOME_PATH,
                heading="## Recent Answers",
                bullet=bullet,
                marker=answer_target,
            )
        )
    return fixes


def apply_backlink_fixes(fixes: list[BacklinkFix]) -> int:
    grouped: dict[Path, list[BacklinkFix]] = {}
    for fix in fixes:
        grouped.setdefault(fix.target_path, []).append(fix)

    applied = 0
    for target_path, target_fixes in grouped.items():
        text = target_path.read_text(encoding="utf-8")
        updated_text = text
        for heading in sorted({fix.heading for fix in target_fixes}):
            section_fixes = [fix for fix in target_fixes if fix.heading == heading]
            new_text, count = insert_section_bullets(
                updated_text,
                heading,
                [fix.bullet for fix in section_fixes],
                [fix.marker for fix in section_fixes],
            )
            updated_text = new_text
            applied += count
        if updated_text != text:
            target_path.write_text(updated_text, encoding="utf-8")

    return applied


def collect_findings(strict: bool = False) -> list[Finding]:
    findings: list[Finding] = []

    try:
        registry = load_registry()
    except json.JSONDecodeError as exc:
        return [Finding("error", "registry-json", f"{REGISTRY_PATH} is not valid JSON: {exc}")]

    # Load Topic Atlas concept set for atlas-stale check
    _atlas_concepts: set[str] = set()
    _atlas_path = INDEXES_DIR / "Topic_Atlas.md"
    if _atlas_path.exists():
        _atlas_text = _atlas_path.read_text(encoding="utf-8")
        _atlas_concepts = set(re.findall(r"\[\[Concepts/([^|\]]+)", _atlas_text))

    registry_ids = [item["id"] for item in registry]
    registry_id_set = set(registry_ids)
    raw_ids = raw_dir_ids()
    note_ids = source_note_ids()
    source_note_meta = source_note_frontmatters()

    # Check for duplicate source notes (same source_id in multiple paths)
    id_paths = source_note_id_paths()
    for source_id, paths in sorted(id_paths.items()):
        if len(paths) > 1:
            path_list = ", ".join(p.relative_to(ROOT).as_posix() for p in paths)
            findings.append(
                Finding(
                    "error",
                    "duplicate-source-note",
                    f"Source ID `{source_id}` has multiple note files: {path_list}",
                )
            )

    # Check for non-canonical source filenames (files in Sources/ not matching src-[hex]{10}.md)
    _canonical_re = re.compile(r"^src-[0-9a-f]{10}$")
    for path in sorted(SOURCES_DIR.rglob("*.md")):
        if not _canonical_re.match(path.stem):
            findings.append(
                Finding(
                    "warning",
                    "noncanonical-source-filename",
                    f"{path.relative_to(ROOT)} does not follow the canonical src-[0-9a-f]{{10}} naming convention and is invisible to most tooling",
                )
            )

    seen: set[str] = set()
    for source_id in registry_ids:
        if source_id in seen:
            findings.append(
                Finding("error", "duplicate-registry-id", f"Duplicate registry id `{source_id}`")
            )
        seen.add(source_id)

    for source_id in sorted(registry_id_set - raw_ids):
        findings.append(
            Finding(
                "error",
                "missing-raw-dir",
                f"Registry entry `{source_id}` has no matching raw directory",
            )
        )

    for source_id in sorted(registry_id_set - note_ids):
        findings.append(
            Finding(
                "error",
                "missing-source-note",
                f"Registry entry `{source_id}` has no matching source note",
            )
        )

    for source_id in sorted(raw_ids - registry_id_set):
        findings.append(
            Finding(
                "warning",
                "orphan-raw-dir",
                f"Raw directory `{source_id}` is not present in the registry",
            )
        )

    for source_id in sorted(note_ids - registry_id_set):
        if source_note_meta.get(source_id, {}).get("source_kind") in {
            "imported_model_report",
            "imported-model-report",
            "imported_model_report_citation",
            "citation-stub",
        }:
            continue
        findings.append(
            Finding(
                "warning",
                "orphan-source-note",
                f"Source note `{source_id}` is not present in the registry",
            )
        )

    for item in registry:
        source_id = item["id"]
        metadata_path = RAW_DIR / source_id / "metadata.json"
        if not metadata_path.exists():
            findings.append(
                Finding(
                    "error",
                    "missing-raw-metadata",
                    f"Registry entry `{source_id}` has no matching raw metadata file",
                )
            )
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings.append(
                Finding(
                    "error",
                    "raw-metadata-json",
                    f"{metadata_path.relative_to(ROOT)} is not valid JSON: {exc}",
                )
            )
            continue

        for field in ("content_hash", "last_checked_at"):
            if not item.get(field):
                findings.append(
                    Finding(
                        "error",
                        f"missing-registry-{field}",
                        f"Registry entry `{source_id}` is missing `{field}`",
                    )
                )
            if not metadata.get(field):
                findings.append(
                    Finding(
                        "error",
                        f"missing-raw-{field}",
                        f"{metadata_path.relative_to(ROOT)} is missing `{field}`",
                    )
                )
            elif item.get(field) and item[field] != metadata[field]:
                findings.append(
                    Finding(
                        "error",
                        f"mismatched-{field}",
                        f"Registry entry `{source_id}` and {metadata_path.relative_to(ROOT)} disagree on `{field}`",
                    )
                )

    for note_path in sorted(SOURCES_DIR.rglob("src-*.md")):
        text = note_path.read_text(encoding="utf-8")
        frontmatter, _ = parse_frontmatter(text)
        match = SOURCE_ID_RE.search(text)
        if not match:
            findings.append(
                Finding(
                    "error",
                    "missing-source-id-frontmatter",
                    f"{note_path.relative_to(ROOT)} has no `source_id` frontmatter",
                )
            )
            continue
        if match.group(1) != note_path.stem:
            findings.append(
                Finding(
                    "error",
                    "mismatched-source-id-frontmatter",
                    f"{note_path.relative_to(ROOT)} declares `{match.group(1)}` but filename is `{note_path.stem}`",
                )
            )
        evidence_match = EVIDENCE_STRENGTH_RE.search(text)
        if not evidence_match:
            findings.append(
                Finding(
                    "error",
                    "missing-evidence-strength-frontmatter",
                    f"{note_path.relative_to(ROOT)} has no `evidence_strength` frontmatter",
                )
            )
        elif evidence_match.group(1) not in VALID_EVIDENCE_STRENGTHS:
            findings.append(
                Finding(
                    "error",
                    "invalid-evidence-strength",
                    f"{note_path.relative_to(ROOT)} declares unsupported evidence strength `{evidence_match.group(1)}`",
                )
            )

        source_status = frontmatter.get("source_status")
        if source_status is None:
            findings.append(
                Finding(
                    "warning",
                    "missing-source-status",
                    f"{note_path.relative_to(ROOT)} is missing `source_status` frontmatter",
                )
            )

        source_kind = frontmatter.get("source_kind")
        evidence_strength = frontmatter.get("evidence_strength")
        source_url = str(frontmatter.get("source_url", "") or "")
        is_pdf_source = source_kind in ("paper-pdf", "arxiv-paper") or source_url.lower().endswith(
            ".pdf"
        )
        if is_pdf_source and evidence_strength in {"primary-doc", "strong", "official-spec"}:
            if (
                "extraction_coverage" not in frontmatter
                or frontmatter.get("extraction_coverage") is None
            ):
                findings.append(
                    Finding(
                        "error",
                        "missing-pdf-extraction-coverage",
                        f"{note_path.relative_to(ROOT)} is a PDF with strong evidence strength `{evidence_strength}` but lacks `extraction_coverage` metadata",
                    )
                )
        source_kind = frontmatter.get("source_kind")
        if source_kind in {"imported_model_report", "imported-model-report"}:
            if frontmatter.get("authority") != "lead_only":
                findings.append(
                    Finding(
                        "error",
                        "imported-report-authority",
                        f"{note_path.relative_to(ROOT)} must declare `authority: lead_only`",
                    )
                )
            if frontmatter.get("verification_state") != "needs_primary_sources":
                findings.append(
                    Finding(
                        "error",
                        "imported-report-verification",
                        f"{note_path.relative_to(ROOT)} must declare `verification_state: needs_primary_sources`",
                    )
                )
            if frontmatter.get("evidence_strength") != "secondary":
                findings.append(
                    Finding(
                        "warning",
                        "imported-report-strength",
                        f"{note_path.relative_to(ROOT)} should usually use `evidence_strength: secondary`",
                    )
                )
        elif source_kind in {"imported_model_report_citation", "citation-stub"}:
            if not frontmatter.get("canonical_url"):
                findings.append(
                    Finding(
                        "error",
                        "imported-citation-url",
                        f"{note_path.relative_to(ROOT)} must declare `canonical_url`",
                    )
                )
            if frontmatter.get("authority") != "lead_only":
                findings.append(
                    Finding(
                        "error",
                        "imported-citation-authority",
                        f"{note_path.relative_to(ROOT)} must declare `authority: lead_only`",
                    )
                )
            if frontmatter.get("verification_state") != "needs_fetch":
                findings.append(
                    Finding(
                        "error",
                        "imported-citation-verification",
                        f"{note_path.relative_to(ROOT)} must declare `verification_state: needs_fetch`",
                    )
                )
            if frontmatter.get("evidence_strength") != "stub":
                findings.append(
                    Finding(
                        "warning",
                        "imported-citation-strength",
                        f"{note_path.relative_to(ROOT)} should usually use `evidence_strength: stub`",
                    )
                )
        required_source_sections = {
            "Reliability notes": (
                "Reliability notes",
                "Reliability Notes",
                "Extraction quality",
                "Extraction Quality",
                "Notes on Extraction Quality",
            ),
            "Candidate concepts": (
                "Candidate concepts",
                "Candidate Concepts",
                "Candidate Concepts to Promote",
                "Related Concepts",
            ),
        }
        for display_name, accepted_headings in required_source_sections.items():
            if not has_any_markdown_heading(text, accepted_headings):
                findings.append(
                    Finding(
                        "warning",
                        "missing-source-section",
                        f"{note_path.relative_to(ROOT)} is missing section `## {display_name}`",
                    )
                )
        tags = frontmatter.get("tags")
        if not tags:
            findings.append(
                Finding(
                    "error",
                    "missing-source-tags",
                    f"{note_path.relative_to(ROOT)} is missing `tags` frontmatter",
                )
            )
        elif not isinstance(tags, list):
            findings.append(
                Finding(
                    "error",
                    "invalid-source-tags-format",
                    f"{note_path.relative_to(ROOT)} `tags` frontmatter must be a list",
                )
            )
        elif "kb/source" not in tags:
            findings.append(
                Finding(
                    "error",
                    "missing-source-tag-kb",
                    f"{note_path.relative_to(ROOT)} `tags` must include `kb/source`",
                )
            )

        if strict:
            if not frontmatter.get("source_url"):
                findings.append(
                    Finding(
                        "warning",
                        "missing-source-metadata",
                        f"{note_path.relative_to(ROOT)} is missing `source_url` frontmatter",
                    )
                )
            if not frontmatter.get("source_kind"):
                findings.append(
                    Finding(
                        "warning",
                        "missing-source-metadata",
                        f"{note_path.relative_to(ROOT)} is missing `source_kind` frontmatter",
                    )
                )

    for status_path in sorted(RESEARCH_NOTES_DIR.glob("*-status.md")):
        frontmatter, _ = parse_frontmatter(status_path.read_text(encoding="utf-8"))
        if frontmatter.get("type") != "research-status":
            findings.append(
                Finding(
                    "error",
                    "invalid-research-status-type",
                    f"{status_path.relative_to(ROOT)} must declare `type: research-status`",
                )
            )
        if not frontmatter.get("title"):
            findings.append(
                Finding(
                    "error",
                    "missing-research-status-title",
                    f"{status_path.relative_to(ROOT)} is missing `title`",
                )
            )
        if not frontmatter.get("topic_slug"):
            findings.append(
                Finding(
                    "error",
                    "missing-research-status-topic-slug",
                    f"{status_path.relative_to(ROOT)} is missing `topic_slug`",
                )
            )
        tier = frontmatter.get("quality_tier")
        if tier not in VALID_RESEARCH_TIERS:
            findings.append(
                Finding(
                    "error",
                    "invalid-research-tier",
                    f"{status_path.relative_to(ROOT)} declares unsupported `quality_tier` `{tier}`",
                )
            )
        phase = frontmatter.get("phase")
        if phase not in VALID_RESEARCH_PHASES:
            findings.append(
                Finding(
                    "error",
                    "invalid-research-phase",
                    f"{status_path.relative_to(ROOT)} declares unsupported `phase` `{phase}`",
                )
            )
        for field in ("brief_path", "progress_path", "imports_path"):
            if not frontmatter.get(field):
                findings.append(
                    Finding(
                        "error",
                        f"missing-research-status-{field}",
                        f"{status_path.relative_to(ROOT)} is missing `{field}`",
                    )
                )
        if phase in {
            "findings",
            "contrarian-review",
            "report-drafting",
            "done",
        } and not frontmatter.get("findings_path"):
            findings.append(
                Finding(
                    "error",
                    "missing-research-findings-path",
                    f"{status_path.relative_to(ROOT)} is missing `findings_path` for phase `{phase}`",
                )
            )
        if phase in {"contrarian-review", "report-drafting", "done"} and not frontmatter.get(
            "review_path"
        ):
            findings.append(
                Finding(
                    "error",
                    "missing-research-review-path",
                    f"{status_path.relative_to(ROOT)} is missing `review_path` for phase `{phase}`",
                )
            )
        if phase == "done" and not frontmatter.get("report_path"):
            findings.append(
                Finding(
                    "error",
                    "missing-research-report-path",
                    f"{status_path.relative_to(ROOT)} is missing `report_path` for phase `done`",
                )
            )

    for progress_path in sorted(RESEARCH_NOTES_DIR.glob("*-progress.md")):
        frontmatter, _ = parse_frontmatter(progress_path.read_text(encoding="utf-8"))
        if frontmatter.get("type") != "research-progress":
            findings.append(
                Finding(
                    "error",
                    "invalid-research-progress-type",
                    f"{progress_path.relative_to(ROOT)} must declare `type: research-progress`",
                )
            )
        if not frontmatter.get("title") or not frontmatter.get("topic_slug"):
            findings.append(
                Finding(
                    "error",
                    "missing-research-progress-frontmatter",
                    f"{progress_path.relative_to(ROOT)} is missing title or topic_slug",
                )
            )
        if frontmatter.get("quality_tier") not in VALID_RESEARCH_TIERS:
            findings.append(
                Finding(
                    "error",
                    "invalid-research-progress-tier",
                    f"{progress_path.relative_to(ROOT)} declares unsupported `quality_tier` `{frontmatter.get('quality_tier')}`",
                )
            )

    for findings_path in sorted(RESEARCH_FINDINGS_DIR.glob("*.md")):
        frontmatter, _ = parse_frontmatter(findings_path.read_text(encoding="utf-8"))
        if frontmatter.get("type") != "research-findings":
            findings.append(
                Finding(
                    "error",
                    "invalid-research-findings-type",
                    f"{findings_path.relative_to(ROOT)} must declare `type: research-findings`",
                )
            )
        if not frontmatter.get("topic_slug"):
            findings.append(
                Finding(
                    "error",
                    "missing-research-findings-topic-slug",
                    f"{findings_path.relative_to(ROOT)} is missing `topic_slug`",
                )
            )

    for review_path in sorted(RESEARCH_NOTES_DIR.glob("*-contrarian-review.md")):
        frontmatter, _ = parse_frontmatter(review_path.read_text(encoding="utf-8"))
        if frontmatter.get("type") != "research-review":
            findings.append(
                Finding(
                    "error",
                    "invalid-research-review-type",
                    f"{review_path.relative_to(ROOT)} must declare `type: research-review`",
                )
            )
        if not frontmatter.get("topic_slug"):
            findings.append(
                Finding(
                    "error",
                    "missing-research-review-topic-slug",
                    f"{review_path.relative_to(ROOT)} is missing `topic_slug`",
                )
            )

    for report_path in sorted(RESEARCH_REPORTS_DIR.glob("*.md")):
        frontmatter, _ = parse_frontmatter(report_path.read_text(encoding="utf-8"))
        if frontmatter.get("type") != "research-report":
            findings.append(
                Finding(
                    "error",
                    "invalid-research-report-type",
                    f"{report_path.relative_to(ROOT)} must declare `type: research-report`",
                )
            )
        if not frontmatter.get("topic_slug"):
            findings.append(
                Finding(
                    "error",
                    "missing-research-report-topic-slug",
                    f"{report_path.relative_to(ROOT)} is missing `topic_slug`",
                )
            )

    for manifest_path in sorted(RESEARCH_ARCHIVE_DIR.rglob("MANIFEST.md")):
        frontmatter, _ = parse_frontmatter(manifest_path.read_text(encoding="utf-8"))
        if frontmatter.get("type") != "research-archive-manifest":
            findings.append(
                Finding(
                    "error",
                    "invalid-archive-manifest-type",
                    f"{manifest_path.relative_to(ROOT)} must declare `type: research-archive-manifest`",
                )
            )
        if (
            not frontmatter.get("topic_slug")
            or not frontmatter.get("archive_date")
            or not frontmatter.get("final_phase")
        ):
            findings.append(
                Finding(
                    "error",
                    "missing-archive-manifest-fields",
                    f"{manifest_path.relative_to(ROOT)} is missing required archive manifest frontmatter",
                )
            )

    home_text = HOME_PATH.read_text(encoding="utf-8")
    home_frontmatter, _ = parse_frontmatter(home_text)
    if home_frontmatter.get("type") != "home":
        findings.append(
            Finding(
                "error",
                "invalid-home-type",
                f"{HOME_PATH.relative_to(ROOT)} must declare `type: home`",
            )
        )
    if not home_frontmatter.get("title"):
        findings.append(
            Finding(
                "error",
                "missing-home-title",
                f"{HOME_PATH.relative_to(ROOT)} is missing a `title` frontmatter field",
            )
        )
    if not home_frontmatter.get("tags"):
        findings.append(
            Finding(
                "error",
                "missing-home-tags",
                f"{HOME_PATH.relative_to(ROOT)} is missing `tags` frontmatter",
            )
        )
    for target in (
        "Indexes/Vault_Dashboard",
        "Indexes/Workflow_Atlas",
        "Indexes/Topic_Atlas",
        "Runbooks/Agent_Workflow_Quick_Reference",
        "TODO",
    ):
        if f"[[{target}" not in home_text:
            findings.append(
                Finding(
                    "warning",
                    "missing-home-navigation-link",
                    f"{HOME_PATH.relative_to(ROOT)} is missing a navigation link to `{target}`",
                )
            )

    for page_path in concept_paths():
        text = page_path.read_text(encoding="utf-8")
        if page_path == HOME_PATH:
            continue
        frontmatter, _ = parse_frontmatter(text)
        if frontmatter.get("type") == "redirect":
            continue
        if frontmatter.get("type") != "concept":
            findings.append(
                Finding(
                    "error",
                    "invalid-concept-type",
                    f"{page_path.relative_to(ROOT)} must declare `type: concept`",
                )
            )
        if not frontmatter.get("title"):
            findings.append(
                Finding(
                    "error",
                    "missing-concept-title",
                    f"{page_path.relative_to(ROOT)} is missing a `title` frontmatter field",
                )
            )
        tags = frontmatter.get("tags")
        if not tags:
            findings.append(
                Finding(
                    "error",
                    "missing-concept-tags",
                    f"{page_path.relative_to(ROOT)} is missing `tags` frontmatter",
                )
            )
        elif not isinstance(tags, list):
            findings.append(
                Finding(
                    "error",
                    "invalid-concept-tags-format",
                    f"{page_path.relative_to(ROOT)} `tags` frontmatter must be a list",
                )
            )
        elif "kb/concept" not in tags:
            findings.append(
                Finding(
                    "error",
                    "missing-concept-tag-kb",
                    f"{page_path.relative_to(ROOT)} `tags` must include `kb/concept`",
                )
            )

        evidence_status = frontmatter.get("evidence_status")
        VALID_EVIDENCE_STATUSES = {"seed", "synthesized", "verified", "contested"}
        if not evidence_status:
            findings.append(
                Finding(
                    "error",
                    "missing-evidence-status-frontmatter",
                    f"{page_path.relative_to(ROOT)} is missing `evidence_status` frontmatter",
                )
            )
        elif evidence_status not in VALID_EVIDENCE_STATUSES:
            findings.append(
                Finding(
                    "error",
                    "invalid-evidence-status",
                    f"{page_path.relative_to(ROOT)} declares unsupported evidence status `{evidence_status}`",
                )
            )
        claim_quality = frontmatter.get("claim_quality")
        if not claim_quality:
            findings.append(
                Finding(
                    "error",
                    "missing-claim-quality-frontmatter",
                    f"{page_path.relative_to(ROOT)} is missing `claim_quality` frontmatter",
                )
            )
        elif claim_quality not in VALID_CLAIM_QUALITIES:
            findings.append(
                Finding(
                    "error",
                    "invalid-claim-quality",
                    f"{page_path.relative_to(ROOT)} declares unsupported claim quality `{claim_quality}`",
                )
            )
        evidence_source_ids = extract_evidence_source_ids(text)
        if not evidence_source_ids:
            findings.append(
                Finding(
                    "warning",
                    "unsupported-claim-risk",
                    f"{page_path.relative_to(ROOT)} has no cited source summaries in its Evidence section",
                )
            )
        else:
            observed_strengths: list[str | None] = []
            observed_kinds: list[str | None] = []
            for source_id in evidence_source_ids:
                source_path = find_source_note(source_id)
                if not source_path or not source_path.exists():
                    continue
                source_text = source_path.read_text(encoding="utf-8")
                source_meta = source_note_meta.get(source_id, {})
                observed_kinds.append(source_meta.get("source_kind"))
                m = EVIDENCE_STRENGTH_RE.search(source_text)
                if m:
                    observed_strengths.append(m.group(1))
            if observed_strengths and all(
                strength in {"stub", "image-only"} for strength in observed_strengths
            ):
                findings.append(
                    Finding(
                        "warning",
                        "unsupported-claim-risk",
                        f"{page_path.relative_to(ROOT)} relies only on stub/image-only evidence in its Evidence section",
                    )
                )
            if strict and observed_strengths and any(s == "stub" for s in observed_strengths):
                stub_count = observed_strengths.count("stub")
                findings.append(
                    Finding(
                        "warning",
                        "stub-source-cited-by-concept",
                        f"{page_path.relative_to(ROOT)} cites {stub_count} stub source(s) in its Evidence section",
                    )
                )
            imported_kinds = [kind for kind in observed_kinds if kind == "imported_model_report"]
            if imported_kinds and len(imported_kinds) == len(
                [kind for kind in observed_kinds if kind is not None]
            ):
                findings.append(
                    Finding(
                        "warning",
                        "imported-report-only-evidence",
                        f"{page_path.relative_to(ROOT)} relies only on imported model-generated reports in its Evidence section",
                    )
                )
        if claim_quality == "conflicting" and not has_open_questions_heading(text):
            findings.append(
                Finding(
                    "warning",
                    "conflicting-claim-no-open-questions",
                    f"{page_path.relative_to(ROOT)} has claim_quality: conflicting but no ## Open Questions section documenting the conflict",
                )
            )
        if claim_quality not in (None, "conflicting") and not has_open_questions_heading(text):
            findings.append(
                Finding(
                    "warning",
                    "missing-open-questions",
                    f"{page_path.relative_to(ROOT)} is missing a ## Open Questions section",
                )
            )
        direct_claims, total_claims, direct_source_ids = key_claim_direct_citation_stats(text)
        direct_rate = direct_claims / total_claims if total_claims else 0.0
        if claim_quality == "supported" and direct_rate < 0.9:
            findings.append(
                Finding(
                    "error",
                    "low-citation-rate-for-supported-concept",
                    f"{page_path.relative_to(ROOT)} is claim_quality: supported but its direct citation rate in Key Claims is {direct_rate:.1%} ({direct_claims}/{total_claims}), below the 90% threshold. Cite claims directly or demote to provisional/weak.",
                )
            )

        # Check for revoked sources backing supported claims
        if claim_quality == "supported" and evidence_source_ids:
            for source_id in evidence_source_ids:
                source_path = find_source_note(source_id)
                if not source_path or not source_path.exists():
                    continue
                source_fm = source_note_meta.get(source_id, {})
                s_status = source_fm.get("source_status")
                if s_status in REVOKED_SOURCE_STATUSES:
                    findings.append(
                        Finding(
                            "error",
                            "revoked-source-backs-supported-claim",
                            f"{page_path.relative_to(ROOT)} is claim_quality: supported but cites source `{source_id}` with source_status: {s_status}",
                        )
                    )

        # Check: model-generated source backing a supported concept
        if claim_quality == "supported" and evidence_source_ids:
            for source_id in evidence_source_ids:
                source_fm = source_note_meta.get(source_id, {})
                if source_fm.get("evidence_strength") == "model-generated":
                    findings.append(
                        Finding(
                            "error",
                            "model-generated-source-backs-supported",
                            f"{page_path.relative_to(ROOT)} is claim_quality: supported but cites model-generated source {source_id}",
                        )
                    )
                    break

        # Check for strong claims based only on partial repository snapshots
        if claim_quality == "supported":
            has_strong_non_partial = False
            for source_id in evidence_source_ids:
                source_path = find_source_note(source_id)
                if not source_path or not source_path.exists():
                    continue
                source_fm, _ = parse_frontmatter(source_path.read_text(encoding="utf-8"))
                strength = source_fm.get("evidence_strength")
                kind = source_fm.get("source_kind")

                is_partial_repo = False
                if kind == "github-repo-snapshot":
                    sampled = source_fm.get("sampled_file_count")
                    tracked = source_fm.get("tracked_file_count")
                    if sampled is not None and tracked is not None and int(sampled) < int(tracked):
                        is_partial_repo = True
                if strength == "primary-doc-partial":
                    is_partial_repo = True

                if not is_partial_repo:
                    if strength in {"primary-doc", "strong", "official-spec"}:
                        has_strong_non_partial = True

            if not has_strong_non_partial and evidence_source_ids:
                findings.append(
                    Finding(
                        "warning",
                        "strong-claim-partial-repo-only",
                        f"{page_path.relative_to(ROOT)} is claim_quality: supported but relies only on partial repository snapshots in its Evidence section",
                    )
                )
        # Check repo_manifest.json coverage_completeness for supported concept pages
        if claim_quality == "supported" and evidence_source_ids:
            gh_sources = []
            non_gh_sources = []
            for source_id in evidence_source_ids:
                source_path = find_source_note(source_id)
                if not source_path or not source_path.exists():
                    continue
                source_fm = source_note_meta.get(source_id, {})
                kind = source_fm.get("source_kind", "")
                if kind == "github-repo-snapshot":
                    gh_sources.append(source_id)
                else:
                    non_gh_sources.append(source_id)
            if gh_sources and not non_gh_sources:
                all_partial = True
                for source_id in gh_sources:
                    manifest_path = RAW_DIR / source_id / "repo_manifest.json"
                    if manifest_path.exists():
                        try:
                            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                            cc = manifest.get("coverage_completeness", "unknown")
                        except json.JSONDecodeError:
                            cc = "unknown"
                    else:
                        cc = "unknown"
                    if cc != "partial":
                        all_partial = False
                        break
                if all_partial:
                    findings.append(
                        Finding(
                            "warning",
                            "supported-claim-partial-manifest-only",
                            f"{page_path.relative_to(ROOT)} is claim_quality: supported and all github-repo-snapshot sources have coverage_completeness: partial in their repo_manifest.json with no non-partial alternative source",
                        )
                    )

        if strict and claim_quality == "provisional" and direct_rate < 0.7:
            findings.append(
                Finding(
                    "warning",
                    "low-citation-rate-for-provisional-concept",
                    f"{page_path.relative_to(ROOT)} is claim_quality: provisional but its direct citation rate in Key Claims is {direct_rate:.1%} ({direct_claims}/{total_claims}), below the 70% threshold.",
                )
            )
        if claim_quality == "conflicting":
            conflict_source_ids = direct_source_ids | open_question_inline_source_ids(text)
            if len(conflict_source_ids) < 2:
                findings.append(
                    Finding(
                        "warning",
                        "conflicting-claim-needs-two-sided-citations",
                        f"{page_path.relative_to(ROOT)} is claim_quality: conflicting but does not directly cite at least two source IDs across Key Claims/Open Questions.",
                    )
                )
        # Concept page length warning
        line_count = text.count("\n")
        if line_count > 400:
            findings.append(
                Finding(
                    "warning",
                    "concept-page-too-long",
                    f"{page_path.relative_to(ROOT)} has {line_count} lines (>400) — consider splitting into child concept pages",
                )
            )
        if frontmatter.get("revalidation_required"):
            findings.append(
                Finding(
                    "warning",
                    "revalidation-required",
                    f"{page_path.relative_to(ROOT)} is flagged for revalidation (upstream source changed); review and clear the flag when done",
                )
            )
        for match in SOURCE_REF_RE.finditer(text):
            source_id = match.group(1)
            if source_id not in note_ids:
                findings.append(
                    Finding(
                        "error",
                        "missing-source-link-target",
                        f"{page_path.relative_to(ROOT)} links to missing source note `{source_id}`",
                    )
                )
        # T12: symbol-coverage check — if a supported concept makes a code/architecture claim
        # citing a github source that has symbols.json, at least one symbol name should
        # appear in the claim text or the source note text.  Emit a warning (not an error).
        if claim_quality == "supported":
            _arch_kw = {
                "architecture",
                "module",
                "component",
                "interface",
                "class",
                "function",
                "api",
                "protocol",
                "system",
            }
            page_text_lower = text.lower()
            # Only run the check if the page contains architecture-related language
            if any(kw in page_text_lower for kw in _arch_kw):
                for source_id in evidence_source_ids:
                    symbols_path = RAW_DIR / source_id / "symbols.json"
                    if not symbols_path.exists():
                        continue
                    try:
                        sym_data = json.loads(symbols_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        continue
                    sym_names = [
                        s["name"].lower()
                        for s in sym_data.get("symbols", [])
                        if s.get("kind") not in {"section", "subsection"}
                    ]
                    if not sym_names:
                        continue
                    # Gather text corpus: concept page + source note (if it exists)
                    corpus = page_text_lower
                    src_note = find_source_note(source_id)
                    if src_note and src_note.exists():
                        corpus += "\n" + src_note.read_text(encoding="utf-8").lower()
                    if not any(name in corpus for name in sym_names):
                        findings.append(
                            Finding(
                                "warning",
                                "symbol-coverage-gap",
                                f"{page_path.relative_to(ROOT)} is claim_quality: supported and cites "
                                f"`{source_id}` (which has symbols.json), but no extracted code symbol "
                                f"from that source appears in the concept page or source note",
                            )
                        )

        if strict and _atlas_concepts and page_path.stem not in _atlas_concepts:
            findings.append(
                Finding(
                    "warning",
                    "atlas-stale",
                    f"{page_path.relative_to(ROOT)} is not listed in `notes/Indexes/Topic_Atlas.md`",
                )
            )

    for index_path in index_paths():
        text = index_path.read_text(encoding="utf-8")
        frontmatter, _ = parse_frontmatter(text)
        if frontmatter.get("type") != "index":
            findings.append(
                Finding(
                    "error",
                    "invalid-index-type",
                    f"{index_path.relative_to(ROOT)} must declare `type: index`",
                )
            )
        if not frontmatter.get("title"):
            findings.append(
                Finding(
                    "error",
                    "missing-index-title",
                    f"{index_path.relative_to(ROOT)} is missing a `title` frontmatter field",
                )
            )
        tags = frontmatter.get("tags")
        if not tags:
            findings.append(
                Finding(
                    "error",
                    "missing-index-tags",
                    f"{index_path.relative_to(ROOT)} is missing `tags` frontmatter",
                )
            )
        elif not isinstance(tags, list):
            findings.append(
                Finding(
                    "error",
                    "invalid-index-tags-format",
                    f"{index_path.relative_to(ROOT)} `tags` frontmatter must be a list",
                )
            )
        elif "kb/index" not in tags:
            findings.append(
                Finding(
                    "error",
                    "missing-index-tag-kb",
                    f"{index_path.relative_to(ROOT)} `tags` must include `kb/index`",
                )
            )

    home_text = HOME_PATH.read_text(encoding="utf-8")
    for answer_path in sorted(ANSWERS_DIR.glob("*.md")):
        answer_text = answer_path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(answer_text)
        if frontmatter.get("type") != "answer":
            findings.append(
                Finding(
                    "error",
                    "invalid-answer-type",
                    f"{answer_path.relative_to(ROOT)} must declare `type: answer`",
                )
            )
        if not frontmatter.get("title"):
            findings.append(
                Finding(
                    "error",
                    "missing-answer-title",
                    f"{answer_path.relative_to(ROOT)} is missing a `title` frontmatter field",
                )
            )
        if not frontmatter.get("asked_at"):
            findings.append(
                Finding(
                    "error",
                    "missing-answer-asked-at",
                    f"{answer_path.relative_to(ROOT)} is missing an `asked_at` frontmatter field",
                )
            )
        answer_quality = frontmatter.get("answer_quality")
        if not answer_quality:
            findings.append(
                Finding(
                    "error",
                    "missing-answer-quality",
                    f"{answer_path.relative_to(ROOT)} is missing an `answer_quality` frontmatter field",
                )
            )
        elif answer_quality not in VALID_ANSWER_QUALITIES:
            findings.append(
                Finding(
                    "error",
                    "invalid-answer-quality",
                    f"{answer_path.relative_to(ROOT)} declares unsupported answer quality `{answer_quality}`",
                )
            )
        answer_scope = frontmatter.get("scope")
        if not answer_scope:
            findings.append(
                Finding(
                    "error",
                    "missing-answer-scope",
                    f"{answer_path.relative_to(ROOT)} is missing a `scope` frontmatter field",
                )
            )
        elif answer_scope not in VALID_ANSWER_SCOPES:
            findings.append(
                Finding(
                    "error",
                    "invalid-answer-scope",
                    f"{answer_path.relative_to(ROOT)} declares unsupported answer scope `{answer_scope}`",
                )
            )
        sources_consulted = frontmatter.get("sources_consulted")
        if sources_consulted is not None and not isinstance(sources_consulted, list):
            findings.append(
                Finding(
                    "error",
                    "invalid-answer-sources-consulted",
                    f"{answer_path.relative_to(ROOT)} must declare `sources_consulted` as a list when present",
                )
            )
        if answer_quality == "durable" and not sources_consulted:
            findings.append(
                Finding(
                    "warning",
                    "answer-missing-provenance",
                    f"{answer_path.relative_to(ROOT)} is durable but has no structured `sources_consulted` provenance list",
                )
            )
        tags = frontmatter.get("tags")
        if not tags:
            findings.append(
                Finding(
                    "error",
                    "missing-answer-tags",
                    f"{answer_path.relative_to(ROOT)} is missing `tags` frontmatter",
                )
            )
        elif not isinstance(tags, list):
            findings.append(
                Finding(
                    "error",
                    "invalid-answer-tags-format",
                    f"{answer_path.relative_to(ROOT)} `tags` frontmatter must be a list",
                )
            )
        elif "kb/answer" not in tags:
            findings.append(
                Finding(
                    "error",
                    "missing-answer-tag-kb",
                    f"{answer_path.relative_to(ROOT)} `tags` must include `kb/answer`",
                )
            )

        query_class = frontmatter.get("query_class")
        VALID_QUERY_CLASSES = {
            "lookup",
            "synthesis",
            "contradiction",
            "freshness",
            "code",
            "audit",
            "research",
        }
        if not query_class:
            findings.append(
                Finding(
                    "error",
                    "missing-answer-query-class",
                    f"{answer_path.relative_to(ROOT)} is missing `query_class` frontmatter field",
                )
            )
        elif query_class not in VALID_QUERY_CLASSES:
            findings.append(
                Finding(
                    "error",
                    "invalid-answer-query-class",
                    f"{answer_path.relative_to(ROOT)} declares unsupported query class `{query_class}`",
                )
            )

        retrieval_path = frontmatter.get("retrieval_path")
        if retrieval_path is None:
            findings.append(
                Finding(
                    "error",
                    "missing-answer-retrieval-path",
                    f"{answer_path.relative_to(ROOT)} is missing `retrieval_path` frontmatter field",
                )
            )
        elif not isinstance(retrieval_path, list):
            findings.append(
                Finding(
                    "error",
                    "invalid-answer-retrieval-path-format",
                    f"{answer_path.relative_to(ROOT)} `retrieval_path` frontmatter must be a list",
                )
            )
        else:
            valid_methods = {"exact", "bm25", "graph", "manual"}
            valid_layers = {
                "claim",
                "concept",
                "source",
                "contradiction",
                "scorecard",
                "symbol",
                "registry",
            }
            for idx, step in enumerate(retrieval_path):
                if not isinstance(step, dict):
                    findings.append(
                        Finding(
                            "error",
                            "invalid-answer-retrieval-path-step",
                            f"{answer_path.relative_to(ROOT)}: step {idx} in `retrieval_path` must be a dictionary",
                        )
                    )
                    continue
                for key in ("method", "layer", "query", "results_count"):
                    if key not in step:
                        findings.append(
                            Finding(
                                "error",
                                "missing-answer-retrieval-path-step-key",
                                f"{answer_path.relative_to(ROOT)}: step {idx} is missing `{key}`",
                            )
                        )
                method = step.get("method")
                if method is not None and method not in valid_methods:
                    findings.append(
                        Finding(
                            "error",
                            "invalid-answer-retrieval-path-step-method",
                            f"{answer_path.relative_to(ROOT)}: step {idx} has invalid method `{method}`",
                        )
                    )
                layer = step.get("layer")
                if layer is not None and layer not in valid_layers:
                    findings.append(
                        Finding(
                            "error",
                            "invalid-answer-retrieval-path-step-layer",
                            f"{answer_path.relative_to(ROOT)}: step {idx} has invalid layer `{layer}`",
                        )
                    )
                results_count = step.get("results_count")
                if results_count is not None and not isinstance(results_count, int):
                    findings.append(
                        Finding(
                            "error",
                            "invalid-answer-retrieval-path-step-results-count",
                            f"{answer_path.relative_to(ROOT)}: step {idx} `results_count` must be an integer",
                        )
                    )

        fetch_required = frontmatter.get("fetch_required")
        if fetch_required is None:
            findings.append(
                Finding(
                    "error",
                    "missing-answer-fetch-required",
                    f"{answer_path.relative_to(ROOT)} is missing `fetch_required` frontmatter field",
                )
            )
        elif not isinstance(fetch_required, bool):
            findings.append(
                Finding(
                    "error",
                    "invalid-answer-fetch-required-format",
                    f"{answer_path.relative_to(ROOT)} `fetch_required` frontmatter must be a boolean",
                )
            )

        if frontmatter.get("revalidation_required"):
            findings.append(
                Finding(
                    "warning",
                    "answer-revalidation-required",
                    f"{answer_path.relative_to(ROOT)} is flagged for revalidation (upstream source changed); review and clear the flag when done",
                )
            )
        if not ANSWER_HEADING_RE.search(body):
            findings.append(
                Finding(
                    "error",
                    "missing-answer-heading",
                    f"{answer_path.relative_to(ROOT)} has no top-level heading",
                )
            )
        if not ANSWER_SUBHEADING_RE.search(body):
            findings.append(
                Finding(
                    "error",
                    "missing-answer-section",
                    f"{answer_path.relative_to(ROOT)} has no second-level section",
                )
            )
        if ANSWER_PLACEHOLDER in answer_text:
            findings.append(
                Finding(
                    "error",
                    "answer-scaffold-placeholder",
                    f"{answer_path.relative_to(ROOT)} still contains scaffold placeholders",
                )
            )
        updates_match = ANSWER_VAULT_UPDATES_RE.search(body)
        updates_text = updates_match.group(1).strip() if updates_match else ""
        has_updates = bool(updates_text and updates_text not in {"- None.", "None.", "- None"})
        if answer_quality == "memo-only" and has_updates:
            findings.append(
                Finding(
                    "error",
                    "answer-quality-mismatch",
                    f"{answer_path.relative_to(ROOT)} is marked memo-only but contains durable Vault Updates",
                )
            )
        if answer_scope == "private" and answer_quality == "durable":
            findings.append(
                Finding(
                    "error",
                    "answer-scope-mismatch",
                    f"{answer_path.relative_to(ROOT)} is durable but marked private; durable answers should be shared",
                )
            )
        if answer_scope == "shared" and answer_quality == "memo-only":
            findings.append(
                Finding(
                    "error",
                    "answer-scope-mismatch",
                    f"{answer_path.relative_to(ROOT)} is memo-only but marked shared; memo-only answers should stay private",
                )
            )
        if answer_quality == "durable" and not has_updates:
            findings.append(
                Finding(
                    "error",
                    "answer-quality-mismatch",
                    f"{answer_path.relative_to(ROOT)} is marked durable but its Vault Updates section is empty or None",
                )
            )
        answer_link = f"[[Answers/{answer_path.stem}|"
        if answer_link not in home_text and f"[[Answers/{answer_path.stem}]]" not in home_text:
            findings.append(
                Finding(
                    "error",
                    "missing-answer-home-link",
                    f"{answer_path.relative_to(ROOT)} is not linked from notes/Home.md",
                )
            )

    # Check reciprocal Related Concepts links between concept pages
    concept_texts: dict[str, str] = {}
    for page_path in sorted(CONCEPTS_DIR.glob("*.md")):
        concept_texts[page_path.stem] = page_path.read_text(encoding="utf-8")

    # Semantic Edge Predicates Reciprocity Checks (runs always, not just strict)
    for concept_name, text in sorted(concept_texts.items()):
        edges_A = _extract_typed_edges(text)
        for related_name in sorted(extract_related_concept_names(text)):
            if related_name not in concept_texts:
                continue
            related_text = concept_texts[related_name]
            edges_B = _extract_typed_edges(related_text)

            # Check supersedes -> superseded_by
            if related_name in edges_A.get("supersedes", []):
                if concept_name not in edges_B.get("superseded_by", []):
                    findings.append(
                        Finding(
                            "warning",
                            "missing-reciprocal-predicate",
                            f"notes/Concepts/{concept_name}.md lists `supersedes::` [[Concepts/{related_name}]] but the reciprocal `superseded_by::` [[Concepts/{concept_name}]] is absent on notes/Concepts/{related_name}.md",
                        )
                    )

            # Check superseded_by -> supersedes
            if related_name in edges_A.get("superseded_by", []):
                if concept_name not in edges_B.get("supersedes", []):
                    findings.append(
                        Finding(
                            "warning",
                            "missing-reciprocal-predicate",
                            f"notes/Concepts/{concept_name}.md lists `superseded_by::` [[Concepts/{related_name}]] but the reciprocal `supersedes::` [[Concepts/{concept_name}]] is absent on notes/Concepts/{related_name}.md",
                        )
                    )

            # Check contrasts_with symmetry
            if related_name in edges_A.get("contrasts_with", []):
                if concept_name not in edges_B.get("contrasts_with", []):
                    findings.append(
                        Finding(
                            "warning",
                            "missing-reciprocal-predicate",
                            f"notes/Concepts/{concept_name}.md lists `contrasts_with::` [[Concepts/{related_name}]] but the reciprocal `contrasts_with::` [[Concepts/{concept_name}]] is absent on notes/Concepts/{related_name}.md",
                        )
                    )

            # Check part_of reverse link
            if related_name in edges_A.get("part_of", []):
                if concept_name not in extract_related_concept_names(related_text):
                    findings.append(
                        Finding(
                            "warning",
                            "missing-hub-subpage-link",
                            f"notes/Concepts/{concept_name}.md lists `part_of::` [[Concepts/{related_name}]] but the hub page notes/Concepts/{related_name}.md has no link back to the subpage [[Concepts/{concept_name}]]",
                        )
                    )

    # Generic Reciprocal Check (strict-only, excluding directional targets)
    if strict:
        for concept_name, text in sorted(concept_texts.items()):
            edges_A = _extract_typed_edges(text)
            directional_targets = set()
            for pred in ("conforms_to", "extends", "derived_from"):
                directional_targets.update(edges_A.get(pred, []))

            for related_name in sorted(extract_related_concept_names(text)):
                if related_name not in concept_texts:
                    continue  # missing page caught separately
                if related_name in directional_targets:
                    continue  # directional links do not require reverse links
                if concept_name not in extract_related_concept_names(concept_texts[related_name]):
                    findings.append(
                        Finding(
                            "warning",
                            "missing-reciprocal-concept-link",
                            f"notes/Concepts/{concept_name}.md lists {related_name} in Related Concepts but the reverse link is absent",
                        )
                    )

    backlink_severity = "error" if strict else "warning"
    for note_path in sorted(SOURCES_DIR.rglob("src-*.md")):
        text = note_path.read_text(encoding="utf-8")
        related_concepts = sorted(set(RELATED_CONCEPT_RE.findall(text)))
        for concept_ref in related_concepts:
            concept_path = ROOT / "notes" / f"{concept_ref}.md"
            if not concept_path.exists():
                findings.append(
                    Finding(
                        "error",
                        "missing-related-concept",
                        f"{note_path.relative_to(ROOT)} references missing concept `{concept_ref}`",
                    )
                )
                continue
            if note_path.stem not in concept_path.read_text(encoding="utf-8"):
                findings.append(
                    Finding(
                        backlink_severity,
                        "missing-concept-backlink",
                        f"{note_path.relative_to(ROOT)} references `{concept_ref}` but {concept_path.relative_to(ROOT)} does not cite `{note_path.stem}`",
                    )
                )

    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint the vault for structural consistency.")
    parser.add_argument(
        "--strict", action="store_true", help="Treat backlink drift warnings as errors."
    )
    parser.add_argument(
        "--fix-backlinks",
        action="store_true",
        help="Append missing source backlinks into concept Evidence sections before linting.",
    )
    parser.add_argument(
        "--check", action="store_true", help="Check if generated index files match disk."
    )
    args = parser.parse_args()
    lint_vault(strict=args.strict, fix_backlinks=args.fix_backlinks, check=args.check)


def lint_vault(
    strict: bool = False, fix_backlinks: bool = False, check: bool = False
) -> list[Finding]:
    if fix_backlinks:
        fixes = collect_backlink_fixes(strict=strict)
        applied = apply_backlink_fixes(fixes)
        print(f"Applied {applied} backlink fix(es)")

    findings = collect_findings(strict=strict)
    if check:
        try:
            import sys

            # Ensure scripts directory is in path
            scripts_dir = str(Path(__file__).parent)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from generate_indexes import (
                get_sources_data,
                get_concepts_data,
                generate_source_atlas_content,
                generate_topic_atlas_content,
                generate_source_registry_content,
                generate_updated_home_content,
                generate_vault_dashboard_content,
            )

            sources = get_sources_data()
            concepts = get_concepts_data()

            # Check Source Atlas
            source_atlas_path = INDEXES_DIR / "Source_Atlas.md"
            generated_source_atlas = generate_source_atlas_content(sources)
            if (
                not source_atlas_path.exists()
                or source_atlas_path.read_text(encoding="utf-8") != generated_source_atlas
            ):
                findings.append(
                    Finding(
                        "error",
                        "index-out-of-sync",
                        "Source_Atlas.md is out of sync or missing. Run generate_indexes.py to fix.",
                    )
                )

            # Check Topic Atlas
            topic_atlas_path = INDEXES_DIR / "Topic_Atlas.md"
            generated_topic_atlas = generate_topic_atlas_content(concepts)
            if (
                not topic_atlas_path.exists()
                or topic_atlas_path.read_text(encoding="utf-8") != generated_topic_atlas
            ):
                findings.append(
                    Finding(
                        "error",
                        "index-out-of-sync",
                        "Topic_Atlas.md is out of sync or missing. Run generate_indexes.py to fix.",
                    )
                )

            # Check Source Registry
            source_registry_path = INDEXES_DIR / "Source_Registry.md"
            generated_source_registry = generate_source_registry_content()
            if (
                not source_registry_path.exists()
                or source_registry_path.read_text(encoding="utf-8") != generated_source_registry
            ):
                findings.append(
                    Finding(
                        "error",
                        "index-out-of-sync",
                        "Source_Registry.md is out of sync or missing. Run generate_indexes.py to fix.",
                    )
                )

            # Check Home Concepts
            generated_home = generate_updated_home_content(concepts)
            if not HOME_PATH.exists() or HOME_PATH.read_text(encoding="utf-8") != generated_home:
                findings.append(
                    Finding(
                        "error",
                        "index-out-of-sync",
                        "Home.md (concept list) is out of sync or missing. Run generate_indexes.py to fix.",
                    )
                )

            # Check Vault Dashboard
            vault_dashboard_path = INDEXES_DIR / "Vault_Dashboard.md"
            generated_vault_dashboard = generate_vault_dashboard_content(sources, concepts)
            if (
                not vault_dashboard_path.exists()
                or vault_dashboard_path.read_text(encoding="utf-8") != generated_vault_dashboard
            ):
                findings.append(
                    Finding(
                        "error",
                        "index-out-of-sync",
                        "Vault_Dashboard.md is out of sync or missing. Run generate_indexes.py to fix.",
                    )
                )
        except Exception as e:
            findings.append(
                Finding("error", "index-out-of-sync", f"Failed to run index checks: {e}")
            )
    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warning"]

    print(f"Lint results: {len(errors)} error(s), {len(warnings)} warning(s)")
    for severity in ("error", "warning"):
        group = [finding for finding in findings if finding.severity == severity]
        if not group:
            continue
        print(f"\n{severity.upper()}:")
        for finding in group:
            print(f"- [{finding.code}] {finding.message}")
    if errors:
        raise SystemExit(1)
    return findings


if __name__ == "__main__":
    main()
