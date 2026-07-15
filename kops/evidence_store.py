"""Persistence for the canonical evidence objects (M1 task D1.1).

Three stores, each chosen to match the immutability contract of what it holds:

* **SourceVersion** — append-only JSON Lines at ``data/history/source_versions.jsonl``
  (mirrors ``data/history/signals.jsonl``). A version is identified by
  ``(source_id, content_hash)``; the *first* record for a version id wins and is
  never overwritten, so prior versions are immutable.
* **ValidationEvent** — append-only JSON Lines at
  ``data/history/validation_events.jsonl``. Events are only ever appended.
* **ContextPackage** — content-addressed JSON at
  ``data/evidence/context_packages/<package_hash>.json``. Writing the same
  package is idempotent.

Every store envelope is stamped with ``schema_version`` via the object
``to_dict`` payloads. The base directories are injectable so tests never touch a
real vault.
"""

from __future__ import annotations

import json
from pathlib import Path

from kops.evidence_model import ContextPackage, SourceVersion, ValidationEvent
from kops.kb_paths import ROOT
from kops.utils import ensure_dir


class EvidenceStoreError(RuntimeError):
    """Raised on an illegal store operation (e.g. mutating a frozen version)."""


def _append_jsonl(path: Path, record: dict) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


class EvidenceStore:
    """File-backed persistence for the append-only + content-addressed objects."""

    def __init__(
        self,
        base_dir: Path | None = None,
        history_dir: Path | None = None,
    ) -> None:
        self.base_dir = Path(base_dir) if base_dir else (ROOT / "data" / "evidence")
        self.history_dir = Path(history_dir) if history_dir else (ROOT / "data" / "history")
        self.source_versions_path = self.history_dir / "source_versions.jsonl"
        self.validation_events_path = self.history_dir / "validation_events.jsonl"
        self.context_dir = self.base_dir / "context_packages"

    # -- SourceVersion (immutable, append-only) ---------------------------- #

    def append_source_version(self, version: SourceVersion) -> SourceVersion:
        """Append a version. If its version id already exists, the stored
        (immutable) record wins and nothing is written — prior versions are
        never overwritten."""
        existing = {rec.get("version_id"): rec for rec in _read_jsonl(self.source_versions_path)}
        stored = existing.get(version.version_id)
        if stored is not None:
            if stored.get("content_hash") != version.content_hash:
                # Cannot happen (version_id derives from content_hash) but guard.
                raise EvidenceStoreError(f"version id {version.version_id} content_hash mismatch")
            return SourceVersion.from_dict(stored)
        _append_jsonl(self.source_versions_path, version.to_dict())
        return version

    def source_versions(self, source_id: str | None = None) -> list[SourceVersion]:
        records = _read_jsonl(self.source_versions_path)
        versions = [SourceVersion.from_dict(rec) for rec in records]
        if source_id is not None:
            versions = [v for v in versions if v.source_id == source_id]
        return versions

    def latest_source_version(self, source_id: str) -> SourceVersion | None:
        versions = self.source_versions(source_id)
        return versions[-1] if versions else None

    # -- ValidationEvent (append-only) ------------------------------------- #

    def append_validation_event(self, event: ValidationEvent) -> ValidationEvent:
        _append_jsonl(self.validation_events_path, event.to_dict())
        return event

    def validation_events(self, target_id: str | None = None) -> list[ValidationEvent]:
        records = _read_jsonl(self.validation_events_path)
        events = [ValidationEvent.from_dict(rec) for rec in records]
        if target_id is not None:
            events = [e for e in events if e.target_id == target_id]
        return events

    # -- ContextPackage (content-addressed) -------------------------------- #

    def _context_path(self, package_hash: str) -> Path:
        return self.context_dir / f"{package_hash}.json"

    def save_context_package(self, package: ContextPackage) -> str:
        payload = package.to_dict()
        path = self._context_path(package.package_hash)
        ensure_dir(path.parent)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return package.package_hash

    def load_context_package(self, package_hash: str) -> ContextPackage | None:
        path = self._context_path(package_hash)
        if not path.exists():
            return None
        return ContextPackage.from_dict(json.loads(path.read_text(encoding="utf-8")))


__all__ = ["EvidenceStore", "EvidenceStoreError"]
