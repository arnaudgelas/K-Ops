from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kops.lint_vault as lint_vault  # noqa: E402


class LintVaultTests(unittest.TestCase):
    def test_key_claim_direct_citation_stats(self) -> None:
        text = (
            "## Key Claims\n\n"
            "- Direct claim ([[Sources/src-1111111111|source]]).\n"
            "- Anchored claim src-2222222222#page=12.\n"
            "- Missing claim.\n"
        )
        direct, total, source_ids = lint_vault.key_claim_direct_citation_stats(text)
        self.assertEqual(direct, 2)
        self.assertEqual(total, 3)
        self.assertEqual(source_ids, {"src-1111111111", "src-2222222222"})

    def test_collect_findings_on_minimal_vault(self) -> None:
        original = {
            "ROOT": lint_vault.ROOT,
            "REGISTRY_PATH": lint_vault.REGISTRY_PATH,
            "RAW_DIR": lint_vault.RAW_DIR,
            "SOURCES_DIR": lint_vault.SOURCES_DIR,
            "ANSWERS_DIR": lint_vault.ANSWERS_DIR,
            "CONCEPTS_DIR": lint_vault.CONCEPTS_DIR,
            "INDEXES_DIR": lint_vault.INDEXES_DIR,
            "HOME_PATH": lint_vault.HOME_PATH,
            "RESEARCH_DIR": lint_vault.RESEARCH_DIR,
            "RESEARCH_NOTES_DIR": lint_vault.RESEARCH_NOTES_DIR,
            "RESEARCH_BRIEFS_DIR": lint_vault.RESEARCH_BRIEFS_DIR,
            "RESEARCH_FINDINGS_DIR": lint_vault.RESEARCH_FINDINGS_DIR,
            "RESEARCH_REPORTS_DIR": lint_vault.RESEARCH_REPORTS_DIR,
            "RESEARCH_IMPORTS_DIR": lint_vault.RESEARCH_IMPORTS_DIR,
            "RESEARCH_ARCHIVE_DIR": lint_vault.RESEARCH_ARCHIVE_DIR,
        }
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_root = Path(tmpdir)
                notes_dir = tmp_root / "notes"
                raw_dir = tmp_root / "data" / "raw"
                research_dir = tmp_root / "research"
                for path in [
                    notes_dir / "Concepts",
                    notes_dir / "Sources",
                    notes_dir / "Answers",
                    notes_dir / "Indexes",
                    raw_dir,
                    research_dir / "notes",
                    research_dir / "briefs",
                    research_dir / "findings",
                    research_dir / "reports",
                    research_dir / "imports",
                    research_dir / "archive",
                ]:
                    path.mkdir(parents=True, exist_ok=True)

                (tmp_root / "data" / "registry.json").write_text("[]\n", encoding="utf-8")
                minimal_home = (
                    "---\ntitle: Home\ntype: home\ntags:\n  - kb/home\n---\n"
                    "# Home\n\n"
                    "[[Indexes/Vault_Dashboard]]\n"
                    "[[Indexes/Workflow_Atlas]]\n"
                    "[[Indexes/Topic_Atlas]]\n"
                    "[[Runbooks/Agent_Workflow_Quick_Reference]]\n"
                    "[[TODO]]\n"
                )
                (notes_dir / "Home.md").write_text(minimal_home, encoding="utf-8")

                lint_vault.ROOT = tmp_root
                lint_vault.REGISTRY_PATH = tmp_root / "data" / "registry.json"
                lint_vault.RAW_DIR = raw_dir
                lint_vault.SOURCES_DIR = notes_dir / "Sources"
                lint_vault.ANSWERS_DIR = notes_dir / "Answers"
                lint_vault.CONCEPTS_DIR = notes_dir / "Concepts"
                lint_vault.INDEXES_DIR = notes_dir / "Indexes"
                lint_vault.HOME_PATH = notes_dir / "Home.md"
                lint_vault.RESEARCH_DIR = research_dir
                lint_vault.RESEARCH_NOTES_DIR = research_dir / "notes"
                lint_vault.RESEARCH_BRIEFS_DIR = research_dir / "briefs"
                lint_vault.RESEARCH_FINDINGS_DIR = research_dir / "findings"
                lint_vault.RESEARCH_REPORTS_DIR = research_dir / "reports"
                lint_vault.RESEARCH_IMPORTS_DIR = research_dir / "imports"
                lint_vault.RESEARCH_ARCHIVE_DIR = research_dir / "archive"

                findings = lint_vault.collect_findings(strict=False)
                self.assertEqual(findings, [])
        finally:
            for name, value in original.items():
                setattr(lint_vault, name, value)


if __name__ == "__main__":
    unittest.main()
