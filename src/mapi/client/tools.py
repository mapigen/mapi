# src/mapi/client/tools.py
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..exceptions import ServiceNotFoundError
from ..models.domain import ParameterRef
from ..models.response import MapiResult

if TYPE_CHECKING:
    from .client import Mapi


class ToolService:
    """Converts Operation metadata into LLM function calling definitions."""

    def __init__(self, client: Mapi) -> None:
        self._client = client

    def to_tool(
        self,
        provider: str,
        api: str,
        operation: str,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Export JSON Schema function calling definition for an operation."""
        src = source or self._client._discovery.get_api_info(provider, api).sources[0]
        service_data = self._client._cache.get(provider, api, src)
        op = service_data.operations.get(operation)
        if op is None:
            raise ServiceNotFoundError(
                f"Operation '{operation}' not found in '{provider}/{api}/{src}'",
                service=f"{provider}/{api}/{src}",
                operation=operation,
            )

        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_union in op.parameters:
            if isinstance(param_union, ParameterRef):
                param = service_data.components.parameters.get(param_union.component_name)
            else:
                param = param_union

            if param is None:
                continue

            param_schema = dict(param.schema_) if param.schema_ else {}
            prop_def: dict[str, Any] = {
                "type": param_schema.get("type", "string"),
            }
            if param.description:
                prop_def["description"] = param.description
            elif "description" in param_schema:
                prop_def["description"] = param_schema["description"]
            if "enum" in param_schema:
                prop_def["enum"] = param_schema["enum"]
            if "default" in param_schema:
                prop_def["default"] = param_schema["default"]

            properties[param.name] = prop_def
            if param.is_required:
                required.append(param.name)

        func_name = f"{provider}_{api}_{operation}".replace("-", "_")
        return {
            "type": "function",
            "function": {
                "name": func_name,
                "description": op.summary
                or op.description
                or f"Execute {operation} on {provider}/{api}",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def call_tool(self, tool_name: str, **arguments: Any) -> MapiResult:
        """Execute a function call returned by an LLM (e.g. 'pokeapi_REST_pokemon_retrieve')."""
        parts = tool_name.split("_", 2)
        if len(parts) < 3:
            raise ValueError(
                f"Invalid tool_name format '{tool_name}'. Expected format: '<provider>_<api>_<operation>'"
            )
        provider, api, operation = parts[0], parts[1], parts[2]
        info = self._client._discovery.get_api_info(provider, api)
        return self._client.execute(provider, api, info.sources[0], operation, **arguments)
