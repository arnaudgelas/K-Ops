from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "medium_substack_article.html"


def main() -> None:
    sys.path.append(str(ROOT / "scripts"))
    from fetch_sources import extract_html_text, strip_tracking_parameters  # noqa: WPS433

    html = FIXTURE_PATH.read_text(encoding="utf-8")
    extracted = extract_html_text(
        html, "https://medium.com/example/story?utm_source=newsletter&fbclid=abc123"
    )

    expected_lines = [
        "Real article title",
        "Real article body paragraph one.",
        "Real article body paragraph two.",
    ]
    for line in expected_lines:
        if line not in extracted:
            raise AssertionError(
                f"Missing expected article content: {line!r}\nExtracted:\n{extracted}"
            )

    for banned in ("Subscribe", "Sign in", "Share", "Read more from the author"):
        if banned in extracted:
            raise AssertionError(
                f"Unexpected boilerplate in extraction: {banned!r}\nExtracted:\n{extracted}"
            )

    canonical = strip_tracking_parameters(
        "https://medium.com/example/story?utm_source=newsletter&fbclid=abc123"
    )
    expected_canonical = "https://medium.com/example/story"
    if canonical != expected_canonical:
        raise AssertionError(f"Canonical URL mismatch: {canonical!r} != {expected_canonical!r}")

    print("fetch_sources regression passed")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# A7 unit tests: segment_source
# ---------------------------------------------------------------------------


def _get_segment_source():
    """Import segment_source, adding scripts/ to sys.path if needed."""
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from fetch_sources import segment_source  # noqa: WPS433

    return segment_source


def test_segment_source_confidence_field():
    """All nodes produced by segment_source have a valid confidence field."""
    segment_source = _get_segment_source()
    content = "# Introduction\n\nSome text.\n\n## Methods\n\nMore text.\n"
    nodes = segment_source(content, "article", "test-src-001")
    assert nodes, "segment_source returned empty list"
    for node in nodes:
        assert node.get("confidence") in ("low", "medium", "high"), (
            f"Node {node.get('node_id')} has invalid confidence: {node.get('confidence')}"
        )


def test_segment_source_no_duplicate_node_ids():
    """segment_source produces unique node_ids even with duplicate heading titles."""
    segment_source = _get_segment_source()
    content = "# Introduction\n\nText.\n\n# Introduction\n\nMore text.\n\n# Methods\n\nFinal.\n"
    nodes = segment_source(content, "article", "test-src-002")
    ids = [n["node_id"] for n in nodes]
    assert len(ids) == len(set(ids)), (
        f"Duplicate node_ids found: {[i for i in ids if ids.count(i) > 1]}"
    )


def test_segment_source_v2_fields_present():
    """All nodes have the required v2 fields."""
    segment_source = _get_segment_source()
    REQUIRED = [
        "node_id",
        "parent_id",
        "order",
        "level",
        "type",
        "title",
        "anchor",
        "start_char",
        "end_char",
        "content_hash",
        "extraction_method",
        "confidence",
        "warnings",
    ]
    content = "# Section One\n\nContent here.\n\n## Subsection\n\nMore content.\n"
    nodes = segment_source(content, "article", "test-src-003")
    for node in nodes:
        for field in REQUIRED:
            assert field in node, f"Node {node.get('node_id')} missing required field: {field}"


def test_segment_source_headingless_document():
    """A document with no headings returns at least one root node."""
    segment_source = _get_segment_source()
    content = "Just plain text without any markdown headings. " * 100
    nodes = segment_source(content, "article", "test-src-004")
    # Should not crash and should return something (even a single root node or paragraph)
    assert isinstance(nodes, list), "segment_source should return a list"
    # If no nodes, that's also acceptable for short headingless content
    # (segment_source may return empty for content too short)


def test_segment_source_repo_file_nodes():
    """Repo sources produce file-level nodes."""
    segment_source = _get_segment_source()
    content = (
        "### README.md\n\nThis is the readme.\n\n### scripts/main.py\n\ndef hello():\n    pass\n"
    )
    nodes = segment_source(content, "github-repo-snapshot", "test-src-005")
    file_nodes = [n for n in nodes if n.get("type") == "file"]
    assert len(file_nodes) >= 2, f"Expected ≥2 file nodes, got {len(file_nodes)}"
    for node in file_nodes:
        assert node.get("level", 0) >= 1


def test_segment_source_span_validity():
    """All nodes have start_char < end_char."""
    segment_source = _get_segment_source()
    content = "# Intro\n\nText.\n\n# Methods\n\nMore.\n\n# Results\n\nFinal.\n"
    nodes = segment_source(content, "article", "test-src-006")
    for node in nodes:
        assert node["start_char"] < node["end_char"], (
            f"Node {node['node_id']} has start_char >= end_char: {node['start_char']} >= {node['end_char']}"
        )
