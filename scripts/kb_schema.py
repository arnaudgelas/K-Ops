"""Frontmatter schema validation against config/schema.yaml.

Usage (within scripts):
    from kb_schema import Validator
    v = Validator()
    issues = v.validate_source_note(frontmatter, path)
    issues = v.validate_concept_page(frontmatter, path)
    issues = v.validate_answer_memo(frontmatter, path)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from utils import ROOT


_SCHEMA_PATH = ROOT / "config" / "schema.yaml"
_CANONICAL_SOURCE_ID_RE = re.compile(r"^src-[0-9a-f]{10}$")

# Maps registry `kind` values to schema `source_kind` enum values
KIND_ALIASES: dict[str, str] = {
    "github_repo_snapshot": "github-repo",
    "repo_native": "github-repo",
    "url": "web-page",
    "file": "other",
    "article": "web-page",
    "web-page": "web-page",
    "github-repo": "github-repo",
    "pdf": "pdf",
    "imported_model_report": "imported_model_report",
    "imported_model_report_citation": "imported_model_report_citation",
    "other": "other",
}

VALID_SOURCE_KINDS = frozenset(KIND_ALIASES.values())


def normalize_source_kind(raw: str) -> str:
    """Normalize a registry or frontmatter kind value to the schema enum."""
    return KIND_ALIASES.get(raw, "other")


def _load_schema() -> dict:
    return yaml.safe_load(_SCHEMA_PATH.read_text(encoding="utf-8"))


class ValidationIssue:
    def __init__(self, severity: str, field: str, message: str, path: Path | None = None) -> None:
        self.severity = severity
        self.field = field
        self.message = message
        self.path = path

    def __repr__(self) -> str:
        loc = f" [{self.path}]" if self.path else ""
        return f"[{self.severity}] {self.field}: {self.message}{loc}"


class Validator:
    def __init__(self) -> None:
        self._schema = _load_schema()

    def _check_required(
        self,
        note_type: str,
        frontmatter: dict[str, Any],
        path: Path | None,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        spec = self._schema.get(note_type, {})
        for field in spec.get("required", []):
            if field not in frontmatter or frontmatter[field] is None or frontmatter[field] == "":
                issues.append(
                    ValidationIssue(
                        "error",
                        field,
                        f"required field `{field}` is missing or empty",
                        path,
                    )
                )
        return issues

    def validate_source_note(
        self, frontmatter: dict[str, Any], path: Path | None = None
    ) -> list[ValidationIssue]:
        issues = self._check_required("source_note", frontmatter, path)
        source_id = frontmatter.get("source_id", "")
        if source_id and not _CANONICAL_SOURCE_ID_RE.match(str(source_id)):
            issues.append(
                ValidationIssue(
                    "error",
                    "source_id",
                    f"`source_id` value `{source_id}` does not match canonical src-[0-9a-f]{{10}} pattern",
                    path,
                )
            )
        return issues

    def validate_concept_page(
        self, frontmatter: dict[str, Any], path: Path | None = None
    ) -> list[ValidationIssue]:
        if frontmatter.get("type") == "redirect":
            return []
        return self._check_required("concept_page", frontmatter, path)

    def validate_answer_memo(
        self, frontmatter: dict[str, Any], path: Path | None = None
    ) -> list[ValidationIssue]:
        return self._check_required("answer_memo", frontmatter, path)


def run_strict_validation() -> int:
    """Validate all source notes, concept pages, and answer memos against the schema.
    Returns the number of errors found.
    """
    from utils import CONFIG
    from utils import parse_frontmatter

    validator = Validator()
    all_issues: list[ValidationIssue] = []

    for path in sorted(CONFIG.summaries_dir.rglob("src-*.md")):
        fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        all_issues.extend(validator.validate_source_note(fm, path))

    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        all_issues.extend(validator.validate_concept_page(fm, path))

    for path in sorted(CONFIG.answers_dir.glob("*.md")):
        fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        all_issues.extend(validator.validate_answer_memo(fm, path))

    errors = [i for i in all_issues if i.severity == "error"]
    warnings = [i for i in all_issues if i.severity != "error"]

    print(f"Schema validation: {len(errors)} error(s), {len(warnings)} warning(s)")
    for issue in sorted(all_issues, key=lambda i: (i.severity, str(i.path or ""))):
        label = str(issue.path.relative_to(ROOT)) if issue.path else "?"
        print(f"  [{issue.severity}] {label}: {issue.message}")

    return len(errors)
