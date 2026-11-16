# src/mapi/client/execution.py
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, NoReturn, TypeVar

import msgspec
from niquests.exceptions import ConnectionError, HTTPError, Timeout

from ..exceptions import (
    ClientError,
    RateLimitError,
    ServerError,
    ServiceNotFoundError,
    TransportError,
    ValidationError,
)
from ..models.request import BatchRequest, RequestConfig
from ..models.response import HeadersDict, MapiResult, ResponseMetadata

if TYPE_CHECKING:
    from .client import Mapi

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
    status: Any = "success",
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
            status=status,
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


def _extract_call_flags(
    kwargs: dict[str, Any],
    _type: Any,
    _raw: bool,
    _dry_run: bool,
    _idempotent: bool,
    _stream: bool,
) -> tuple[Any, bool, bool, bool, bool]:
    """Efficiently extract special control flags from kwargs with minimal pop overhead."""
    target_type = (
        _type
        or ("_type" in kwargs and kwargs.pop("_type"))
        or ("target_type" in kwargs and kwargs.pop("target_type"))
        or None
    )
    raw = (
        _raw
        or ("_raw" in kwargs and kwargs.pop("_raw"))
        or ("raw" in kwargs and kwargs.pop("raw"))
        or False
    )
    dry_run = (
        _dry_run
        or ("_dry_run" in kwargs and kwargs.pop("_dry_run"))
        or ("dry_run" in kwargs and kwargs.pop("dry_run"))
        or False
    )
    idempotent = (
        _idempotent
        or ("_idempotent" in kwargs and kwargs.pop("_idempotent"))
        or ("idempotent" in kwargs and kwargs.pop("idempotent"))
        or False
    )
    stream = (
        _stream
        or ("_stream" in kwargs and kwargs.pop("_stream"))
        or ("stream" in kwargs and kwargs.pop("stream"))
        or False
    )
    return target_type, raw, dry_run, idempotent, stream


class RequestExecutor:
    """
    Core HTTP request execution pipeline for sync, async, and batch calls.
    Encapsulates parameter resolution, wire dispatch, response body decoding,
    and structured error mapping.
    """

    def __init__(self, client: Mapi) -> None:
        self._client = client

    def prepare_request(
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        kwargs: dict[str, Any],
        idempotent: bool = False,
    ) -> tuple[str, RequestConfig]:
        """Validate parameters and construct RequestConfig."""
        service_name = f"{provider}/{api}/{source}"
        cfg = getattr(self._client, "_config", None)
        base_url = cfg.base_url if cfg else None
        server_variables = cfg.server_variables if cfg else None
        default_headers = cfg.default_headers if cfg else None
        server_pattern = cfg.server_pattern if cfg else None
        server_tag = cfg.server_tag if cfg else None
        timeout = cfg.default_timeout if cfg else 30.0

        config = self._client._builder.build(
            provider,
            api,
            source,
            operation,
            base_url=base_url,
            server_variables=server_variables,
            default_headers=default_headers,
            server_pattern=server_pattern,
            server_tag=server_tag,
            idempotent=idempotent,
            timeout=timeout,
            **kwargs,
        )
        return service_name, config

    def decode_response(
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
                decoders = getattr(self._client, "_typed_decoders", None)
                if decoders is not None:
                    decoder = decoders.get(target_type)
                    if decoder is None:
                        decoder = msgspec.json.Decoder(target_type)
                        decoders[target_type] = decoder
                    return decoder.decode(content)
                return msgspec.json.decode(content, type=target_type)
            try:
                decoder = getattr(self._client, "_json_decoder", None)
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
        target_type, raw, dry_run, idempotent, stream = _extract_call_flags(
            kwargs, _type, _raw, _dry_run, _idempotent, _stream
        )

        (service_name, config), prep_time = _measure(
            self.prepare_request, provider, api, source, operation, kwargs, idempotent=idempotent
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
            auth = getattr(self._client, "_auth", None)
            response, net_time = _measure(
                self._client._transport.request, config, auth=auth, stream=stream
            )
            raw_headers = getattr(response, "headers", None)
            resp_headers = (
                HeadersDict(raw_headers) if isinstance(raw_headers, Mapping) else HeadersDict()
            )
            if stream:
                data = getattr(response, "iter_content", lambda: response)()
                post_time = 0.0
            else:
                data, post_time = _measure(self.decode_response, response, target_type, raw)

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
        target_type, raw, dry_run, idempotent, stream = _extract_call_flags(
            kwargs, _type, _raw, _dry_run, _idempotent, _stream
        )

        (service_name, config), prep_time = _measure(
            self.prepare_request, provider, api, source, operation, kwargs, idempotent=idempotent
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
            auth = getattr(self._client, "_auth", None)
            response, net_time = await _ameasure(
                self._client._transport.arequest(config, auth=auth, stream=stream)
            )
            raw_headers = getattr(response, "headers", None)
            resp_headers = (
                HeadersDict(raw_headers) if isinstance(raw_headers, Mapping) else HeadersDict()
            )
            if stream:
                data = getattr(response, "iter_content", lambda: response)()
                post_time = 0.0
            else:
                data, post_time = _measure(self.decode_response, response, target_type, raw)

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
        """Execute multiple API operations concurrently with bounded concurrency."""
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run_single(
            req: BatchRequest | tuple[str, str, str, dict[str, Any]],
        ) -> MapiResult:
            async with semaphore:
                if isinstance(req, BatchRequest):
                    source = req.source or (
                        self._client._discovery.get_api_info(req.provider, req.api).sources[0]
                        if hasattr(self._client, "_discovery")
                        else "default"
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
                source = (
                    self._client._discovery.get_api_info(provider, api).sources[0]
                    if hasattr(self._client, "_discovery")
                    else "default"
                )
                return await self.aexecute(provider, api, source, operation, **kw)

        tasks = [_run_single(req) for req in requests]
        return list(await asyncio.gather(*tasks, return_exceptions=return_exceptions))
