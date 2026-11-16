# src/mapi/models/response.py
from __future__ import annotations

import contextlib
from typing import Any, Literal

import msgspec

from ..constants import (
    HEADER_CONTENT_TYPE_LOWER,
    HEADER_ETAG_LOWER,
    HEADER_RATELIMIT_LIMIT,
    HEADER_RATELIMIT_REMAINING,
    HEADER_RATELIMIT_RESET,
    HEADER_RETRY_AFTER_LOWER,
    HEADER_X_RATELIMIT_LIMIT,
    HEADER_X_RATELIMIT_REMAINING,
    HEADER_X_RATELIMIT_RESET,
)


class HeadersDict(dict[str, str]):
    """Case-insensitive dictionary for HTTP response headers preserving original casing."""

    __slots__ = ("_lower_map",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lower_map: dict[str, str] | None = None

    def _ensure_lower(self) -> dict[str, str]:
        if self._lower_map is None:
            self._lower_map = {str(k).lower(): str(v) for k, v in self.items()}
        return self._lower_map

    def __getitem__(self, key: str) -> str:
        k_lower = str(key).lower()
        lower_map = self._ensure_lower()
        if k_lower in lower_map:
            return lower_map[k_lower]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        k_lower = str(key).lower()
        return self._ensure_lower().get(k_lower, default)

    def __contains__(self, key: object) -> bool:
        return str(key).lower() in self._ensure_lower()


_EMPTY_HEADERS: HeadersDict = HeadersDict()


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
        return self._get_header(HEADER_CONTENT_TYPE_LOWER)

    @property
    def etag(self) -> str | None:
        """ETag header value."""
        return self._get_header(HEADER_ETAG_LOWER)

    @property
    def retry_after(self) -> float | None:
        """Retry-After header value in seconds, if present and parseable."""
        val = self._get_header(HEADER_RETRY_AFTER_LOWER)
        if val is None:
            return None
        with contextlib.suppress(ValueError):
            return float(val)
        return None

    @property
    def rate_limit_limit(self) -> int | None:
        """Rate limit maximum request quota."""
        val = self._get_header(HEADER_X_RATELIMIT_LIMIT) or self._get_header(HEADER_RATELIMIT_LIMIT)
        if val is not None:
            with contextlib.suppress(ValueError):
                return int(val)
        return None

    @property
    def rate_limit_remaining(self) -> int | None:
        """Rate limit remaining request quota."""
        val = self._get_header(HEADER_X_RATELIMIT_REMAINING) or self._get_header(HEADER_RATELIMIT_REMAINING)
        if val is not None:
            with contextlib.suppress(ValueError):
                return int(val)
        return None

    @property
    def rate_limit_reset(self) -> int | None:
        """Rate limit reset epoch or delta."""
        val = self._get_header(HEADER_X_RATELIMIT_RESET) or self._get_header(HEADER_RATELIMIT_RESET)
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
