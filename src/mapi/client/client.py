from __future__ import annotations
from datetime import datetime, timezone
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, NoReturn, Optional, TypeVar, Union

import msgspec
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
from ..models.request import RequestConfig
from ..models.response import MapiResult, ResponseMetadata
from ..proxy.provider import ProviderProxy
from ..registry.discovery import DiscoveryService, RegistryManager
from ..registry.loader import DiskLoader
from ..transport.niquests import NiquestsTransport
from ..validation.param_validator import ParameterValidator
from .request_builder import RequestBuilder

log = logging.getLogger("mapi")
T = TypeVar("T")


def _utc_now_iso() -> str:
    """Return ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_ms(seconds: float) -> int:
    """Convert elapsed seconds to integer milliseconds (non-negative)."""
    return max(0, int(round(seconds * 1000)))


def _measure(fn: Callable[..., T], *args: Any, **kwargs: Any) -> tuple[T, float]:
    """Execute a synchronous callable and return (result, elapsed_seconds)."""
    t0 = time.perf_counter()
    return fn(*args, **kwargs), time.perf_counter() - t0


async def _ameasure(coro: Awaitable[T]) -> tuple[T, float]:
    """Await an asynchronous coroutine and return (result, elapsed_seconds)."""
    t0 = time.perf_counter()
    return await coro, time.perf_counter() - t0


def _build_result(
    service_name: str,
    operation: str,
    status_code: int,
    data: Any,
    ops_time: float,
    net_time: float,
) -> MapiResult:
    """Construct an immutable MapiResult with isolated ops vs network telemetry."""
    return MapiResult(
        data=data,
        metadata=ResponseMetadata(
            service=service_name,
            operation=operation,
            duration_ms=_to_ms(ops_time),
            network_duration_ms=_to_ms(net_time),
            status="success",
            http_status=status_code,
            timestamp=_utc_now_iso(),
        ),
    )


def _handle_transport_error(exc: Exception, service_name: str, operation: str) -> NoReturn:
    """Map transport-level errors to domain-specific MapiError hierarchy."""
    if isinstance(exc, HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status == 429:
            raise RateLimitError(
                str(exc), service=service_name, operation=operation, http_status=status, cause=exc
            ) from exc
        elif status is not None and 500 <= status < 600:
            raise ServerError(
                str(exc), service=service_name, operation=operation, http_status=status, cause=exc
            ) from exc
        elif status is not None and 400 <= status < 500:
            raise ClientError(
                str(exc), service=service_name, operation=operation, http_status=status, cause=exc
            ) from exc
        raise TransportError(
            str(exc), service=service_name, operation=operation, http_status=status, cause=exc
        ) from exc
    elif isinstance(exc, (ConnectionError, Timeout)):
        raise TransportError(
            str(exc), service=service_name, operation=operation, cause=exc
        ) from exc
    raise exc


class Mapi:
    """
    Universal API client. Factory composition root.

    Synchronous usage:
        client = Mapi()
        result = client.pokeapi.REST("pokemon_retrieve", id="ditto")
        print(result.data)

    Asynchronous usage:
        async with Mapi() as client:
            result = await client.pokeapi.REST.aexecute("pokemon_retrieve", id="ditto")

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
        self._json_decoder = msgspec.json.Decoder()

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

    def _prepare_request(
        self, provider: str, api: str, source: str, operation: str, kwargs: dict[str, Any]
    ) -> tuple[str, RequestConfig]:
        """Validate parameters and build RequestConfig."""
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
        return service_name, config

    def _decode_response(self, response: Any) -> Any:
        """Decode response body directly with msgspec C decoder, falling back to response.json()."""
        content = getattr(response, "content", None)
        if isinstance(content, (bytes, bytearray, memoryview)) and content:
            try:
                return self._json_decoder.decode(content)
            except Exception:
                pass
        if hasattr(response, "json") and callable(response.json):
            try:
                return response.json()
            except Exception:
                return None
        return None

    def execute(
        self, provider: str, api: str, source: str, operation: str, **kwargs: Any
    ) -> MapiResult:
        """Execute an API operation synchronously."""
        (service_name, config), prep_time = _measure(
            self._prepare_request, provider, api, source, operation, kwargs
        )
        try:
            response, net_time = _measure(self._transport.request, config, auth=self._auth)
            data, post_time = _measure(self._decode_response, response)
            return _build_result(
                service_name, operation, response.status_code, data, prep_time + post_time, net_time
            )
        except (ValidationError, ServiceNotFoundError):
            raise
        except Exception as exc:
            _handle_transport_error(exc, service_name, operation)

    async def aexecute(
        self, provider: str, api: str, source: str, operation: str, **kwargs: Any
    ) -> MapiResult:
        """Execute an API operation asynchronously."""
        (service_name, config), prep_time = _measure(
            self._prepare_request, provider, api, source, operation, kwargs
        )
        try:
            response, net_time = await _ameasure(
                self._transport.arequest(config, auth=self._auth)
            )
            data, post_time = _measure(self._decode_response, response)
            return _build_result(
                service_name, operation, response.status_code, data, prep_time + post_time, net_time
            )
        except (ValidationError, ServiceNotFoundError):
            raise
        except Exception as exc:
            _handle_transport_error(exc, service_name, operation)

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
