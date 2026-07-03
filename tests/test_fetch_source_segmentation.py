"""Tests for large-source segmentation metadata."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_sources import segment_source  # noqa: E402


def test_segment_source_confidence_field():
    content = "# Introduction\n\nSome text.\n\n## Methods\n\nMore text.\n"
    nodes = segment_source(content, "article", "test-src-001")
    assert nodes
    for node in nodes:
        assert node.get("confidence") in ("low", "medium", "high")


def test_segment_source_no_duplicate_node_ids():
    content = "# Introduction\n\nText.\n\n# Introduction\n\nMore text.\n\n# Methods\n\nFinal.\n"
    nodes = segment_source(content, "article", "test-src-002")
    ids = [node["node_id"] for node in nodes]
    assert len(ids) == len(set(ids))


def test_segment_source_v2_fields_present():
    required = {
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
    }
    content = "# Section One\n\nContent here.\n\n## Subsection\n\nMore content.\n"
    nodes = segment_source(content, "article", "test-src-003")
    for node in nodes:
        assert required <= set(node)


def test_segment_source_headingless_document_returns_list():
    content = "Just plain text without any markdown headings. " * 100
    nodes = segment_source(content, "article", "test-src-004")
    assert isinstance(nodes, list)


def test_segment_source_repo_file_nodes():
    content = (
        "### README.md\n\nThis is the readme.\n\n### scripts/main.py\n\ndef hello():\n    pass\n"
    )
    nodes = segment_source(content, "github-repo-snapshot", "test-src-005")
    file_nodes = [node for node in nodes if node.get("type") == "file"]
    assert len(file_nodes) >= 2
    for node in file_nodes:
        assert node.get("level", 0) >= 1


def test_segment_source_span_validity():
    content = "# Intro\n\nText.\n\n# Methods\n\nMore.\n\n# Results\n\nFinal.\n"
    nodes = segment_source(content, "article", "test-src-006")
    for node in nodes:
        assert node["start_char"] < node["end_char"]
