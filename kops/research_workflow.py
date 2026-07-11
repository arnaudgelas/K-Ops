from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from kops.kb_runtime import agent_run, build_prompt
from kops.research_artifacts import (
    copy_imported_report,
    render_research_brief,
    render_research_findings,
    render_research_manifest,
    render_research_progress,
    render_research_report,
    render_research_review,
    render_research_status,
    research_source_note_path,
)
from kops.utils import (
    CONFIG,
    ROOT,
    dump_frontmatter,
    ensure_dir,
    parse_frontmatter,
    slugify,
    write_text,
)

RESEARCH_ROOT = CONFIG.research_dir
RESEARCH_BRIEFS = RESEARCH_ROOT / "briefs"
RESEARCH_FINDINGS = RESEARCH_ROOT / "findings"
RESEARCH_NOTES = RESEARCH_ROOT / "notes"
RESEARCH_REPORTS = RESEARCH_ROOT / "reports"
RESEARCH_IMPORTS = RESEARCH_ROOT / "imports"
RESEARCH_ARCHIVE = RESEARCH_ROOT / "archive"
RESEARCH_PHASES = {
    "briefing",
    "source-collection",
    "findings",
    "contrarian-review",
    "report-drafting",
    "done",
    "blocked",
}
RESEARCH_TIERS = {"fast", "standard", "deep"}


def research_slug(text: str) -> str:
    slug = slugify(text.strip())
    return slug or "research-topic"


def research_date() -> str:
    return dt.date.today().isoformat()


def research_timestamp() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def ensure_research_dirs() -> None:
    for path in [
        RESEARCH_ROOT,
        RESEARCH_BRIEFS,
        RESEARCH_FINDINGS,
        RESEARCH_NOTES,
        RESEARCH_REPORTS,
        RESEARCH_IMPORTS,
        RESEARCH_ARCHIVE,
    ]:
        ensure_dir(path)


def research_status_path(slug: str) -> Path:
    return RESEARCH_NOTES / f"{slug}-status.md"


def research_progress_path(slug: str) -> Path:
    return RESEARCH_NOTES / f"{slug}-progress.md"


def research_brief_path(slug: str, date_label: str) -> Path:
    return RESEARCH_BRIEFS / f"{slug}-{date_label}.md"


def research_findings_path(slug: str, date_label: str) -> Path:
    return RESEARCH_FINDINGS / f"{slug}-{date_label}.md"


def research_report_path(slug: str, date_label: str) -> Path:
    return RESEARCH_REPORTS / f"{slug}-{date_label}.md"


def research_review_path(slug: str) -> Path:
    return RESEARCH_NOTES / f"{slug}-contrarian-review.md"


def research_import_dir(slug: str) -> Path:
    return RESEARCH_IMPORTS / slug


def research_archive_dir(slug: str) -> Path:
    return RESEARCH_ARCHIVE / slug


def parse_research_file(path: Path) -> tuple[dict, str]:
    return parse_frontmatter(path.read_text(encoding="utf-8"))


def load_research_status(slug: str) -> tuple[dict, str, Path] | None:
    path = research_status_path(slug)
    if not path.exists():
        return None
    frontmatter, body = parse_research_file(path)
    return frontmatter, body, path


def set_research_status_phase(
    slug: str,
    *,
    topic: str | None = None,
    tier: str | None = None,
    phase: str | None = None,
    brief_path: Path | None = None,
    progress_path: Path | None = None,
    findings_path: Path | None = None,
    review_path: Path | None = None,
    report_path: Path | None = None,
) -> None:
    loaded = load_research_status(slug)
    if not loaded:
        raise FileNotFoundError(f"Missing research status file for topic slug `{slug}`")
    frontmatter, body, path = loaded
    now = research_timestamp()
    if topic:
        frontmatter["title"] = topic
    if tier:
        frontmatter["quality_tier"] = tier
    if phase:
        frontmatter["phase"] = phase
    frontmatter["updated_at"] = now
    if brief_path:
        frontmatter["brief_path"] = str(brief_path.relative_to(ROOT))
    if progress_path:
        frontmatter["progress_path"] = str(progress_path.relative_to(ROOT))
    if findings_path:
        frontmatter["findings_path"] = str(findings_path.relative_to(ROOT))
    if review_path:
        frontmatter["review_path"] = str(review_path.relative_to(ROOT))
    if report_path:
        frontmatter["report_path"] = str(report_path.relative_to(ROOT))
    body_lines = body.splitlines()
    if body_lines:
        body_lines[0] = "# Research Status"
        body = "\n".join(body_lines) + ("\n" if not body.endswith("\n") else "")
    write_text(path, dump_frontmatter(frontmatter) + body.lstrip("\n"))


def append_research_progress(slug: str, message: str) -> None:
    path = research_progress_path(slug)
    if not path.exists():
        raise FileNotFoundError(f"Missing research progress file for topic slug `{slug}`")
    frontmatter, body = parse_research_file(path)
    lines = body.rstrip("\n").splitlines()
    lines.extend(["", f"- [{research_timestamp()}] {message}", ""])
    frontmatter["updated_at"] = research_timestamp()
    write_text(path, dump_frontmatter(frontmatter) + "\n".join(lines).lstrip("\n"))


def ensure_research_scaffold(topic: str, tier: str) -> tuple[str, Path, Path, Path, Path, Path]:
    ensure_research_dirs()
    slug = research_slug(topic)
    created_at = research_date()
    brief_path = research_brief_path(slug, created_at)
    status_path = research_status_path(slug)
    progress_path = research_progress_path(slug)
    findings_path = research_findings_path(slug, created_at)
    review_path = research_review_path(slug)
    report_path = research_report_path(slug, created_at)
    imports_dir = research_import_dir(slug)
    ensure_dir(imports_dir)

    if not brief_path.exists():
        write_text(
            brief_path,
            render_research_brief(topic, slug, tier, created_at, brief_path, status_path),
        )
    if not progress_path.exists():
        write_text(progress_path, render_research_progress(topic, slug, tier, created_at))
    if not status_path.exists():
        write_text(
            status_path,
            render_research_status(
                topic,
                slug,
                tier,
                "briefing",
                created_at,
                created_at,
                brief_path,
                progress_path,
                findings_path if findings_path.exists() else None,
                review_path,
                report_path if report_path.exists() else None,
                imports_dir,
            ),
        )
    return slug, brief_path, status_path, progress_path, findings_path, report_path


def move_path_to_archive(source: Path, archive_root: Path, moved: list[str]) -> None:
    if not source.exists():
        return
    destination = archive_root / source.relative_to(RESEARCH_ROOT)
    ensure_dir(destination.parent)
    if source.is_dir():
        ensure_dir(destination)
        for child in sorted(source.iterdir()):
            move_path_to_archive(child, archive_root, moved)
        shutil.rmtree(source)
        return
    shutil.move(str(source), str(destination))
    moved.append(str(destination.relative_to(ROOT)))


def topic_from_status_or_arg(arg: str | None) -> tuple[str, str]:
    if not arg:
        raise ValueError("A topic or slug is required.")
    slug = research_slug(arg)
    loaded = load_research_status(slug)
    if loaded:
        frontmatter, _, _ = loaded
        topic = str(frontmatter.get("title") or arg)
        return slug, topic
    return slug, arg.strip()


def cmd_research_start(topic: str, tier: str = "standard") -> None:
    if tier not in RESEARCH_TIERS:
        raise ValueError(f"Unsupported quality tier: {tier}")
    slug, brief_path, status_path, progress_path, findings_path, report_path = (
        ensure_research_scaffold(topic, tier)
    )
    print(f"Research scaffold ready: {slug}")
    print(f"- brief: {brief_path.relative_to(ROOT)}")
    print(f"- status: {status_path.relative_to(ROOT)}")
    print(f"- progress: {progress_path.relative_to(ROOT)}")
    print(f"- findings: {findings_path.relative_to(ROOT)}")
    print(f"- report: {report_path.relative_to(ROOT)}")


def cmd_research_status(target: str = "all") -> None:
    ensure_research_dirs()
    active_statuses = sorted(RESEARCH_NOTES.glob("*-status.md"))
    archived_statuses = sorted(RESEARCH_ARCHIVE.rglob("*-status.md"))

    def status_summary(path: Path) -> str:
        frontmatter, _ = parse_research_file(path)
        topic = str(frontmatter.get("title") or path.stem.replace("-status", ""))
        slug = str(frontmatter.get("topic_slug") or research_slug(topic))
        tier = str(frontmatter.get("quality_tier") or "unknown")
        phase = str(frontmatter.get("phase") or "unknown")
        brief_path = (
            ROOT / str(frontmatter["brief_path"]) if frontmatter.get("brief_path") else None
        )
        findings_path = (
            ROOT / str(frontmatter["findings_path"]) if frontmatter.get("findings_path") else None
        )
        report_path = (
            ROOT / str(frontmatter["report_path"]) if frontmatter.get("report_path") else None
        )
        review_path = research_review_path(slug)
        brief_exists = "yes" if brief_path and brief_path.exists() else "no"
        findings_exists = "yes" if findings_path and findings_path.exists() else "no"
        review_exists = "yes" if review_path.exists() else "no"
        report_exists = "yes" if report_path and report_path.exists() else "no"
        return (
            f"- {slug}: phase={phase}, tier={tier}, brief={brief_exists}, findings={findings_exists}, "
            f"review={review_exists}, report={report_exists}, path={path.relative_to(ROOT)}"
        )

    if target not in {"all", "--include-archived"}:
        slug = research_slug(target)
        path = research_status_path(slug)
        if path.exists():
            print(status_summary(path))
            print(f"Resume from {path.relative_to(ROOT)}")
            return
        for candidate in archived_statuses:
            if candidate.stem.startswith(slug):
                print("Archived")
                print(status_summary(candidate))
                return
        print(f"No research run found for `{target}`")
        return

    print("Active")
    for path in active_statuses:
        print(status_summary(path))
    if archived_statuses:
        print("\nArchived")
        for path in archived_statuses:
            print(status_summary(path))


def cmd_research_collect(agent: str, topic: str, tier: str = "standard") -> None:
    slug, brief_path, status_path, progress_path, findings_path, report_path = (
        ensure_research_scaffold(topic, tier)
    )
    set_research_status_phase(
        slug,
        topic=topic,
        tier=tier,
        phase="source-collection",
        brief_path=brief_path,
        progress_path=progress_path,
        findings_path=findings_path,
        report_path=report_path,
    )
    if not findings_path.exists():
        write_text(
            findings_path,
            render_research_findings(topic, slug, tier, research_timestamp(), status_path),
        )
    prompt = build_prompt(
        "research_collect_prompt.md",
        brief_path=str(brief_path.relative_to(ROOT)),
        status_path=str(status_path.relative_to(ROOT)),
        progress_path=str(progress_path.relative_to(ROOT)),
        findings_path=str(findings_path.relative_to(ROOT)),
    )
    agent_run(agent, prompt)
    if not findings_path.exists():
        raise FileNotFoundError(f"Expected findings file was not written: {findings_path}")
    append_research_progress(slug, "Completed source collection and initial findings distillation.")
    set_research_status_phase(
        slug,
        topic=topic,
        tier=tier,
        phase="findings",
        brief_path=brief_path,
        progress_path=progress_path,
        findings_path=findings_path,
        report_path=report_path,
    )
    print(f"Source collection complete: {findings_path.relative_to(ROOT)}")


def cmd_research_review(agent: str, topic: str, tier: str = "standard") -> None:
    slug, brief_path, status_path, progress_path, findings_path, report_path = (
        ensure_research_scaffold(topic, tier)
    )
    review_path = research_review_path(slug)
    if not findings_path.exists():
        raise FileNotFoundError(f"Cannot review `{slug}` before findings exist: {findings_path}")
    if not review_path.exists():
        write_text(
            review_path,
            render_research_review(topic, slug, tier, research_timestamp(), status_path),
        )
    set_research_status_phase(
        slug,
        topic=topic,
        tier=tier,
        phase="contrarian-review",
        brief_path=brief_path,
        progress_path=progress_path,
        findings_path=findings_path,
        review_path=review_path,
        report_path=report_path,
    )
    prompt = build_prompt(
        "research_review_prompt.md",
        brief_path=str(brief_path.relative_to(ROOT)),
        findings_path=str(findings_path.relative_to(ROOT)),
        review_path=str(review_path.relative_to(ROOT)),
    )
    agent_run(agent, prompt)
    if not review_path.exists():
        raise FileNotFoundError(f"Expected contrarian review was not written: {review_path}")
    append_research_progress(slug, "Completed contrarian review.")
    print(f"Review written: {review_path.relative_to(ROOT)}")


def cmd_research_report(
    agent: str, topic: str, tier: str = "standard", require_review: bool = True
) -> None:
    slug, brief_path, status_path, progress_path, findings_path, report_path = (
        ensure_research_scaffold(topic, tier)
    )
    review_path = research_review_path(slug)
    if not findings_path.exists():
        raise FileNotFoundError(f"Cannot draft report without findings: {findings_path}")
    if require_review and not review_path.exists():
        raise FileNotFoundError(f"Cannot draft report without contrarian review: {review_path}")
    if not report_path.exists():
        write_text(
            report_path,
            render_research_report(
                topic, slug, tier, research_timestamp(), status_path, review_path
            ),
        )
    set_research_status_phase(
        slug,
        topic=topic,
        tier=tier,
        phase="report-drafting",
        brief_path=brief_path,
        progress_path=progress_path,
        findings_path=findings_path,
        review_path=review_path,
        report_path=report_path,
    )
    prompt = build_prompt(
        "research_report_prompt.md",
        brief_path=str(brief_path.relative_to(ROOT)),
        findings_path=str(findings_path.relative_to(ROOT)),
        review_path=str(review_path.relative_to(ROOT)),
        report_path=str(report_path.relative_to(ROOT)),
    )
    agent_run(agent, prompt)
    if not report_path.exists():
        raise FileNotFoundError(f"Expected report was not written: {report_path}")
    append_research_progress(slug, "Completed final report drafting.")
    set_research_status_phase(
        slug,
        topic=topic,
        tier=tier,
        phase="done",
        brief_path=brief_path,
        progress_path=progress_path,
        findings_path=findings_path,
        review_path=review_path,
        report_path=report_path,
    )
    print(f"Report written: {report_path.relative_to(ROOT)}")


def cmd_research_import(
    topic: str,
    imported_path: str,
    provider: str,
    canonical_origin: str | None = None,
    tier: str = "standard",
) -> None:
    slug, brief_path, status_path, progress_path, findings_path, report_path = (
        ensure_research_scaffold(topic, tier)
    )
    source_path = Path(imported_path).expanduser()
    origin = canonical_origin or source_path.as_posix()
    copied_path, source_id, title, citations, manifest_path = copy_imported_report(
        source_path, slug, provider, origin
    )
    append_research_progress(
        slug,
        f"Imported model-generated report `{source_path}` as lead note `{source_id}` with {len(citations)} extracted citation(s).",
    )
    set_research_status_phase(
        slug,
        topic=topic,
        tier=tier,
        phase="source-collection",
        brief_path=brief_path,
        progress_path=progress_path,
        findings_path=findings_path,
        report_path=report_path,
    )
    print(f"Imported report copied to {copied_path.relative_to(ROOT)}")
    print(f"Manifest written to {manifest_path.relative_to(ROOT)}")
    print(f"Source note written to {research_source_note_path(source_id).relative_to(ROOT)}")
    if citations:
        print(f"Citation stubs created: {len(citations)}")


def cmd_research_archive(topic: str) -> None:
    slug, _ = topic_from_status_or_arg(topic)
    status_info = load_research_status(slug)
    if not status_info:
        raise FileNotFoundError(f"Cannot archive missing research run `{slug}`")
    frontmatter, _, status_path = status_info
    phase = str(frontmatter.get("phase") or "")
    if phase != "done":
        raise RuntimeError(f"Refusing to archive `{slug}` because phase is `{phase}` not `done`")
    archive_root = research_archive_dir(slug)
    if archive_root.exists() and any(archive_root.iterdir()):
        raise RuntimeError(
            f"Archive destination already exists and is not empty: {archive_root.relative_to(ROOT)}"
        )
    ensure_dir(archive_root)
    moved: list[str] = []
    topic_title = str(frontmatter.get("title") or slug)
    tier = str(frontmatter.get("quality_tier") or "standard")
    archive_date = research_date()
    paths_to_move = [
        ROOT / str(frontmatter["brief_path"]) if frontmatter.get("brief_path") else None,
        ROOT / str(frontmatter["findings_path"]) if frontmatter.get("findings_path") else None,
        ROOT / str(frontmatter["report_path"]) if frontmatter.get("report_path") else None,
        ROOT / str(frontmatter["progress_path"]) if frontmatter.get("progress_path") else None,
        ROOT / str(frontmatter["review_path"]) if frontmatter.get("review_path") else None,
        status_path,
    ]
    imports_dir = (
        ROOT / str(frontmatter["imports_path"])
        if frontmatter.get("imports_path")
        else research_import_dir(slug)
    )
    if imports_dir.exists():
        paths_to_move.append(imports_dir)
    for path in paths_to_move:
        if not path or not path.exists():
            continue
        destination = archive_root / path.relative_to(RESEARCH_ROOT)
        ensure_dir(destination.parent)
        shutil.move(str(path), str(destination))
        moved.append(str(destination.relative_to(ROOT)))
    manifest_path = archive_root / "MANIFEST.md"
    write_text(
        manifest_path, render_research_manifest(topic_title, slug, tier, archive_date, phase, moved)
    )
    print(f"Archived run written to {archive_root.relative_to(ROOT)}")
    print(f"Manifest: {manifest_path.relative_to(ROOT)}")
