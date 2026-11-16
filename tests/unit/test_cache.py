from __future__ import annotations
from unittest.mock import MagicMock

from mapi.cache import ServiceCache
from mapi.registry.loader import DiskLoader


class TestServiceCache:
    def _create_cache(self, sample_service_data, pinned=frozenset(), maxsize=10):
        loader = MagicMock(spec=DiskLoader)
        loader.load_service.return_value = sample_service_data
        cache = ServiceCache(loader, pinned_keys=pinned, maxsize=maxsize)
        return cache, loader

    def test_first_call_loads_from_disk(self, sample_service_data):
        cache, loader = self._create_cache(sample_service_data)
        data = cache.get("provider", "api", "source")
        assert data.service_name == sample_service_data.service_name
        loader.load_service.assert_called_once_with("provider", "api", "source")

    def test_subsequent_call_uses_lru(self, sample_service_data):
        cache, loader = self._create_cache(sample_service_data)
        cache.get("provider", "api", "source")
        cache.get("provider", "api", "source")
        cache.get("provider", "api", "source")
        loader.load_service.assert_called_once()

    def test_pinned_key_never_evicted(self, sample_service_data):
        cache, loader = self._create_cache(
            sample_service_data, pinned=frozenset(["p:a:s"])
        )
        cache.get("p", "a", "s")
        cache.get("p", "a", "s")
        loader.load_service.assert_called_once_with("p", "a", "s")
        info = cache.cache_info()
        assert info["pinned_count"] == 1
        assert "p:a:s" in info["pinned_keys"]

    def test_clear_evicts_cache(self, sample_service_data):
        cache, loader = self._create_cache(sample_service_data)
        cache.get("p", "a", "s")
        cache.clear()
        cache.get("p", "a", "s")
        assert loader.load_service.call_count == 2

    def test_cache_info_format(self, sample_service_data):
        cache, _ = self._create_cache(sample_service_data)
        info = cache.cache_info()
        assert "pinned_count" in info
        assert "pinned_keys" in info
        assert "lru" in info
        assert "hits" in info["lru"]
        assert "misses" in info["lru"]
