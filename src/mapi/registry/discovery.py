from __future__ import annotations
import logging
import threading
from typing import Optional

from ..models.domain import Operation
from ..models.registry import ApiInfo, ServiceRegistry
from ..exceptions import ServiceNotFoundError
from .loader import DiskLoader

log = logging.getLogger(__name__)


class RegistryManager:
    """
    Thread-safe lazy loader for ServiceRegistry.
    Double-checked locking ensures single load even under concurrent access.
    """

    def __init__(self, loader: DiskLoader) -> None:
        self._loader = loader
        self._registry: Optional[ServiceRegistry] = None
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
    """
    Provider/API/operation discovery service.
    
    Replaces mapigen's DiscoveryClient (which used static methods and module-level
    lru_cache) with an injectable, testable service.
    """

    def __init__(self, registry_manager: RegistryManager, loader: DiskLoader) -> None:
        self._rm = registry_manager
        self._loader = loader

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
            provider in self._rm.registry.providers
            and api in self._rm.registry.providers[provider]
        )

    def get_api_info(self, provider: str, api: str) -> ApiInfo:
        api_info = self._rm.registry.providers.get(provider, {}).get(api)
        if api_info is None:
            raise ServiceNotFoundError(
                f"API '{api}' not found for provider '{provider}'",
                service=f"{provider}/{api}",
            )
        return api_info

    def _resolve_source(self, provider: str, api: str, source: Optional[str]) -> str:
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

    def list_operations(self, provider: str, api: str, source: Optional[str] = None) -> list[str]:
        src = self._resolve_source(provider, api, source)
        try:
            sd = self._loader.load_service(provider, api, src)
            return list(sd.operations.keys())
        except ServiceNotFoundError:
            return []

    def operation_exists(
        self, provider: str, api: str, operation: str, source: Optional[str] = None
    ) -> bool:
        src = self._resolve_source(provider, api, source)
        try:
            sd = self._loader.load_service(provider, api, src)
            return operation in sd.operations
        except ServiceNotFoundError:
            return False

    def get_operation(
        self, provider: str, api: str, operation: str, source: Optional[str] = None
    ) -> Operation:
        src = self._resolve_source(provider, api, source)
        sd = self._loader.load_service(provider, api, src)
        op = sd.operations.get(operation)
        if op is None:
            raise ServiceNotFoundError(
                f"Operation '{operation}' not found in '{provider}/{api}/{src}'",
                service=f"{provider}/{api}/{src}",
                operation=operation,
            )
        return op
