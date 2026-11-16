from __future__ import annotations
import logging
from typing import Any, Optional

import niquests
from niquests.auth import AuthBase
from niquests.models import Response

from ..models.request import RequestConfig

log = logging.getLogger(__name__)


class NiquestsTransport:
    """
    HTTP transport backed by niquests.
    
    - Sync: reuses a single Session for connection pooling.
    - Async: lazily creates one AsyncSession and reuses it across requests.
    - Context manager support for automatic cleanup.
    """

    def __init__(self, **session_kwargs: Any) -> None:
        self._kwargs = session_kwargs
        self._sync_session = niquests.Session(**session_kwargs)
        self._async_session: Optional[niquests.AsyncSession] = None

    # --- Sync ---

    def request(self, config: RequestConfig, auth: Optional[AuthBase] = None) -> Response:
        log.debug("sync %s %s", config.method, config.url)
        kw: dict[str, Any] = {"timeout": config.timeout}
        if config.params:
            kw["params"] = config.params
        if config.headers:
            kw["headers"] = config.headers
        if config.json_body is not None and config.method not in ("GET", "HEAD"):
            kw["json"] = config.json_body
        if auth is not None:
            kw["auth"] = auth
        response: Response = self._sync_session.request(config.method, config.url, **kw)
        response.raise_for_status()
        return response

    def close(self) -> None:
        self._sync_session.close()

    # --- Async ---

    async def arequest(self, config: RequestConfig, auth: Optional[AuthBase] = None) -> Response:
        log.debug("async %s %s", config.method, config.url)
        if self._async_session is None:
            self._async_session = niquests.AsyncSession(**self._kwargs)
        kw: dict[str, Any] = {"timeout": config.timeout}
        if config.params:
            kw["params"] = config.params
        if config.headers:
            kw["headers"] = config.headers
        if config.json_body is not None and config.method not in ("GET", "HEAD"):
            kw["json"] = config.json_body
        if auth is not None:
            kw["auth"] = auth
        response: Response = await self._async_session.request(config.method, config.url, **kw)
        response.raise_for_status()
        return response

    async def aclose(self) -> None:
        if self._async_session is not None:
            await self._async_session.close()
            self._async_session = None

    # --- Context managers ---

    def __enter__(self) -> "NiquestsTransport":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    async def __aenter__(self) -> "NiquestsTransport":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()
