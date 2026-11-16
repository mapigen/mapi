from __future__ import annotations

import logging
from typing import Any

import msgspec

from ..cache.service_cache import ServiceCache
from ..exceptions import ServiceNotFoundError, ValidationError
from ..models.domain import Parameter, ParameterRef

log = logging.getLogger(__name__)

_TYPE_MAP: dict[str, Any] = {
    "integer": int,
    "string": str,
    "boolean": bool,
    "number": float,
}


def _openapi_to_python(schema: dict[str, Any]) -> Any:
    """Convert an OpenAPI schema 'type' to a Python type hint for msgspec."""
    openapi_type = schema.get("type")
    if not isinstance(openapi_type, str):
        return Any
    if openapi_type == "array":
        item_type = _openapi_to_python(schema.get("items", {}))
        return list[item_type]
    return _TYPE_MAP.get(openapi_type, Any)


class ParameterValidator:
    """Validates call kwargs against an operation's declared OpenAPI parameter schema."""

    def __init__(self, cache: ServiceCache) -> None:
        self._cache = cache
        self._struct_cache: dict[tuple[str, str, str, str], type[msgspec.Struct] | None] = {}

    def clear_cache(self) -> None:
        """Clear cached compiled parameter structs."""
        self._struct_cache.clear()

    def validate(
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        kwargs: dict[str, Any],
        service_data: Any | None = None,
        op_details: Any | None = None,
    ) -> None:
        """Raise ValidationError if kwargs fail parameter schema validation."""
        service_name = f"{provider}/{api}/{source}"
        cache_key = (provider, api, source, operation)

        # 1. Fast-path: Check compiled struct cache
        if cache_key in self._struct_cache:
            cached_struct = self._struct_cache[cache_key]
            if cached_struct is None:
                return
            try:
                msgspec.convert(kwargs, cached_struct, strict=False)
                return
            except msgspec.ValidationError as exc:
                raise ValidationError(str(exc), service=service_name, operation=operation) from exc

        # 2. First-time compile: Resolve service data and operation
        if service_data is None:
            service_data = self._cache.get(provider, api, source)

        if op_details is None:
            op_details = service_data.operations.get(operation)

        if not op_details:
            raise ServiceNotFoundError(
                f"Operation '{operation}' not found in '{service_name}'",
                service=service_name,
                operation=operation,
            )

        struct_fields: list[tuple] = []
        for param_union in op_details.parameters:
            if isinstance(param_union, ParameterRef):
                param: Parameter = service_data.components.parameters[param_union.component_name]
            else:
                param = param_union

            if not param.name.isidentifier():
                log.debug("Skipping non-identifier parameter: %s", param.name)
                continue

            py_type = _openapi_to_python(param.schema_)

            if param.required:
                struct_fields.append((param.name, py_type))
            else:
                struct_fields.append((param.name, py_type | None, None))

        if not struct_fields:
            self._struct_cache[cache_key] = None
            return

        param_struct = msgspec.defstruct(f"{operation}_params", struct_fields, gc=False)
        self._struct_cache[cache_key] = param_struct

        try:
            msgspec.convert(kwargs, param_struct, strict=False)
        except msgspec.ValidationError as exc:
            raise ValidationError(
                str(exc),
                service=service_name,
                operation=operation,
            ) from exc
