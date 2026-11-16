# tests/unit/client/test_client.py
from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from mapi import ApiKeyAuth, BearerAuth, Mapi
from mapi.proxy.api import ApiProxy
from mapi.proxy.provider import ProviderProxy
from tests.unit.client.conftest import build_test_mapi


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
        client = build_test_mapi(sample_service_data, sample_registry)
        provider = client.pokeapi
        assert isinstance(provider, ProviderProxy)

    def test_unknown_provider_raises_attribute_error(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        with pytest.raises(AttributeError, match="has no attribute 'nonexistent'"):
            _ = client.nonexistent

    def test_known_api_returns_api_proxy(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        api = client.pokeapi.REST
        assert isinstance(api, ApiProxy)

    def test_unknown_api_raises_attribute_error(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        with pytest.raises(AttributeError, match="not found for provider"):
            _ = client.pokeapi.UNKNOWN_API

    def test_real_attributes_not_intercepted_by_getattr(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        # discovery and _config are real attributes/properties
        assert client.discovery is client._discovery
        assert client._config is not None


class TestMapiContextManager:
    def test_sync_context_manager_closes_transport(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        with client:
            pass
        cast(MagicMock, client._transport.close).assert_called_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_closes_transport(
        self, sample_service_data, sample_registry
    ):
        client = build_test_mapi(sample_service_data, sample_registry)
        async with client:
            pass
        cast(MagicMock, client._transport.aclose).assert_called_once()

    def test_clear_cache_delegates(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        client.clear_cache()
        cast(MagicMock, client._cache.clear).assert_called_once()
