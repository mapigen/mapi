from __future__ import annotations

from pathlib import Path

import msgspec
import pytest
import zstandard as zstd

from mapi.exceptions import ConfigurationError, ServiceNotFoundError
from mapi.models.domain import ServiceData
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
