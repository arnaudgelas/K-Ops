"""Tests for lint_vault.py against a synthetic minimal vault."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def make_vault(tmp_path: Path) -> dict[str, Path]:
    """Create the directory skeleton that lint_vault expects."""
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    registry = tmp_path / "data" / "registry.json"
    registry.write_text("[]", encoding="utf-8")

    notes = tmp_path / "notes"
    concepts = notes / "Concepts"
    sources = notes / "Sources"
    answers = notes / "Answers"
    for d in (concepts, sources, answers):
        d.mkdir(parents=True)

    home = notes / "Home.md"
    home.write_text(
        "---\ntitle: Home\ntype: home\n---\n# Home\n",
        encoding="utf-8",
    )
    return {
        "raw": raw,
        "registry": registry,
        "notes": notes,
        "concepts": concepts,
        "sources": sources,
        "answers": answers,
        "home": home,
    }


def _patch_lint_vault(lint_vault_mod, vault: dict) -> None:
    """Directly patch lint_vault module-level path constants to point at tmp vault."""
    lint_vault_mod.REGISTRY_PATH = vault["registry"]
    lint_vault_mod.RAW_DIR = vault["raw"]
    lint_vault_mod.SOURCES_DIR = vault["sources"]
    lint_vault_mod.CONCEPTS_DIR = vault["concepts"]
    lint_vault_mod.ANSWERS_DIR = vault["answers"]
    lint_vault_mod.HOME_PATH = vault["home"]
    lint_vault_mod.RESEARCH_DIR = vault["notes"].parent / "research"
    lint_vault_mod.RESEARCH_NOTES_DIR = lint_vault_mod.RESEARCH_DIR / "notes"
    lint_vault_mod.RESEARCH_BRIEFS_DIR = lint_vault_mod.RESEARCH_DIR / "briefs"
    lint_vault_mod.RESEARCH_FINDINGS_DIR = lint_vault_mod.RESEARCH_DIR / "findings"
    lint_vault_mod.RESEARCH_REPORTS_DIR = lint_vault_mod.RESEARCH_DIR / "reports"
    lint_vault_mod.RESEARCH_IMPORTS_DIR = lint_vault_mod.RESEARCH_DIR / "imports"
    lint_vault_mod.RESEARCH_ARCHIVE_DIR = lint_vault_mod.RESEARCH_DIR / "archive"


def test_empty_vault_no_findings(tmp_path):
    """An empty but structurally valid vault should produce no errors."""
    vault = make_vault(tmp_path)
    import lint_vault
    _patch_lint_vault(lint_vault, vault)

    findings = lint_vault.collect_findings(strict=False)
    errors = [f for f in findings if f.severity == "error"]
    assert errors == [], f"Unexpected errors: {[f.message for f in errors]}"


def test_orphan_raw_dir_produces_warning(tmp_path):
    vault = make_vault(tmp_path)
    # Add a raw dir without a registry entry
    (vault["raw"] / "src-deadbeef01").mkdir()

    import lint_vault
    _patch_lint_vault(lint_vault, vault)

    findings = lint_vault.collect_findings(strict=False)
    codes = {f.code for f in findings}
    assert "orphan-raw-dir" in codes
