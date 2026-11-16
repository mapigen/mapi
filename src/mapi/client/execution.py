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

from ..constants import (
    DEFAULT_SOURCE,
    FLAG_DRY_RUN,
    FLAG_DRY_RUN_ALT,
    FLAG_IDEMPOTENT,
    FLAG_IDEMPOTENT_ALT,
    FLAG_RAW,
    FLAG_RAW_ALT,
    FLAG_STREAM,
    FLAG_STREAM_ALT,
    FLAG_TARGET_TYPE,
    FLAG_TYPE,
    STATUS_DRY_RUN,
    STATUS_SUCCESS,
)
from ..exceptions import (
    ClientError,
    RateLimitError,
    ServerError,
    ServiceNotFoundError,
    TransportError,
    ValidationError,
)
from ..models.request import BatchRequest, RequestConfig
from ..models.response import _EMPTY_HEADERS, HeadersDict, MapiResult, ResponseMetadata

if TYPE_CHECKING:
    from .client import Mapi

log = logging.getLogger("mapi")
T = TypeVar("T")
_now = datetime.now
_UTC = UTC


def _utc_now_iso() -> str:
    """Return ISO 8601 UTC timestamp."""
    return _now(_UTC).isoformat()


def _to_ms(seconds: float) -> int:
    """Convert elapsed seconds to integer milliseconds (non-negative)."""
    return int(round(seconds * 1000)) if seconds > 0 else 0


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
    status: Any = STATUS_SUCCESS,
) -> MapiResult:
    """Construct MapiResult with timing metadata."""
    return MapiResult(
        data=data,
        metadata=ResponseMetadata(
            service=service_name,
            operation=operation,
            duration_ms=_to_ms(ops_time),
            network_duration_ms=_to_ms(net_time),
            headers=headers if headers is not None else _EMPTY_HEADERS,
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
    """Extract control flags from kwargs."""
    target_type = _type
    raw = _raw
    dry_run = _dry_run
    idempotent = _idempotent
    stream = _stream

    if kwargs:
        if FLAG_TYPE in kwargs:
            target_type = kwargs.pop(FLAG_TYPE)
        elif FLAG_TARGET_TYPE in kwargs:
            target_type = kwargs.pop(FLAG_TARGET_TYPE)

        if FLAG_RAW in kwargs:
            raw = raw or bool(kwargs.pop(FLAG_RAW))
        elif FLAG_RAW_ALT in kwargs:
            raw = raw or bool(kwargs.pop(FLAG_RAW_ALT))

        if FLAG_DRY_RUN in kwargs:
            dry_run = dry_run or bool(kwargs.pop(FLAG_DRY_RUN))
        elif FLAG_DRY_RUN_ALT in kwargs:
            dry_run = dry_run or bool(kwargs.pop(FLAG_DRY_RUN_ALT))

        if FLAG_IDEMPOTENT in kwargs:
            idempotent = idempotent or bool(kwargs.pop(FLAG_IDEMPOTENT))
        elif FLAG_IDEMPOTENT_ALT in kwargs:
            idempotent = idempotent or bool(kwargs.pop(FLAG_IDEMPOTENT_ALT))

        if FLAG_STREAM in kwargs:
            stream = stream or bool(kwargs.pop(FLAG_STREAM))
        elif FLAG_STREAM_ALT in kwargs:
            stream = stream or bool(kwargs.pop(FLAG_STREAM_ALT))

    return target_type, raw, dry_run, idempotent, stream


def _extract_response_headers(response: Any) -> HeadersDict:
    """Extract and wrap response headers into HeadersDict."""
    resp_dict = getattr(response, "__dict__", None)
    raw = resp_dict.get("headers") if resp_dict is not None else getattr(response, "headers", None)

    if raw is None:
        return _EMPTY_HEADERS
    if isinstance(raw, HeadersDict):
        return raw
    if isinstance(raw, dict) or Mapping in type(raw).__mro__:
        return HeadersDict(raw)
    return _EMPTY_HEADERS


class RequestExecutor:
    """HTTP request execution pipeline for sync, async, and batch calls."""

    def __init__(self, client: Mapi) -> None:
        self._client = client

    def prepare_request(
        self,
        provider: str,
        api: str,
        source: str | None,
        operation: str,
        kwargs: dict[str, Any],
        idempotent: bool = False,
    ) -> tuple[str, RequestConfig]:
        """Validate parameters and construct RequestConfig."""
        if source is None:
            try:
                info = self._client._discovery.get_api_info(provider, api)
                source = info.sources[0] if info.sources else DEFAULT_SOURCE
            except Exception:
                source = DEFAULT_SOURCE

        service_name = f"{provider}/{api}/{source}"
        cfg = self._client._config
        config = self._client._builder.build(
            provider,
            api,
            source,
            operation,
            base_url=cfg.base_url,
            server_variables=cfg.server_variables,
            default_headers=cfg.default_headers,
            server_pattern=cfg.server_pattern,
            server_tag=cfg.server_tag,
            idempotent=idempotent,
            timeout=cfg.default_timeout,
            **kwargs,
        )
        return service_name, config

    def decode_response(
        self,
        response: Any,
        target_type: Any = None,
        raw: bool = False,
    ) -> Any:
        """Decode response body using msgspec or response.json()."""
        content = getattr(response, "content", None)
        if raw:
            return (
                msgspec.Raw(content)
                if isinstance(content, (bytes, bytearray, memoryview))
                else content
            )

        if isinstance(content, (bytes, bytearray, memoryview)) and content:
            if target_type is not None:
                decoders = self._client._typed_decoders
                decoder = decoders.get(target_type)
                if decoder is None:
                    decoder = msgspec.json.Decoder(target_type)
                    decoders[target_type] = decoder
                return decoder.decode(content)
            try:
                return self._client._json_decoder.decode(content)
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
        target_type, raw, dry_run, idempotent, stream = _extract_call_flags(
            kwargs, _type, _raw, _dry_run, _idempotent, _stream
        )

        t_start = time.perf_counter()
        service_name, config = self.prepare_request(
            provider, api, source, operation, kwargs, idempotent=idempotent
        )
        prep_time = time.perf_counter() - t_start

        if dry_run:
            return MapiResult(
                data=config,
                metadata=ResponseMetadata(
                    service=service_name,
                    operation=operation,
                    duration_ms=_to_ms(prep_time),
                    network_duration_ms=0,
                    headers=HeadersDict(config.headers),
                    status=STATUS_DRY_RUN,
                    http_status=None,
                    timestamp=_utc_now_iso(),
                ),
            )

        try:
            auth = self._client._auth
            t_net = time.perf_counter()
            response = self._client._transport.request(config, auth=auth, stream=stream)
            net_time = time.perf_counter() - t_net

            resp_headers = _extract_response_headers(response)

            if stream:
                data = getattr(response, "iter_content", lambda: response)()
                post_time = 0.0
            else:
                t_post = time.perf_counter()
                data = self.decode_response(response, target_type, raw)
                post_time = time.perf_counter() - t_post

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
        target_type, raw, dry_run, idempotent, stream = _extract_call_flags(
            kwargs, _type, _raw, _dry_run, _idempotent, _stream
        )

        t_start = time.perf_counter()
        service_name, config = self.prepare_request(
            provider, api, source, operation, kwargs, idempotent=idempotent
        )
        prep_time = time.perf_counter() - t_start

        if dry_run:
            return MapiResult(
                data=config,
                metadata=ResponseMetadata(
                    service=service_name,
                    operation=operation,
                    duration_ms=_to_ms(prep_time),
                    network_duration_ms=0,
                    headers=HeadersDict(config.headers),
                    status=STATUS_DRY_RUN,
                    http_status=None,
                    timestamp=_utc_now_iso(),
                ),
            )

        try:
            auth = self._client._auth
            t_net = time.perf_counter()
            response = await self._client._transport.arequest(config, auth=auth, stream=stream)
            net_time = time.perf_counter() - t_net

            resp_headers = _extract_response_headers(response)

            if stream:
                data = getattr(response, "iter_content", lambda: response)()
                post_time = 0.0
            else:
                t_post = time.perf_counter()
                data = self.decode_response(response, target_type, raw)
                post_time = time.perf_counter() - t_post

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

    def batch(
        self,
        requests: Sequence[BatchRequest | tuple[str, str, str, dict[str, Any]]],
        *,
        return_exceptions: bool = False,
    ) -> list[Any]:
        """Execute multiple API operations synchronously in a sequential loop."""
        results: list[Any] = []
        for req in requests:
            try:
                if isinstance(req, BatchRequest):
                    source = req.source or (
                        self._client._discovery.get_api_info(req.provider, req.api).sources[0]
                        if hasattr(self._client, "_discovery")
                        else DEFAULT_SOURCE
                    )
                    res = self.execute(
                        req.provider,
                        req.api,
                        source,
                        req.operation,
                        _type=req.type,
                        _raw=req.raw,
                        **req.kwargs,
                    )
                else:
                    provider, api, operation, kw = req
                    source = (
                        self._client._discovery.get_api_info(provider, api).sources[0]
                        if hasattr(self._client, "_discovery")
                        else DEFAULT_SOURCE
                    )
                    res = self.execute(provider, api, source, operation, **kw)
                results.append(res)
            except Exception as exc:
                if return_exceptions:
                    results.append(exc)
                else:
                    raise
        return results

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
                        else DEFAULT_SOURCE
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
                    else DEFAULT_SOURCE
                )
                return await self.aexecute(provider, api, source, operation, **kw)

        tasks = [_run_single(req) for req in requests]
        return list(await asyncio.gather(*tasks, return_exceptions=return_exceptions))
