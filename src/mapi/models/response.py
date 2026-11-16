# src/mapi/models/response.py
from __future__ import annotations
from typing import Any, Literal, Optional
import msgspec


class ResponseMetadata(msgspec.Struct, frozen=True):
    """Telemetry for a completed API call."""
    service: str
    operation: str
    duration_ms: int
    status: Literal["success", "error"]
    http_status: Optional[int] = None
    timestamp: str = ""
    error_type: Optional[str] = None
    error_category: Optional[str] = None


class MapiResult(msgspec.Struct, frozen=True):
    """The single return type for all execute() / aexecute() calls."""
    data: Optional[Any]
    metadata: ResponseMetadata
