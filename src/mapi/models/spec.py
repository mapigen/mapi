# src/mapi/models/spec.py
from __future__ import annotations

import msgspec


class SpecDiffResult(msgspec.Struct, frozen=True):
    """Result of checking differences between an active spec and a candidate/upstream spec."""

    has_diff: bool
    provider: str
    api: str
    added_operations: list[str] = msgspec.field(default_factory=list)
    removed_operations: list[str] = msgspec.field(default_factory=list)
    modified_operations: list[str] = msgspec.field(default_factory=list)
    current_hash: str | None = None
    remote_hash: str | None = None
    details: str = ""
