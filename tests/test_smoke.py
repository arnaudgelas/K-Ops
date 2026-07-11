"""Smoke tests for kb.py CLI subcommands."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kops.kb"] + args,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_validate_exits_zero():
    result = _run(["validate"])
    assert result.returncode == 0, f"validate failed:\n{result.stderr}"


def test_add_help_exits_zero():
    result = _run(["add", "--help"])
    assert result.returncode == 0, f"add --help failed:\n{result.stderr}"
    assert "Ingest one URL" in result.stdout


def test_validate_strict_exits_zero():
    result = _run(["validate", "--strict"])
    assert result.returncode == 0, f"validate --strict failed:\n{result.stderr}"


def test_lint_exits_zero():
    result = _run(["lint"])
    assert result.returncode == 0, f"lint failed:\n{result.stderr}"


def test_lint_strict_exits_zero():
    result = _run(["lint", "--strict"])
    assert result.returncode == 0, f"lint --strict failed:\n{result.stderr}"


def test_compile_show_prompt_exits_zero():
    result = _run(["compile", "--agent", "claude", "--show-prompt"])
    assert result.returncode == 0, f"compile --show-prompt failed:\n{result.stderr}"
    assert len(result.stdout) > 0, "compile --show-prompt produced no output"


def test_heal_show_prompt_exits_zero():
    result = _run(["heal", "--agent", "claude", "--show-prompt"])
    assert result.returncode == 0, f"heal --show-prompt failed:\n{result.stderr}"
    assert len(result.stdout) > 0, "heal --show-prompt produced no output"


def test_fetch_queue_exits_zero():
    result = _run(["fetch-queue", "--format", "text"])
    assert result.returncode == 0, f"fetch-queue failed:\n{result.stderr}"


def test_scorecard_exits_zero():
    result = _run(["scorecard"])
    assert result.returncode == 0, f"scorecard failed:\n{result.stderr}"


def test_claim_map_exits_zero():
    result = _run(["claim-map", "--concept", "Workflow_Pattern_Inventory"])
    assert result.returncode == 0, f"claim-map failed:\n{result.stderr}"
    assert "graph TD" in result.stdout, "claim-map produced no Mermaid output"
