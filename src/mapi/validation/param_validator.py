from __future__ import annotations
import logging
from typing import Any, List, Optional

import msgspec

from ..models.domain import Parameter, ParameterRef
from ..cache.service_cache import ServiceCache
from ..exceptions import ServiceNotFoundError, ValidationError

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
        return List[item_type]
    return _TYPE_MAP.get(openapi_type, Any)


class ParameterValidator:
    """
    Validates call kwargs against an operation's declared OpenAPI parameter schema.

    Uses msgspec.defstruct to synthesize an operation-specific typed Struct,
    then executes zero-copy schema validation with msgspec.convert.
    """

    def __init__(self, cache: ServiceCache) -> None:
        self._cache = cache

    def validate(
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        kwargs: dict[str, Any],
    ) -> None:
        """Raise ValidationError if kwargs fail parameter schema validation."""
        service_name = f"{provider}/{api}/{source}"
        service_data = self._cache.get(provider, api, source)

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
                struct_fields.append((param.name, Optional[py_type], None))

        if not struct_fields:
            return

        ParamStruct = msgspec.defstruct(f"{operation}_params", struct_fields, gc=False)
        try:
            msgspec.convert(kwargs, ParamStruct, strict=False)
        except msgspec.ValidationError as exc:
            raise ValidationError(
                str(exc),
                service=service_name,
                operation=operation,
            ) from exc
