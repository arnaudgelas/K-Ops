from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import utils  # noqa: E402


class UtilsTests(unittest.TestCase):
    def test_dump_frontmatter_round_trips_unicode(self) -> None:
        data = {"title": "Café, 東京", "tags": ["naïve", "résumé"]}
        rendered = utils.dump_frontmatter(data)
        self.assertIn("Café, 東京", rendered)
        parsed, body = utils.parse_frontmatter(rendered + "body\n")
        self.assertEqual(parsed, data)
        self.assertEqual(body, "body\n")

    def test_load_config_can_read_alternate_config_path(self) -> None:
        original_config_path = utils.CONFIG_PATH
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                config_path = tmp_path / "kb_config.yaml"
                config_path.write_text(
                    "\n".join(
                        [
                            "project_name: temp",
                            "raw_dir: data/raw",
                            "registry_path: data/registry.json",
                            "vault_dir: notes",
                            "research_dir: research",
                            "home_note: notes/Home.md",
                            "todo_note: notes/TODO.md",
                            "concepts_dir: notes/Concepts",
                            "summaries_dir: notes/Sources",
                            "answers_dir: notes/Answers",
                            "attachments_dir: attachments",
                            "outputs_dir: outputs",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                utils.CONFIG_PATH = config_path
                utils.load_config.cache_clear()
                loaded = utils.load_config()
                self.assertEqual(loaded.project_name, "temp")
                self.assertEqual(loaded.research_dir.name, "research")
        finally:
            utils.CONFIG_PATH = original_config_path
            utils.load_config.cache_clear()


if __name__ == "__main__":
    unittest.main()
