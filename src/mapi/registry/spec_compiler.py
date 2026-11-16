# src/mapi/registry/spec_compiler.py
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from ..constants import (
    EXT_JSON,
    EXT_YAML,
    EXT_YML,
    MAPI_EXT_JSON,
    MIME_APPLICATION_JSON,
    OPENAPI_EXT_JSON,
    OPENAPI_EXT_YAML,
    PARAM_IN_BODY,
    VALID_HTTP_METHODS,
)
from ..models.domain import (
    Components,
    HttpMethod,
    Operation,
    Parameter,
    ParameterRef,
    Server,
    ServiceData,
)

_KNOWN_SPEC_EXTENSIONS = (
    OPENAPI_EXT_JSON,
    MAPI_EXT_JSON,
    OPENAPI_EXT_YAML,
    EXT_JSON,
    EXT_YAML,
    EXT_YML,
)


def infer_provider(spec: dict[str, Any], url_or_path: str | None = None) -> str:
    """
    Auto-infer a provider name from OpenAPI server URLs, info title, or URL/path.
    """
    # 1. Inspect server URLs
    servers = spec.get("servers")
    if isinstance(servers, list) and servers:
        for s in servers:
            if isinstance(s, dict) and "url" in s:
                u = s["url"]
                parsed = urllib.parse.urlparse(u)
                hostname = parsed.hostname or ""
                if hostname and hostname not in ("localhost", "127.0.0.1", ""):
                    # Strip common subdomains
                    clean_host = re.sub(
                        r"^(api|sandbox|dev|v\d+|www|staging)\.", "", hostname, flags=re.IGNORECASE
                    )
                    parts = clean_host.split(".")
                    if parts and parts[0]:
                        candidate = re.sub(r"[^a-zA-Z0-9_]+", "", parts[0]).lower()
                        if candidate:
                            return candidate

    # 2. Inspect info.title
    info = spec.get("info")
    if isinstance(info, dict) and "title" in info:
        title = str(info["title"]).strip()
        # Remove trailing words like 'API', 'OpenAPI', 'Service', 'v1', etc.
        title_clean = re.sub(
            r"\b(api|openapi|service|rest|v\d+)\b", "", title, flags=re.IGNORECASE
        ).strip()
        tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", title_clean) if t]
        if tokens:
            return tokens[0].lower()

    # 3. Inspect url_or_path
    if url_or_path:
        parsed = urllib.parse.urlparse(url_or_path)
        path = parsed.path or url_or_path
        stem = path.split("/")[-1].split("?")[0].split("#")[0]
        for ext in _KNOWN_SPEC_EXTENSIONS:
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        candidate = re.sub(r"[^a-zA-Z0-9_]+", "", stem).lower()
        if candidate and candidate not in ("openapi", "swagger", "spec"):
            return candidate

    return "dynamic"


def compile_spec(spec: dict[str, Any], service_name: str) -> ServiceData:
    """
    Compile an OpenAPI 3.0 / 3.1 dictionary into a native ServiceData struct.
    """
    # 1. Servers
    raw_servers = spec.get("servers", [])
    servers: list[Server] = []
    if isinstance(raw_servers, list):
        for s in raw_servers:
            if isinstance(s, dict) and "url" in s and s["url"]:
                servers.append(
                    Server(
                        url=str(s["url"]),
                        description=str(s.get("description", "")),
                        variables=s.get("variables"),
                    )
                )
    if not servers:
        servers.append(Server(url="/", description="Default server"))

    # 2. Components
    raw_components = spec.get("components", {})
    comp_parameters: dict[str, Parameter] = {}
    schemas: dict[str, dict[str, Any]] = {}
    if isinstance(raw_components, dict):
        schemas = raw_components.get("schemas", {})
        raw_params = raw_components.get("parameters", {})
        if isinstance(raw_params, dict):
            for p_name, p_def in raw_params.items():
                if isinstance(p_def, dict) and "name" in p_def and "in" in p_def:
                    comp_parameters[p_name] = Parameter(
                        name=p_def["name"],
                        in_=p_def["in"],
                        schema_=p_def.get("schema", {}),
                        description=str(p_def.get("description", "")),
                        required=bool(p_def.get("required", False)),
                    )

    # 3. Operations
    operations: dict[str, Operation] = {}
    paths = spec.get("paths", {})
    if isinstance(paths, dict):
        for path_str, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            path_level_params = path_item.get("parameters", [])
            if not isinstance(path_level_params, list):
                path_level_params = []

            for method_str, op_dict in path_item.items():
                method_lower = method_str.lower()
                if method_lower not in VALID_HTTP_METHODS or not isinstance(op_dict, dict):
                    continue

                op_id = op_dict.get("operationId")
                if not op_id:
                    # Synthesize stable operationId: e.g. get_users_by_id
                    clean_path = re.sub(r"[{}]", "", path_str).strip("/")
                    clean_path = re.sub(r"[^a-zA-Z0-9]+", "_", clean_path).strip("_")
                    op_id = f"{method_lower}_{clean_path}" if clean_path else method_lower

                # Aggregate parameters: operation-level overrides path-level
                combined_params: list[Parameter | ParameterRef] = []
                seen_params: set[str] = set()

                all_raw_params = list(path_level_params) + list(op_dict.get("parameters", []))
                for p in all_raw_params:
                    if not isinstance(p, dict):
                        continue
                    if "$ref" in p:
                        ref_str = p["$ref"]
                        comp_name = ref_str.split("/")[-1]
                        if comp_name not in seen_params:
                            seen_params.add(comp_name)
                            combined_params.append(ParameterRef(ref=ref_str))
                    elif "name" in p and "in" in p:
                        p_name = p["name"]
                        if p_name not in seen_params:
                            seen_params.add(p_name)
                            combined_params.append(
                                Parameter(
                                    name=p_name,
                                    in_=p["in"],
                                    schema_=p.get("schema", {}),
                                    description=str(p.get("description", "")),
                                    required=bool(p.get("required", False)),
                                )
                            )

                # Request body parameters (OpenAPI 3.x requestBody)
                request_body = op_dict.get("requestBody")
                if isinstance(request_body, dict):
                    content = request_body.get("content", {})
                    json_content = content.get(MIME_APPLICATION_JSON, {})
                    body_schema = json_content.get("schema", {})
                    # If properties exist in body schema, expose them as body parameters
                    if isinstance(body_schema, dict) and "properties" in body_schema:
                        req_fields = set(body_schema.get("required", []))
                        for prop_name, prop_def in body_schema["properties"].items():
                            if prop_name not in seen_params:
                                seen_params.add(prop_name)
                                combined_params.append(
                                    Parameter(
                                        name=prop_name,
                                        in_=PARAM_IN_BODY,
                                        schema_=prop_def if isinstance(prop_def, dict) else {},
                                        description=str(prop_def.get("description", ""))
                                        if isinstance(prop_def, dict)
                                        else "",
                                        required=prop_name in req_fields,
                                    )
                                )

                method_enum: HttpMethod = method_lower.upper()  # type: ignore
                operations[op_id] = Operation(
                    service=service_name,
                    path=path_str,
                    method=method_enum,
                    operation_id=op_id,
                    summary=str(op_dict.get("summary", "")),
                    description=str(op_dict.get("description", "")),
                    parameters=combined_params,
                    deprecated=bool(op_dict.get("deprecated", False)),
                )

    return ServiceData(
        format_version=3,
        service_name=service_name,
        servers=servers,
        components=Components(parameters=comp_parameters, schemas=schemas),
        operations=operations,
    )
