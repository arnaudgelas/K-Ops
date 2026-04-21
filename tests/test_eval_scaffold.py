"""Tests for the eval-setup / eval-check scaffolding."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
QA_GOLDEN = ROOT / "tests" / "qa_golden.yaml"


def test_qa_golden_yaml_has_required_shape():
    data = yaml.safe_load(QA_GOLDEN.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data.get("version") == "1.0"
    assert isinstance(data.get("questions"), list)
    assert data["questions"], "qa_golden.yaml should contain at least one question"
    for item in data["questions"]:
        assert isinstance(item, dict)
        assert item.get("id")
        assert item.get("question")


def test_eval_check_command_passes():
    result = subprocess.run(
        [sys.executable, "scripts/kb.py", "eval-check"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Eval check OK" in result.stdout


def test_eval_setup_is_idempotent():
    result = subprocess.run(
        [sys.executable, "scripts/kb.py", "eval-setup"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "already exists" in result.stdout
