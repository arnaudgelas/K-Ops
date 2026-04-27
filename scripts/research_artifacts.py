from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from utils import CONFIG, ROOT, dump_frontmatter, ensure_dir, find_source_note, now_stamp, short_hash, slugify, write_text

RESEARCH_IMPORTED_KIND = "imported_model_report"
RESEARCH_IMPORTED_CITATION_KIND = "imported_model_report_citation"
REPORT_URL_RE = re.compile(r"\((https?://[^)\s]+)\)|(?<!\]\()(?<!\]\[)(https?://[^\s<>\]]+)", re.IGNORECASE)
RESEARCH_IMPORTS = ROOT / "research" / "imports"


def research_timestamp() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Import-workflow helpers (ported from agkb)
# ---------------------------------------------------------------------------


def research_source_note_path(source_id: str) -> Path:
    return find_source_note(source_id) or CONFIG.summaries_dir / f"{source_id}.md"


def imported_report_source_id(canonical_origin: str, content: str) -> str:
    return f"src-{short_hash(canonical_origin + '|' + content)}"


def imported_report_bundle_dir(topic_slug: str, provider: str, imported_stamp: str) -> Path:
    return ROOT / "research" / "imports" / topic_slug / f"{provider}-{imported_stamp}"


def normalize_url(url: str) -> str:
    url = url.strip().rstrip(".,;:)]}>'\"")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return url
    normalized = parsed._replace(fragment="")
    return urlunsplit(normalized)


def extract_report_citations(text: str) -> list[dict[str, str]]:
    citations: dict[str, dict[str, str]] = {}
    for match in REPORT_URL_RE.finditer(text):
        url = normalize_url(match.group(1) or match.group(2) or "")
        if not url:
            continue
        label = "link" if match.group(1) else (urlsplit(url).netloc or url)
        citations.setdefault(url, {"url": url, "label": label})
    return list(citations.values())


def citation_source_id(url: str) -> str:
    return f"src-{short_hash(url)}"


def render_import_manifest_bundle(
    topic: str,
    slug: str,
    provider: str,
    canonical_origin: str,
    imported_path: Path,
    report_note_path: Path,
    bundle_path: Path,
    citations: list[dict[str, str]],
) -> str:
    data = {
        "title": f"Imported report manifest: {topic.strip() or slug}",
        "type": "research-import-manifest",
        "topic_slug": slug,
        "provider": provider,
        "canonical_origin": canonical_origin,
        "imported_report_path": str(imported_path.relative_to(ROOT)),
        "report_note_path": str(report_note_path.relative_to(ROOT)),
        "bundle_path": str(bundle_path.relative_to(ROOT)),
        "citation_count": len(citations),
        "created_at": now_stamp(),
    }
    body_lines = [
        "# Imported Report Manifest",
        "",
        "## Citations",
        "",
        "| URL | Label | Source ID | Status |",
        "|---|---|---|---|",
    ]
    for item in citations:
        body_lines.append(f"| {item['url']} | {item['label']} | {item['source_id']} | {item['status']} |")
    if len(citations) == 0:
        body_lines.extend(["", "- No citations were detected in the imported report."])
    body_lines.extend(["", "## Notes", "", "- Imported reports are leads, not authority.", ""])
    return dump_frontmatter(data) + "\n".join(body_lines)


def render_imported_report_source_note(
    source_id: str,
    title: str,
    slug: str,
    imported_path: Path,
    canonical_origin: str,
    created_at: str,
) -> str:
    return dump_frontmatter(
        {
            "title": title,
            "type": "source-summary",
            "source_id": source_id,
            "source_kind": RESEARCH_IMPORTED_KIND,
            "evidence_strength": "secondary",
            "imported_from": str(imported_path.relative_to(ROOT)),
            "canonical_origin": canonical_origin,
            "topic_slug": slug,
            "authority": "lead_only",
            "verification_state": "needs_primary_sources",
            "created_at": created_at,
        }
    ) + "\n".join(
        [
            f"# {title}",
            "",
            "## Summary",
            "",
            "This imported report is a lead generator, not final authority.",
            "",
            "## Key Claims",
            "",
            "- Pending extraction from the imported report.",
            "",
            "## Evidence Notes",
            "",
            "- Verify the claims against primary sources before promoting them into concept pages.",
            "",
            "## Related Concepts",
            "",
            "- Pending.",
            "",
            "## Backlinks",
            "",
            "- Imported report sources must remain traceable to their raw input.",
            "",
        ]
    )


def render_imported_citation_source_note(
    source_id: str,
    title: str,
    topic_slug: str,
    url: str,
    report_source_id: str,
    provider: str,
    created_at: str,
) -> str:
    return dump_frontmatter(
        {
            "title": title,
            "type": "source-summary",
            "source_id": source_id,
            "source_kind": RESEARCH_IMPORTED_CITATION_KIND,
            "evidence_strength": "stub",
            "canonical_url": url,
            "topic_slug": topic_slug,
            "parent_source_id": report_source_id,
            "provider": provider,
            "authority": "lead_only",
            "verification_state": "needs_fetch",
            "created_at": created_at,
        }
    ) + "\n".join(
        [
            f"# {title}",
            "",
            "## Summary",
            "",
            "This is a citation extracted from an imported model-generated report and should be treated as a lead.",
            "",
            "## Key Claims",
            "",
            "- Pending verification.",
            "",
            "## Evidence Notes",
            "",
            f"- Canonical URL: {url}",
            f"- Parent imported report: [[Sources/{report_source_id}|source-{report_source_id}]]",
            "",
            "## Related Concepts",
            "",
            "- Pending.",
            "",
            "## Backlinks",
            "",
            "- Imported citation stub.",
            "",
        ]
    )


def copy_imported_report(
    imported_path: Path,
    topic_slug: str,
    provider: str,
    canonical_origin: str,
) -> tuple[Path, str, str, list[dict[str, str]], Path]:
    if not imported_path.exists():
        raise FileNotFoundError(imported_path)
    ensure_dir(RESEARCH_IMPORTS / topic_slug)
    imported_stamp = now_stamp()
    bundle_dir = imported_report_bundle_dir(topic_slug, provider, imported_stamp)
    ensure_dir(bundle_dir)
    content = imported_path.read_text(encoding="utf-8")
    source_id = imported_report_source_id(canonical_origin, content)
    title = f"Imported report: {provider} {imported_path.stem}"
    target_path = bundle_dir / imported_path.name
    write_text(target_path, content)
    citations = extract_report_citations(content)
    note_path = research_source_note_path(source_id)
    if not note_path.exists():
        write_text(
            note_path,
            render_imported_report_source_note(
                source_id=source_id,
                title=title,
                slug=topic_slug,
                imported_path=target_path,
                canonical_origin=canonical_origin,
                created_at=now_stamp(),
            ),
        )
    citation_items: list[dict[str, str]] = []
    for citation in citations:
        citation_id = citation_source_id(citation["url"])
        citation_title = citation["label"] if citation["label"] else citation["url"]
        citation_note = research_source_note_path(citation_id)
        if not citation_note.exists():
            write_text(
                citation_note,
                render_imported_citation_source_note(
                    source_id=citation_id,
                    title=f"Imported citation: {citation_title}",
                    topic_slug=topic_slug,
                    url=citation["url"],
                    report_source_id=source_id,
                    provider=provider,
                    created_at=now_stamp(),
                ),
            )
        citation_items.append(
            {
                "url": citation["url"],
                "label": citation_title,
                "source_id": citation_id,
                "status": "stub-created" if citation_note.exists() else "created",
            }
        )

    manifest_path = bundle_dir / "manifest.md"
    write_text(
        manifest_path,
        render_import_manifest_bundle(
            topic=title,
            slug=topic_slug,
            provider=provider,
            canonical_origin=canonical_origin,
            imported_path=target_path,
            report_note_path=note_path,
            bundle_path=bundle_dir,
            citations=citation_items,
        ),
    )
    return target_path, source_id, title, citation_items, manifest_path


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
