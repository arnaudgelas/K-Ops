from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_sources import clean_article_text, extract_html_text, strip_tracking_parameters  # noqa: E402


class FetchSourcesTests(unittest.TestCase):
    def test_strip_tracking_parameters(self) -> None:
        url = "https://example.com/story?utm_source=newsletter&ref=home&fbclid=abc123"
        self.assertEqual(strip_tracking_parameters(url), "https://example.com/story?ref=home")

    def test_clean_article_text_removes_boilerplate_lines(self) -> None:
        text = "First line\n\nSubscribe\n\nSecond line\nRead more from the author\n"
        self.assertEqual(clean_article_text(text), "First line\n\nSecond line")

    def test_extract_html_text_uses_article_body(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "medium_substack_article.html"
        raw_html = fixture.read_text(encoding="utf-8")
        extracted = extract_html_text(
            raw_html, "https://example.substack.com/p/story?utm_source=feed"
        )
        self.assertIn("Real article body paragraph one.", extracted)
        self.assertIn("Real article body paragraph two.", extracted)

    def test_large_source_segmenting_and_manifest(self) -> None:
        import tempfile
        import shutil
        import json
        from fetch_sources import ingest_one

        # Create a large text file (so normalized_content becomes exactly 15,000 chars with newline)
        large_content = "A" * 14999

        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(large_content)
            tmp_path = Path(tmp.name)

        try:
            # Ingest the file
            metadata = ingest_one(str(tmp_path))
            source_id = metadata["id"]
            source_dir = ROOT / "data" / "raw" / source_id

            # Verify the manifest exists
            manifest_path = source_dir / "large_source_manifest.json"
            self.assertTrue(manifest_path.exists())

            # Read manifest
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIsNone(manifest["page_count"])
            self.assertEqual(manifest["text_extraction_coverage"], 100.0)

            # Verify chunk parts exist and have correct overlap
            # 15,000 characters split with 10,000 window and 1,000 overlap:
            # Chunk 1: [0:10000] (len 10000)
            # Chunk 2: [9000:15000] (len 6000)
            chunks = manifest["page_level_chunks"]
            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0]["length"], 10000)
            self.assertEqual(chunks[1]["length"], 6000)

            part1_path = ROOT / chunks[0]["path"]
            part2_path = ROOT / chunks[1]["path"]
            self.assertTrue(part1_path.exists())
            self.assertTrue(part2_path.exists())

            part1_content = part1_path.read_text(encoding="utf-8")
            part2_content = part2_path.read_text(encoding="utf-8")
            self.assertEqual(part1_content, "A" * 10000)
            self.assertEqual(part2_content, ("A" * 5999) + "\n")

            # Clean up raw files
            shutil.rmtree(source_dir)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_extract_html_bibliographic_metadata(self) -> None:
        from fetch_sources import extract_html_bibliographic_metadata

        html = """
        <html>
          <head>
            <meta name="citation_title" content="A Great Title">
            <meta name="citation_author" content="Alice Smith">
            <meta name="citation_author" content="Bob Jones">
            <meta name="citation_doi" content="10.1234/5678">
            <meta name="citation_publication_date" content="2023/11/05">
            <meta name="citation_journal_title" content="Journal of Knowledge Base Maintenance">
          </head>
          <body>
            Text
          </body>
        </html>
        """
        meta = extract_html_bibliographic_metadata(html)
        self.assertEqual(meta["author"], "Alice Smith, Bob Jones")
        self.assertEqual(meta["doi"], "10.1234/5678")
        self.assertEqual(meta["year"], 2023)
        self.assertEqual(meta["journal"], "Journal of Knowledge Base Maintenance")

    def test_process_large_source_html_diagnostics(self) -> None:
        import shutil
        from fetch_sources import process_large_source

        large_content = "A" * 12000
        html = f"""
        <html>
          <head>
            <meta name="citation_doi" content="10.1234/5678">
          </head>
          <body>
            <p>{large_content}</p>
            <img src="fig1.png">
            <table><tr><td>cell</td></tr></table>
            <figure><img src="fig2.png"></figure>
          </body>
        </html>
        """

        source_id = "src-htmltest"
        source_dir = ROOT / "data" / "raw" / source_id
        source_dir.mkdir(parents=True, exist_ok=True)

        try:
            manifest = process_large_source(
                normalized_content=large_content,
                source_dir=source_dir,
                source_id=source_id,
                is_pdf=False,
                raw_html=html,
            )
            self.assertIsNotNone(manifest)
            self.assertEqual(
                manifest["figures_tables_status"]["figures"]["count"], 3
            )  # 2 img, 1 figure tag
            self.assertEqual(manifest["figures_tables_status"]["tables"]["count"], 1)
            self.assertEqual(manifest["bibliographic_metadata"]["doi"], "10.1234/5678")
        finally:
            shutil.rmtree(source_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
