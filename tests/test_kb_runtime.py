"""Tests for agent runtime prompt plumbing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kb_runtime  # noqa: E402
import retrieval  # noqa: E402


class _FakeVaultIndex:
    def build(self) -> None:
        return None

    def search(self, query: str, top_k: int = 8) -> list[dict]:
        assert query == "workflow pattern"
        assert top_k == 8
        return [
            {
                "id": "Workflow_Pattern_Inventory",
                "kind": "concept",
                "title": "Workflow Pattern Inventory",
                "score": 1.25,
                "retrieval_method": "bm25",
                "path": "notes/Concepts/Workflow_Pattern_Inventory.md",
                "snippet": "A catalog of workflow patterns.",
            }
        ]


def test_build_ask_retrieval_context_includes_seed_results(monkeypatch):
    monkeypatch.setattr(retrieval, "VaultIndex", _FakeVaultIndex)

    context = kb_runtime.build_ask_retrieval_context("workflow pattern")

    assert "Seed retrieval was run before agent handoff" in context
    assert "Workflow_Pattern_Inventory" in context
    assert "notes/Concepts/Workflow_Pattern_Inventory.md" in context
    assert "method=bm25" in context
    assert "results_count=1" in context


def test_compile_plan_is_written_from_registry(tmp_path, monkeypatch):
    registry_path = tmp_path / "data" / "registry.json"
    summaries_dir = tmp_path / "notes" / "Sources"
    registry_path.parent.mkdir(parents=True)
    summaries_dir.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            [
                {"id": "src-1111111111"},
                {"id": "src-2222222222", "prompt_injection_detected": True},
                {"id": "src-3333333333"},
            ]
        ),
        encoding="utf-8",
    )
    (summaries_dir / "src-3333333333.md").write_text("---\n---\n", encoding="utf-8")
    monkeypatch.setattr(
        kb_runtime,
        "CONFIG",
        type("C", (), {"registry_path": registry_path, "summaries_dir": summaries_dir})(),
    )
    monkeypatch.setattr(kb_runtime, "ROOT", tmp_path)

    summary = kb_runtime._build_compile_plan_summary()
    plan = json.loads((tmp_path / ".tmp" / "compile_plan.json").read_text(encoding="utf-8"))

    assert "Deterministic compile plan written" in summary
    assert plan["to_summarize"] == ["src-1111111111"]
    assert plan["skip"] == ["src-3333333333"]
    assert plan["flag_for_review"] == [
        {"id": "src-2222222222", "reasons": ["prompt_injection_detected"]}
    ]


def test_cmd_ask_injects_retrieval_context(tmp_path, monkeypatch):
    answers_dir = tmp_path / "notes" / "Answers"
    answers_dir.mkdir(parents=True)
    captured_kwargs: dict[str, str] = {}

    monkeypatch.setattr(kb_runtime, "ROOT", tmp_path)
    monkeypatch.setattr(
        kb_runtime,
        "CONFIG",
        type(
            "C",
            (),
            {
                "answers_dir": answers_dir,
                "allow_web_fetch_during_qa": False,
                "file_answer_back_into_vault": False,
            },
        )(),
    )
    monkeypatch.setattr(kb_runtime, "build_ask_retrieval_context", lambda question: "seed context")

    def fake_build_prompt(template_name: str, **kwargs: str) -> Path:
        assert template_name == "ask_prompt.md"
        captured_kwargs.update(kwargs)
        prompt_path = tmp_path / ".tmp" / "ask.md"
        prompt_path.parent.mkdir()
        prompt_path.write_text("prompt", encoding="utf-8")
        return prompt_path

    def fake_agent_run(agent: str, prompt_path: Path) -> None:
        answer_path = next(answers_dir.glob("*.md"))
        answer_text = answer_path.read_text(encoding="utf-8")
        answer_text = answer_text.replace(
            "retrieval_path: []",
            "\n".join(
                [
                    "retrieval_path:",
                    "  - method: bm25",
                    "    layer: concept",
                    "    query: workflow pattern",
                    "    results_count: 1",
                ]
            ),
        )
        answer_text = answer_text.replace(kb_runtime.ANSWER_PLACEHOLDER, "## Summary\n\nAnswered.")
        answer_path.write_text(answer_text, encoding="utf-8")

    monkeypatch.setattr(kb_runtime, "build_prompt", fake_build_prompt)
    monkeypatch.setattr(kb_runtime, "agent_run", fake_agent_run)

    kb_runtime.cmd_ask("claude", "workflow pattern")

    assert captured_kwargs["retrieval_context"] == "seed context"
    assert captured_kwargs["web_fetch_policy"] == "disabled"


def test_cmd_ask_rejects_missing_retrieval_path(tmp_path, monkeypatch):
    answers_dir = tmp_path / "notes" / "Answers"
    answers_dir.mkdir(parents=True)

    monkeypatch.setattr(kb_runtime, "ROOT", tmp_path)
    monkeypatch.setattr(
        kb_runtime,
        "CONFIG",
        type(
            "C",
            (),
            {
                "answers_dir": answers_dir,
                "allow_web_fetch_during_qa": False,
                "file_answer_back_into_vault": False,
            },
        )(),
    )
    monkeypatch.setattr(kb_runtime, "build_ask_retrieval_context", lambda question: "seed context")

    def fake_build_prompt(template_name: str, **kwargs: str) -> Path:
        prompt_path = tmp_path / ".tmp" / "ask.md"
        prompt_path.parent.mkdir()
        prompt_path.write_text("prompt", encoding="utf-8")
        return prompt_path

    def fake_agent_run(agent: str, prompt_path: Path) -> None:
        answer_path = next(answers_dir.glob("*.md"))
        answer_text = answer_path.read_text(encoding="utf-8")
        answer_path.write_text(
            answer_text.replace(kb_runtime.ANSWER_PLACEHOLDER, "## Summary\n\nAnswered."),
            encoding="utf-8",
        )

    monkeypatch.setattr(kb_runtime, "build_prompt", fake_build_prompt)
    monkeypatch.setattr(kb_runtime, "agent_run", fake_agent_run)

    try:
        kb_runtime.cmd_ask("claude", "workflow pattern")
    except RuntimeError as exc:
        assert "retrieval_path" in str(exc)
    else:
        raise AssertionError("cmd_ask should reject answer memos without retrieval_path provenance")
