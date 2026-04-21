from __future__ import annotations

import datetime as dt
from pathlib import Path

from utils import ROOT, dump_frontmatter


def research_timestamp() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def render_research_brief(
    topic: str,
    slug: str,
    tier: str,
    created_at: str,
    brief_path: Path,
    status_path: Path,
) -> str:
    return "\n".join(
        [
            dump_frontmatter(
                {
                    "title": topic.strip() or slug,
                    "type": "research-brief",
                    "topic_slug": slug,
                    "quality_tier": tier,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "status_path": str(status_path.relative_to(ROOT)),
                    "brief_path": str(brief_path.relative_to(ROOT)),
                }
            ).rstrip(),
            "# Research Brief",
            "",
            "## Research Question",
            "",
            topic.strip() or slug,
            "",
            "## Scope",
            "",
            "- Working question:",
            f"  - {topic.strip() or slug}",
            f"- Quality tier: `{tier}`",
            "",
            "## Assumptions",
            "",
            "- None recorded yet.",
            "",
            "## Subquestions",
            "",
            "- Triage and refine this question.",
            "",
            "## Open Questions",
            "",
            "- What evidence would falsify the emerging thesis?",
            "",
        ]
    )


def render_research_status(
    topic: str,
    slug: str,
    tier: str,
    phase: str,
    created_at: str,
    updated_at: str,
    brief_path: Path,
    progress_path: Path,
    findings_path: Path | None,
    review_path: Path,
    report_path: Path | None,
    imports_dir: Path,
) -> str:
    data: dict = {
        "title": topic.strip() or slug,
        "type": "research-status",
        "topic_slug": slug,
        "quality_tier": tier,
        "phase": phase,
        "created_at": created_at,
        "updated_at": updated_at,
        "brief_path": str(brief_path.relative_to(ROOT)),
        "progress_path": str(progress_path.relative_to(ROOT)),
        "review_path": str(review_path.relative_to(ROOT)),
        "imports_path": str(imports_dir.relative_to(ROOT)),
    }
    if findings_path:
        data["findings_path"] = str(findings_path.relative_to(ROOT))
    if report_path:
        data["report_path"] = str(report_path.relative_to(ROOT))
    body = "\n".join(
        [
            "# Research Status",
            "",
            f"- Topic: {topic.strip() or slug}",
            f"- Slug: `{slug}`",
            f"- Quality tier: `{tier}`",
            f"- Phase: `{phase}`",
            f"- Updated: {updated_at}",
            "",
            "## Next Step",
            "",
            "- Resume from the first incomplete phase recorded here.",
            "",
            "## Files",
            "",
            f"- Brief: `{brief_path.relative_to(ROOT)}`",
            f"- Progress: `{progress_path.relative_to(ROOT)}`",
            f"- Review: `{review_path.relative_to(ROOT)}`",
            f"- Imports: `{imports_dir.relative_to(ROOT)}`",
            f"- Findings: `{findings_path.relative_to(ROOT) if findings_path else 'pending'}`",
            f"- Report: `{report_path.relative_to(ROOT) if report_path else 'pending'}`",
            "",
        ]
    )
    return dump_frontmatter(data) + body


def render_research_progress(topic: str, slug: str, tier: str, created_at: str) -> str:
    return dump_frontmatter(
        {
            "title": topic.strip() or slug,
            "type": "research-progress",
            "topic_slug": slug,
            "quality_tier": tier,
            "created_at": created_at,
            "updated_at": created_at,
        }
    ) + "\n".join(
        [
            "# Progress Log",
            "",
            f"- [{created_at}] Initialized research run for `{topic.strip() or slug}` at tier `{tier}`.",
            "",
        ]
    )


def render_research_findings(
    topic: str, slug: str, tier: str, created_at: str, status_path: Path
) -> str:
    return dump_frontmatter(
        {
            "title": topic.strip() or slug,
            "type": "research-findings",
            "topic_slug": slug,
            "quality_tier": tier,
            "created_at": created_at,
            "updated_at": created_at,
            "status_path": str(status_path.relative_to(ROOT)),
        }
    ) + "\n".join(
        [
            "# Findings",
            "",
            "## Key Claims",
            "",
            "- Pending source collection.",
            "",
            "## Evidence",
            "",
            "- Pending source notes.",
            "",
            "## Open Questions",
            "",
            "- Pending research.",
            "",
        ]
    )


def render_research_review(
    topic: str, slug: str, tier: str, created_at: str, status_path: Path
) -> str:
    return dump_frontmatter(
        {
            "title": topic.strip() or slug,
            "type": "research-review",
            "topic_slug": slug,
            "quality_tier": tier,
            "created_at": created_at,
            "updated_at": created_at,
            "status_path": str(status_path.relative_to(ROOT)),
        }
    ) + "\n".join(
        [
            "# Contrarian Review",
            "",
            "## Strongest Objections",
            "",
            "- Pending review.",
            "",
            "## Missing Evidence",
            "",
            "- Pending review.",
            "",
            "## Claims To Soften",
            "",
            "- Pending review.",
            "",
        ]
    )


def render_research_report(
    topic: str,
    slug: str,
    tier: str,
    created_at: str,
    status_path: Path,
    review_path: Path,
) -> str:
    return dump_frontmatter(
        {
            "title": topic.strip() or slug,
            "type": "research-report",
            "topic_slug": slug,
            "quality_tier": tier,
            "created_at": created_at,
            "updated_at": created_at,
            "status_path": str(status_path.relative_to(ROOT)),
            "review_path": str(review_path.relative_to(ROOT)),
        }
    ) + "\n".join(
        [
            "# Report",
            "",
            "## Executive Summary",
            "",
            "- Pending synthesis.",
            "",
            "## Methodology",
            "",
            "- Pending synthesis.",
            "",
            "## Evidence and Analysis",
            "",
            "- Pending synthesis.",
            "",
            "## Contradictory or Missing Evidence",
            "",
            "- Pending synthesis.",
            "",
        ]
    )


def render_research_manifest(
    topic: str, slug: str, tier: str, archive_date: str, final_phase: str, moved_files: list[str]
) -> str:
    return dump_frontmatter(
        {
            "title": topic.strip() or slug,
            "type": "research-archive-manifest",
            "topic_slug": slug,
            "quality_tier": tier,
            "archive_date": archive_date,
            "final_phase": final_phase,
        }
    ) + "\n".join(["# Archive Manifest", "", *[f"- {item}" for item in moved_files], ""])
