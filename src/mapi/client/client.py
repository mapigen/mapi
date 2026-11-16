from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.parse
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, TypeVar

import msgspec
from niquests.auth import AuthBase
from niquests.exceptions import ConnectionError, HTTPError, Timeout

from ..auth import ApiKeyAuth, BearerAuth
from ..cache.hot_cache import HotOpCache
from ..cache.service_cache import ServiceCache
from ..exceptions import (
    ClientError,
    RateLimitError,
    ServerError,
    ServiceNotFoundError,
    SpecUpdateAvailableWarning,
    TransportError,
    ValidationError,
)
from ..models.config import ClientConfig
from ..models.domain import ParameterRef
from ..models.registry import ApiInfo, ServiceRegistry
from ..models.request import BatchRequest, RequestConfig
from ..models.response import HeadersDict, MapiResult, ResponseMetadata
from ..models.spec import SpecDiffResult
from ..proxy.provider import ProviderProxy
from ..registry.discovery import DiscoveryService, RegistryManager
from ..registry.loader import DiskLoader
from ..registry.spec_compiler import compile_spec, infer_provider
from ..transport.niquests import NiquestsTransport
from ..validation.param_validator import ParameterValidator
from .request_builder import RequestBuilder

log = logging.getLogger("mapi")
T = TypeVar("T")


def _utc_now_iso() -> str:
    """Return ISO 8601 UTC timestamp."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    status_code: int | None,
    data: Any,
    ops_time: float,
    net_time: float,
    headers: dict[str, str] | None = None,
) -> MapiResult:
    """Construct an immutable MapiResult with isolated ops vs network telemetry."""
    return MapiResult(
        data=data,
        metadata=ResponseMetadata(
            service=service_name,
            operation=operation,
            duration_ms=_to_ms(ops_time),
            network_duration_ms=_to_ms(net_time),
            headers=headers or {},
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
        validator = ParameterValidator(self._cache) if cfg.validate_on_execute else None
        self._builder = RequestBuilder(self._cache, validator, hot_cache=self._hot_op_cache)
        transport_kwargs.setdefault("multiplexed", cfg.multiplexed)
        transport_kwargs.setdefault("retries", cfg.retries)
        self._transport = transport or NiquestsTransport(**transport_kwargs)
        self._config = cfg
        self._json_decoder = msgspec.json.Decoder()
        self._typed_decoders: dict[Any, msgspec.json.Decoder[Any]] = {}
        self._registered_specs: dict[tuple[str, str], Any] = {}

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
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        kwargs: dict[str, Any],
        idempotent: bool = False,
    ) -> tuple[str, RequestConfig]:
        """Validate parameters and build RequestConfig."""
        service_name = f"{provider}/{api}/{source}"
        config = self._builder.build(
            provider,
            api,
            source,
            operation,
            base_url=self._config.base_url,
            server_variables=self._config.server_variables,
            default_headers=self._config.default_headers,
            server_pattern=self._config.server_pattern,
            server_tag=self._config.server_tag,
            idempotent=idempotent,
            timeout=self._config.default_timeout,
            **kwargs,
        )
        return service_name, config

    def _decode_response(
        self,
        response: Any,
        target_type: Any = None,
        raw: bool = False,
    ) -> Any:
        """Decode response body directly with msgspec C decoder, falling back to response.json()."""
        content = getattr(response, "content", None)
        if raw:
            return (
                msgspec.Raw(content)
                if isinstance(content, (bytes, bytearray, memoryview))
                else content
            )

        if isinstance(content, (bytes, bytearray, memoryview)) and content:
            if target_type is not None:
                decoders = getattr(self, "_typed_decoders", None)
                if decoders is not None:
                    decoder = decoders.get(target_type)
                    if decoder is None:
                        decoder = msgspec.json.Decoder(target_type)
                        decoders[target_type] = decoder
                    return decoder.decode(content)
                return msgspec.json.decode(content, type=target_type)
            try:
                decoder = getattr(self, "_json_decoder", None)
                if decoder is not None:
                    return decoder.decode(content)
                return msgspec.json.decode(content)
            except Exception:
                pass
        if hasattr(response, "json") and callable(response.json):
            try:
                return response.json()
            except Exception:
                return None
        return None

    def execute(
        self,
        provider: str,
        api: str,
        source: str,
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
        target_type = _type or kwargs.pop("target_type", None) or kwargs.pop("_type", None)
        raw = _raw or kwargs.pop("raw", False) or kwargs.pop("_raw", False)
        dry_run = _dry_run or kwargs.pop("dry_run", False) or kwargs.pop("_dry_run", False)
        idempotent = (
            _idempotent or kwargs.pop("idempotent", False) or kwargs.pop("_idempotent", False)
        )
        stream = _stream or kwargs.pop("stream", False) or kwargs.pop("_stream", False)

        (service_name, config), prep_time = _measure(
            self._prepare_request, provider, api, source, operation, kwargs, idempotent=idempotent
        )

        if dry_run:
            return MapiResult(
                data=config,
                metadata=ResponseMetadata(
                    service=service_name,
                    operation=operation,
                    duration_ms=_to_ms(prep_time),
                    network_duration_ms=0,
                    headers=HeadersDict(config.headers),
                    status="dry_run",
                    http_status=None,
                    timestamp=_utc_now_iso(),
                ),
            )

        try:
            response, net_time = _measure(
                self._transport.request, config, auth=self._auth, stream=stream
            )
            raw_headers = getattr(response, "headers", None)
            resp_headers = (
                HeadersDict(raw_headers) if isinstance(raw_headers, Mapping) else HeadersDict()
            )
            if stream:
                data = getattr(response, "iter_content", lambda: response)()
                post_time = 0.0
            else:
                data, post_time = _measure(self._decode_response, response, target_type, raw)

            return _build_result(
                service_name,
                operation,
                response.status_code,
                data,
                prep_time + post_time,
                net_time,
                headers=resp_headers,
            )
        except (ValidationError, ServiceNotFoundError):
            raise
        except Exception as exc:
            _handle_transport_error(exc, service_name, operation)

    async def aexecute(
        self,
        provider: str,
        api: str,
        source: str,
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
        target_type = _type or kwargs.pop("target_type", None) or kwargs.pop("_type", None)
        raw = _raw or kwargs.pop("raw", False) or kwargs.pop("_raw", False)
        dry_run = _dry_run or kwargs.pop("dry_run", False) or kwargs.pop("_dry_run", False)
        idempotent = (
            _idempotent or kwargs.pop("idempotent", False) or kwargs.pop("_idempotent", False)
        )
        stream = _stream or kwargs.pop("stream", False) or kwargs.pop("_stream", False)

        (service_name, config), prep_time = _measure(
            self._prepare_request, provider, api, source, operation, kwargs, idempotent=idempotent
        )

        if dry_run:
            return MapiResult(
                data=config,
                metadata=ResponseMetadata(
                    service=service_name,
                    operation=operation,
                    duration_ms=_to_ms(prep_time),
                    network_duration_ms=0,
                    headers=HeadersDict(config.headers),
                    status="dry_run",
                    http_status=None,
                    timestamp=_utc_now_iso(),
                ),
            )

        try:
            response, net_time = await _ameasure(
                self._transport.arequest(config, auth=self._auth, stream=stream)
            )
            raw_headers = getattr(response, "headers", None)
            resp_headers = (
                HeadersDict(raw_headers) if isinstance(raw_headers, Mapping) else HeadersDict()
            )
            if stream:
                data = getattr(response, "iter_content", lambda: response)()
                post_time = 0.0
            else:
                data, post_time = _measure(self._decode_response, response, target_type, raw)

            return _build_result(
                service_name,
                operation,
                response.status_code,
                data,
                prep_time + post_time,
                net_time,
                headers=resp_headers,
            )
        except (ValidationError, ServiceNotFoundError):
            raise
        except Exception as exc:
            _handle_transport_error(exc, service_name, operation)

    async def abatch(
        self,
        requests: Sequence[BatchRequest | tuple[str, str, str, dict[str, Any]]],
        *,
        max_concurrency: int = 10,
        return_exceptions: bool = False,
    ) -> list[Any]:
        """
        Execute multiple API operations concurrently with bounded concurrency.

        Accepts a sequence of BatchRequest instances or (provider, api, operation, kwargs) tuples.
        """
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run_single(
            req: BatchRequest | tuple[str, str, str, dict[str, Any]],
        ) -> MapiResult:
            async with semaphore:
                if isinstance(req, BatchRequest):
                    source = (
                        req.source or self._discovery.get_api_info(req.provider, req.api).sources[0]
                    )
                    return await self.aexecute(
                        req.provider,
                        req.api,
                        source,
                        req.operation,
                        _type=req.type,
                        _raw=req.raw,
                        **req.kwargs,
                    )
                provider, api, operation, kw = req
                source = self._discovery.get_api_info(provider, api).sources[0]
                return await self.aexecute(provider, api, source, operation, **kw)

        tasks = [_run_single(req) for req in requests]
        return list(await asyncio.gather(*tasks, return_exceptions=return_exceptions))

    # --- LLM Function Calling & AI Ergonomics ---

    def to_tool(
        self,
        provider: str,
        api: str,
        operation: str,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Export standard JSON Schema / OpenAI function calling definition for an operation."""
        src = source or self._discovery.get_api_info(provider, api).sources[0]
        service_data = self._cache.get(provider, api, src)
        op = service_data.operations.get(operation)
        if op is None:
            raise ServiceNotFoundError(
                f"Operation '{operation}' not found in '{provider}/{api}/{src}'",
                service=f"{provider}/{api}/{src}",
                operation=operation,
            )

        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_union in op.parameters:
            if isinstance(param_union, ParameterRef):
                param = service_data.components.parameters.get(param_union.component_name)
            else:
                param = param_union

            if param is None:
                continue

            param_schema = dict(param.schema_) if param.schema_ else {}
            prop_def: dict[str, Any] = {
                "type": param_schema.get("type", "string"),
            }
            if param.description:
                prop_def["description"] = param.description
            elif "description" in param_schema:
                prop_def["description"] = param_schema["description"]
            if "enum" in param_schema:
                prop_def["enum"] = param_schema["enum"]
            if "default" in param_schema:
                prop_def["default"] = param_schema["default"]

            properties[param.name] = prop_def
            if param.required:
                required.append(param.name)

        func_name = f"{provider}_{api}_{operation}".replace("-", "_")
        return {
            "type": "function",
            "function": {
                "name": func_name,
                "description": op.summary
                or op.description
                or f"Execute {operation} on {provider}/{api}",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def call_tool(self, tool_name: str, **arguments: Any) -> MapiResult:
        """Execute a function call returned by an LLM (e.g. 'pokeapi_REST_pokemon_retrieve')."""
        parts = tool_name.split("_", 2)
        if len(parts) < 3:
            raise ValueError(
                f"Invalid tool_name format '{tool_name}'. Expected format: '<provider>_<api>_<operation>'"
            )
        provider, api, operation = parts[0], parts[1], parts[2]
        info = self._discovery.get_api_info(provider, api)
        return self.execute(provider, api, info.sources[0], operation, **arguments)

    # --- Dynamic Spec Registration & Update Lifecycle ---

    def register_spec(
        self,
        spec_source: str | Path | dict[str, Any],
        provider: str | None = None,
        api: str = "REST",
        source: str = "dynamic",
    ) -> str:
        """
        Dynamically register an OpenAPI specification at runtime.

        :param spec_source: OpenAPI spec dict, JSON/YAML string, URL, or Path.
        :param provider: Optional provider name. If None, auto-inferred from servers URL or title.
        :param api: API identifier (default 'REST').
        :param source: Source identifier (default 'dynamic').
        :return: The resolved provider name.
        """
        spec = self._resolve_spec_source(spec_source)
        resolved_provider = provider or infer_provider(
            spec, str(spec_source) if isinstance(spec_source, (str, Path)) else None
        )

        service_name = f"{resolved_provider}/{api}/{source}"
        service_data = compile_spec(spec, service_name=service_name)

        # Store in ServiceCache
        self._cache.put(resolved_provider, api, source, service_data)

        # Register in RegistryManager
        reg = self._registry_mgr.registry
        current_providers = dict(reg.providers)
        prov_apis = dict(current_providers.get(resolved_provider, {}))
        prov_apis[api] = ApiInfo(
            sources=[source],
            operation_count=len(service_data.operations),
            popularity_rank=1,
            auth_types=[],
            primary_auth="",
        )
        current_providers[resolved_provider] = prov_apis
        self._registry_mgr._registry = ServiceRegistry(
            version=reg.version,
            generated_at=reg.generated_at,
            providers=current_providers,
        )

        # Save registered spec source for diff checking
        self._registered_specs[(resolved_provider, api)] = spec_source

        return resolved_provider

    def check_spec_diff(
        self,
        provider: str,
        api: str = "REST",
        spec_source: str | Path | dict[str, Any] | None = None,
        source: str = "dynamic",
    ) -> SpecDiffResult:
        """
        Check if an upstream specification has differences compared to the active registered spec.
        Emits SpecUpdateAvailableWarning if changes are detected.
        """
        target_source = spec_source
        if target_source is None:
            target_source = self._registered_specs.get((provider, api))

        if target_source is None:
            return SpecDiffResult(
                has_diff=False,
                provider=provider,
                api=api,
                details="No remote spec source configured to check diff",
            )

        new_spec = self._resolve_spec_source(target_source)
        candidate_data = compile_spec(new_spec, service_name=f"{provider}/{api}/{source}")
        current_data = self._cache.get(provider, api, source)

        curr_ops = set(current_data.operations.keys())
        cand_ops = set(candidate_data.operations.keys())

        added = sorted(list(cand_ops - curr_ops))
        removed = sorted(list(curr_ops - cand_ops))
        modified: list[str] = []

        for op_id in curr_ops & cand_ops:
            c_op = current_data.operations[op_id]
            n_op = candidate_data.operations[op_id]
            if (
                c_op.method != n_op.method
                or c_op.path != n_op.path
                or len(c_op.parameters) != len(n_op.parameters)
            ):
                modified.append(op_id)
        modified.sort()

        has_diff = bool(added or removed or modified)
        if has_diff:
            msg = (
                f"Specification update available for '{provider}/{api}': "
                f"{len(added)} added, {len(removed)} removed, {len(modified)} modified operations."
            )
            warnings.warn(msg, SpecUpdateAvailableWarning, stacklevel=2)
            log.warning(msg)

        return SpecDiffResult(
            has_diff=has_diff,
            provider=provider,
            api=api,
            added_operations=added,
            removed_operations=removed,
            modified_operations=modified,
            details=f"{len(added)} added, {len(removed)} removed, {len(modified)} modified",
        )

    def update_spec(
        self,
        provider: str,
        api: str = "REST",
        spec_source: str | Path | dict[str, Any] | None = None,
        source: str = "dynamic",
        force: bool = False,
    ) -> bool:
        """
        Atomically update an existing spec in-place with zero downtime for readers.
        """
        target_source = spec_source
        if target_source is None:
            target_source = self._registered_specs.get((provider, api))

        if target_source is None:
            raise ServiceNotFoundError(
                f"Cannot update spec for '{provider}/{api}': no spec source provided",
                service=f"{provider}/{api}",
            )

        diff = self.check_spec_diff(provider, api, spec_source=target_source, source=source)
        if not diff.has_diff and not force:
            return False

        new_spec = self._resolve_spec_source(target_source)
        service_name = f"{provider}/{api}/{source}"
        new_data = compile_spec(new_spec, service_name=service_name)

        # Atomically update in ServiceCache
        self._cache.put(provider, api, source, new_data)

        # Invalidate hot op cache entries for this service
        self._hot_op_cache.clear_matching(provider, api, source)

        self._registered_specs[(provider, api)] = target_source

        return True

    def _resolve_spec_source(self, spec_source: str | Path | dict[str, Any]) -> dict[str, Any]:
        """Load and decode OpenAPI spec from dict, Path, file, URL, or JSON/YAML string."""
        if isinstance(spec_source, dict):
            return spec_source

        if isinstance(spec_source, Path) or (
            isinstance(spec_source, str)
            and not spec_source.startswith(("http://", "https://", "{"))
            and Path(spec_source).exists()
        ):
            p = Path(spec_source)
            raw = p.read_bytes()
            if p.suffix in (".yaml", ".yml"):
                return msgspec.yaml.decode(raw)
            return msgspec.json.decode(raw)

        if isinstance(spec_source, str):
            if spec_source.startswith(("http://", "https://")):
                resp = self._transport._sync_session.get(spec_source)
                resp.raise_for_status()
                content = resp.content or b""
                if spec_source.endswith((".yaml", ".yml")):
                    return msgspec.yaml.decode(content)
                return msgspec.json.decode(content)
            # Try JSON first, then YAML
            try:
                return msgspec.json.decode(spec_source.encode("utf-8"))
            except Exception:
                return msgspec.yaml.decode(spec_source.encode("utf-8"))

        raise ValueError(f"Unsupported spec source: {type(spec_source)}")

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
        """
        Automatically paginate through results of an API operation.
        Yields each page as a MapiResult.
        """
        current_kwargs = dict(kwargs)
        page_count = 0

        while page_count < max_pages:
            result = self.execute(
                provider, api, source, operation, _type=_type, _raw=_raw, **current_kwargs
            )
            yield result
            page_count += 1

            next_kwargs = self._extract_next_pagination_kwargs(result, current_kwargs)
            if next_kwargs is None or next_kwargs == current_kwargs:
                break
            current_kwargs = next_kwargs

    async def apaginate(
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
        """
        Asynchronously paginate through results of an API operation.
        Yields each page as a MapiResult.
        """
        current_kwargs = dict(kwargs)
        page_count = 0

        while page_count < max_pages:
            result = await self.aexecute(
                provider, api, source, operation, _type=_type, _raw=_raw, **current_kwargs
            )
            yield result
            page_count += 1

            next_kwargs = self._extract_next_pagination_kwargs(result, current_kwargs)
            if next_kwargs is None or next_kwargs == current_kwargs:
                break
            current_kwargs = next_kwargs

    @staticmethod
    def _extract_next_pagination_kwargs(
        result: MapiResult, current_kwargs: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Extract next page parameters from Link header, cursor fields, or numeric page."""
        new_kwargs = dict(current_kwargs)
        data = result.data

        # 1. Check Link header (RFC 5988: <url>; rel="next")
        link_header = result.metadata.headers.get("link")
        if link_header:
            match = re.search(r'<([^>]+)>;\s*rel="next"', link_header, re.IGNORECASE)
            if match:
                next_url = match.group(1)
                parsed = urllib.parse.urlparse(next_url)
                params = urllib.parse.parse_qs(parsed.query)
                for k, v in params.items():
                    new_kwargs[k] = v[0] if len(v) == 1 else v
                return new_kwargs

        # 2. Inspect dict data for cursors
        if isinstance(data, dict):
            if data.get("has_more") is False:
                return None
            for cursor_key in ("next_cursor", "next_token", "cursor", "next"):
                cursor_val = data.get(cursor_key)
                if cursor_val and isinstance(cursor_val, str):
                    new_kwargs[cursor_key] = cursor_val
                    return new_kwargs

            items = None
            for key in ("data", "items", "results"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break

            if items and data.get("has_more") is True:
                last_item = items[-1]
                if isinstance(last_item, dict) and "id" in last_item:
                    new_kwargs["starting_after"] = last_item["id"]
                    return new_kwargs

        # 3. Numeric page pagination
        if "page" in current_kwargs and isinstance(current_kwargs["page"], int):
            if isinstance(data, list) and len(data) == 0:
                return None
            if isinstance(data, dict):
                items = None
                for key in ("data", "items", "results"):
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break
                if items is not None and len(items) == 0:
                    return None
            new_kwargs["page"] = current_kwargs["page"] + 1
            return new_kwargs

        # 4. Offset pagination
        if "offset" in current_kwargs and isinstance(current_kwargs["offset"], int):
            limit = current_kwargs.get("limit", 20)
            if isinstance(data, list):
                if len(data) == 0:
                    return None
                new_kwargs["offset"] = current_kwargs["offset"] + len(data)
                return new_kwargs
            elif isinstance(data, dict):
                items = None
                for key in ("data", "items", "results"):
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break
                if items is not None:
                    if len(items) == 0:
                        return None
                    new_kwargs["offset"] = current_kwargs["offset"] + len(items)
                    return new_kwargs
            new_kwargs["offset"] = current_kwargs["offset"] + limit
            return new_kwargs

        return None

    def clear_cache(self) -> None:
        """Flush in-memory service definitions cache, hot op cache, typed decoders, and path cache."""
        self._cache.clear()
        if hasattr(self, "_hot_op_cache"):
            self._hot_op_cache.clear()
        if hasattr(self, "_loader") and hasattr(self._loader, "clear_cache"):
            self._loader.clear_cache()
        if hasattr(self, "_typed_decoders"):
            self._typed_decoders.clear()
        if hasattr(self, "_builder") and self._builder._validator is not None:
            self._builder._validator.clear_cache()

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
        return f"Mapi(base_url={self._config.base_url!r})"
