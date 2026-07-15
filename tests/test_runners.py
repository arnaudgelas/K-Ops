"""Tests for the three execution roles introduced in roadmap task S0.2."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from kops import kb_runtime, runners


# --------------------------------------------------------------------------- #
# Helpers: write throwaway provider stub scripts and point KB_JUDGE_CMD at them
# --------------------------------------------------------------------------- #


def _write_stub(tmp_path: Path, name: str, body: str) -> str:
    """Write a python stub script and return a ``KB_*_CMD`` invocation string."""
    script = tmp_path / name
    script.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    return f"{sys.executable} {script}"


VALID_JUDGE_STUB = """
import json, os, sys
# Prove confinement: attempt a write in the (temp) cwd and report where we are.
open("JUDGE_WAS_HERE", "w").write("marker")
print(json.dumps({"label": "supported", "confidence": 0.9, "cwd": os.getcwd()}))
"""

SCHEMA_JUDGE = {
    "required": ["label", "confidence"],
    "properties": {
        "label": {"type": "string", "enum": ["supported", "refuted", "unclear"]},
        "confidence": {"type": "number"},
    },
}


# --------------------------------------------------------------------------- #
# Judge role
# --------------------------------------------------------------------------- #


def test_judge_run_cannot_alter_repo(tmp_path, monkeypatch):
    cmd = _write_stub(tmp_path, "judge_ok.py", VALID_JUDGE_STUB)
    monkeypatch.setenv("KB_JUDGE_CMD", cmd)
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")

    result = runners.judge_run("Does the quote support the claim?", SCHEMA_JUDGE)

    # Verdict validated and returned.
    assert result.verdict["label"] == "supported"
    # It executed in a throwaway temp dir, never the repo root.
    reported_cwd = Path(result.verdict["cwd"]).resolve()
    assert reported_cwd != Path.cwd().resolve()
    assert str(reported_cwd).startswith(str(Path(tempfile.gettempdir()).resolve()))
    # The marker the stub wrote landed in the confined dir and was cleaned up;
    # it never touched the repository working tree.
    assert not (Path.cwd() / "JUDGE_WAS_HERE").exists()
    assert not reported_cwd.exists()  # temp dir removed after the run


def test_judge_records_prompt_and_model_fingerprint(tmp_path, monkeypatch):
    cmd = _write_stub(tmp_path, "judge_ok.py", VALID_JUDGE_STUB)
    monkeypatch.setenv("KB_JUDGE_CMD", cmd)
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")

    r1 = runners.judge_run("same prompt", SCHEMA_JUDGE)
    r2 = runners.judge_run("same prompt", SCHEMA_JUDGE)
    r3 = runners.judge_run("different prompt", SCHEMA_JUDGE)

    assert len(r1.fingerprint) == 64  # sha256 hexdigest
    assert r1.fingerprint == r2.fingerprint  # deterministic for same prompt+provider
    assert r1.fingerprint != r3.fingerprint  # prompt change changes fingerprint


def test_judge_parse_failure_raises(tmp_path, monkeypatch):
    cmd = _write_stub(tmp_path, "judge_bad.py", "print('not json at all')\n")
    monkeypatch.setenv("KB_JUDGE_CMD", cmd)
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")

    with pytest.raises(runners.JudgeError):
        runners.judge_run("prompt", SCHEMA_JUDGE)


def test_judge_schema_failure_raises(tmp_path, monkeypatch):
    # Missing required 'confidence' and invalid enum value.
    body = "import json\nprint(json.dumps({'label': 'maybe'}))\n"
    cmd = _write_stub(tmp_path, "judge_schema.py", body)
    monkeypatch.setenv("KB_JUDGE_CMD", cmd)
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")

    with pytest.raises(runners.JudgeError):
        runners.judge_run("prompt", SCHEMA_JUDGE)


def test_judge_enforces_timeout(tmp_path, monkeypatch):
    body = "import time\ntime.sleep(5)\nprint('{}')\n"
    cmd = _write_stub(tmp_path, "judge_slow.py", body)
    monkeypatch.setenv("KB_JUDGE_CMD", cmd)
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")

    with pytest.raises(runners.JudgeError, match="timeout"):
        runners.judge_run("prompt", SCHEMA_JUDGE, timeout=1)


def test_judge_enforces_output_bound(tmp_path, monkeypatch):
    body = "print('x' * 100000)\n"
    cmd = _write_stub(tmp_path, "judge_big.py", body)
    monkeypatch.setenv("KB_JUDGE_CMD", cmd)
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")

    with pytest.raises(runners.JudgeError, match="output"):
        runners.judge_run("prompt", SCHEMA_JUDGE, max_output_bytes=1000)


def test_judge_enforces_input_bound(tmp_path, monkeypatch):
    cmd = _write_stub(tmp_path, "judge_ok.py", VALID_JUDGE_STUB)
    monkeypatch.setenv("KB_JUDGE_CMD", cmd)
    monkeypatch.setenv("KB_JUDGE_AGENT", "codex")

    with pytest.raises(runners.JudgeError, match="input"):
        runners.judge_run("x" * 5000, SCHEMA_JUDGE, max_input_bytes=1000)


# --------------------------------------------------------------------------- #
# Independent configurability
# --------------------------------------------------------------------------- #


def test_judge_and_generator_independently_configurable(monkeypatch):
    monkeypatch.setenv("KB_CODEX_CMD", "generator-cli --generate")
    monkeypatch.setenv("KB_JUDGE_CMD", "judge-cli --classify")

    generator_cmd = runners.detect_agent_command("codex")
    judge_cmd = runners.resolve_judge_command("codex")

    assert generator_cmd == ["generator-cli", "--generate"]
    assert judge_cmd == ["judge-cli", "--classify"]
    assert generator_cmd != judge_cmd


def test_judge_agent_configurable_independently(monkeypatch):
    monkeypatch.delenv("KB_JUDGE_AGENT", raising=False)
    assert runners.resolve_judge_agent() == "codex"
    monkeypatch.setenv("KB_JUDGE_AGENT", "claude")
    assert runners.resolve_judge_agent() == "claude"
    # An explicit argument still overrides the env default.
    assert runners.resolve_judge_agent("gemini") == "gemini"


# --------------------------------------------------------------------------- #
# Generator roles: read-only must not grant write-oriented flags
# --------------------------------------------------------------------------- #


def test_readonly_generator_omits_full_auto(tmp_path):
    prompt = tmp_path / "p.md"
    prompt.write_text("hello", encoding="utf-8")
    cmd = runners.build_generator_command("codex", ["codex"], prompt, "hello", full_auto=False)
    assert "--full-auto" not in cmd


def test_mutating_generator_grants_full_auto(tmp_path):
    prompt = tmp_path / "p.md"
    prompt.write_text("hello", encoding="utf-8")
    cmd = runners.build_generator_command("codex", ["codex"], prompt, "hello", full_auto=True)
    assert "--full-auto" in cmd


# --------------------------------------------------------------------------- #
# Git checkpoints around mutating runs
# --------------------------------------------------------------------------- #


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_mutating_run_produces_before_after_git_record(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    monkeypatch.setattr(kb_runtime, "ROOT", repo)

    prompt = repo / "prompt.md"
    prompt.write_text("do work", encoding="utf-8")

    def fake_agent_run(agent, prompt_path):
        # Simulate a mutating write into the repo working tree.
        (repo / "new_note.md").write_text("written by agent\n", encoding="utf-8")

    monkeypatch.setattr(kb_runtime, "agent_run", fake_agent_run)

    record = kb_runtime.mutating_agent_run("codex", prompt)

    assert isinstance(record, runners.GitCheckpoint)
    assert record.is_repo is True
    assert record.changed is True
    assert "new_note.md" in record.porcelain_after
    assert "new_note.md" not in record.porcelain_before
    # The before/after record is persisted and recoverable.
    persisted = list((repo / ".tmp").glob("mutating_run_record.*.json"))
    assert persisted, "expected a persisted git record under .tmp/"


def test_mutating_run_handles_non_git_dir(tmp_path, monkeypatch):
    non_repo = tmp_path / "plain"
    non_repo.mkdir()
    monkeypatch.setattr(kb_runtime, "ROOT", non_repo)

    prompt = non_repo / "prompt.md"
    prompt.write_text("do work", encoding="utf-8")
    monkeypatch.setattr(kb_runtime, "agent_run", lambda a, p: None)

    record = kb_runtime.mutating_agent_run("codex", prompt)
    assert record.is_repo is False
    assert record.changed is False
