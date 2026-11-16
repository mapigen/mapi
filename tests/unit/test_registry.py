from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import msgspec
import pytest
import zstandard as zstd

from mapi.exceptions import ConfigurationError, ServiceNotFoundError
from mapi.models.domain import ServiceData
from mapi.registry.discovery import DiscoveryService, RegistryManager
from mapi.registry.loader import DiskLoader


def _write_service_data(
    base_dir: Path,
    provider: str,
    api: str,
    source: str,
    service_data: ServiceData,
    compressed: bool = False,
) -> Path:
    service_dir = base_dir / provider / source / api
    service_dir.mkdir(parents=True, exist_ok=True)
    payload = msgspec.json.encode(service_data)
    if compressed:
        target = service_dir / f"{api}.utilize.json.zst"
        target.write_bytes(zstd.ZstdCompressor().compress(payload))
    else:
        target = service_dir / f"{api}.utilize.json"
        target.write_bytes(payload)
    return target


class TestDiskLoader:
    def test_missing_registry_raises(self, tmp_path):
        loader = DiskLoader(data_dir=tmp_path, registry_path=tmp_path / "absent.json")
        with pytest.raises(ConfigurationError, match="not found"):
            loader.load_registry()

    def test_load_valid_registry(self, tmp_path, sample_registry):
        reg_file = tmp_path / "services.json"
        reg_file.write_bytes(msgspec.json.encode(sample_registry))
        loader = DiskLoader(data_dir=tmp_path, registry_path=reg_file)
        reg = loader.load_registry()
        assert "pokeapi" in reg.providers
        assert reg.version == "1.0"

    def test_load_uncompressed_service(self, tmp_path, sample_service_data):
        _write_service_data(
            tmp_path, "pokemon", "REST", "v2", sample_service_data, compressed=False
        )
        loader = DiskLoader(data_dir=tmp_path, registry_path=tmp_path / "s.json")
        data = loader.load_service("pokemon", "REST", "v2")
        assert data.service_name == sample_service_data.service_name

    def test_load_compressed_service(self, tmp_path, sample_service_data):
        _write_service_data(tmp_path, "pokemon", "REST", "v2", sample_service_data, compressed=True)
        loader = DiskLoader(data_dir=tmp_path, registry_path=tmp_path / "s.json")
        data = loader.load_service("pokemon", "REST", "v2")
        assert data.service_name == sample_service_data.service_name

    def test_missing_service_raises_service_not_found(self, tmp_path):
        loader = DiskLoader(data_dir=tmp_path, registry_path=tmp_path / "s.json")
        with pytest.raises(ServiceNotFoundError, match="not found"):
            loader.load_service("nonexistent", "api", "src")

    def test_path_caching_and_clear_cache(self, tmp_path, sample_service_data):
        target = _write_service_data(
            tmp_path, "pokemon", "REST", "v2", sample_service_data, compressed=True
        )
        loader = DiskLoader(data_dir=tmp_path, registry_path=tmp_path / "s.json")
        assert len(loader._path_cache) == 0

        # First load populates cache
        loader.load_service("pokemon", "REST", "v2")
        key = ("pokemon", "REST", "v2")
        assert key in loader._path_cache
        path, is_compressed, is_msgpack = loader._path_cache[key]
        assert path == target
        assert is_compressed is True
        assert is_msgpack is False

        # Clear cache empties path cache
        loader.clear_cache()
        assert len(loader._path_cache) == 0


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
        _ = rm.registry
        assert loader.load_registry.call_count == 2


class TestDiscoveryService:
    def _create_discovery(self, registry, service_data=None):
        loader = MagicMock(spec=DiskLoader)
        if service_data:
            loader.load_service.return_value = service_data
        rm = RegistryManager(loader)
        rm._registry = registry
        return DiscoveryService(rm, loader), loader

    def test_providers_queries(self, sample_registry):
        ds, _ = self._create_discovery(sample_registry)
        assert "pokeapi" in ds.list_providers()
        assert "github" in ds.list_providers()
        assert ds.provider_exists("pokeapi") is True
        assert ds.provider_exists("unknown_svc") is False

    def test_api_queries(self, sample_registry):
        ds, _ = self._create_discovery(sample_registry)
        assert ds.list_apis("pokeapi") == ["REST"]
        assert ds.api_exists("pokeapi", "REST") is True
        assert ds.api_exists("pokeapi", "UNKNOWN") is False

    def test_get_api_info(self, sample_registry):
        ds, _ = self._create_discovery(sample_registry)
        info = ds.get_api_info("pokeapi", "REST")
        assert info.sources == ["openapi"]
        assert info.primary_auth == "none"

    def test_get_api_info_missing_raises(self, sample_registry):
        ds, _ = self._create_discovery(sample_registry)
        with pytest.raises(ServiceNotFoundError):
            ds.get_api_info("pokeapi", "GRAPHQL")

    def test_list_operations(self, sample_registry, sample_service_data):
        ds, _ = self._create_discovery(sample_registry, sample_service_data)
        ops = ds.list_operations("pokeapi", "REST")
        assert "get_user" in ops

    def test_operation_exists(self, sample_registry, sample_service_data):
        ds, _ = self._create_discovery(sample_registry, sample_service_data)
        assert ds.operation_exists("pokeapi", "REST", "get_user") is True
        assert ds.operation_exists("pokeapi", "REST", "fake_op") is False

    def test_get_operation(self, sample_registry, sample_service_data):
        ds, _ = self._create_discovery(sample_registry, sample_service_data)
        op = ds.get_operation("pokeapi", "REST", "get_user")
        assert op.path == "/users/{user_id}"
        assert op.method == "GET"

    def test_get_operation_missing_raises(self, sample_registry, sample_service_data):
        ds, _ = self._create_discovery(sample_registry, sample_service_data)
        with pytest.raises(ServiceNotFoundError):
            ds.get_operation("pokeapi", "REST", "missing_op")
