# src/mapi/client/client.py
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any

import msgspec
from niquests.auth import AuthBase

from ..auth import ApiKeyAuth, BearerAuth
from ..cache.hot_cache import HotOpCache
from ..cache.service_cache import ServiceCache
from ..models.config import ClientConfig
from ..models.domain import SpecDiffResult
from ..models.request import BatchRequest, RequestConfig
from ..models.response import MapiResult
from ..proxy.provider import ProviderProxy
from ..registry.discovery import DiscoveryService, RegistryManager
from ..registry.loader import DiskLoader
from ..transport.niquests import NiquestsTransport
from ..validation.param_validator import ParameterValidator
from .dynamic import DynamicSpecService
from .execution import RequestExecutor
from .pagination import PaginationService
from .request_builder import RequestBuilder
from .tools import ToolService

log = logging.getLogger("mapi")


class Mapi:
    """
    Universal API client.

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
        config: ClientConfig | None = None,
        auth: AuthBase | str | None = None,
        transport: NiquestsTransport | None = None,
        data_dir: Path | None = None,
        registry_path: Path | None = None,
        packfile_path: Path | None = None,
        base_url: str | None = None,
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
                multiplexed=cfg.multiplexed,
                retries=cfg.retries,
                server_variables=cfg.server_variables,
                default_headers=cfg.default_headers,
                server_pattern=cfg.server_pattern,
                server_tag=cfg.server_tag,
            )

        if isinstance(auth, str):
            auth = BearerAuth(auth)
        self._auth: AuthBase | None = auth
        self._config = cfg

        # 1. Registry & Caching infrastructure
        self._loader = DiskLoader(
            data_dir=data_dir, registry_path=registry_path, packfile_path=packfile_path
        )
        self._registry_mgr = RegistryManager(self._loader)
        self._cache = ServiceCache(
            self._loader,
            pinned_keys=frozenset(cfg.pinned_services),
            maxsize=cfg.cache_maxsize,
        )
        self._discovery = DiscoveryService(self._registry_mgr, self._loader, cache=self._cache)
        self._hot_op_cache = HotOpCache(maxsize=cfg.cache_maxsize * 8)

        # 2. Request building & Validation
        validator = ParameterValidator(self._cache) if cfg.validate_on_execute else None
        self._builder = RequestBuilder(self._cache, validator, hot_cache=self._hot_op_cache)

        # 3. HTTP Transport
        transport_kwargs.setdefault("multiplexed", cfg.multiplexed)
        transport_kwargs.setdefault("retries", cfg.retries)
        self._transport = transport or NiquestsTransport(**transport_kwargs)

        # 4. Decoders
        self._json_decoder = msgspec.json.Decoder()
        self._typed_decoders: dict[Any, msgspec.json.Decoder[Any]] = {}

        # 5. Modular sub-services bound to this client instance
        self._executor = RequestExecutor(self)
        self._tools = ToolService(self)
        self._dynamic = DynamicSpecService(self)
        self._paginator = PaginationService(self)

        # 6. Fluent proxy cache
        self._provider_proxies: dict[str, ProviderProxy] = {}

        log.setLevel(getattr(logging, cfg.log_level.upper(), logging.INFO))

    def __getattr__(self, name: str) -> ProviderProxy:
        """Dynamically resolve provider names without intercepting real attributes."""
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
        proxies = getattr(self, "_provider_proxies", None)
        if proxies is not None:
            proxy = proxies.get(name)
            if proxy is not None:
                return proxy
        try:
            if hasattr(self, "_discovery") and self._discovery.provider_exists(name):
                p = ProviderProxy(self, name)
                if proxies is not None:
                    proxies[name] = p
                return p
        except Exception:
            pass
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    @property
    def discovery(self) -> DiscoveryService:
        """Access discovery services (providers, APIs, operations)."""
        return self._discovery

    def _prepare_request(
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        kwargs: dict[str, Any],
        idempotent: bool = False,
    ) -> tuple[str, RequestConfig]:
        """Validate parameters and build RequestConfig (delegates to executor)."""
        try:
            return self._executor.prepare_request(
                provider, api, source, operation, kwargs, idempotent=idempotent
            )
        except AttributeError:
            executor = RequestExecutor(self)
            self._executor = executor
            return executor.prepare_request(
                provider, api, source, operation, kwargs, idempotent=idempotent
            )

    def _decode_response(
        self,
        response: Any,
        target_type: Any = None,
        raw: bool = False,
    ) -> Any:
        """Decode response body (delegates to executor)."""
        try:
            return self._executor.decode_response(response, target_type=target_type, raw=raw)
        except AttributeError:
            executor = RequestExecutor(self)
            self._executor = executor
            return executor.decode_response(response, target_type=target_type, raw=raw)

    def execute(
        self,
        provider: str,
        api: str,
        source: str | None,
        operation: str,
        *,
        _type: Any = None,
        _raw: bool = False,
        _dry_run: bool = False,
        _idempotent: bool = False,
        _stream: bool = False,
        **kwargs: Any,
    ) -> MapiResult:
        """Execute an API operation synchronously."""
        try:
            return self._executor.execute(
                provider,
                api,
                source,
                operation,
                _type=_type,
                _raw=_raw,
                _dry_run=_dry_run,
                _idempotent=_idempotent,
                _stream=_stream,
                **kwargs,
            )
        except AttributeError:
            executor = RequestExecutor(self)
            self._executor = executor
            return executor.execute(
                provider,
                api,
                source,
                operation,
                _type=_type,
                _raw=_raw,
                _dry_run=_dry_run,
                _idempotent=_idempotent,
                _stream=_stream,
                **kwargs,
            )

    async def aexecute(
        self,
        provider: str,
        api: str,
        source: str | None,
        operation: str,
        *,
        _type: Any = None,
        _raw: bool = False,
        _dry_run: bool = False,
        _idempotent: bool = False,
        _stream: bool = False,
        **kwargs: Any,
    ) -> MapiResult:
        """Execute an API operation asynchronously."""
        executor = getattr(self, "_executor", None)
        if executor is None:
            executor = RequestExecutor(self)
            self._executor = executor
        return await executor.aexecute(
            provider,
            api,
            source,
            operation,
            _type=_type,
            _raw=_raw,
            _dry_run=_dry_run,
            _idempotent=_idempotent,
            _stream=_stream,
            **kwargs,
        )

    def batch(
        self,
        requests: Sequence[BatchRequest | tuple[str, str, str, dict[str, Any]]],
        *,
        return_exceptions: bool = False,
    ) -> list[Any]:
        """Execute multiple API operations synchronously in a sequential loop."""
        executor = getattr(self, "_executor", None)
        if executor is None:
            executor = RequestExecutor(self)
            self._executor = executor
        return executor.batch(requests, return_exceptions=return_exceptions)

    async def abatch(
        self,
        requests: Sequence[BatchRequest | tuple[str, str, str, dict[str, Any]]],
        *,
        max_concurrency: int = 10,
        return_exceptions: bool = False,
    ) -> list[Any]:
        """Execute multiple API operations concurrently with bounded concurrency."""
        executor = getattr(self, "_executor", None)
        if executor is None:
            executor = RequestExecutor(self)
            self._executor = executor
        return await executor.abatch(
            requests, max_concurrency=max_concurrency, return_exceptions=return_exceptions
        )

    # --- LLM Function Calling & AI Ergonomics ---

    def to_tool(
        self,
        provider: str,
        api: str,
        operation: str,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Export standard JSON Schema / OpenAI function calling definition for an operation."""
        tools = getattr(self, "_tools", None)
        if tools is None:
            tools = ToolService(self)
            self._tools = tools
        return tools.to_tool(provider, api, operation, source=source)

    def call_tool(self, tool_name: str, **arguments: Any) -> MapiResult:
        """Execute a function call returned by an LLM (e.g. 'pokeapi_REST_pokemon_retrieve')."""
        tools = getattr(self, "_tools", None)
        if tools is None:
            tools = ToolService(self)
            self._tools = tools
        return tools.call_tool(tool_name, **arguments)

    # --- Dynamic Spec Registration & Update Lifecycle ---

    def register_spec(
        self,
        spec_source: str | Path | dict[str, Any],
        provider: str | None = None,
        api: str = "REST",
        source: str = "dynamic",
    ) -> str:
        """Dynamically register an OpenAPI specification at runtime."""
        dynamic = getattr(self, "_dynamic", None)
        if dynamic is None:
            dynamic = DynamicSpecService(self)
            self._dynamic = dynamic
        return dynamic.register_spec(spec_source, provider=provider, api=api, source=source)

    def check_spec_diff(
        self,
        provider: str,
        api: str = "REST",
        spec_source: str | Path | dict[str, Any] | None = None,
        source: str = "dynamic",
    ) -> SpecDiffResult:
        """Check if an upstream specification has differences compared to active spec."""
        dynamic = getattr(self, "_dynamic", None)
        if dynamic is None:
            dynamic = DynamicSpecService(self)
            self._dynamic = dynamic
        return dynamic.check_spec_diff(provider, api=api, spec_source=spec_source, source=source)

    def update_spec(
        self,
        provider: str,
        api: str = "REST",
        spec_source: str | Path | dict[str, Any] | None = None,
        source: str = "dynamic",
        force: bool = False,
    ) -> bool:
        """Atomically update an existing spec in-place with zero downtime for readers."""
        dynamic = getattr(self, "_dynamic", None)
        if dynamic is None:
            dynamic = DynamicSpecService(self)
            self._dynamic = dynamic
        return dynamic.update_spec(
            provider, api=api, spec_source=spec_source, source=source, force=force
        )

    # --- Auto-Pagination ---

    def paginate(
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        *,
        max_pages: int = 100,
        _type: Any = None,
        _raw: bool = False,
        **kwargs: Any,
    ) -> Iterator[MapiResult]:
        """Automatically paginate through results of an API operation."""
        paginator = getattr(self, "_paginator", None)
        if paginator is None:
            paginator = PaginationService(self)
            self._paginator = paginator
        return paginator.paginate(
            provider,
            api,
            source,
            operation,
            max_pages=max_pages,
            _type=_type,
            _raw=_raw,
            **kwargs,
        )

    def apaginate(
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        *,
        max_pages: int = 100,
        _type: Any = None,
        _raw: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[MapiResult]:
        """Asynchronously paginate through results of an API operation."""
        paginator = getattr(self, "_paginator", None)
        if paginator is None:
            paginator = PaginationService(self)
            self._paginator = paginator
        return paginator.apaginate(
            provider,
            api,
            source,
            operation,
            max_pages=max_pages,
            _type=_type,
            _raw=_raw,
            **kwargs,
        )

    def clear_cache(self) -> None:
        """Flush in-memory service definitions cache, hot op cache, decoders, and path cache."""
        if hasattr(self, "_cache"):
            self._cache.clear()
        if hasattr(self, "_hot_op_cache"):
            self._hot_op_cache.clear()
        if hasattr(self, "_loader") and hasattr(self._loader, "clear_cache"):
            self._loader.clear_cache()
        if hasattr(self, "_typed_decoders"):
            self._typed_decoders.clear()
        if hasattr(self, "_builder") and self._builder._validator is not None:
            self._builder._validator.clear_cache()
        if hasattr(self, "_provider_proxies"):
            self._provider_proxies.clear()

    # --- Context Managers ---

    def __enter__(self) -> Mapi:
        return self

    def __exit__(self, *_: Any) -> None:
        self._transport.close()

    async def __aenter__(self) -> Mapi:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._transport.aclose()

    def __repr__(self) -> str:
        base_url = getattr(self, "_config", ClientConfig()).base_url
        return f"Mapi(base_url={base_url!r})"
