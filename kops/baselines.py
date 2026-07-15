"""baselines.py — Comparable retrieval+answer baselines for the M1 benchmark.

Roadmap task ``E1.3``. The M1 thesis is that K-Ops's *governance* (source
exclusion, consequence gating, claim admission) produces measurably better
answers than simpler approaches — not merely that internal K-Ops versions
differ from each other. To measure that, the benchmark has to run the SAME
questions through several distinct configurations and hand the results to the
E1.4 metrics harness. This module builds those runners.

Design goals
------------
- **Reproducible & offline.** BM25 retrieval is deterministic (``k1=1.5``,
  ``b=0.75``, stable sort). The LLM is *injected* as a ``Provider`` object, so
  tests pass a deterministic fake and never touch a network or a model. There
  is no RNG anywhere in this module.
- **No fabricated numbers.** This ships the harness and a mock provider only.
  Real runs require an explicit real provider (``AgentCliProvider``) and are
  documented in ``research/benchmarks/BASELINES.md``. Nothing here invents
  benchmark scores.

The four baselines
------------------
Each baseline differs in (a) how context is retrieved and (b) whether K-Ops
governance is applied to that retrieval:

1. ``raw-agent`` — *no retrieval, no governance.* The question is handed to the
   provider with an EMPTY context. This captures what a bare LLM produces with
   no grounding in the corpus. (Choice: empty context rather than dumping the
   whole corpus, so the "no retrieval" condition is unambiguous and cheap. The
   whole-corpus variant is a documented future option, see ``BASELINES.md``.)

2. ``bm25-agent`` — *pure lexical retrieval, governance OFF.* Top-k
   ``VaultIndex.bm25(..., command="search", include_flagged=True)``. The
   ``include_flagged=True`` is deliberate: this baseline gets NONE of K-Ops's
   exclusion filtering, so a flagged / revoked / adversarial / prompt-injected
   source CAN enter its context. It is the "just BM25 + an LLM" strawman.

3. ``current-kops`` — *governed retrieval, governance ON.* The real ``ask``
   retrieval path: ``VaultIndex.search(..., command="ask")`` with exclusion
   filtering on by default, so flagged sources are refused before they reach
   the provider. This mirrors ``kb_runtime.build_ask_retrieval_context``.

4. ``improved-kops`` — *governed retrieval + M1 improvements hook.* Currently
   aliases ``current-kops`` behaviour behind the ``improved`` flag so the
   harness supports four distinct configs today. As the M1 evidence-model /
   atomic-claim / entailment wiring lands (roadmap E1.2, J1.x) it is toggled on
   here. See the ``TODO(E1.2)`` marker in :func:`_retrieve_governed`.

An optional fifth slot, ``compiled-wiki``, is registered as a documented STUB
(:class:`_CompiledWikiUnavailable`) — it raises with a clear message rather than
fabricating a comparator that is not reproducible yet.

Output record schema
---------------------
:meth:`BaselineResult.to_record` emits one flat JSON object per (baseline,
question). Suites are written as JSON Lines to ``data/baseline_runs/<date>.jsonl``
(mirroring the ``data/eval_runs`` convention) for the E1.4 metrics harness to
consume. Fields are documented on :class:`BaselineResult`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from kops import retrieval
from kops.retrieval import VaultIndex
from kops.utils import detect_agent_command, shell_join

# --------------------------------------------------------------------------- #
# Baseline identifiers
# --------------------------------------------------------------------------- #

RAW_AGENT = "raw-agent"
BM25_AGENT = "bm25-agent"
CURRENT_KOPS = "current-kops"
IMPROVED_KOPS = "improved-kops"
COMPILED_WIKI = "compiled-wiki"

#: The four reproducible baselines, in reporting order.
BASELINE_NAMES: tuple[str, ...] = (RAW_AGENT, BM25_AGENT, CURRENT_KOPS, IMPROVED_KOPS)

DEFAULT_TOP_K = 8


# --------------------------------------------------------------------------- #
# Provider protocol + concrete providers
# --------------------------------------------------------------------------- #


@runtime_checkable
class Provider(Protocol):
    """An injectable answer generator.

    A provider turns a (question, retrieval-context) pair into answer text. It
    is the ONLY place a baseline could touch an LLM, so injecting it keeps the
    whole harness deterministic and offline in tests. Implementations must
    expose a stable ``name`` and ``fingerprint`` for provenance.
    """

    name: str

    @property
    def fingerprint(self) -> str:  # pragma: no cover - structural
        """Stable provenance string identifying provider + configuration."""
        ...

    def generate(self, question: str, context: str) -> str:  # pragma: no cover - structural
        """Return answer text for ``question`` given retrieval ``context``."""
        ...


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DeterministicProvider:
    """A canned, offline provider for tests and dry runs.

    Given the same inputs it always returns the same answer, so a suite is fully
    reproducible. Supply answers in one of three ways (checked in order):

    - ``answers`` dict keyed by question text -> canned answer;
    - ``answer_fn`` callable ``(question, context) -> str``;
    - otherwise a default template that echoes the question and a deterministic
      digest of the context (so tests can assert the context actually flowed
      through to the provider).
    """

    def __init__(
        self,
        answers: dict[str, str] | None = None,
        *,
        answer_fn: Callable[[str, str], str] | None = None,
        name: str = "deterministic",
        version: str = "1",
    ) -> None:
        self._answers = dict(answers or {})
        self._answer_fn = answer_fn
        self.name = name
        self._version = version

    @property
    def fingerprint(self) -> str:
        # Answers are part of the config: two fakes with different canned
        # answers must fingerprint differently for honest provenance.
        payload = json.dumps(
            {"name": self.name, "version": self._version, "answers": sorted(self._answers.items())},
            sort_keys=True,
        )
        return f"{self.name}:{_sha256(payload)[:16]}"

    def generate(self, question: str, context: str) -> str:
        if question in self._answers:
            return self._answers[question]
        if self._answer_fn is not None:
            return self._answer_fn(question, context)
        digest = _sha256(context)[:12] if context else "no-context"
        return f"[{self.name}] answer to: {question} (context={digest})"


class AgentCliProvider:
    """Real provider backed by a provider CLI (codex / claude / gemini).

    Resolves the command via :func:`detect_agent_command` (honouring the
    ``KB_CODEX_CMD`` / ``KB_CLAUDE_CMD`` / ``KB_GEMINI_CMD`` overrides), sends a
    read-only prompt built from the question + retrieval context, and captures
    stdout as the answer. This is for REAL benchmark runs only — it is never
    exercised by the test suite (which injects :class:`DeterministicProvider`),
    and this module never calls it implicitly. See ``BASELINES.md``.
    """

    def __init__(self, agent: str = "codex", *, timeout: int = 300) -> None:
        self.agent = agent
        self.name = f"agent-cli:{agent}"
        self._timeout = timeout
        self._base_cmd = detect_agent_command(agent)

    @property
    def fingerprint(self) -> str:
        return f"{self.name}:{_sha256(shell_join(self._base_cmd))[:16]}"

    def _build_prompt(self, question: str, context: str) -> str:
        header = (
            "Answer the question using ONLY the retrieval context below. "
            "If the context is empty or insufficient, say so explicitly."
        )
        ctx = context.strip() or "(no retrieval context provided)"
        return f"{header}\n\n# Question\n{question}\n\n# Retrieval context\n{ctx}\n"

    def _build_cmd(self, prompt: str) -> list[str]:
        # Read-only invocation: never grant write/full-auto flags.
        if self.agent == "codex":
            return self._base_cmd + [
                "exec",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                prompt,
            ]
        if self.agent == "claude":
            return self._base_cmd + ["-p", prompt]
        if self.agent == "gemini":
            return self._base_cmd + ["-p", prompt]
        raise ValueError(self.agent)

    def generate(self, question: str, context: str) -> str:
        prompt = self._build_prompt(question, context)
        cmd = self._build_cmd(prompt)
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=self._timeout, check=True
        )
        return (proc.stdout or "").strip()


# --------------------------------------------------------------------------- #
# Retrieval strategies (deterministic; governance on/off is the axis)
# --------------------------------------------------------------------------- #


def _retrieve_none(index: VaultIndex, question: str, top_k: int) -> list[dict]:
    """raw-agent: no retrieval at all."""
    return []


def _retrieve_bm25_lexical(index: VaultIndex, question: str, top_k: int) -> list[dict]:
    """bm25-agent: pure lexical BM25, governance OFF (flagged sources included).

    ``include_flagged=True`` deliberately bypasses K-Ops exclusion filtering so
    this is a true "BM25 + LLM" strawman with no governance.
    """
    return index.bm25(question, top_k=top_k, command="search", include_flagged=True)


def _retrieve_governed(index: VaultIndex, question: str, top_k: int) -> list[dict]:
    """current-kops / improved-kops: governed retrieval, exclusion ON.

    Mirrors ``kb_runtime.build_ask_retrieval_context``: ``command="ask"`` scopes
    which audited overrides may re-admit a source, and exclusion filtering is on
    by default so flagged / revoked / adversarial sources never reach the
    provider.

    TODO(E1.2): improved-kops should additionally apply the M1 evidence-model /
    atomic-claim / entailment re-ranking here once those land. Today it aliases
    current-kops so the harness supports four distinct configs.
    """
    return index.search(question, top_k=top_k, command="ask")


# --------------------------------------------------------------------------- #
# Baseline config registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BaselineConfig:
    """Static description of one baseline: how it retrieves + whether it governs."""

    name: str
    retrieval_method: str
    governance: bool
    retrieve: Callable[[VaultIndex, str, int], list[dict]]
    improved: bool = False
    description: str = ""


_REGISTRY: dict[str, BaselineConfig] = {
    RAW_AGENT: BaselineConfig(
        name=RAW_AGENT,
        retrieval_method="none",
        governance=False,
        retrieve=_retrieve_none,
        description="No retrieval; bare LLM over an empty context.",
    ),
    BM25_AGENT: BaselineConfig(
        name=BM25_AGENT,
        retrieval_method="bm25-lexical",
        governance=False,
        retrieve=_retrieve_bm25_lexical,
        description="Pure lexical BM25 top-k, governance OFF (flagged included).",
    ),
    CURRENT_KOPS: BaselineConfig(
        name=CURRENT_KOPS,
        retrieval_method="governed-ask",
        governance=True,
        retrieve=_retrieve_governed,
        description="Governed ask retrieval; flagged sources excluded.",
    ),
    IMPROVED_KOPS: BaselineConfig(
        name=IMPROVED_KOPS,
        retrieval_method="governed-ask",
        governance=True,
        retrieve=_retrieve_governed,
        improved=True,
        description="Governed retrieval + M1 improvements hook (TODO E1.2).",
    ),
}


class _CompiledWikiUnavailable:
    """Documented stub for the optional compiled-wiki comparator.

    A reproducible compiled-wiki baseline is not available yet, so rather than
    fabricate one this slot raises with a clear message. Wire a real
    implementation here when the compiled-wiki artifact is reproducible.
    """

    name = COMPILED_WIKI

    def __call__(self, *_args: object, **_kwargs: object) -> "BaselineResult":
        raise NotImplementedError(
            "compiled-wiki comparator is not reproducible yet; it is a documented "
            "stub slot (see research/benchmarks/BASELINES.md). Do not fabricate it."
        )


compiled_wiki_stub = _CompiledWikiUnavailable()


def baseline_config(name: str) -> BaselineConfig:
    """Return the config for ``name`` or raise a clear error."""
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(BASELINE_NAMES)
        raise ValueError(f"unknown baseline {name!r}; known baselines: {known}") from None


# --------------------------------------------------------------------------- #
# Result record
# --------------------------------------------------------------------------- #


@dataclass
class RetrievedItem:
    """One retrieved context item (subset of the retrieval result shape)."""

    id: str
    kind: str
    retrieval_method: str
    score: float
    snippet: str = ""
    source_id: str = ""
    anchor: str = ""

    @classmethod
    def from_result(cls, r: dict) -> "RetrievedItem":
        return cls(
            id=r.get("id", ""),
            kind=r.get("kind", ""),
            retrieval_method=r.get("retrieval_method", ""),
            score=float(r.get("score", 0.0)),
            snippet=str(r.get("snippet", "")),
            source_id=str(r.get("source_id", "")),
            anchor=str(r.get("anchor", "")),
        )


@dataclass
class BaselineResult:
    """Result of running one baseline over one question.

    Schema (also the JSONL record shape from :meth:`to_record`):

    - ``baseline``: one of :data:`BASELINE_NAMES`.
    - ``question`` / ``question_id``: the query and its optional id.
    - ``retrieval_method``: ``none`` | ``bm25-lexical`` | ``governed-ask``.
    - ``governance``: bool — whether K-Ops exclusion/governance was applied.
    - ``improved``: bool — whether the M1 improvements hook is active.
    - ``retrieved``: list of context items (id / kind / method / score / spans).
    - ``retrieved_ids``: convenience list of the retrieved ids.
    - ``context``: the exact context string handed to the provider.
    - ``answer``: the provider's answer text.
    - ``provider`` / ``provider_fingerprint``: provider provenance.
    - ``top_k`` / ``generated_at``: run parameters.
    """

    baseline: str
    question: str
    retrieval_method: str
    governance: bool
    improved: bool
    retrieved: list[RetrievedItem]
    context: str
    answer: str
    provider: str
    provider_fingerprint: str
    top_k: int
    question_id: str | None = None
    generated_at: str = ""

    @property
    def retrieved_ids(self) -> list[str]:
        return [item.id for item in self.retrieved]

    def to_record(self) -> dict:
        record = asdict(self)
        record["retrieved_ids"] = self.retrieved_ids
        return record


# --------------------------------------------------------------------------- #
# Context rendering (deterministic)
# --------------------------------------------------------------------------- #


def render_context(results: list[dict]) -> str:
    """Render retrieval results into a deterministic context block.

    Same ordering + fields as ``kb_runtime._format_seed_retrieval_result`` so a
    baseline's context resembles the real ask context package.
    """
    if not results:
        return ""
    blocks: list[str] = [f"Retrieval returned {len(results)} result(s):"]
    for r in results:
        parts = [
            f"- id: {r.get('id', '')}",
            f"  kind: {r.get('kind', '')}",
            f"  method: {r.get('retrieval_method', '')}",
            f"  score: {r.get('score', 0)}",
            f"  title: {r.get('title', '')}",
        ]
        if r.get("source_id") and r.get("anchor"):
            parts.append(f"  source_anchor: {r['source_id']}#{r['anchor']}")
        snippet = " ".join(str(r.get("snippet") or "").split())
        if snippet:
            parts.append(f"  snippet: {snippet[:240]}")
        blocks.append("\n".join(parts))
    return "\n".join(blocks)


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #


def _resolve_index(vault: VaultIndex | None) -> VaultIndex:
    if vault is not None:
        return vault
    return retrieval.get_index()


def run_baseline(
    name: str,
    question: str,
    *,
    vault: VaultIndex | None = None,
    provider: Provider,
    top_k: int = DEFAULT_TOP_K,
    question_id: str | None = None,
) -> BaselineResult:
    """Run one baseline over one question and return a :class:`BaselineResult`.

    ``vault`` is a pre-built :class:`VaultIndex` (built against the target
    corpus). When ``None`` the module-level singleton is used. ``provider`` is
    injected — pass a :class:`DeterministicProvider` in tests.
    """
    config = baseline_config(name)
    index = _resolve_index(vault)
    results = config.retrieve(index, question, top_k)
    context = render_context(results)
    answer = provider.generate(question, context)
    return BaselineResult(
        baseline=config.name,
        question=question,
        question_id=question_id,
        retrieval_method=config.retrieval_method,
        governance=config.governance,
        improved=config.improved,
        retrieved=[RetrievedItem.from_result(r) for r in results],
        context=context,
        answer=answer,
        provider=provider.name,
        provider_fingerprint=provider.fingerprint,
        top_k=top_k,
        generated_at=dt.datetime.now().replace(microsecond=0).isoformat(),
    )


def run_all_baselines(
    question: str,
    *,
    vault: VaultIndex | None = None,
    provider: Provider,
    top_k: int = DEFAULT_TOP_K,
    question_id: str | None = None,
    baselines: tuple[str, ...] = BASELINE_NAMES,
) -> list[BaselineResult]:
    """Run every named baseline over a single question."""
    index = _resolve_index(vault)
    return [
        run_baseline(
            name,
            question,
            vault=index,
            provider=provider,
            top_k=top_k,
            question_id=question_id,
        )
        for name in baselines
    ]


def load_questions(path: Path) -> list[dict]:
    """Load a ``questions.jsonl`` file, skipping ``_comment`` header lines."""
    questions: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        if "_comment" in data:
            continue
        questions.append(data)
    return questions


def run_suite(
    questions: list[dict],
    *,
    vault: VaultIndex | None = None,
    provider: Provider,
    top_k: int = DEFAULT_TOP_K,
    baselines: tuple[str, ...] = BASELINE_NAMES,
) -> list[BaselineResult]:
    """Run every baseline over every question. Deterministic ordering."""
    index = _resolve_index(vault)
    out: list[BaselineResult] = []
    for q in questions:
        qtext = q.get("question", "")
        qid = q.get("id")
        out.extend(
            run_all_baselines(
                qtext,
                vault=index,
                provider=provider,
                top_k=top_k,
                question_id=qid,
                baselines=baselines,
            )
        )
    return out


def write_results(results: list[BaselineResult], out_path: Path) -> Path:
    """Write baseline results as JSON Lines to ``out_path``."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r.to_record(), ensure_ascii=False) + "\n")
    return out_path


# --------------------------------------------------------------------------- #
# Vault targeting for the CLI (--vault)
# --------------------------------------------------------------------------- #


class _VaultCfg:
    """Minimal config object exposing the fields VaultIndex reads."""

    def __init__(self, summaries_dir: Path, concepts_dir: Path) -> None:
        self.summaries_dir = summaries_dir
        self.concepts_dir = concepts_dir


def build_vault_index(home: Path) -> VaultIndex:
    """Build a VaultIndex pointed at the vault rooted at ``home``.

    Reads ``home/config/kb_config.yaml`` for the notes layout and points the
    retrieval module's ``ROOT`` / ``CONFIG`` at that vault (the same technique
    the test suite uses). Intended for the CLI entry point.
    """
    import yaml

    cfg_path = home / "config" / "kb_config.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    summaries = home / data["summaries_dir"]
    concepts = home / data["concepts_dir"]
    retrieval.CONFIG = _VaultCfg(summaries, concepts)  # type: ignore[assignment]
    retrieval.ROOT = home  # type: ignore[assignment]
    index = VaultIndex()
    index.build()
    return index


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #


def _build_provider(spec: str) -> Provider:
    """Resolve a ``--provider`` spec into a Provider.

    - ``deterministic`` (default): offline canned provider for dry runs/tests.
    - ``agent-cli:<agent>`` (e.g. ``agent-cli:codex``): REAL provider — invokes
      the provider CLI. Requires the CLI (or a ``KB_*_CMD`` stub) on PATH.
    """
    if spec == "deterministic":
        return DeterministicProvider()
    if spec.startswith("agent-cli:"):
        agent = spec.split(":", 1)[1] or "codex"
        return AgentCliProvider(agent)
    raise SystemExit(
        f"unknown --provider spec: {spec!r} (use 'deterministic' or 'agent-cli:<agent>')"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kops.baselines",
        description="Run M1 comparison baselines over a benchmark question set.",
    )
    parser.add_argument(
        "--vault",
        required=True,
        help="Vault root (contains config/kb_config.yaml). E.g. the E1.1 corpus.",
    )
    parser.add_argument(
        "--questions",
        help="Path to questions.jsonl. Defaults to <vault>/../questions.jsonl if present.",
    )
    parser.add_argument(
        "--provider",
        default="deterministic",
        help="Provider spec: 'deterministic' (offline, default) or 'agent-cli:<agent>' (real).",
    )
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        "--out",
        help="Output JSONL path. Defaults to data/baseline_runs/<date>.jsonl under the vault.",
    )
    parser.add_argument(
        "--baseline",
        action="append",
        choices=list(BASELINE_NAMES),
        help="Restrict to specific baseline(s). Repeatable. Default: all four.",
    )
    args = parser.parse_args(argv)

    home = Path(args.vault).expanduser().resolve()
    if not (home / "config" / "kb_config.yaml").exists():
        raise SystemExit(f"no config/kb_config.yaml under --vault {home}")
    # Make ROOT/CONFIG line up with the target vault for anything downstream.
    os.environ["KB_HOME"] = str(home)
    index = build_vault_index(home)

    if args.questions:
        questions_path = Path(args.questions).expanduser().resolve()
    else:
        candidate = home.parent / "questions.jsonl"
        questions_path = candidate if candidate.exists() else home / "questions.jsonl"
    if not questions_path.exists():
        raise SystemExit(f"questions file not found: {questions_path}")
    questions = load_questions(questions_path)

    provider = _build_provider(args.provider)
    baselines = tuple(args.baseline) if args.baseline else BASELINE_NAMES
    results = run_suite(
        questions, vault=index, provider=provider, top_k=args.top_k, baselines=baselines
    )

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
    else:
        date = dt.date.today().isoformat()
        out_path = home / "data" / "baseline_runs" / f"{date}.jsonl"
    write_results(results, out_path)

    print(f"Wrote {len(results)} baseline records to {out_path}")
    print(f"  questions: {len(questions)} | baselines: {', '.join(baselines)}")
    print(f"  provider: {provider.name} ({provider.fingerprint})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
