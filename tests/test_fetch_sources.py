"""Tests for fetch_sources.py utilities."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_sources import (  # noqa: E402
    clean_article_text,
    extract_html_text,
    is_url,
    read_input_list,
    strip_tracking_parameters as remove_tracking_params,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# is_url
# ---------------------------------------------------------------------------

def test_is_url_http():
    assert is_url("http://example.com") is True


def test_is_url_https():
    assert is_url("https://example.com/path?q=1") is True


def test_is_url_local_path():
    assert is_url("/some/local/file.txt") is False


def test_is_url_relative():
    assert is_url("relative/path") is False


# ---------------------------------------------------------------------------
# remove_tracking_params
# ---------------------------------------------------------------------------

def test_remove_utm_params():
    url = "https://example.com/article?utm_source=twitter&utm_medium=social&id=42"
    cleaned = remove_tracking_params(url)
    assert "utm_source" not in cleaned
    assert "utm_medium" not in cleaned
    assert "id=42" in cleaned


def test_remove_fbclid():
    url = "https://example.com/?fbclid=abc123&page=1"
    cleaned = remove_tracking_params(url)
    assert "fbclid" not in cleaned
    assert "page=1" in cleaned


def test_no_tracking_params_unchanged():
    url = "https://example.com/article?q=search&page=2"
    assert remove_tracking_params(url) == url


# ---------------------------------------------------------------------------
# read_input_list
# ---------------------------------------------------------------------------

def test_read_input_list_skips_comments_and_blanks(tmp_path):
    f = tmp_path / "sources.txt"
    f.write_text("# comment\n\nhttps://a.com\n  https://b.com  \n# another\n", encoding="utf-8")
    items = read_input_list(f)
    assert items == ["https://a.com", "https://b.com"]


# ---------------------------------------------------------------------------
# extract_html_text — using the fixture
# ---------------------------------------------------------------------------

def test_extract_html_text_returns_string():
    fixture = FIXTURE_DIR / "medium_substack_article.html"
    html = fixture.read_text(encoding="utf-8")
    result = extract_html_text(html, "https://example.substack.com/p/article")
    assert isinstance(result, str)
    assert len(result) > 0


def test_extract_html_text_strips_boilerplate():
    fixture = FIXTURE_DIR / "medium_substack_article.html"
    html = fixture.read_text(encoding="utf-8")
    result = extract_html_text(html, "https://example.substack.com/p/article")
    # Should not contain raw script/style content
    assert "<script" not in result
    assert "<style" not in result


# ---------------------------------------------------------------------------
# clean_article_text
# ---------------------------------------------------------------------------

def test_clean_article_text_removes_subscribe_lines():
    text = "Interesting paragraph.\n\nSubscribe\n\nAnother paragraph."
    cleaned = clean_article_text(text)
    assert "Subscribe" not in cleaned
    assert "Interesting paragraph." in cleaned


def test_clean_article_text_no_strip_needed():
    text = "Normal content\n\nMore normal content\n"
    assert clean_article_text(text).strip()
