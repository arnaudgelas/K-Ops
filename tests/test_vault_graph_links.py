"""Regression tests for aliased-wikilink extraction in vault_graph.

Before this fix, the graph link extractors did not match `[[Sources/src-x|alias]]`
(only the bare or sub-foldered form), so evidence citations written with an alias —
the vault's own convention — produced no cites_source/supported_by edge. That silently
weakened retract's blast radius, community-audit gaps, and scorecard orphan metrics.
"""

from __future__ import annotations

from kops.vault_graph import (
    EVIDENCE_SECTION_RE,
    INLINE_SOURCE_CITE_RE,
    SOURCE_LINK_RE,
    extract_section_links,
)

SID = "src-1234567890"


def _evidence(link: str) -> str:
    return f"## Evidence / Source Basis\n\n- {link}\n"


def test_section_links_match_aliased_wikilink():
    assert extract_section_links(_evidence(f"[[Sources/{SID}|{SID}]]"), EVIDENCE_SECTION_RE) == [
        SID
    ]


def test_section_links_still_match_bare_and_subfoldered():
    assert extract_section_links(_evidence(f"[[Sources/{SID}]]"), EVIDENCE_SECTION_RE) == [SID]
    assert extract_section_links(_evidence(f"[[Sources/web/{SID}]]"), EVIDENCE_SECTION_RE) == [SID]


def test_inline_cite_matches_all_forms():
    assert INLINE_SOURCE_CITE_RE.findall(f"claim ([[Sources/{SID}|{SID}]]).") == [SID]
    assert INLINE_SOURCE_CITE_RE.findall(f"claim [[Sources/{SID}]] here") == [SID]
    assert INLINE_SOURCE_CITE_RE.findall(f"[[Sources/web/{SID}#page=2|Title]]") == [SID]


def test_source_link_re_matches_aliased_wikilink():
    assert SOURCE_LINK_RE.findall(f"- [[Sources/{SID}|{SID}]]") == [SID]


def test_inline_cite_ignores_non_source_wikilinks():
    assert INLINE_SOURCE_CITE_RE.findall("[[Concepts/Foo|Foo]] and [[Home]]") == []
