# src/mapi/models/config.py
from __future__ import annotations

import os

import msgspec


class ClientConfig(msgspec.Struct, frozen=True):
    """Immutable client configuration."""

    base_url: str | None = None
    default_timeout: float = 30.0
    validate_on_execute: bool = True
    pinned_services: tuple[str, ...] = ()
    cache_maxsize: int = 64
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> ClientConfig:
        """Create config from environment variables (MAPI_* prefix)."""
        return cls(
            cache_maxsize=int(os.environ.get("MAPI_CACHE_MAXSIZE", 64)),
            pinned_services=tuple(
                s.strip()
                for s in os.environ.get("MAPI_PINNED_SERVICES", "").split(",")
                if s.strip()
            ),
        )
