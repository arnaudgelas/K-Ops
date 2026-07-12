"""Tests for kops.content_drift — content-hash drift detection + baseline backfill."""

from __future__ import annotations

from kops import content_drift as cd
from kops.utils import parse_frontmatter


def _write_note(sources_dir, source_id, content_hash=None):
    lines = ["---", f"source_id: {source_id}", "title: T", "type: source-summary"]
    if content_hash is not None:
        lines.append(f"content_hash: {content_hash}")
    lines += ["---", "", "## Summary", "", "body"]
    (sources_dir / f"{source_id}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_detect_statuses(tmp_path, monkeypatch):
    sources = tmp_path / "Sources"
    sources.mkdir()
    _write_note(sources, "src-sync", content_hash="aaaa")
    _write_note(sources, "src-drift", content_hash="cccc")
    _write_note(sources, "src-nobase")  # no baseline
    _write_note(sources, "src-noraw", content_hash="dddd")

    current = {"src-sync": "aaaa", "src-drift": "bbbb", "src-nobase": "eeee", "src-noraw": None}
    monkeypatch.setattr(cd, "SOURCES_DIR", sources)
    monkeypatch.setattr(cd, "current_raw_hash", lambda sid: current.get(sid))

    by_id = {r["source_id"]: r["status"] for r in cd.detect()}
    assert by_id == {
        "src-sync": "in-sync",
        "src-drift": "drifted",
        "src-nobase": "no-baseline",
        "src-noraw": "no-raw",
    }


def test_detect_reports_hash_pair_on_drift(tmp_path, monkeypatch):
    sources = tmp_path / "Sources"
    sources.mkdir()
    _write_note(sources, "src-x", content_hash="old123")
    monkeypatch.setattr(cd, "SOURCES_DIR", sources)
    monkeypatch.setattr(cd, "current_raw_hash", lambda sid: "new456")
    (r,) = cd.detect()
    assert r["recorded"] == "old123" and r["current"] == "new456" and r["status"] == "drifted"


def test_backfill_seeds_missing_baseline(tmp_path, monkeypatch):
    sources = tmp_path / "Sources"
    sources.mkdir()
    _write_note(sources, "src-x")  # no content_hash
    monkeypatch.setattr(cd, "SOURCES_DIR", sources)
    monkeypatch.setattr(cd, "current_raw_hash", lambda sid: "hhhh")

    assert cd.backfill_content_hash() == 1
    fm, _ = parse_frontmatter((sources / "src-x.md").read_text(encoding="utf-8"))
    assert fm["content_hash"] == "hhhh"


def test_backfill_does_not_overwrite_without_force(tmp_path, monkeypatch):
    sources = tmp_path / "Sources"
    sources.mkdir()
    _write_note(sources, "src-x", content_hash="old")
    monkeypatch.setattr(cd, "SOURCES_DIR", sources)
    monkeypatch.setattr(cd, "current_raw_hash", lambda sid: "new")

    # without force: existing baseline is left alone
    assert cd.backfill_content_hash() == 0
    fm, _ = parse_frontmatter((sources / "src-x.md").read_text(encoding="utf-8"))
    assert fm["content_hash"] == "old"

    # with force: re-baselined to current
    assert cd.backfill_content_hash(force=True) == 1
    fm, _ = parse_frontmatter((sources / "src-x.md").read_text(encoding="utf-8"))
    assert fm["content_hash"] == "new"


def test_backfill_skips_sources_without_raw(tmp_path, monkeypatch):
    sources = tmp_path / "Sources"
    sources.mkdir()
    _write_note(sources, "src-local")  # a local-file source with no raw hash
    monkeypatch.setattr(cd, "SOURCES_DIR", sources)
    monkeypatch.setattr(cd, "current_raw_hash", lambda sid: None)
    assert cd.backfill_content_hash() == 0
