# src/mapi/models/config.py
from __future__ import annotations

import os

import msgspec

from ..constants import (
    DEFAULT_HEADERS,
    ENV_MAPI_CACHE_MAXSIZE,
    ENV_MAPI_PINNED_SERVICES,
    ENV_MAPI_SERVER_PATTERN,
    ENV_MAPI_SERVER_TAG,
)


def _default_headers() -> dict[str, str]:
    return dict(DEFAULT_HEADERS)


class ClientConfig(msgspec.Struct, frozen=True, gc=False):
    """Immutable client configuration."""

    base_url: str | None = None
    default_timeout: float = 30.0
    validate_on_execute: bool = True
    pinned_services: tuple[str, ...] = ()
    cache_maxsize: int = 64
    log_level: str = "INFO"
    multiplexed: bool = True
    retries: int = 0
    server_variables: dict[str, str] = msgspec.field(default_factory=dict)
    default_headers: dict[str, str] = msgspec.field(default_factory=_default_headers)
    server_pattern: str | None = None
    server_tag: str | None = None

    @classmethod
    def from_env(cls) -> ClientConfig:
        """Create config from environment variables (MAPI_* prefix)."""
        server_tag = os.environ.get(ENV_MAPI_SERVER_TAG) or os.environ.get(ENV_MAPI_SERVER_PATTERN)
        return cls(
            cache_maxsize=int(os.environ.get(ENV_MAPI_CACHE_MAXSIZE, 64)),
            pinned_services=tuple(
                s.strip()
                for s in os.environ.get(ENV_MAPI_PINNED_SERVICES, "").split(",")
                if s.strip()
            ),
            server_tag=server_tag,
            server_pattern=server_tag,
        )
