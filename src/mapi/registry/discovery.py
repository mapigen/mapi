from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import msgspec

from ..exceptions import ServiceNotFoundError
from ..models.domain import Operation, ServiceData
from ..models.registry import ApiInfo, ServiceRegistry
from .loader import DiskLoader

if TYPE_CHECKING:
    from ..cache.service_cache import ServiceCache

log = logging.getLogger(__name__)


class RegistryManager:
    """Thread-safe lazy loader for ServiceRegistry."""

    def __init__(self, loader: DiskLoader) -> None:
        self._loader = loader
        self._registry: ServiceRegistry | None = None
        self._lock = threading.Lock()

    @property
    def registry(self) -> ServiceRegistry:
        if self._registry is None:
            with self._lock:
                if self._registry is None:
                    self._registry = self._loader.load_registry()
        return self._registry

    def invalidate(self) -> None:
        """Force reload on next access (useful for testing or hot-reloading)."""
        with self._lock:
            self._registry = None


class DiscoveryService:
    """Provider, API, and operation discovery service."""

    def __init__(
        self,
        registry_manager: RegistryManager,
        loader: DiskLoader,
        cache: ServiceCache | None = None,
    ) -> None:
        self._rm = registry_manager
        self._loader = loader
        self._cache = cache

    def _get_service_data(self, provider: str, api: str, source: str) -> ServiceData:
        if self._cache is not None:
            return self._cache.get(provider, api, source)
        return self._loader.load_service(provider, api, source)

    def _get_local_popularity_rank(
        self, provider: str, api: str, sources: list[str]
    ) -> int | None:
        """Check local storage (metadata.yml or popularity.json) for existing popularity rank.

        Rule of thumb: Local storage ranks take absolute precedence over registry defaults.
        """
        data_dir = getattr(self._loader, "data_dir", None)
        if isinstance(data_dir, Path) and data_dir.is_dir():
            pop_file = data_dir / "popularity.json"
            if pop_file.is_file():
                try:
                    import json

                    pop_map = json.loads(pop_file.read_text(encoding="utf-8"))
                    key_full = f"{provider}/{api}"
                    if key_full in pop_map:
                        return int(pop_map[key_full])
                    if provider in pop_map:
                        return int(pop_map[provider])
                except Exception:
                    pass

        load_meta = getattr(self._loader, "load_service_metadata", None)
        if callable(load_meta):
            for src in sources:
                meta = load_meta(provider, api, src)
                if isinstance(meta, dict) and "popularity_rank" in meta:
                    try:
                        return int(meta["popularity_rank"])
                    except (ValueError, TypeError):
                        pass
        return None

    # --- Provider level ---

    def list_providers(self) -> list[str]:
        return list(self._rm.registry.providers.keys())

    def provider_exists(self, provider: str) -> bool:
        return provider in self._rm.registry.providers

    # --- API level ---

    def list_apis(self, provider: str) -> list[str]:
        return list(self._rm.registry.providers.get(provider, {}).keys())

    def api_exists(self, provider: str, api: str) -> bool:
        return (
            provider in self._rm.registry.providers and api in self._rm.registry.providers[provider]
        )

    def get_api_info(self, provider: str, api: str) -> ApiInfo:
        api_info = self._rm.registry.providers.get(provider, {}).get(api)
        if api_info is None:
            raise ServiceNotFoundError(
                f"API '{api}' not found for provider '{provider}'",
                service=f"{provider}/{api}",
            )
        local_rank = self._get_local_popularity_rank(provider, api, api_info.sources)
        if local_rank is not None and local_rank != api_info.popularity_rank:
            return msgspec.structs.replace(api_info, popularity_rank=local_rank)
        return api_info

    def _resolve_source(self, provider: str, api: str, source: str | None) -> str:
        if source is not None:
            return source
        info = self.get_api_info(provider, api)
        if not info.sources:
            raise ServiceNotFoundError(
                f"No sources found for '{provider}/{api}'",
                service=f"{provider}/{api}",
            )
        return info.sources[0]

    # --- Operation level ---

    def list_operations(self, provider: str, api: str, source: str | None = None) -> list[str]:
        src = self._resolve_source(provider, api, source)
        try:
            sd = self._get_service_data(provider, api, src)
            return list(sd.operations.keys())
        except ServiceNotFoundError:
            return []

    def operation_exists(
        self, provider: str, api: str, operation: str, source: str | None = None
    ) -> bool:
        src = self._resolve_source(provider, api, source)
        try:
            sd = self._get_service_data(provider, api, src)
            return operation in sd.operations
        except ServiceNotFoundError:
            return False

    def get_operation(
        self, provider: str, api: str, operation: str, source: str | None = None
    ) -> Operation:
        src = self._resolve_source(provider, api, source)
        sd = self._get_service_data(provider, api, src)
        op = sd.operations.get(operation)
        if op is None:
            raise ServiceNotFoundError(
                f"Operation '{operation}' not found in '{provider}/{api}/{src}'",
                service=f"{provider}/{api}/{src}",
                operation=operation,
            )
        return op

    def is_cached(self, provider: str, api: str, source: str | None = None) -> bool:
        """Check if an API service specification is held in memory cache."""
        src = self._resolve_source(provider, api, source)
        if self._cache is not None:
            return self._cache.is_cached(provider, api, src)
        return False
