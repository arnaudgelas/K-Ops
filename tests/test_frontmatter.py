"""Tests for parse_frontmatter and dump_frontmatter."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from utils import dump_frontmatter, parse_frontmatter  # noqa: E402


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------

def test_parse_simple():
    text = "---\ntitle: Hello\ntype: note\n---\n# Body\n"
    data, body = parse_frontmatter(text)
    assert data == {"title": "Hello", "type": "note"}
    assert body == "# Body\n"


def test_parse_no_frontmatter():
    text = "# Plain document\n\nNo frontmatter here.\n"
    data, body = parse_frontmatter(text)
    assert data == {}
    assert body == text


def test_parse_empty_frontmatter():
    text = "---\n---\n# Body\n"
    data, body = parse_frontmatter(text)
    assert data == {}
    assert body == "# Body\n"


def test_parse_unicode():
    text = "---\ntitle: こんにちは\n---\nBody\n"
    data, body = parse_frontmatter(text)
    assert data["title"] == "こんにちは"


def test_parse_list_tags():
    text = "---\ntags:\n  - kb/source\n  - kb/answer\n---\nBody\n"
    data, body = parse_frontmatter(text)
    assert data["tags"] == ["kb/source", "kb/answer"]


def test_parse_dashes_in_body():
    """Frontmatter delimiter in body should not confuse the parser."""
    text = "---\ntitle: test\n---\n# Header\n\n---\n\nHR above\n"
    data, body = parse_frontmatter(text)
    assert data == {"title": "test"}
    assert "---" in body


# ---------------------------------------------------------------------------
# dump_frontmatter
# ---------------------------------------------------------------------------

def test_dump_round_trip():
    original = {"title": "Test", "type": "note", "tags": ["kb/test"]}
    dumped = dump_frontmatter(original)
    parsed, _ = parse_frontmatter(dumped + "body\n")
    assert parsed == original


def test_dump_unicode_preserved():
    data = {"title": "日本語タイトル"}
    dumped = dump_frontmatter(data)
    assert "\\u" not in dumped  # allow_unicode=True must be set
    assert "日本語タイトル" in dumped


def test_dump_wraps_in_delimiters():
    dumped = dump_frontmatter({"x": 1})
    assert dumped.startswith("---\n")
    assert dumped.endswith("\n---\n")


def test_dump_preserves_insertion_order():
    data = {"title": "A", "type": "B", "z": "C", "a": "D"}
    dumped = dump_frontmatter(data)
    keys = [line.split(":")[0] for line in dumped.splitlines() if ":" in line]
    assert keys == ["title", "type", "z", "a"]
