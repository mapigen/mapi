# src/mapi/models/request.py
from __future__ import annotations

from typing import Any

import msgspec

from .domain import HttpMethod


class RequestConfig(msgspec.Struct, frozen=True, gc=False):
    """Fully resolved HTTP request parameters."""

    method: HttpMethod
    url: str
    params: dict[str, Any] = msgspec.field(default_factory=dict)
    headers: dict[str, str] = msgspec.field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    timeout: float = 30.0


class BatchRequest(msgspec.Struct, frozen=True, gc=False):
    """An operation request specification for abatch execution."""

    provider: str
    api: str
    operation: str
    source: str | None = None
    kwargs: dict[str, Any] = msgspec.field(default_factory=dict)
    type: Any | None = None
    raw: bool = False
