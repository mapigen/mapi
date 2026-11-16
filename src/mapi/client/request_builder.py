from __future__ import annotations

import contextlib
import logging
import uuid
from typing import TYPE_CHECKING, Any

import msgspec

from ..cache.service_cache import ServiceCache
from ..exceptions import ServiceNotFoundError
from ..models.domain import Parameter, ParameterRef
from ..models.request import RequestConfig
from ..validation.param_validator import ParameterValidator

if TYPE_CHECKING:
    from ..cache.hot_cache import HotOpCache

log = logging.getLogger(__name__)


class RequestBuilder:
    """
    Constructs an immutable RequestConfig from operation metadata and call kwargs.
    """

    def __init__(
        self,
        cache: ServiceCache,
        validator: ParameterValidator | None = None,
        hot_cache: HotOpCache | None = None,
    ) -> None:
        self._cache = cache
        self._validator = validator
        self._hot_cache = hot_cache

    def build(
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        *,
        base_url: str | None = None,
        server_variables: dict[str, str] | None = None,
        default_headers: dict[str, str] | None = None,
        server_pattern: str | None = None,
        server_tag: str | None = None,
        idempotent: bool = False,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> RequestConfig:
        service_name = f"{provider}/{api}/{source}"
        cache_key = (provider, api, source, operation)

        # 1. Retrieve operation (check HotOpCache first)
        op = self._hot_cache.get(cache_key) if self._hot_cache is not None else None
        service_data = self._cache.get(provider, api, source)

        if op is None:
            op = service_data.operations.get(operation)
            if op is None:
                raise ServiceNotFoundError(
                    f"Operation '{operation}' not found in '{service_name}'",
                    service=service_name,
                    operation=operation,
                )
            if self._hot_cache is not None:
                self._hot_cache.put(cache_key, op)

        # 2. Parameter schema validation
        if self._validator is not None:
            self._validator.validate(
                provider, api, source, operation, kwargs, service_data=service_data, op_details=op
            )

        # 3. Resolve server by tag/pattern or fallback
        effective_tag = (
            kwargs.pop("server_tag", None)
            or kwargs.pop("server_pattern", None)
            or server_tag
            or server_pattern
        )

        if base_url:
            resolved_base_url = base_url
        elif service_data.servers:
            server = service_data.servers[0]
            if effective_tag:
                tag_lower = str(effective_tag).lower()
                for s in service_data.servers:
                    if tag_lower in s.url.lower() or (
                        s.description and tag_lower in s.description.lower()
                    ):
                        server = s
                        break
            url = server.url
            if "{" in url and "}" in url and server.variables:
                vars_map: dict[str, str] = {}
                for var_name, var_def in server.variables.items():
                    if isinstance(var_def, dict) and "default" in var_def:
                        vars_map[var_name] = str(var_def["default"])
                    elif isinstance(var_def, (str, int, float, bool)):
                        vars_map[var_name] = str(var_def)
                if server_variables:
                    vars_map.update(server_variables)
                for var_name in server.variables:
                    if var_name in kwargs:
                        vars_map[var_name] = str(kwargs.pop(var_name))
                with contextlib.suppress(KeyError):
                    url = url.format(**vars_map)
            resolved_base_url = url
        else:
            resolved_base_url = None

        if not resolved_base_url:
            raise ServiceNotFoundError(
                f"No server URL configured for '{service_name}'",
                service=service_name,
            )

        # 4. Bucket kwargs into path, query, body, and headers
        path_params: dict[str, Any] = {}
        query_params: dict[str, Any] = {}
        body_params: dict[str, Any] = {}
        headers: dict[str, str] = {
            "User-Agent": "mapi/0.1.0",
            "Accept": "application/json",
        }
        if default_headers:
            headers.update(default_headers)

        effective_idempotent = (
            idempotent or kwargs.pop("_idempotent", False) or kwargs.pop("idempotent", False)
        )
        if (
            effective_idempotent
            and op.method in ("POST", "PUT", "PATCH", "DELETE")
            and "Idempotency-Key" not in headers
        ):
            headers["Idempotency-Key"] = str(uuid.uuid4())

        for param_union in op.parameters:
            if isinstance(param_union, ParameterRef):
                param: Parameter = service_data.components.parameters[param_union.component_name]
            else:
                param = param_union

            if param.name not in kwargs:
                continue

            value = kwargs[param.name]
            if isinstance(value, msgspec.Struct):
                value = msgspec.to_builtins(value)
            if param.in_ == "path":
                path_params[param.name] = value
            elif param.in_ == "query":
                query_params[param.name] = value
            elif param.in_ == "body":
                body_params[param.name] = value
            elif param.in_ == "header":
                headers[param.name] = str(value)

        # 5. Format path
        try:
            formatted_path = op.path.format(**path_params)
        except KeyError as exc:
            raise ServiceNotFoundError(
                f"Missing required path parameter: {exc}",
                service=service_name,
                operation=operation,
            ) from exc

        clean_path = formatted_path if formatted_path.startswith("/") else f"/{formatted_path}"
        full_url = f"{resolved_base_url.rstrip('/')}{clean_path}"

        return RequestConfig(
            method=op.method,
            url=full_url,
            params=query_params,
            headers=headers,
            json_body=body_params if body_params else None,
            timeout=timeout,
        )
