# src/mapi/models/request.py
from __future__ import annotations
from typing import Any, Dict, Optional
import msgspec
from .domain import HttpMethod


class RequestConfig(msgspec.Struct, frozen=True, gc=False):
    """Fully resolved HTTP request parameters."""
    method: HttpMethod
    url: str
    params: Dict[str, Any] = msgspec.field(default_factory=dict)
    headers: Dict[str, str] = msgspec.field(default_factory=dict)
    json_body: Optional[Dict[str, Any]] = None
    timeout: float = 30.0
