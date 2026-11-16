from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import msgspec
import pytest
from niquests.exceptions import HTTPError

from mapi import ApiKeyAuth, BatchRequest, BearerAuth, Mapi, MapiResult
from mapi.exceptions import (
    ClientError,
    RateLimitError,
    ServerError,
)
from mapi.models import Server
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
    mock_resp.headers = {"Content-Type": "application/json", "X-RateLimit-Remaining": "4999"}
    mock_resp.content = b'{"id": 1, "name": "pikachu"}'
    mock_resp.json.return_value = {"id": 1, "name": "pikachu"}
    transport.request.return_value = mock_resp
    transport.arequest = AsyncMock(return_value=mock_resp)
    transport.aclose = AsyncMock()
    client._transport = transport

    client._auth = None
    client._config = ClientConfig()
    client._json_decoder = msgspec.json.Decoder()
    client._typed_decoders = {}
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

    def test_sync_execute_typed_model(self, sample_service_data, sample_registry):
        import msgspec

        class Pokemon(msgspec.Struct):
            id: int
            name: str

        client = _build_test_mapi(sample_service_data, sample_registry)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"id": 25, "name": "pikachu"}'
        mock_resp.json.return_value = {"id": 25, "name": "pikachu"}
        cast(MagicMock, client._transport.request).return_value = mock_resp

        result = client.pokeapi.REST("get_pokemon", id="pikachu", _type=Pokemon)
        assert isinstance(result.data, Pokemon)
        assert result.data.id == 25
        assert result.data.name == "pikachu"

    def test_sync_execute_raw_response(self, sample_service_data, sample_registry):
        import msgspec

        client = _build_test_mapi(sample_service_data, sample_registry)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"id": 25, "name": "pikachu"}'
        cast(MagicMock, client._transport.request).return_value = mock_resp

        result = client.pokeapi.REST("get_pokemon", id="pikachu", _raw=True)
        assert isinstance(result.data, msgspec.Raw)
        assert bytes(result.data) == b'{"id": 25, "name": "pikachu"}'

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

    def test_response_headers_captured(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        result = client.pokeapi.REST("get_pokemon", id="pikachu")
        assert result.metadata.headers.get("X-RateLimit-Remaining") == "4999"
        assert result.metadata.headers.get("Content-Type") == "application/json"

    @pytest.mark.asyncio
    async def test_abatch_execution(self, sample_service_data, sample_registry):
        client = _build_test_mapi(sample_service_data, sample_registry)
        requests = [
            BatchRequest(
                provider="pokeapi", api="REST", operation="get_pokemon", kwargs={"id": "ditto"}
            ),
            ("pokeapi", "REST", "get_pokemon", {"id": "pikachu"}),
        ]
        results = await client.abatch(requests, max_concurrency=2)
        assert len(results) == 2
        assert all(isinstance(r, MapiResult) for r in results)

    def test_templated_server_url_resolution(self, sample_service_data):
        from mapi.client.request_builder import RequestBuilder

        sample_service_data = msgspec.structs.replace(
            sample_service_data,
            servers=[
                Server(
                    url="https://{subdomain}.example.com:{port}/{version}",
                    variables={
                        "subdomain": {"default": "api"},
                        "port": {"default": "443"},
                        "version": {"default": "v1"},
                    },
                )
            ],
        )
        cache = MagicMock()
        cache.get.return_value = sample_service_data
        builder = RequestBuilder(cache)

        config = builder.build("mock_service", "REST", "openapi", "get_user", user_id=123)
        assert config.url == "https://api.example.com:443/v1/users/123"

        config2 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=123,
            subdomain="sandbox",
            port="8443",
        )
        assert config2.url == "https://sandbox.example.com:8443/v1/users/123"

    def test_client_config_multiplexed_defaults(self):
        cfg = ClientConfig()
        assert cfg.multiplexed is True
        assert cfg.retries == 0
        assert cfg.server_variables == {}
        assert cfg.default_headers == {"User-Agent": "mapi/0.1.0", "Accept": "application/json"}

    def test_default_headers_additive_and_overrides(self, sample_service_data):
        from mapi.client.request_builder import RequestBuilder

        cache = MagicMock()
        cache.get.return_value = sample_service_data
        builder = RequestBuilder(cache)

        # 1. Base defaults applied
        c1 = builder.build("mock_service", "REST", "openapi", "get_user", user_id=1)
        assert c1.headers.get("User-Agent") == "mapi/0.1.0"
        assert c1.headers.get("Accept") == "application/json"

        # 2. Additive user headers
        c2 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=1,
            default_headers={"X-Custom-Tenant": "tenant-abc"},
        )
        assert c2.headers.get("User-Agent") == "mapi/0.1.0"
        assert c2.headers.get("Accept") == "application/json"
        assert c2.headers.get("X-Custom-Tenant") == "tenant-abc"

        # 3. User can override standard default header
        c3 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=1,
            default_headers={"User-Agent": "custom-agent/2.0"},
        )
        assert c3.headers.get("User-Agent") == "custom-agent/2.0"
        assert c3.headers.get("Accept") == "application/json"

    def test_server_tag_and_pattern_selection(self, sample_service_data):
        from mapi.client.request_builder import RequestBuilder

        sample_service_data = msgspec.structs.replace(
            sample_service_data,
            servers=[
                Server(url="https://api.example.com/v1", description="Production"),
                Server(url="https://sandbox.example.com/v1", description="Sandbox Environment"),
                Server(url="https://eu.example.com/v1", description="European Union DC"),
            ],
        )
        cache = MagicMock()
        cache.get.return_value = sample_service_data
        builder = RequestBuilder(cache)

        # Default picks first server
        c0 = builder.build("mock_service", "REST", "openapi", "get_user", user_id=1)
        assert c0.url == "https://api.example.com/v1/users/1"

        # Match by description tag
        c1 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=1,
            server_tag="sandbox",
        )
        assert c1.url == "https://sandbox.example.com/v1/users/1"

        # Match by URL pattern
        c2 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=1,
            server_pattern="eu.example.com",
        )
        assert c2.url == "https://eu.example.com/v1/users/1"

        # Fallback to first if pattern unmatched
        c3 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=1,
            server_tag="nonexistent",
        )
        assert c3.url == "https://api.example.com/v1/users/1"

    def test_response_metadata_convenience_properties(self):
        from mapi.models.response import HeadersDict, ResponseMetadata

        raw = {
            "Content-Type": "application/json; charset=utf-8",
            "ETag": '"33a64df551425fcc55e4d42a148795d9f25f89d4"',
            "Retry-After": "120",
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "4995",
            "X-RateLimit-Reset": "1731776400",
        }
        headers = HeadersDict(raw)
        meta = ResponseMetadata(
            service="test",
            operation="test_op",
            duration_ms=5,
            status="success",
            headers=headers,
        )

        assert meta.content_type == "application/json; charset=utf-8"
        assert meta.etag == '"33a64df551425fcc55e4d42a148795d9f25f89d4"'
        assert meta.retry_after == 120.0
        assert meta.rate_limit_limit == 5000
        assert meta.rate_limit_remaining == 4995
        assert meta.rate_limit_reset == 1731776400

        # Case-insensitive dict lookups
        assert headers["content-type"] == headers["Content-Type"]
        assert headers.get("etag") == headers.get("ETag")
        assert "x-ratelimit-remaining" in headers
        assert "X-RateLimit-Remaining" in headers

    def test_discovery_uses_cache(self, sample_service_data):
        from mapi.registry.discovery import DiscoveryService

        rm = MagicMock()
        loader = MagicMock()
        cache = MagicMock()
        cache.get.return_value = sample_service_data

        discovery = DiscoveryService(rm, loader, cache=cache)
        discovery._resolve_source = MagicMock(return_value="openapi")

        ops = discovery.list_operations("mock", "api", "openapi")
        assert "get_user" in ops
        cache.get.assert_called_once_with("mock", "api", "openapi")
        loader.load_service.assert_not_called()
