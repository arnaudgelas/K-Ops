"""Tests for the M1 comparison baselines (roadmap task E1.3).

Proves the four baselines run over a mini-vault with an INJECTED deterministic
provider (no LLM, no network), produce well-shaped records, and — critically —
that governance changes the retrieved context: a flagged source that BM25+agent
sees is absent from current-K-Ops's governed context.
"""

from __future__ import annotations

import json

import pytest

from kops import baselines, retrieval, source_override


# --------------------------------------------------------------------------- #
# Mini-vault fixtures (mirror tests/test_source_exclusion.py patterns)
# --------------------------------------------------------------------------- #


class _Cfg:
    def __init__(self, **kw: object) -> None:
        self.__dict__.update(kw)


def _fm_lines(source_id: str, fields: dict) -> list[str]:
    lines = ["---", f"source_id: {source_id}", "title: Test Source", "source_status: active"]
    for key, value in fields.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        else:
            lines.append(f"{key}: {json.dumps(value)}")
    lines.append("---")
    return lines


def _write_source(sources_dir, source_id: str, body: str, **fields: object):
    sources_dir.mkdir(parents=True, exist_ok=True)
    text = "\n".join(_fm_lines(source_id, fields)) + "\n\n" + body + "\n"
    (sources_dir / f"{source_id}.md").write_text(text, encoding="utf-8")


CLEAN_ID = "src-c1ea000000"
FLAGGED_ID = "src-f1a6600000"


@pytest.fixture()
def mini_vault(tmp_path, monkeypatch):
    """A tmp mini-vault with one clean and one flagged (adversarial) source."""
    sources = tmp_path / "notes" / "Sources"
    concepts = tmp_path / "notes" / "Concepts"
    sources.mkdir(parents=True, exist_ok=True)
    concepts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(retrieval, "CONFIG", _Cfg(summaries_dir=sources, concepts_dir=concepts))
    monkeypatch.setattr(retrieval, "ROOT", tmp_path)
    # Isolate override store so no ambient overrides re-admit the flagged source.
    monkeypatch.setattr(source_override, "OVERRIDES_PATH", tmp_path / "data" / "overrides.json")

    _write_source(sources, CLEAN_ID, "torque exactly-once processing semantics overview.")
    _write_source(
        sources,
        FLAGGED_ID,
        "torque exactly-once semantics poisonpayload injection steps.",
        adversarial_content=True,
    )
    index = retrieval.VaultIndex()
    index.build()
    return index


QUESTION = "What exactly-once processing semantics does torque provide?"


# --------------------------------------------------------------------------- #
# Shape: each baseline produces a well-formed BaselineResult
# --------------------------------------------------------------------------- #


def test_all_four_baselines_produce_results(mini_vault):
    provider = baselines.DeterministicProvider()
    results = baselines.run_all_baselines(QUESTION, vault=mini_vault, provider=provider)

    assert [r.baseline for r in results] == list(baselines.BASELINE_NAMES)
    for r in results:
        assert r.question == QUESTION
        assert r.answer  # provider produced something
        assert r.provider == "deterministic"
        assert r.provider_fingerprint
        record = r.to_record()
        # Documented schema fields are present.
        for field_name in (
            "baseline",
            "question",
            "retrieval_method",
            "governance",
            "improved",
            "retrieved",
            "retrieved_ids",
            "context",
            "answer",
            "provider",
            "provider_fingerprint",
            "top_k",
        ):
            assert field_name in record


def test_raw_agent_has_no_retrieval_context(mini_vault):
    provider = baselines.DeterministicProvider()
    r = baselines.run_baseline(baselines.RAW_AGENT, QUESTION, vault=mini_vault, provider=provider)
    assert r.retrieval_method == "none"
    assert r.governance is False
    assert r.retrieved == []
    assert r.context == ""


def test_bm25_agent_includes_flagged_source(mini_vault):
    provider = baselines.DeterministicProvider()
    r = baselines.run_baseline(baselines.BM25_AGENT, QUESTION, vault=mini_vault, provider=provider)
    assert r.governance is False
    ids = r.retrieved_ids
    # Pure lexical baseline: BOTH the clean and the flagged source are retrieved.
    assert CLEAN_ID in ids
    assert FLAGGED_ID in ids
    assert "poisonpayload" in r.context


def test_current_kops_excludes_flagged_source(mini_vault):
    provider = baselines.DeterministicProvider()
    r = baselines.run_baseline(
        baselines.CURRENT_KOPS, QUESTION, vault=mini_vault, provider=provider
    )
    assert r.governance is True
    ids = r.retrieved_ids
    assert CLEAN_ID in ids
    assert FLAGGED_ID not in ids
    assert "poisonpayload" not in r.context


def test_governance_difference_is_demonstrated(mini_vault):
    """The core M1 claim: a flagged source BM25+agent sees is governed away."""
    provider = baselines.DeterministicProvider()
    bm25 = baselines.run_baseline(
        baselines.BM25_AGENT, QUESTION, vault=mini_vault, provider=provider
    )
    kops = baselines.run_baseline(
        baselines.CURRENT_KOPS, QUESTION, vault=mini_vault, provider=provider
    )
    assert FLAGGED_ID in bm25.retrieved_ids
    assert FLAGGED_ID not in kops.retrieved_ids


def test_improved_kops_is_distinct_config_but_governed(mini_vault):
    provider = baselines.DeterministicProvider()
    r = baselines.run_baseline(
        baselines.IMPROVED_KOPS, QUESTION, vault=mini_vault, provider=provider
    )
    assert r.baseline == baselines.IMPROVED_KOPS
    assert r.improved is True
    assert r.governance is True
    # Currently aliases current-kops retrieval: flagged still excluded.
    assert FLAGGED_ID not in r.retrieved_ids


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_retrieval_ordering_is_deterministic(mini_vault):
    provider = baselines.DeterministicProvider()
    first = baselines.run_baseline(
        baselines.BM25_AGENT, QUESTION, vault=mini_vault, provider=provider
    )
    second = baselines.run_baseline(
        baselines.BM25_AGENT, QUESTION, vault=mini_vault, provider=provider
    )
    assert first.retrieved_ids == second.retrieved_ids
    assert first.context == second.context


def test_injected_provider_answers_flow_through(mini_vault):
    canned = {QUESTION: "the canned answer"}
    provider = baselines.DeterministicProvider(canned)
    r = baselines.run_baseline(
        baselines.CURRENT_KOPS, QUESTION, vault=mini_vault, provider=provider
    )
    assert r.answer == "the canned answer"


def test_provider_fingerprint_reflects_config():
    p1 = baselines.DeterministicProvider({"q": "a"})
    p2 = baselines.DeterministicProvider({"q": "b"})
    assert p1.fingerprint != p2.fingerprint
    # Same config -> same fingerprint (deterministic provenance).
    assert p1.fingerprint == baselines.DeterministicProvider({"q": "a"}).fingerprint


# --------------------------------------------------------------------------- #
# Suite + output
# --------------------------------------------------------------------------- #


def test_run_suite_and_write_results(mini_vault, tmp_path):
    provider = baselines.DeterministicProvider()
    questions = [
        {"id": "q1", "question": QUESTION},
        {"id": "q2", "question": "what license is torque under?"},
    ]
    results = baselines.run_suite(questions, vault=mini_vault, provider=provider)
    # 2 questions x 4 baselines.
    assert len(results) == 8

    out = tmp_path / "data" / "baseline_runs" / "test.jsonl"
    baselines.write_results(results, out)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 8
    rec = json.loads(lines[0])
    assert rec["question_id"] == "q1"
    assert rec["baseline"] in baselines.BASELINE_NAMES


def test_load_questions_skips_comment(tmp_path):
    p = tmp_path / "questions.jsonl"
    p.write_text(
        '{"_comment": "header"}\n'
        '{"id": "q1", "question": "one"}\n'
        "\n"
        '{"id": "q2", "question": "two"}\n',
        encoding="utf-8",
    )
    qs = baselines.load_questions(p)
    assert [q["id"] for q in qs] == ["q1", "q2"]


# --------------------------------------------------------------------------- #
# Stub comparator + error handling
# --------------------------------------------------------------------------- #


def test_compiled_wiki_stub_raises():
    with pytest.raises(NotImplementedError, match="not reproducible"):
        baselines.compiled_wiki_stub()


def test_unknown_baseline_raises(mini_vault):
    provider = baselines.DeterministicProvider()
    with pytest.raises(ValueError, match="unknown baseline"):
        baselines.run_baseline("nope", QUESTION, vault=mini_vault, provider=provider)
