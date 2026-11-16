# src/mapi/models/response.py
from __future__ import annotations

import contextlib
from typing import Any, Literal

import msgspec


class HeadersDict(dict[str, str]):
    """Case-insensitive dictionary for HTTP response headers preserving original casing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lower_map: dict[str, str] = {str(k).lower(): str(v) for k, v in self.items()}

    def __getitem__(self, key: str) -> str:
        k_lower = str(key).lower()
        if k_lower in self._lower_map:
            return self._lower_map[k_lower]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        k_lower = str(key).lower()
        return self._lower_map.get(k_lower, default)

    def __contains__(self, key: object) -> bool:
        return str(key).lower() in self._lower_map


class ResponseMetadata(msgspec.Struct, frozen=True, gc=False):
    """Telemetry for a completed API call."""

    service: str
    operation: str
    duration_ms: int
    status: Literal["success", "error", "dry_run"]
    http_status: int | None = None
    network_duration_ms: int | None = None
    headers: dict[str, str] = msgspec.field(default_factory=dict)
    timestamp: str = ""
    error_type: str | None = None
    error_category: str | None = None

    @property
    def content_type(self) -> str | None:
        """Content-Type header value."""
        return self._get_header("content-type")

    @property
    def etag(self) -> str | None:
        """ETag header value."""
        return self._get_header("etag")

    @property
    def retry_after(self) -> float | None:
        """Retry-After header value in seconds, if present and parseable."""
        val = self._get_header("retry-after")
        if val is None:
            return None
        with contextlib.suppress(ValueError):
            return float(val)
        return None

    @property
    def rate_limit_limit(self) -> int | None:
        """Rate limit maximum request quota."""
        val = self._get_header("x-ratelimit-limit") or self._get_header("ratelimit-limit")
        if val is not None:
            with contextlib.suppress(ValueError):
                return int(val)
        return None

    @property
    def rate_limit_remaining(self) -> int | None:
        """Rate limit remaining request quota."""
        val = self._get_header("x-ratelimit-remaining") or self._get_header("ratelimit-remaining")
        if val is not None:
            with contextlib.suppress(ValueError):
                return int(val)
        return None

    @property
    def rate_limit_reset(self) -> int | None:
        """Rate limit reset epoch or delta."""
        val = self._get_header("x-ratelimit-reset") or self._get_header("ratelimit-reset")
        if val is not None:
            with contextlib.suppress(ValueError):
                return int(val)
        return None

    def _get_header(self, name: str) -> str | None:
        """Case-insensitive header retrieval."""
        lower = name.lower()
        if lower in self.headers:
            return self.headers[lower]
        for k, v in self.headers.items():
            if k.lower() == lower:
                return v
        return None


class MapiResult(msgspec.Struct, frozen=True):
    """The single return type for all execute() / aexecute() calls."""

    data: Any | None
    metadata: ResponseMetadata
