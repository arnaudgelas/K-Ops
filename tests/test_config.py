"""Tests for config loading and validation."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
import yaml

# Ensure the scripts/ directory is importable when running from the repo root.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def write_config(tmp_path: Path, content: str) -> Path:
    cfg = tmp_path / "kb_config.yaml"
    cfg.write_text(textwrap.dedent(content), encoding="utf-8")
    return cfg


def reload_config(config_path: Path):
    """Clear lru_cache and reload config from the given path."""
    import utils
    utils.load_config.cache_clear()
    old = os.environ.get("KB_CONFIG_PATH")
    os.environ["KB_CONFIG_PATH"] = str(config_path)
    try:
        return utils.load_config()
    finally:
        utils.load_config.cache_clear()
        if old is None:
            os.environ.pop("KB_CONFIG_PATH", None)
        else:
            os.environ["KB_CONFIG_PATH"] = old


MINIMAL_CONFIG = """
    project_name: Test
    raw_dir: data/raw
    registry_path: data/registry.json
    vault_dir: notes
    research_dir: research
    home_note: notes/Home.md
    todo_note: notes/TODO.md
    concepts_dir: notes/Concepts
    summaries_dir: notes/Sources
    answers_dir: notes/Answers
    attachments_dir: notes/Attachments
    outputs_dir: outputs
"""


def test_load_config_success(tmp_path):
    cfg_path = write_config(tmp_path, MINIMAL_CONFIG)
    config = reload_config(cfg_path)
    assert config.project_name == "Test"
    assert config.research_dir.name == "research"


def test_load_config_behavioral_defaults(tmp_path):
    cfg_path = write_config(tmp_path, MINIMAL_CONFIG)
    config = reload_config(cfg_path)
    # Defaults when keys are absent
    assert config.allow_web_fetch_during_qa is False
    assert config.file_answer_back_into_vault is True
    assert config.use_obsidian_wikilinks is True


def test_load_config_behavioral_explicit(tmp_path):
    content = MINIMAL_CONFIG + """
    allow_web_fetch_during_qa: true
    file_answer_back_into_vault: false
    use_obsidian_wikilinks: false
    """
    cfg_path = write_config(tmp_path, content)
    config = reload_config(cfg_path)
    assert config.allow_web_fetch_during_qa is True
    assert config.file_answer_back_into_vault is False
    assert config.use_obsidian_wikilinks is False


def test_load_config_missing_key_raises(tmp_path):
    # Omit research_dir
    content = """
    project_name: Test
    raw_dir: data/raw
    registry_path: data/registry.json
    vault_dir: notes
    home_note: notes/Home.md
    todo_note: notes/TODO.md
    concepts_dir: notes/Concepts
    summaries_dir: notes/Sources
    answers_dir: notes/Answers
    attachments_dir: notes/Attachments
    outputs_dir: outputs
    """
    cfg_path = write_config(tmp_path, content)
    with pytest.raises(SystemExit, match="research_dir"):
        reload_config(cfg_path)


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        reload_config(tmp_path / "nonexistent.yaml")


def test_load_config_not_a_mapping_raises(tmp_path):
    cfg_path = tmp_path / "kb_config.yaml"
    cfg_path.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not a YAML mapping"):
        reload_config(cfg_path)
