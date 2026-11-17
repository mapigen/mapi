from __future__ import annotations

import threading
from functools import lru_cache

from ..models.domain import ServiceData
from ..registry.loader import DiskLoader


class ServiceCache:
    """
    Thread-safe pinned-LRU cache for ServiceData objects.

    Pinned keys are held in memory permanently.
    Evictable keys are governed by functools.lru_cache.
    """

    def __init__(
        self,
        loader: DiskLoader,
        pinned_keys: frozenset[str] = frozenset(),
        maxsize: int = 64,
    ) -> None:
        self._loader = loader
        self._pinned_keys = pinned_keys
        self._pinned: dict[str, ServiceData] = {}
        self._cached_keys: set[str] = set()
        self._lock = threading.Lock()

        loader_ref = loader

        @lru_cache(maxsize=maxsize)
        def _lru_load(provider: str, api: str, source: str) -> ServiceData:
            return loader_ref.load_service(provider, api, source)

        self._lru_load = _lru_load

    def get(self, provider: str, api: str, source: str) -> ServiceData:
        """Return ServiceData, retrieving from cache or loading from disk."""
        key = f"{provider}:{api}:{source}"
        with self._lock:
            self._cached_keys.add(key)
        if self._pinned_keys and key in self._pinned_keys:
            if key in self._pinned:
                return self._pinned[key]
            with self._lock:
                if key not in self._pinned:
                    self._pinned[key] = self._loader.load_service(provider, api, source)
                return self._pinned[key]
        return self._lru_load(provider, api, source)

    def is_cached(self, provider: str, api: str, source: str) -> bool:
        """Check if an API service is currently held in memory cache."""
        key = f"{provider}:{api}:{source}"
        with self._lock:
            return key in self._pinned or key in self._cached_keys

    def put(
        self,
        provider: str,
        api: str,
        source: str,
        data: ServiceData,
        pinned: bool = True,
    ) -> None:
        """Store or update a ServiceData instance in cache."""
        key = f"{provider}:{api}:{source}"
        with self._lock:
            self._cached_keys.add(key)
            self._pinned[key] = data
            if pinned and key not in self._pinned_keys:
                self._pinned_keys = self._pinned_keys | {key}

    def clear(self) -> None:
        """Evict all cached entries."""
        with self._lock:
            self._pinned.clear()
            self._cached_keys.clear()
        self._lru_load.cache_clear()

    def cache_info(self) -> dict:
        """Return diagnostic metrics for cache monitoring."""
        with self._lock:
            return {
                "pinned_count": len(self._pinned),
                "pinned_keys": sorted(self._pinned_keys),
                "lru": self._lru_load.cache_info()._asdict(),
            }
