from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from niquests.exceptions import HTTPError

from mapi import ApiKeyAuth, BearerAuth, Mapi, MapiResult
from mapi.exceptions import (
    ClientError,
    RateLimitError,
    ServerError,
)
from mapi.models.config import ClientConfig
from mapi.models.request import RequestConfig
from mapi.proxy.api import ApiProxy
from mapi.proxy.provider import ProviderProxy


def _build_test_mapi(sample_service_data, sample_registry) -> Mapi:
    """Build a Mapi instance with mocked dependencies for isolated unit testing."""
    client = Mapi.__new__(Mapi)

    discovery = MagicMock()
    discovery.provider_exists.side_effect = lambda p: p in ("pokeapi", "github")
    discovery.api_exists.side_effect = lambda p, a: (
        (p, a)
        in (
            ("pokeapi", "REST"),
            ("github", "rest"),
        )
    )
    discovery.get_api_info.return_value = MagicMock(sources=["openapi"])
    client._discovery = discovery

    cache = MagicMock()
    cache.get.return_value = sample_service_data
    client._cache = cache

    builder = MagicMock()
    builder.build.return_value = RequestConfig(method="GET", url="https://api.example.com/users/1")
    client._builder = builder

    transport = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "name": "pikachu"}
    transport.request.return_value = mock_resp
    transport.arequest = AsyncMock(return_value=mock_resp)
    transport.aclose = AsyncMock()
    client._transport = transport

    client._auth = None
    client._config = ClientConfig()
    return client


class TestMapiInit:
    def test_string_token_auto_converts_to_bearer(self):
        with (
            patch("mapi.client.client.DiskLoader"),
            patch("mapi.client.client.RegistryManager"),
            patch("mapi.client.client.DiscoveryService"),
            patch("mapi.client.client.ServiceCache"),
            patch("mapi.client.client.ParameterValidator"),
            patch("mapi.client.client.RequestBuilder"),
            patch("mapi.client.client.NiquestsTransport"),
        ):
            client = Mapi(auth="test_token_xyz")
        assert isinstance(client._auth, BearerAuth)
        assert client._auth.token == "test_token_xyz"

    def test_auth_namespace_helpers(self):
        assert Mapi.Auth.ApiKey is ApiKeyAuth
        assert Mapi.Auth.Bearer is BearerAuth


class TestMapiDynamicProxy:
    def test_known_provider_returns_provider_proxy(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        provider = client.pokeapi
        assert isinstance(provider, ProviderProxy)

    def test_unknown_provider_raises_attribute_error(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        with pytest.raises(AttributeError, match="has no attribute 'nonexistent'"):
            _ = client.nonexistent

    def test_known_api_returns_api_proxy(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        api = client.pokeapi.REST
        assert isinstance(api, ApiProxy)

    def test_unknown_api_raises_attribute_error(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        with pytest.raises(AttributeError, match="not found for provider"):
            _ = client.pokeapi.UNKNOWN_API

    def test_real_attributes_not_intercepted_by_getattr(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        # discovery and _config are real attributes/properties
        assert client.discovery is client._discovery
        assert client._config is not None


class TestMapiExecution:
    def test_sync_execute_success(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        result = client.execute("pokeapi", "REST", "openapi", "get_pokemon", id="pikachu")
        assert isinstance(result, MapiResult)
        assert result.data == {"id": 1, "name": "pikachu"}
        assert result.metadata.status == "success"
        assert result.metadata.http_status == 200
        assert result.metadata.network_duration_ms is not None
        assert result.metadata.duration_ms >= 0

    def test_proxy_call_syntax(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        result = client.pokeapi.REST("get_pokemon", id="pikachu")
        assert isinstance(result, MapiResult)
        assert result.data == {"id": 1, "name": "pikachu"}

    @pytest.mark.asyncio
    async def test_async_aexecute_success(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        result = await client.aexecute("pokeapi", "REST", "openapi", "get_pokemon", id="pikachu")
        assert isinstance(result, MapiResult)
        assert result.data == {"id": 1, "name": "pikachu"}
        assert result.metadata.network_duration_ms is not None

    @pytest.mark.asyncio
    async def test_proxy_async_aexecute_syntax(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        result = await client.pokeapi.REST.aexecute("get_pokemon", id="pikachu")
        assert isinstance(result, MapiResult)
        assert result.data == {"id": 1, "name": "pikachu"}

    def test_rate_limit_429_raises(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        resp = MagicMock()
        resp.status_code = 429
        cast(MagicMock, client._transport.request).side_effect = HTTPError(
            "Too Many Requests", response=resp
        )
        with pytest.raises(RateLimitError) as exc_info:
            client.pokeapi.REST("get_pokemon")
        assert exc_info.value.http_status == 429

    def test_server_error_503_raises(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        resp = MagicMock()
        resp.status_code = 503
        cast(MagicMock, client._transport.request).side_effect = HTTPError(
            "Service Unavailable", response=resp
        )
        with pytest.raises(ServerError) as exc_info:
            client.pokeapi.REST("get_pokemon")
        assert exc_info.value.http_status == 503

    def test_client_error_404_raises(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        resp = MagicMock()
        resp.status_code = 404
        cast(MagicMock, client._transport.request).side_effect = HTTPError(
            "Not Found", response=resp
        )
        with pytest.raises(ClientError) as exc_info:
            client.pokeapi.REST("get_pokemon")
        assert exc_info.value.http_status == 404


class TestMapiContextManager:
    def test_sync_context_manager_closes_transport(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        with client:
            pass
        cast(MagicMock, client._transport.close).assert_called_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_closes_transport(
        self, sample_service_data, sample_registry
    ):
        client = _build_test_mapi(sample_service_data, sample_registry)
        async with client:
            pass
        cast(MagicMock, client._transport.aclose).assert_called_once()

    def test_clear_cache_delegates(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        client.clear_cache()
        cast(MagicMock, client._cache.clear).assert_called_once()
