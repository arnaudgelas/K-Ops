"""Execution roles for K-Ops agent invocations (roadmap task S0.2).

The vault historically had a single runner (``kb_runtime.agent_run``) that ran
every provider with write-oriented flags, no timeout, no output cap and no
confinement — a compile agent, an answer agent and a (future) judge all shared
the same blast radius.  This module splits that single primitive into three
roles with different trust and confinement levels:

- ``execute_generator`` — the shared generator primitive used by the mutating
  and read-only roles.  ``full_auto=True`` grants write-oriented flags
  (compile/heal/render/research); ``full_auto=False`` withholds them (answer
  generation).  Callers in :mod:`kops.kb_runtime` wrap this as
  ``agent_run`` / ``readonly_agent_run`` / ``mutating_agent_run``.
- ``judge_run`` — a pure structured classifier.  It runs in a throwaway
  temporary working directory (never the repo), enforces a subprocess timeout,
  bounds input and output size, validates output against a strict JSON schema
  (a parse/validation failure is raised, never silently passed), records a
  model + prompt fingerprint, and grants no write-oriented flags.

Confinement here is best-effort at the CLI-flag level.  True OS-level
sandboxing (network namespaces, seccomp, filesystem jails) is **not** provided
by this module; the per-provider notes below record what each CLI flag actually
buys and where OS-level isolation would still be required.

Provider confinement notes
--------------------------
- **codex**: ``--full-auto`` is the write-enabling flag; the generator passes it
  only in the mutating role.  The judge passes ``--sandbox read-only`` (Codex's
  documented read-only execution mode) and never ``--full-auto``.  Codex's own
  sandbox does not, by itself, guarantee network isolation for the model call.
- **claude**: ``claude -p`` does not write or invoke tools unless tools are
  explicitly allowed; the judge grants none.  There is no cross-platform flag to
  hard-disable network from the CLI — OS-level isolation would be needed.
- **gemini**: exposes no read-only/sandbox flag we can rely on; the judge simply
  withholds any write/tool grant and relies on the confined cwd.  Network and
  tool isolation for gemini require OS-level sandboxing (known limitation).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from kops.utils import detect_agent_command, shell_join

# --------------------------------------------------------------------------- #
# Generator role (mutating + read-only share this primitive)
# --------------------------------------------------------------------------- #


def build_generator_command(
    agent: str, base_cmd: list[str], prompt_path: Path, prompt_text: str, *, full_auto: bool
) -> list[str]:
    """Build the provider command for a generator run.

    ``full_auto`` gates write-oriented flags: it is ``True`` for the mutating
    role and ``False`` for the read-only (answer) role, which must never grant
    Codex ``--full-auto``.
    """
    if agent == "codex":
        flags = ["exec", "--skip-git-repo-check"]
        if full_auto:
            flags.append("--full-auto")
        return base_cmd + flags + [prompt_text]
    if agent == "claude":
        return base_cmd + ["-p", str(prompt_path)]
    if agent == "gemini":
        return base_cmd + ["-p", prompt_text]
    raise ValueError(agent)


def execute_generator(agent: str, prompt_path: Path, *, full_auto: bool, cwd: Path | str) -> None:
    """Run a generator provider against ``prompt_path`` inside ``cwd``.

    This is the shared primitive behind the mutating and read-only roles. The
    read-only role passes ``full_auto=False`` so no write-oriented provider flag
    is granted.
    """
    base_cmd = detect_agent_command(agent)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    cmd = build_generator_command(agent, base_cmd, prompt_path, prompt_text, full_auto=full_auto)
    role = "mutating" if full_auto else "read-only"
    print(f"\nRunning ({role}): {shell_join(cmd)}\n")
    subprocess.run(cmd, check=True, cwd=str(cwd))


# --------------------------------------------------------------------------- #
# Git checkpoints around mutating runs
# --------------------------------------------------------------------------- #


@dataclass
class GitCheckpoint:
    """Before/after git record for a mutating run.

    Makes uncommitted (potentially destructive) changes visible and
    recoverable.  This never auto-commits and never auto-reverts — it only
    records what changed so a human can recover.
    """

    is_repo: bool
    head: str | None = None
    porcelain_before: str = ""
    porcelain_after: str = ""
    diff_stat: str = ""
    recorded_at: str | None = None

    @property
    def changed(self) -> bool:
        return self.is_repo and self.porcelain_before != self.porcelain_after

    def to_dict(self) -> dict:
        return {
            "is_repo": self.is_repo,
            "head": self.head,
            "porcelain_before": self.porcelain_before,
            "porcelain_after": self.porcelain_after,
            "diff_stat": self.diff_stat,
            "recorded_at": self.recorded_at,
            "changed": self.changed,
        }


def _git(args: list[str], cwd: Path | str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return 127, ""
    return proc.returncode, proc.stdout


def git_checkpoint_before(cwd: Path | str) -> GitCheckpoint:
    """Record repo HEAD + working-tree status before a mutating run.

    Degrades gracefully when ``cwd`` is not a git repository.
    """
    code, _ = _git(["rev-parse", "--is-inside-work-tree"], cwd)
    if code != 0:
        return GitCheckpoint(is_repo=False)
    _, head = _git(["rev-parse", "HEAD"], cwd)
    _, porcelain = _git(["status", "--porcelain"], cwd)
    return GitCheckpoint(is_repo=True, head=head.strip() or None, porcelain_before=porcelain)


def git_checkpoint_after(before: GitCheckpoint, cwd: Path | str) -> GitCheckpoint:
    """Complete a checkpoint with the post-run status and diff stat."""
    import datetime as _dt

    before.recorded_at = _dt.datetime.now().replace(microsecond=0).isoformat()
    if not before.is_repo:
        return before
    _, porcelain = _git(["status", "--porcelain"], cwd)
    _, diff_stat = _git(["diff", "--stat"], cwd)
    before.porcelain_after = porcelain
    before.diff_stat = diff_stat
    return before


def persist_git_record(record: GitCheckpoint, cwd: Path | str) -> Path | None:
    """Print a human summary of the checkpoint and persist it under ``.tmp/``.

    Returns the path of the persisted record, or ``None`` when ``cwd`` is not a
    git repo (nothing durable to record).
    """
    if not record.is_repo:
        print("Git checkpoint: not a git repository; no before/after record produced.")
        return None

    if record.changed:
        print("Git checkpoint: working tree changed by mutating run.")
        if record.diff_stat.strip():
            print(record.diff_stat.rstrip())
        print("Changes are uncommitted and recoverable (no auto-commit / auto-revert).")
    else:
        print("Git checkpoint: no working-tree changes from mutating run.")

    stamp = (record.recorded_at or "").replace(":", "").replace("-", "") or "record"
    record_dir = Path(cwd) / ".tmp"
    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / f"mutating_run_record.{stamp}.json"
    record_path.write_text(
        json.dumps(record.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return record_path


# --------------------------------------------------------------------------- #
# Judge role (pure structured classifier)
# --------------------------------------------------------------------------- #

JUDGE_TIMEOUT_SECONDS = 120
JUDGE_MAX_INPUT_BYTES = 200_000
JUDGE_MAX_OUTPUT_BYTES = 200_000


class JudgeError(RuntimeError):
    """Raised when a judge run cannot produce a valid, schema-conforming verdict."""


@dataclass
class JudgeResult:
    """Structured, validated result of a judge run."""

    verdict: dict
    fingerprint: str
    agent: str
    model: str | None
    raw_output: str
    schema_keys: list[str] = field(default_factory=list)


def resolve_judge_command(agent: str) -> list[str]:
    """Resolve the judge provider command.

    The judge is independently configurable from the generator: ``KB_JUDGE_CMD``
    overrides the base command outright, otherwise the standard per-provider
    resolution (which honours ``KB_CODEX_CMD`` etc.) applies.
    """
    import shlex

    raw = os.environ.get("KB_JUDGE_CMD")
    if raw:
        return shlex.split(raw)
    return detect_agent_command(agent)


def resolve_judge_agent(explicit: str | None = None) -> str:
    """Resolve which provider backs the judge, independent of the generator."""
    return explicit or os.environ.get("KB_JUDGE_AGENT") or "codex"


def _build_judge_command(
    agent: str, base_cmd: list[str], prompt_path: Path, prompt_text: str
) -> list[str]:
    """Most-restricted provider invocation: no write/tool grants, no ``--full-auto``."""
    if agent == "codex":
        # Read-only sandbox, never --full-auto. See module docstring for the
        # residual network-isolation gap.
        return base_cmd + [
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            prompt_text,
        ]
    if agent == "claude":
        # `claude -p` grants no tools by default; the confined cwd bounds writes.
        return base_cmd + ["-p", str(prompt_path)]
    if agent == "gemini":
        return base_cmd + ["-p", prompt_text]
    raise ValueError(agent)


def _restricted_env() -> dict[str, str]:
    """Minimal environment for the judge subprocess.

    Network is *not* truly disabled here (that needs OS-level isolation); we
    keep only the variables a CLI needs to start and drop unrelated inherited
    state.  Documented as a known limitation.
    """
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
    env = {k: v for k, v in os.environ.items() if k in keep}
    # Pass judge provider overrides through so a stubbed CLI still resolves.
    for k in ("KB_JUDGE_CMD", "KB_CODEX_CMD", "KB_CLAUDE_CMD", "KB_GEMINI_CMD"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def _extract_json(text: str) -> dict:
    """Parse the first JSON object from ``text``; raise ``JudgeError`` on failure."""
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise JudgeError("judge output contained no JSON object")
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise JudgeError(f"judge output was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise JudgeError("judge output JSON was not an object")
    return parsed


def _validate_schema(payload: dict, schema: dict) -> None:
    """Strict, minimal JSON-schema check.

    Supports ``required``, per-property ``type`` and ``enum``.  Any violation is
    raised as ``JudgeError`` — a schema failure is never a silent pass.
    """
    type_map = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    for key in schema.get("required", []):
        if key not in payload:
            raise JudgeError(f"judge verdict missing required field: {key!r}")
    for key, spec in schema.get("properties", {}).items():
        if key not in payload:
            continue
        value = payload[key]
        expected = spec.get("type")
        if expected and expected in type_map:
            py_type = type_map[expected]
            # bool is a subclass of int; guard against accepting bools as numbers
            if expected in {"number", "integer"} and isinstance(value, bool):
                raise JudgeError(f"field {key!r} must be {expected}, got boolean")
            if not isinstance(value, py_type):
                raise JudgeError(f"field {key!r} must be {expected}, got {type(value).__name__}")
        if "enum" in spec and value not in spec["enum"]:
            raise JudgeError(f"field {key!r} value {value!r} not in allowed enum {spec['enum']}")


def _fingerprint(agent: str, base_cmd: list[str], model: str | None, prompt: str) -> str:
    provider_id = f"{agent}:{shell_join(base_cmd)}:{model or ''}"
    digest = hashlib.sha256()
    digest.update(provider_id.encode("utf-8"))
    digest.update(b"\n")
    digest.update(prompt.encode("utf-8"))
    return digest.hexdigest()


def judge_run(
    prompt: str,
    schema: dict,
    *,
    agent: str | None = None,
    model: str | None = None,
    timeout: int = JUDGE_TIMEOUT_SECONDS,
    max_input_bytes: int = JUDGE_MAX_INPUT_BYTES,
    max_output_bytes: int = JUDGE_MAX_OUTPUT_BYTES,
) -> JudgeResult:
    """Run a pure structured classifier and return a validated verdict.

    Guarantees (roadmap S0.2):

    - runs in a throwaway ``tempfile.mkdtemp`` cwd, never the repo, and cannot
      write to the vault;
    - enforces ``timeout`` on the subprocess;
    - bounds input and output size (raises on overflow);
    - grants no write-oriented provider flags and no tool access;
    - validates the output against ``schema`` — a parse or validation failure is
      raised as :class:`JudgeError`, never silently passed;
    - records a model + prompt fingerprint on the result.

    Network is not hard-disabled at this layer (see the module docstring); that
    requires OS-level sandboxing.
    """
    agent = resolve_judge_agent(agent)
    if agent == "codex":
        model = model or os.environ.get("KB_JUDGE_MODEL")

    prompt_bytes = prompt.encode("utf-8")
    if len(prompt_bytes) > max_input_bytes:
        raise JudgeError(
            f"judge input of {len(prompt_bytes)} bytes exceeds bound {max_input_bytes}"
        )

    base_cmd = resolve_judge_command(agent)
    fingerprint = _fingerprint(agent, base_cmd, model, prompt)

    workdir = Path(tempfile.mkdtemp(prefix="kops-judge-"))
    try:
        prompt_path = workdir / "judge_prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        cmd = _build_judge_command(agent, base_cmd, prompt_path, prompt)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_restricted_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise JudgeError(f"judge run exceeded timeout of {timeout}s") from exc

        if proc.returncode != 0:
            raise JudgeError(
                f"judge provider exited {proc.returncode}: {proc.stderr.strip()[:500]}"
            )

        output = proc.stdout or ""
        if len(output.encode("utf-8")) > max_output_bytes:
            raise JudgeError(
                f"judge output of {len(output.encode('utf-8'))} bytes exceeds bound "
                f"{max_output_bytes}"
            )

        payload = _extract_json(output)
        _validate_schema(payload, schema)
        return JudgeResult(
            verdict=payload,
            fingerprint=fingerprint,
            agent=agent,
            model=model,
            raw_output=output,
            schema_keys=sorted(schema.get("properties", {}).keys()),
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
