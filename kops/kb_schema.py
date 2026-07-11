"""Frontmatter schema validation against config/schema.yaml.

Usage (within scripts):
    from kops.kb_schema import Validator
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

import importlib.resources

from kops.utils import ROOT


# schema.yaml ships as package data; loaded via importlib.resources in _load_schema()
_CANONICAL_SOURCE_ID_RE = re.compile(r"^src-[0-9a-f]{10}$")

# Maps registry `kind` values to schema `source_kind` enum values
KIND_ALIASES: dict[str, str] = {
    # Exact matches for the 11 new kinds
    "arxiv-paper": "arxiv-paper",
    "paper-pdf": "paper-pdf",
    "github-repo-snapshot": "github-repo-snapshot",
    "github-file": "github-file",
    "official-doc": "official-doc",
    "spec": "spec",
    "blog": "blog",
    "news": "news",
    "local-file": "local-file",
    "imported-model-report": "imported-model-report",
    "citation-stub": "citation-stub",
    # Legacy mapping / aliases
    "github_repo_snapshot": "github-repo-snapshot",
    "repo_native": "github-repo-snapshot",
    "github-repo": "github-repo-snapshot",
    "pdf": "paper-pdf",
    "url": "blog",
    "article": "blog",
    "web-page": "blog",
    "file": "local-file",
    "imported_model_report": "imported-model-report",
    "imported_model_report_citation": "citation-stub",
    "other": "local-file",
}

VALID_SOURCE_KINDS = frozenset(KIND_ALIASES.values())


def normalize_source_kind(raw: str) -> str:
    """Normalize a registry or frontmatter kind value to the schema enum."""
    return KIND_ALIASES.get(raw, "local-file")


def _load_schema() -> dict:
    schema_text = (
        importlib.resources.files("kops").joinpath("schema.yaml").read_text(encoding="utf-8")
    )
    return yaml.safe_load(schema_text)


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

        tags = frontmatter.get("tags")
        if tags is not None:
            if not isinstance(tags, list):
                issues.append(ValidationIssue("error", "tags", "`tags` must be a list", path))
            elif "kb/source" not in tags:
                issues.append(
                    ValidationIssue("error", "tags", "`tags` must include `kb/source`", path)
                )

        # Enforce kind-specific validation
        source_kind = frontmatter.get("source_kind", "")
        evidence_strength = frontmatter.get("evidence_strength", "")
        source_url = str(frontmatter.get("source_url", "") or "")
        is_pdf = source_kind in ("paper-pdf", "arxiv-paper") or source_url.lower().endswith(".pdf")
        if is_pdf and evidence_strength in {"primary-doc", "strong", "official-spec"}:
            if (
                "extraction_coverage" not in frontmatter
                or frontmatter.get("extraction_coverage") is None
            ):
                issues.append(
                    ValidationIssue(
                        "error",
                        "extraction_coverage",
                        f"PDF source note with strong evidence strength `{evidence_strength}` is missing `extraction_coverage` metadata",
                        path,
                    )
                )

        # Optional field: adversarial_content (bool) — set to true when fetch detected
        # prompt-injection attempts or manipulative instructions in source text.
        # A source flagged adversarial_content: true cannot back supported claims (lint gate).
        adversarial_content = frontmatter.get("adversarial_content")
        if adversarial_content is not None and not isinstance(adversarial_content, bool):
            issues.append(
                ValidationIssue(
                    "error",
                    "adversarial_content",
                    f"`adversarial_content` must be a boolean (true/false), got: {adversarial_content!r}",
                    path,
                )
            )

        if source_kind:
            kinds_spec = self._schema.get("source_kinds", {})
            if source_kind not in kinds_spec:
                issues.append(
                    ValidationIssue(
                        "error",
                        "source_kind",
                        f"`source_kind` `{source_kind}` is not a valid source kind. Valid kinds are: {', '.join(sorted(kinds_spec.keys()))}",
                        path,
                    )
                )
            else:
                kind_spec = kinds_spec[source_kind]
                for field in kind_spec.get("required", []):
                    if (
                        field not in frontmatter
                        or frontmatter[field] is None
                        or frontmatter[field] == ""
                    ):
                        issues.append(
                            ValidationIssue(
                                "error",
                                field,
                                f"required field `{field}` for source kind `{source_kind}` is missing or empty",
                                path,
                            )
                        )
        return issues

    def validate_concept_page(
        self, frontmatter: dict[str, Any], path: Path | None = None
    ) -> list[ValidationIssue]:
        if frontmatter.get("type") == "redirect":
            return []
        issues = self._check_required("concept_page", frontmatter, path)

        tags = frontmatter.get("tags")
        if tags is not None:
            if not isinstance(tags, list):
                issues.append(ValidationIssue("error", "tags", "`tags` must be a list", path))
            elif "kb/concept" not in tags:
                issues.append(
                    ValidationIssue("error", "tags", "`tags` must include `kb/concept`", path)
                )

        evidence_status = frontmatter.get("evidence_status")
        if evidence_status is not None:
            valid_statuses = {"seed", "synthesized", "verified", "contested"}
            if evidence_status not in valid_statuses:
                issues.append(
                    ValidationIssue(
                        "error",
                        "evidence_status",
                        f"`evidence_status` `{evidence_status}` is invalid. Valid values are: {', '.join(sorted(valid_statuses))}",
                        path,
                    )
                )
        return issues

    def validate_answer_memo(
        self, frontmatter: dict[str, Any], path: Path | None = None
    ) -> list[ValidationIssue]:
        issues = self._check_required("answer_memo", frontmatter, path)

        tags = frontmatter.get("tags")
        if tags is not None:
            if not isinstance(tags, list):
                issues.append(ValidationIssue("error", "tags", "`tags` must be a list", path))
            elif "kb/answer" not in tags:
                issues.append(
                    ValidationIssue("error", "tags", "`tags` must include `kb/answer`", path)
                )

        query_class = frontmatter.get("query_class")
        if query_class is not None:
            valid_classes = {
                "lookup",
                "synthesis",
                "contradiction",
                "freshness",
                "code",
                "audit",
                "research",
            }
            if query_class not in valid_classes:
                issues.append(
                    ValidationIssue(
                        "error",
                        "query_class",
                        f"`query_class` `{query_class}` is invalid. Valid values are: {', '.join(sorted(valid_classes))}",
                        path,
                    )
                )

        retrieval_path = frontmatter.get("retrieval_path")
        if retrieval_path is not None:
            if not isinstance(retrieval_path, list):
                issues.append(
                    ValidationIssue(
                        "error", "retrieval_path", "`retrieval_path` must be a list", path
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
                        issues.append(
                            ValidationIssue(
                                "error",
                                f"retrieval_path[{idx}]",
                                f"step {idx} must be a dictionary",
                                path,
                            )
                        )
                        continue
                    for key in ("method", "layer", "query", "results_count"):
                        if key not in step:
                            issues.append(
                                ValidationIssue(
                                    "error",
                                    f"retrieval_path[{idx}].{key}",
                                    f"missing `{key}` in step {idx}",
                                    path,
                                )
                            )
                    method = step.get("method")
                    if method is not None and method not in valid_methods:
                        issues.append(
                            ValidationIssue(
                                "error",
                                f"retrieval_path[{idx}].method",
                                f"invalid method `{method}` in step {idx}",
                                path,
                            )
                        )
                    layer = step.get("layer")
                    if layer is not None and layer not in valid_layers:
                        issues.append(
                            ValidationIssue(
                                "error",
                                f"retrieval_path[{idx}].layer",
                                f"invalid layer `{layer}` in step {idx}",
                                path,
                            )
                        )
                    results_count = step.get("results_count")
                    if results_count is not None and not isinstance(results_count, int):
                        issues.append(
                            ValidationIssue(
                                "error",
                                f"retrieval_path[{idx}].results_count",
                                f"`results_count` in step {idx} must be an integer",
                                path,
                            )
                        )

        fetch_required = frontmatter.get("fetch_required")
        if fetch_required is not None and not isinstance(fetch_required, bool):
            issues.append(
                ValidationIssue(
                    "error", "fetch_required", "`fetch_required` must be a boolean", path
                )
            )

        return issues

    def validate_large_source_manifest(
        self, manifest: dict[str, Any], path: Path | None = None
    ) -> list[ValidationIssue]:
        """Validate a large_source_manifest.json against the v2 node schema."""
        issues: list[ValidationIssue] = []

        _VALID_NODE_TYPES = frozenset(
            {
                "document",
                "part",
                "chapter",
                "section",
                "subsection",
                "heading",
                "page",
                "file",
                "function",
                "class",
                "method",
                "table",
                "figure",
                "caption",
                "abstract",
                "method_section",
                "results",
                "limitations",
                "references",
                "appendix",
                "glossary",
                "speaker",
                "paragraph",
                "segment",
            }
        )
        _VALID_CONFIDENCE = frozenset({"low", "medium", "high"})
        _VALID_EXTRACTION_METHODS = frozenset(
            {
                "pdf-outline",
                "html-heading",
                "md-heading",
                "heuristic",
                "backfill-v1",
                "page-split",
                "file-split",
                "legacy-segment",
            }
        )
        _ANCHOR_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
        _NODE_REQUIRED = {
            "node_id",
            "parent_id",
            "order",
            "level",
            "type",
            "title",
            "anchor",
            "start_char",
            "end_char",
            "page_start",
            "page_end",
            "content_hash",
            "extraction_method",
            "confidence",
            "warnings",
            "source_note_heading",
        }

        version = manifest.get("large_source_manifest_version")
        if version is None:
            issues.append(
                ValidationIssue(
                    "warning",
                    "large_source_manifest_version",
                    "missing `large_source_manifest_version`; expected 2",
                    path,
                )
            )
        elif version != 2:
            issues.append(
                ValidationIssue(
                    "error",
                    "large_source_manifest_version",
                    f"`large_source_manifest_version` is {version!r}, expected 2",
                    path,
                )
            )

        nodes = manifest.get("nodes")
        if nodes is None:
            # v1 manifest without nodes — not an error if version warning already raised
            return issues

        if not isinstance(nodes, list):
            issues.append(
                ValidationIssue(
                    "error",
                    "nodes",
                    "`nodes` must be a list",
                    path,
                )
            )
            return issues

        seen_ids: set[str] = set()
        valid_ids: set[str] = {
            n["node_id"] for n in nodes if isinstance(n, dict) and "node_id" in n
        }

        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                issues.append(
                    ValidationIssue(
                        "error",
                        f"nodes[{idx}]",
                        f"node at index {idx} is not an object",
                        path,
                    )
                )
                continue

            # Required fields presence
            missing = _NODE_REQUIRED - node.keys()
            for field in sorted(missing):
                issues.append(
                    ValidationIssue(
                        "error",
                        f"nodes[{idx}].{field}",
                        f"node[{idx}] missing required field `{field}`",
                        path,
                    )
                )

            node_id = node.get("node_id", f"<index-{idx}>")

            # Uniqueness
            if node_id in seen_ids:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"nodes[{idx}].node_id",
                        f"duplicate node_id `{node_id}`",
                        path,
                    )
                )
            else:
                seen_ids.add(str(node_id))

            # parent_id references
            parent_id = node.get("parent_id")
            if parent_id is not None and parent_id not in valid_ids:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"nodes[{idx}].parent_id",
                        f"parent_id `{parent_id}` does not reference a known node_id",
                        path,
                    )
                )

            # anchor pattern
            anchor = node.get("anchor", "")
            if anchor and not _ANCHOR_RE.match(str(anchor)):
                issues.append(
                    ValidationIssue(
                        "error",
                        f"nodes[{idx}].anchor",
                        f"anchor `{anchor}` does not match [a-z0-9][a-z0-9-]* pattern",
                        path,
                    )
                )

            # confidence enum
            confidence = node.get("confidence")
            if confidence is not None and confidence not in _VALID_CONFIDENCE:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"nodes[{idx}].confidence",
                        f"confidence `{confidence}` must be one of: {', '.join(sorted(_VALID_CONFIDENCE))}",
                        path,
                    )
                )

            # type enum
            node_type = node.get("type")
            if node_type is not None and node_type not in _VALID_NODE_TYPES:
                issues.append(
                    ValidationIssue(
                        "warning",
                        f"nodes[{idx}].type",
                        f"type `{node_type}` is not in preferred node type set",
                        path,
                    )
                )

            # start_char < end_char
            start_char = node.get("start_char")
            end_char = node.get("end_char")
            if isinstance(start_char, int) and isinstance(end_char, int) and start_char >= end_char:
                issues.append(
                    ValidationIssue(
                        "warning",
                        f"nodes[{idx}].start_char",
                        f"start_char ({start_char}) must be < end_char ({end_char})",
                        path,
                    )
                )

            # warnings must be a list
            node_warnings = node.get("warnings")
            if node_warnings is not None and not isinstance(node_warnings, list):
                issues.append(
                    ValidationIssue(
                        "error",
                        f"nodes[{idx}].warnings",
                        "`warnings` must be a list",
                        path,
                    )
                )

        return issues

    def validate_metadata_json(
        self, metadata: dict[str, Any], path: Path | None = None
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        kind = metadata.get("kind", "")
        # Handle both underscore and hyphen forms of github_repo_snapshot
        if kind in {"github_repo_snapshot", "github-repo-snapshot"}:
            required_fields = {
                "git_commit": str,
                "branch": str,
                "tracked_file_count": int,
                "sampled_file_count": int,
                "sampled_paths": list,
                "omitted_paths_manifest": list,
                "coverage_policy": (dict, str),
            }
            for field, expected_type in required_fields.items():
                if field not in metadata or metadata[field] is None:
                    issues.append(
                        ValidationIssue(
                            "warning",
                            field,
                            f"missing metadata field `{field}` for github repository snapshot",
                            path,
                        )
                    )
                else:
                    val = metadata[field]
                    if isinstance(expected_type, tuple):
                        type_ok = any(isinstance(val, t) for t in expected_type)
                    else:
                        type_ok = isinstance(val, expected_type)
                    if not type_ok:
                        issues.append(
                            ValidationIssue(
                                "error",
                                field,
                                f"metadata field `{field}` has type `{type(val).__name__}`, expected `{expected_type}`",
                                path,
                            )
                        )
        return issues


def run_strict_validation() -> int:
    """Validate all source notes, concept pages, and answer memos against the schema.
    Returns the number of errors found.
    """
    from kops.utils import CONFIG
    from kops.utils import parse_frontmatter
    import json

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

    # Also validate raw metadata.json files
    for path in sorted(CONFIG.raw_dir.glob("*/metadata.json")):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
            all_issues.extend(validator.validate_metadata_json(metadata, path))
        except Exception as exc:
            all_issues.append(
                ValidationIssue(
                    "error",
                    "metadata.json",
                    f"failed to load or parse metadata.json: {exc}",
                    path,
                )
            )

    # Validate large_source_manifest.json files
    manifest_paths = sorted(CONFIG.raw_dir.glob("*/large_source_manifest.json"))
    manifest_errors = 0
    manifest_warnings = 0
    for path in manifest_paths:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            m_issues = validator.validate_large_source_manifest(manifest, path)
            all_issues.extend(m_issues)
            manifest_errors += sum(1 for i in m_issues if i.severity == "error")
            manifest_warnings += sum(1 for i in m_issues if i.severity != "error")
        except Exception as exc:
            all_issues.append(
                ValidationIssue(
                    "error",
                    "large_source_manifest.json",
                    f"failed to load or parse large_source_manifest.json: {exc}",
                    path,
                )
            )
            manifest_errors += 1
    print(
        f"Manifest validation: {len(manifest_paths)} file(s) checked, "
        f"{manifest_errors} error(s), {manifest_warnings} warning(s)"
    )

    errors = [i for i in all_issues if i.severity == "error"]
    warnings = [i for i in all_issues if i.severity != "error"]

    print(f"Schema validation: {len(errors)} error(s), {len(warnings)} warning(s)")
    for issue in sorted(all_issues, key=lambda i: (i.severity, str(i.path or ""))):
        label = str(issue.path.relative_to(ROOT)) if issue.path else "?"
        print(f"  [{issue.severity}] {label}: {issue.message}")

    return len(errors)
