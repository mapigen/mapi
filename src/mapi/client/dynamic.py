# src/mapi/client/dynamic.py
from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import msgspec

from ..exceptions import ServiceNotFoundError, SpecUpdateAvailableWarning
from ..models.domain import SpecDiffResult
from ..models.registry import ApiInfo, ServiceRegistry
from ..registry.spec_compiler import compile_spec, infer_provider

if TYPE_CHECKING:
    from .client import Mapi

log = logging.getLogger("mapi")


class DynamicSpecService:
    """Manages OpenAPI ingestion, diff checking, and spec updates."""

    def __init__(self, client: Mapi) -> None:
        self._client = client
        self._registered_specs: dict[tuple[str, str], Any] = {}

    def register_spec(
        self,
        spec_source: str | Path | dict[str, Any],
        provider: str | None = None,
        api: str = "REST",
        source: str = "dynamic",
    ) -> str:
        """
        Dynamically register an OpenAPI specification at runtime.

        :param spec_source: OpenAPI spec dict, JSON/YAML string, URL, or Path.
        :param provider: Optional provider name. If None, auto-inferred from servers URL or title.
        :param api: API identifier (default 'REST').
        :param source: Source identifier (default 'dynamic').
        :return: The resolved provider name.
        """
        spec = self.resolve_spec_source(spec_source)
        resolved_provider = provider or infer_provider(
            spec, str(spec_source) if isinstance(spec_source, (str, Path)) else None
        )

        service_name = f"{resolved_provider}/{api}/{source}"
        service_data = compile_spec(spec, service_name=service_name)

        # Store in ServiceCache
        self._client._cache.put(resolved_provider, api, source, service_data)

        # Register in RegistryManager
        reg = self._client._registry_mgr.registry
        current_providers = dict(reg.providers)
        prov_apis = dict(current_providers.get(resolved_provider, {}))
        prov_apis[api] = ApiInfo(
            sources=[source],
            operation_count=len(service_data.operations),
            popularity_rank=1,
            auth_types=[],
            primary_auth="",
        )
        current_providers[resolved_provider] = prov_apis
        self._client._registry_mgr._registry = ServiceRegistry(
            version=reg.version,
            generated_at=reg.generated_at,
            providers=current_providers,
        )

        # Save registered spec source for diff checking
        self._registered_specs[(resolved_provider, api)] = spec_source

        return resolved_provider

    def check_spec_diff(
        self,
        provider: str,
        api: str = "REST",
        spec_source: str | Path | dict[str, Any] | None = None,
        source: str = "dynamic",
    ) -> SpecDiffResult:
        """
        Check if an upstream specification has differences compared to the active registered spec.
        Emits SpecUpdateAvailableWarning if changes are detected.
        """
        target_source = spec_source
        if target_source is None:
            target_source = self._registered_specs.get((provider, api))

        if target_source is None:
            return SpecDiffResult(
                has_diff=False,
                provider=provider,
                api=api,
                details="No remote spec source configured to check diff",
            )

        new_spec = self.resolve_spec_source(target_source)
        candidate_data = compile_spec(new_spec, service_name=f"{provider}/{api}/{source}")
        current_data = self._client._cache.get(provider, api, source)

        curr_ops = set(current_data.operations.keys())
        cand_ops = set(candidate_data.operations.keys())

        added = sorted(list(cand_ops - curr_ops))
        removed = sorted(list(curr_ops - cand_ops))
        modified: list[str] = []

        for op_id in curr_ops & cand_ops:
            c_op = current_data.operations[op_id]
            n_op = candidate_data.operations[op_id]
            if (
                c_op.method != n_op.method
                or c_op.path != n_op.path
                or len(c_op.parameters) != len(n_op.parameters)
            ):
                modified.append(op_id)
        modified.sort()

        has_diff = bool(added or removed or modified)
        if has_diff:
            msg = (
                f"Specification update available for '{provider}/{api}': "
                f"{len(added)} added, {len(removed)} removed, {len(modified)} modified operations."
            )
            warnings.warn(msg, SpecUpdateAvailableWarning, stacklevel=2)
            log.warning(msg)

        return SpecDiffResult(
            has_diff=has_diff,
            provider=provider,
            api=api,
            added_operations=added,
            removed_operations=removed,
            modified_operations=modified,
            details=f"{len(added)} added, {len(removed)} removed, {len(modified)} modified",
        )

    def update_spec(
        self,
        provider: str,
        api: str = "REST",
        spec_source: str | Path | dict[str, Any] | None = None,
        source: str = "dynamic",
        force: bool = False,
    ) -> bool:
        """Update an existing spec in the client cache."""
        target_source = spec_source
        if target_source is None:
            target_source = self._registered_specs.get((provider, api))

        if target_source is None:
            raise ServiceNotFoundError(
                f"Cannot update spec for '{provider}/{api}': no spec source provided",
                service=f"{provider}/{api}",
            )

        diff = self.check_spec_diff(provider, api, spec_source=target_source, source=source)
        if not diff.has_diff and not force:
            return False

        new_spec = self.resolve_spec_source(target_source)
        service_name = f"{provider}/{api}/{source}"
        new_data = compile_spec(new_spec, service_name=service_name)

        # Atomically update in ServiceCache
        self._client._cache.put(provider, api, source, new_data)

        # Invalidate hot op cache entries for this service
        self._client._hot_op_cache.clear_matching(provider, api, source)

        self._registered_specs[(provider, api)] = target_source

        return True

    def resolve_spec_source(self, spec_source: str | Path | dict[str, Any]) -> dict[str, Any]:
        """Load and decode OpenAPI spec from dict, Path, file, URL, or JSON/YAML string."""
        if isinstance(spec_source, dict):
            return spec_source

        if isinstance(spec_source, Path) or (
            isinstance(spec_source, str)
            and not spec_source.startswith(("http://", "https://", "{"))
            and Path(spec_source).exists()
        ):
            p = Path(spec_source)
            raw = p.read_bytes()
            if p.suffix in (".yaml", ".yml"):
                return msgspec.yaml.decode(raw)
            return msgspec.json.decode(raw)

        if isinstance(spec_source, str):
            if spec_source.startswith(("http://", "https://")):
                sync_session = self._client._transport._sync_session
                resp = sync_session.get(spec_source)
                resp.raise_for_status()
                content = resp.content or b""
                if spec_source.endswith((".yaml", ".yml")):
                    return msgspec.yaml.decode(content)
                return msgspec.json.decode(content)
            # Try JSON first, then YAML
            try:
                return msgspec.json.decode(spec_source.encode("utf-8"))
            except Exception:
                return msgspec.yaml.decode(spec_source.encode("utf-8"))

        raise ValueError(f"Unsupported spec source: {type(spec_source)}")
