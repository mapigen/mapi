from __future__ import annotations
from datetime import datetime, timezone
import logging
import time
from pathlib import Path
from typing import Any, Optional, Union

from niquests.auth import AuthBase
from niquests.exceptions import ConnectionError, HTTPError, Timeout

from ..auth import ApiKeyAuth, BearerAuth
from ..cache.service_cache import ServiceCache
from ..exceptions import (
    ClientError,
    RateLimitError,
    ServerError,
    ServiceNotFoundError,
    TransportError,
    ValidationError,
)
from ..models.config import ClientConfig
from ..models.response import MapiResult, ResponseMetadata
from ..proxy.provider import ProviderProxy
from ..registry.discovery import DiscoveryService, RegistryManager
from ..registry.loader import DiskLoader
from ..transport.niquests import NiquestsTransport
from ..validation.param_validator import ParameterValidator
from .request_builder import RequestBuilder

log = logging.getLogger("mapi")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Mapi:
    """
    Universal API client. Factory composition root.

    Synchronous usage:
        client = Mapi()
        result = client.pokeapi.REST("api_v2_pokemon_retrieve", id="ditto")
        print(result.data)

    Asynchronous usage:
        async with Mapi() as client:
            result = await client.pokeapi.REST.aexecute("api_v2_pokemon_retrieve", id="ditto")

    Authentication helpers:
        Mapi.Auth.ApiKey(key="...", name="X-API-Key")
        Mapi.Auth.Bearer("...")
    """

    class Auth:
        ApiKey = ApiKeyAuth
        Bearer = BearerAuth

    def __init__(
        self,
        config: Optional[ClientConfig] = None,
        auth: Optional[Union[AuthBase, str]] = None,
        transport: Optional[NiquestsTransport] = None,
        data_dir: Optional[Path] = None,
        registry_path: Optional[Path] = None,
        base_url: Optional[str] = None,
        **transport_kwargs: Any,
    ) -> None:
        cfg = config or ClientConfig()
        if base_url is not None:
            # Allow base_url override
            cfg = ClientConfig(
                base_url=base_url,
                default_timeout=cfg.default_timeout,
                validate_on_execute=cfg.validate_on_execute,
                pinned_services=cfg.pinned_services,
                cache_maxsize=cfg.cache_maxsize,
                log_level=cfg.log_level,
            )

        if isinstance(auth, str):
            auth = BearerAuth(auth)
        self._auth: Optional[AuthBase] = auth

        self._loader = DiskLoader(data_dir=data_dir, registry_path=registry_path)
        self._registry_mgr = RegistryManager(self._loader)
        self._discovery = DiscoveryService(self._registry_mgr, self._loader)
        self._cache = ServiceCache(
            self._loader,
            pinned_keys=frozenset(cfg.pinned_services),
            maxsize=cfg.cache_maxsize,
        )
        validator = ParameterValidator(self._cache) if cfg.validate_on_execute else None
        self._builder = RequestBuilder(self._cache, validator)
        self._transport = transport or NiquestsTransport(**transport_kwargs)
        self._config = cfg

        log.setLevel(getattr(logging, cfg.log_level.upper(), logging.INFO))

    def __getattr__(self, name: str) -> ProviderProxy:
        """Dynamically resolve provider names without intercepting real attributes."""
        try:
            if self._discovery.provider_exists(name):
                return ProviderProxy(self, name)
        except Exception:
            pass
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    @property
    def discovery(self) -> DiscoveryService:
        """Access discovery services (providers, APIs, operations)."""
        return self._discovery

    def execute(
        self, provider: str, api: str, source: str, operation: str, **kwargs: Any
    ) -> MapiResult:
        """Execute an API operation synchronously."""
        start = time.monotonic()
        service_name = f"{provider}/{api}/{source}"
        config = self._builder.build(
            provider,
            api,
            source,
            operation,
            base_url=self._config.base_url,
            timeout=self._config.default_timeout,
            **kwargs,
        )
        try:
            response = self._transport.request(config, auth=self._auth)
            duration_ms = int((time.monotonic() - start) * 1000)
            return MapiResult(
                data=response.json(),
                metadata=ResponseMetadata(
                    service=service_name,
                    operation=operation,
                    duration_ms=duration_ms,
                    status="success",
                    http_status=response.status_code,
                    timestamp=_utc_now_iso(),
                ),
            )
        except (ValidationError, ServiceNotFoundError):
            raise
        except HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            duration_ms = int((time.monotonic() - start) * 1000)
            if status == 429:
                raise RateLimitError(
                    str(exc),
                    service=service_name,
                    operation=operation,
                    http_status=status,
                    cause=exc,
                ) from exc
            elif status is not None and 500 <= status < 600:
                raise ServerError(
                    str(exc),
                    service=service_name,
                    operation=operation,
                    http_status=status,
                    cause=exc,
                ) from exc
            elif status is not None and 400 <= status < 500:
                raise ClientError(
                    str(exc),
                    service=service_name,
                    operation=operation,
                    http_status=status,
                    cause=exc,
                ) from exc
            raise TransportError(
                str(exc),
                service=service_name,
                operation=operation,
                http_status=status,
                cause=exc,
            ) from exc
        except (ConnectionError, Timeout) as exc:
            raise TransportError(
                str(exc),
                service=service_name,
                operation=operation,
                cause=exc,
            ) from exc

    async def aexecute(
        self, provider: str, api: str, source: str, operation: str, **kwargs: Any
    ) -> MapiResult:
        """Execute an API operation asynchronously."""
        start = time.monotonic()
        service_name = f"{provider}/{api}/{source}"
        config = self._builder.build(
            provider,
            api,
            source,
            operation,
            base_url=self._config.base_url,
            timeout=self._config.default_timeout,
            **kwargs,
        )
        try:
            response = await self._transport.arequest(config, auth=self._auth)
            duration_ms = int((time.monotonic() - start) * 1000)
            return MapiResult(
                data=response.json(),
                metadata=ResponseMetadata(
                    service=service_name,
                    operation=operation,
                    duration_ms=duration_ms,
                    status="success",
                    http_status=response.status_code,
                    timestamp=_utc_now_iso(),
                ),
            )
        except (ValidationError, ServiceNotFoundError):
            raise
        except HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 429:
                raise RateLimitError(
                    str(exc),
                    service=service_name,
                    operation=operation,
                    http_status=status,
                    cause=exc,
                ) from exc
            elif status is not None and 500 <= status < 600:
                raise ServerError(
                    str(exc),
                    service=service_name,
                    operation=operation,
                    http_status=status,
                    cause=exc,
                ) from exc
            elif status is not None and 400 <= status < 500:
                raise ClientError(
                    str(exc),
                    service=service_name,
                    operation=operation,
                    http_status=status,
                    cause=exc,
                ) from exc
            raise TransportError(
                str(exc),
                service=service_name,
                operation=operation,
                http_status=status,
                cause=exc,
            ) from exc
        except (ConnectionError, Timeout) as exc:
            raise TransportError(
                str(exc),
                service=service_name,
                operation=operation,
                cause=exc,
            ) from exc

    def clear_cache(self) -> None:
        """Flush the in-memory service definitions cache."""
        self._cache.clear()

    # --- Context Managers ---

    def __enter__(self) -> "Mapi":
        return self

    def __exit__(self, *_: Any) -> None:
        self._transport.close()

    async def __aenter__(self) -> "Mapi":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._transport.aclose()

    def __repr__(self) -> str:
        return f"Mapi(base_url={self._config.base_url!r})"
