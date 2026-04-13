from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from utils import CONFIG, ROOT

REGISTRY_PATH = CONFIG.registry_path
RAW_DIR = CONFIG.raw_dir
SOURCES_DIR = CONFIG.summaries_dir
ANSWERS_DIR = CONFIG.answers_dir
CONCEPTS_DIR = CONFIG.concepts_dir
HOME_PATH = CONFIG.home_note

SOURCE_REF_RE = re.compile(r"\[\[Sources/(src-[0-9a-f]{10})\|")
RELATED_CONCEPT_RE = re.compile(r"\[\[(Concepts/[^|\]]+)")
SOURCE_ID_RE = re.compile(r"^source_id:\s*(src-[0-9a-f]{10})\s*$", re.MULTILINE)
TITLE_RE = re.compile(r'^title:\s*"([^"]+)"\s*$', re.MULTILINE)
SUMMARY_SECTION_RE = re.compile(r"## Summary\s+(.+?)(?:\n## |\Z)", re.DOTALL)
RELATED_SECTION_RE = re.compile(r"## Related Concepts\s+(.*?)(?:\n## |\Z)", re.DOTALL)
EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
CONCEPT_LINK_IN_SECTION_RE = re.compile(r"\[\[Concepts/([^|\]]+)")
EVIDENCE_STRENGTH_RE = re.compile(r"^evidence_strength:\s*(\S+)\s*$", re.MULTILINE)
ANSWER_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
ANSWER_HEADING_RE = re.compile(r"^#\s+", re.MULTILINE)
ANSWER_SUBHEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
ANSWER_VAULT_UPDATES_RE = re.compile(r"## Vault Updates\s+(.*?)(?:\n## |\Z)", re.DOTALL)
ANSWER_PLACEHOLDER = "__ANSWER_PENDING__"
VALID_EVIDENCE_STRENGTHS = {"primary-doc", "secondary", "stub", "image-only", "strong"}
VALID_CLAIM_QUALITIES = {"supported", "provisional", "weak", "conflicting", "stale"}
VALID_ANSWER_QUALITIES = {"memo-only", "durable"}
VALID_ANSWER_SCOPES = {"private", "shared"}


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


def insert_section_bullets(text: str, heading: str, bullets: list[str], markers: list[str]) -> tuple[str, int]:
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


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    match = ANSWER_FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        data = {}
    return data, match.group(2)


def source_note_ids() -> set[str]:
    return {path.stem for path in SOURCES_DIR.glob("src-*.md")}


def raw_dir_ids() -> set[str]:
    return {path.name for path in RAW_DIR.iterdir() if path.is_dir()}


def concept_paths() -> list[Path]:
    return sorted(CONCEPTS_DIR.glob("*.md")) + [HOME_PATH]


def extract_related_concept_names(text: str) -> set[str]:
    """Extract concept page stems from the Related Concepts section of a concept page."""
    section_match = RELATED_SECTION_RE.search(text)
    if not section_match:
        return set()
    return set(CONCEPT_LINK_IN_SECTION_RE.findall(section_match.group(1)))


def extract_title(note_text: str, fallback: str) -> str:
    match = TITLE_RE.search(note_text)
    return match.group(1).strip() if match else fallback


def extract_summary_sentence(note_text: str) -> str | None:
    match = SUMMARY_SECTION_RE.search(note_text)
    if not match:
        return None
    paragraph = " ".join(line.strip() for line in match.group(1).strip().splitlines() if line.strip())
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


def build_backlink_bullet(source_id: str, note_path: Path) -> str:
    text = note_path.read_text(encoding="utf-8")
    summary_sentence = extract_summary_sentence(text)
    if summary_sentence:
        return f"- [[Sources/{source_id}|source-{source_id}]]: {summary_sentence}"
    title = extract_title(text, source_id)
    return f"- [[Sources/{source_id}|source-{source_id}]]: {title}."


def collect_backlink_fixes(strict: bool = False) -> list[BacklinkFix]:
    fixes: list[BacklinkFix] = []
    for note_path in sorted(SOURCES_DIR.glob("src-*.md")):
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
        for related_name in sorted(extract_related_concept_names(text)):
            if related_name not in concept_texts:
                continue
            related_text = concept_texts[related_name]
            if concept_name in extract_related_concept_names(related_text):
                continue
            related_path = ROOT / "notes" / f"{related_name}.md"
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

    registry_ids = [item["id"] for item in registry]
    registry_id_set = set(registry_ids)
    raw_ids = raw_dir_ids()
    note_ids = source_note_ids()

    seen: set[str] = set()
    for source_id in registry_ids:
        if source_id in seen:
            findings.append(Finding("error", "duplicate-registry-id", f"Duplicate registry id `{source_id}`"))
        seen.add(source_id)

    for source_id in sorted(registry_id_set - raw_ids):
        findings.append(Finding("error", "missing-raw-dir", f"Registry entry `{source_id}` has no matching raw directory"))

    for source_id in sorted(registry_id_set - note_ids):
        findings.append(Finding("error", "missing-source-note", f"Registry entry `{source_id}` has no matching source note"))

    for source_id in sorted(raw_ids - registry_id_set):
        findings.append(Finding("warning", "orphan-raw-dir", f"Raw directory `{source_id}` is not present in the registry"))

    for source_id in sorted(note_ids - registry_id_set):
        findings.append(Finding("warning", "orphan-source-note", f"Source note `{source_id}` is not present in the registry"))

    for item in registry:
        source_id = item["id"]
        metadata_path = RAW_DIR / source_id / "metadata.json"
        if not metadata_path.exists():
            findings.append(Finding("error", "missing-raw-metadata", f"Registry entry `{source_id}` has no matching raw metadata file"))
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings.append(Finding("error", "raw-metadata-json", f"{metadata_path.relative_to(ROOT)} is not valid JSON: {exc}"))
            continue

        for field in ("content_hash", "last_checked_at"):
            if not item.get(field):
                findings.append(Finding("error", f"missing-registry-{field}", f"Registry entry `{source_id}` is missing `{field}`"))
            if not metadata.get(field):
                findings.append(Finding("error", f"missing-raw-{field}", f"{metadata_path.relative_to(ROOT)} is missing `{field}`"))
            elif item.get(field) and item[field] != metadata[field]:
                findings.append(
                    Finding(
                        "error",
                        f"mismatched-{field}",
                        f"Registry entry `{source_id}` and {metadata_path.relative_to(ROOT)} disagree on `{field}`",
                    )
                )

    for note_path in sorted(SOURCES_DIR.glob("src-*.md")):
        text = note_path.read_text(encoding="utf-8")
        match = SOURCE_ID_RE.search(text)
        if not match:
            findings.append(Finding("error", "missing-source-id-frontmatter", f"{note_path.relative_to(ROOT)} has no `source_id` frontmatter"))
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
            findings.append(Finding("error", "missing-evidence-strength-frontmatter", f"{note_path.relative_to(ROOT)} has no `evidence_strength` frontmatter"))
        elif evidence_match.group(1) not in VALID_EVIDENCE_STRENGTHS:
            findings.append(
                Finding(
                    "error",
                    "invalid-evidence-strength",
                    f"{note_path.relative_to(ROOT)} declares unsupported evidence strength `{evidence_match.group(1)}`",
                )
            )

    for page_path in concept_paths():
        text = page_path.read_text(encoding="utf-8")
        if page_path != HOME_PATH:
            frontmatter, _ = parse_frontmatter(text)
            if frontmatter.get("type") != "concept":
                findings.append(Finding("error", "invalid-concept-type", f"{page_path.relative_to(ROOT)} must declare `type: concept`"))
            if not frontmatter.get("title"):
                findings.append(Finding("error", "missing-concept-title", f"{page_path.relative_to(ROOT)} is missing a `title` frontmatter field"))
            if not frontmatter.get("tags"):
                findings.append(Finding("error", "missing-concept-tags", f"{page_path.relative_to(ROOT)} is missing `tags` frontmatter"))
            claim_quality = frontmatter.get("claim_quality")
            if not claim_quality:
                findings.append(Finding("error", "missing-claim-quality-frontmatter", f"{page_path.relative_to(ROOT)} is missing `claim_quality` frontmatter"))
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
                for source_id in evidence_source_ids:
                    source_path = SOURCES_DIR / f"{source_id}.md"
                    if not source_path.exists():
                        continue
                    source_text = source_path.read_text(encoding="utf-8")
                    m = EVIDENCE_STRENGTH_RE.search(source_text)
                    if m:
                        observed_strengths.append(m.group(1))
                if observed_strengths and all(strength in {"stub", "image-only"} for strength in observed_strengths):
                    findings.append(
                        Finding(
                            "warning",
                            "unsupported-claim-risk",
                            f"{page_path.relative_to(ROOT)} relies only on stub/image-only evidence in its Evidence section",
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

    home_text = HOME_PATH.read_text(encoding="utf-8")
    for answer_path in sorted(ANSWERS_DIR.glob("*.md")):
        answer_text = answer_path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(answer_text)
        if frontmatter.get("type") != "answer":
            findings.append(Finding("error", "invalid-answer-type", f"{answer_path.relative_to(ROOT)} must declare `type: answer`"))
        if not frontmatter.get("title"):
            findings.append(Finding("error", "missing-answer-title", f"{answer_path.relative_to(ROOT)} is missing a `title` frontmatter field"))
        if not frontmatter.get("asked_at"):
            findings.append(Finding("error", "missing-answer-asked-at", f"{answer_path.relative_to(ROOT)} is missing an `asked_at` frontmatter field"))
        answer_quality = frontmatter.get("answer_quality")
        if not answer_quality:
            findings.append(Finding("error", "missing-answer-quality", f"{answer_path.relative_to(ROOT)} is missing an `answer_quality` frontmatter field"))
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
            findings.append(Finding("error", "missing-answer-scope", f"{answer_path.relative_to(ROOT)} is missing a `scope` frontmatter field"))
        elif answer_scope not in VALID_ANSWER_SCOPES:
            findings.append(
                Finding(
                    "error",
                    "invalid-answer-scope",
                    f"{answer_path.relative_to(ROOT)} declares unsupported answer scope `{answer_scope}`",
                )
            )
        if not ANSWER_HEADING_RE.search(body):
            findings.append(Finding("error", "missing-answer-heading", f"{answer_path.relative_to(ROOT)} has no top-level heading"))
        if not ANSWER_SUBHEADING_RE.search(body):
            findings.append(Finding("error", "missing-answer-section", f"{answer_path.relative_to(ROOT)} has no second-level section"))
        if ANSWER_PLACEHOLDER in answer_text:
            findings.append(Finding("error", "answer-scaffold-placeholder", f"{answer_path.relative_to(ROOT)} still contains scaffold placeholders"))
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
            findings.append(Finding("error", "missing-answer-home-link", f"{answer_path.relative_to(ROOT)} is not linked from notes/Home.md"))

    # Check reciprocal Related Concepts links between concept pages
    concept_texts: dict[str, str] = {}
    for page_path in sorted(CONCEPTS_DIR.glob("*.md")):
        concept_texts[page_path.stem] = page_path.read_text(encoding="utf-8")

    for concept_name, text in sorted(concept_texts.items()):
        for related_name in sorted(extract_related_concept_names(text)):
            if related_name not in concept_texts:
                continue  # missing page caught separately
            if concept_name not in extract_related_concept_names(concept_texts[related_name]):
                findings.append(
                    Finding(
                        "warning",
                        "missing-reciprocal-concept-link",
                        f"notes/Concepts/{concept_name}.md lists {related_name} in Related Concepts but the reverse link is absent",
                    )
                )

    backlink_severity = "error" if strict else "warning"
    for note_path in sorted(SOURCES_DIR.glob("src-*.md")):
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
    parser.add_argument("--strict", action="store_true", help="Treat backlink drift warnings as errors.")
    parser.add_argument("--fix-backlinks", action="store_true", help="Append missing source backlinks into concept Evidence sections before linting.")
    args = parser.parse_args()

    if args.fix_backlinks:
        fixes = collect_backlink_fixes(strict=args.strict)
        applied = apply_backlink_fixes(fixes)
        print(f"Applied {applied} backlink fix(es)")

    findings = collect_findings(strict=args.strict)
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

    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
