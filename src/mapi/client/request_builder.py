from __future__ import annotations

import logging
from typing import Any

import msgspec

from ..cache.service_cache import ServiceCache
from ..exceptions import ServiceNotFoundError
from ..models.domain import Parameter, ParameterRef
from ..models.request import RequestConfig
from ..validation.param_validator import ParameterValidator

log = logging.getLogger(__name__)


class RequestBuilder:
    """
    Constructs an immutable RequestConfig from operation metadata and call kwargs.
    """

    def __init__(
        self,
        cache: ServiceCache,
        validator: ParameterValidator | None = None,
    ) -> None:
        self._cache = cache
        self._validator = validator

    def build(
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        *,
        base_url: str | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> RequestConfig:
        service_name = f"{provider}/{api}/{source}"

        # 1. Retrieve service definition (cached in memory)
        service_data = self._cache.get(provider, api, source)
        op = service_data.operations.get(operation)
        if op is None:
            raise ServiceNotFoundError(
                f"Operation '{operation}' not found in '{service_name}'",
                service=service_name,
                operation=operation,
            )

        # 2. Parameter schema validation
        if self._validator is not None:
            self._validator.validate(
                provider, api, source, operation, kwargs, service_data=service_data, op_details=op
            )

        # 3. Resolve base URL
        resolved_base_url = base_url or (
            service_data.servers[0].url if service_data.servers else None
        )
        if not resolved_base_url:
            raise ServiceNotFoundError(
                f"No server URL configured for '{service_name}'",
                service=service_name,
            )

        # 4. Bucket kwargs into path, query, body, and headers
        path_params: dict[str, Any] = {}
        query_params: dict[str, Any] = {}
        body_params: dict[str, Any] = {}
        headers: dict[str, str] = {}

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
