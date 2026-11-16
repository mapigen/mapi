from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client.client import Mapi
from .api import ApiProxy


class ProviderProxy:
    """
    Proxy representing a specific provider.
    
    Attribute access dynamically resolves to an ApiProxy:
        client.pokeapi.REST -> ApiProxy for provider="pokeapi", api="REST"
    """

    __slots__ = ("_client", "_provider")

    def __init__(self, client: Mapi, provider: str) -> None:
        self._client = client
        self._provider = provider

    def __getattr__(self, api: str) -> ApiProxy:
        if not self._client._discovery.api_exists(self._provider, api):
            available = self._client._discovery.list_apis(self._provider)
            raise AttributeError(
                f"API '{api}' not found for provider '{self._provider}'. "
                f"Available APIs: {available}"
            )
        return ApiProxy(self._client, self._provider, api)

    def __repr__(self) -> str:
        return f"ProviderProxy(provider={self._provider!r})"
