from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mapi.exceptions import ServiceNotFoundError
from mapi.models.domain import Operation
from mapi.registry.discovery import DiscoveryService, RegistryManager


class TestRegistryManager:
    def test_lazy_loading(self, sample_registry):
        loader = MagicMock()
        loader.load_registry.return_value = sample_registry
        rm = RegistryManager(loader)
        assert rm._registry is None
        _ = rm.registry
        loader.load_registry.assert_called_once()

    def test_caching_subsequent_calls(self, sample_registry):
        loader = MagicMock()
        loader.load_registry.return_value = sample_registry
        rm = RegistryManager(loader)
        _ = rm.registry
        _ = rm.registry
        loader.load_registry.assert_called_once()

    def test_invalidate_forces_reload(self, sample_registry):
        loader = MagicMock()
        loader.load_registry.return_value = sample_registry
        rm = RegistryManager(loader)
        _ = rm.registry
        rm.invalidate()
        assert rm._registry is None
        _ = rm.registry
        assert loader.load_registry.call_count == 2


class TestDiscoveryService:
    @pytest.fixture
    def setup_discovery(self, sample_registry, sample_service_data):
        loader = MagicMock()
        loader.load_registry.return_value = sample_registry
        loader.load_service.return_value = sample_service_data
        rm = RegistryManager(loader)
        discovery = DiscoveryService(rm, loader)
        return discovery, loader

    def test_providers_queries(self, setup_discovery):
        discovery, _ = setup_discovery
        providers = discovery.list_providers()
        assert "pokeapi" in providers
        assert discovery.provider_exists("pokeapi") is True
        assert discovery.provider_exists("unknown") is False

    def test_api_queries(self, setup_discovery):
        discovery, _ = setup_discovery
        apis = discovery.list_apis("pokeapi")
        assert "REST" in apis
        assert discovery.api_exists("pokeapi", "REST") is True
        assert discovery.api_exists("pokeapi", "GraphQL") is False
        assert discovery.api_exists("unknown", "REST") is False

    def test_get_api_info(self, setup_discovery):
        discovery, _ = setup_discovery
        info = discovery.get_api_info("pokeapi", "REST")
        assert info.sources == ["openapi"]
        assert info.operation_count > 0

    def test_get_api_info_missing_raises(self, setup_discovery):
        discovery, _ = setup_discovery
        with pytest.raises(ServiceNotFoundError, match="not found"):
            discovery.get_api_info("pokeapi", "nonexistent")

    def test_list_operations(self, setup_discovery, sample_service_data):
        discovery, _ = setup_discovery
        ops = discovery.list_operations("pokeapi", "REST", "openapi")
        assert "get_user" in ops

    def test_operation_exists(self, setup_discovery):
        discovery, _ = setup_discovery
        assert discovery.operation_exists("pokeapi", "REST", "get_user", "openapi") is True
        assert discovery.operation_exists("pokeapi", "REST", "absent_op", "openapi") is False

    def test_get_operation(self, setup_discovery):
        discovery, _ = setup_discovery
        op = discovery.get_operation("pokeapi", "REST", "get_user", "openapi")
        assert isinstance(op, Operation)
        assert op.path == "/users/{user_id}"
        assert op.method == "GET"

    def test_get_operation_missing_raises(self, setup_discovery):
        discovery, _ = setup_discovery
        with pytest.raises(ServiceNotFoundError, match="Operation 'absent' not found"):
            discovery.get_operation("pokeapi", "REST", "absent", "openapi")

    def test_discovery_uses_cache(self, sample_service_data):
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
