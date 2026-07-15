"""Source-exclusion filter + audited override object.

Flagged, revoked, adversarial, or prompt-injected sources must not leak into
serving surfaces (retrieval, the ``ask`` answer context, compilation, render/
export). This module is the single, deterministic decision point for "is this
source excluded, and if so may an *explicit, audited* override let it through
for a specific command?".

Design ethos (matches ``consequence_gate.py``): deterministic, non-gameable,
report-and-gate. It reads frontmatter/registry metadata and an on-disk override
store only; no LLM judgement, no silent bypass.

The canonical blocked-status set is imported from ``claim_registry`` so the
compile planner, claim admission, and every serving surface agree on what
"flagged" means and cannot drift apart.

Override object (``data/source_overrides.json``, a JSON list) records, per entry:

- ``source_id`` and ``version`` — which source (and optionally which version)
- ``operator`` — who authorised the bypass (audit: who)
- ``reason`` — why (audit: why)
- ``scope`` — human-readable boundary of the exception
- ``expiry`` — ISO date/datetime after which it is inert (time-bounded)
- ``commands`` — the command(s) it applies to (``"*"`` = all); scoped bypass
- ``created_at`` — when it was recorded (audit: when)

An override lets a flagged source through **only** for a named command, only
until it expires, and only for the matching source id (+ version when pinned).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from kops.claim_registry import _BLOCKED_SOURCE_STATUSES
from kops.utils import ROOT, ensure_dir

# Store lives beside the registry. Module-level so tests can monkeypatch it.
OVERRIDES_PATH = ROOT / "data" / "source_overrides.json"

# Canonical flagging statuses (imported — never re-listed — to prevent drift).
BLOCKED_SOURCE_STATUSES = _BLOCKED_SOURCE_STATUSES


# ---------------------------------------------------------------------------
# Flag detection (pure — works on source-note frontmatter or a registry entry)
# ---------------------------------------------------------------------------


def frontmatter_flag_reasons(meta: dict) -> list[str]:
    """Deterministic exclusion reasons for a source's metadata (empty = clean).

    Accepts either a source-note frontmatter dict or a ``data/registry.json``
    entry; both carry the same field names. Order is stable and canonical so
    every surface reports the same reasons.
    """
    reasons: list[str] = []
    status = str(meta.get("source_status") or "")
    if status in BLOCKED_SOURCE_STATUSES:
        reasons.append(f"source_status:{status}")
    if meta.get("adversarial_content") is True:
        reasons.append("adversarial_content")
    if meta.get("prompt_injection_detected") is True:
        reasons.append("prompt_injection_detected")
    if meta.get("fetch_warning"):
        reasons.append(f"fetch_warning:{meta['fetch_warning']}")
    return reasons


def _source_id_of(meta: dict) -> str:
    return str(meta.get("source_id") or meta.get("id") or "")


def _source_version_of(meta: dict) -> str | None:
    for key in ("source_version", "version", "content_hash"):
        value = meta.get(key)
        if value:
            return str(value)
    return None


# ---------------------------------------------------------------------------
# Override object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceOverride:
    """An explicit, audited, time-bounded, command-scoped exclusion bypass."""

    source_id: str
    operator: str
    reason: str
    scope: str
    expiry: str
    commands: tuple[str, ...]
    version: str | None = None
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> SourceOverride:
        commands = data.get("commands") or []
        if isinstance(commands, str):
            commands = [commands]
        return cls(
            source_id=str(data.get("source_id") or ""),
            operator=str(data.get("operator") or ""),
            reason=str(data.get("reason") or ""),
            scope=str(data.get("scope") or ""),
            expiry=str(data.get("expiry") or ""),
            commands=tuple(str(c) for c in commands),
            version=(str(data["version"]) if data.get("version") else None),
            created_at=str(data.get("created_at") or ""),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["commands"] = list(self.commands)
        return data

    def is_active(self, now: dt.datetime | None = None) -> bool:
        """True while the override has not expired (inclusive of the expiry moment)."""
        deadline = _parse_deadline(self.expiry)
        if deadline is None:
            return False
        return _as_datetime(now or dt.datetime.now()) <= deadline

    def applies_to(self, source_id: str, command: str, version: str | None) -> bool:
        """True if this override targets ``source_id`` for ``command`` (ignoring expiry)."""
        if self.source_id != source_id:
            return False
        if "*" not in self.commands and command not in self.commands:
            return False
        # A version-pinned override applies only to that exact version.
        if self.version is not None and self.version != version:
            return False
        return True


def _as_datetime(value: dt.datetime) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    return dt.datetime.combine(value, dt.time.max)


def _parse_deadline(expiry: str) -> dt.datetime | None:
    """Parse an ISO date or datetime. A bare date expires at end-of-day."""
    if not expiry:
        return None
    text = expiry.strip()
    try:
        parsed = dt.datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    try:
        return dt.datetime.combine(dt.date.fromisoformat(text), dt.time.max)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Store I/O
# ---------------------------------------------------------------------------


def _store_path(path: Path | None = None) -> Path:
    return path if path is not None else OVERRIDES_PATH


def load_overrides(path: Path | None = None) -> list[SourceOverride]:
    store = _store_path(path)
    try:
        raw = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = raw.get("overrides", []) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []
    return [SourceOverride.from_dict(item) for item in entries if isinstance(item, dict)]


def save_overrides(overrides: list[SourceOverride], path: Path | None = None) -> Path:
    store = _store_path(path)
    ensure_dir(store.parent)
    payload = [ov.to_dict() for ov in overrides]
    store.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return store


def add_override(
    *,
    source_id: str,
    operator: str,
    reason: str,
    scope: str,
    expiry: str,
    commands: list[str],
    version: str | None = None,
    created_at: str | None = None,
    path: Path | None = None,
) -> SourceOverride:
    """Record (audit) a new override and append it to the store.

    Fails loudly on missing required audit fields — an override must always say
    who, why, what scope, until when, and for which commands.
    """
    if not source_id:
        raise ValueError("source_id is required")
    if not operator:
        raise ValueError("operator is required (audit: who)")
    if not reason:
        raise ValueError("reason is required (audit: why)")
    if not scope:
        raise ValueError("scope is required")
    if not expiry or _parse_deadline(expiry) is None:
        raise ValueError(f"expiry must be an ISO date/datetime, got {expiry!r}")
    if not commands:
        raise ValueError("commands is required (which commands the override applies to)")

    override = SourceOverride(
        source_id=source_id,
        operator=operator,
        reason=reason,
        scope=scope,
        expiry=expiry,
        commands=tuple(commands),
        version=version,
        created_at=created_at or dt.datetime.now().replace(microsecond=0).isoformat(),
    )
    existing = load_overrides(path)
    existing.append(override)
    save_overrides(existing, path)
    return override


# ---------------------------------------------------------------------------
# Decision point
# ---------------------------------------------------------------------------


def active_override_for(
    source_id: str,
    command: str,
    version: str | None = None,
    *,
    now: dt.datetime | None = None,
    overrides: list[SourceOverride] | None = None,
) -> SourceOverride | None:
    """Return the active, in-scope override that lets ``source_id`` through for
    ``command``, or ``None`` if there is no such (unexpired, matching) override."""
    if overrides is None:
        overrides = load_overrides()
    for ov in overrides:
        if ov.applies_to(source_id, command, version) and ov.is_active(now):
            return ov
    return None


def should_exclude(
    meta: dict,
    *,
    command: str,
    include_flagged: bool = False,
    overrides: list[SourceOverride] | None = None,
    now: dt.datetime | None = None,
) -> tuple[bool, list[str]]:
    """Decide whether a source described by ``meta`` must be excluded for ``command``.

    Returns ``(excluded, reasons)``. ``reasons`` is always the (possibly empty)
    list of flag reasons, even when the source is allowed, so callers can audit
    *why* something was let through.

    A flagged source is excluded unless ``include_flagged`` is set (explicit
    admin/debug opt-in) or an active, in-scope override applies for ``command``.
    """
    reasons = frontmatter_flag_reasons(meta)
    if not reasons:
        return False, reasons
    if include_flagged:
        return False, reasons
    override = active_override_for(
        _source_id_of(meta),
        command,
        _source_version_of(meta),
        now=now,
        overrides=overrides,
    )
    if override is not None:
        return False, reasons
    return True, reasons
