from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client.client import Mapi
from ..models.response import MapiResult


class ApiProxy:
    """
    Proxy representing a specific API (provider/api).

    - Calling the proxy directly executes an operation synchronously:
        client.pokeapi.REST("api_v2_pokemon_retrieve", id="ditto")
    - .aexecute() executes asynchronously:
        await client.pokeapi.REST.aexecute("api_v2_pokemon_retrieve", id="ditto")
    - Accessing an attribute selects an explicit source:
        client.github.rest.openapi("users_get_by_username", username="octocat")
    """

    __slots__ = ("_client", "_provider", "_api", "_source")

    def __init__(
        self,
        client: Mapi,
        provider: str,
        api: str,
        source: str | None = None,
    ) -> None:
        self._client = client
        self._provider = provider
        self._api = api
        self._source = source

    def __call__(
        self,
        operation: str,
        *,
        _type: Any = None,
        _raw: bool = False,
        **kwargs: Any,
    ) -> MapiResult:
        """Execute an API operation synchronously."""
        source = self._source if self._source is not None else self._resolve_source()
        return self._client.execute(
            self._provider, self._api, source, operation, _type=_type, _raw=_raw, **kwargs
        )

    async def aexecute(
        self,
        operation: str,
        *,
        _type: Any = None,
        _raw: bool = False,
        **kwargs: Any,
    ) -> MapiResult:
        """Execute an API operation asynchronously."""
        source = self._source if self._source is not None else self._resolve_source()
        return await self._client.aexecute(
            self._provider, self._api, source, operation, _type=_type, _raw=_raw, **kwargs
        )

    def to_tool(self, operation: str) -> dict[str, Any]:
        """Export standard JSON Schema / OpenAI function calling definition for an operation."""
        source = self._source if self._source is not None else self._resolve_source()
        return self._client.to_tool(self._provider, self._api, operation, source=source)

    def paginate(self, operation: str, **kwargs: Any) -> Iterator[MapiResult]:
        """Automatically paginate through results of an operation."""
        source = self._source if self._source is not None else self._resolve_source()
        return self._client.paginate(self._provider, self._api, source, operation, **kwargs)

    async def apaginate(self, operation: str, **kwargs: Any) -> AsyncIterator[MapiResult]:
        """Asynchronously paginate through results of an operation."""
        source = self._source if self._source is not None else self._resolve_source()
        async for page in self._client.apaginate(
            self._provider, self._api, source, operation, **kwargs
        ):
            yield page

    def __getattr__(self, source_name: str) -> ApiProxy:
        """Return a new ApiProxy scoped to the specified source."""
        if source_name.startswith("_"):
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{source_name}'")
        info = self._client._discovery.get_api_info(self._provider, self._api)
        if source_name not in info.sources:
            raise AttributeError(
                f"Source '{source_name}' not found for '{self._provider}/{self._api}'. "
                f"Available sources: {info.sources}"
            )
        return ApiProxy(self._client, self._provider, self._api, source=source_name)

    def _resolve_source(self) -> str:
        if self._source is not None:
            return self._source
        info = self._client._discovery.get_api_info(self._provider, self._api)
        if not info.sources:
            raise AttributeError(f"No sources configured for API '{self._provider}/{self._api}'")
        self._source = info.sources[0]
        return self._source

    def __repr__(self) -> str:
        return f"ApiProxy(provider={self._provider!r}, api={self._api!r}, source={self._source!r})"
