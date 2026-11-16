# src/mapi/models/response.py
from __future__ import annotations

from typing import Any, Literal

import msgspec


class ResponseMetadata(msgspec.Struct, frozen=True, gc=False):
    """Telemetry for a completed API call."""

    service: str
    operation: str
    duration_ms: int
    status: Literal["success", "error"]
    http_status: int | None = None
    network_duration_ms: int | None = None
    headers: dict[str, str] = msgspec.field(default_factory=dict)
    timestamp: str = ""
    error_type: str | None = None
    error_category: str | None = None


class MapiResult(msgspec.Struct, frozen=True):
    """The single return type for all execute() / aexecute() calls."""

    data: Any | None
    metadata: ResponseMetadata
