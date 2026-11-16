# src/mapi/constants.py
"""Centralized constants for the mapi SDK following clean software engineering standards."""

from __future__ import annotations

from typing import Literal

# --- Versioning & User Agent ---
DEFAULT_VERSION: str = "0.1.0"
DEFAULT_USER_AGENT: str = f"mapi/{DEFAULT_VERSION}"

# --- Content Types & Media Types ---
MIME_APPLICATION_JSON: str = "application/json"
MIME_EVENT_STREAM: str = "text/event-stream"
MIME_APPLICATION_YAML: str = "application/yaml"
MIME_TEXT_PLAIN: str = "text/plain"

# --- HTTP Standard Headers ---
HEADER_USER_AGENT: str = "User-Agent"
HEADER_ACCEPT: str = "Accept"
HEADER_CONTENT_TYPE: str = "Content-Type"
HEADER_AUTHORIZATION: str = "Authorization"
HEADER_IDEMPOTENCY_KEY: str = "Idempotency-Key"
HEADER_ETAG: str = "ETag"
HEADER_RETRY_AFTER: str = "Retry-After"
HEADER_LINK: str = "link"

# Lower-case header variants for case-insensitive lookup
HEADER_CONTENT_TYPE_LOWER: str = "content-type"
HEADER_ETAG_LOWER: str = "etag"
HEADER_RETRY_AFTER_LOWER: str = "retry-after"
HEADER_LINK_LOWER: str = "link"
HEADER_X_RATELIMIT_LIMIT: str = "x-ratelimit-limit"
HEADER_RATELIMIT_LIMIT: str = "ratelimit-limit"
HEADER_X_RATELIMIT_REMAINING: str = "x-ratelimit-remaining"
HEADER_RATELIMIT_REMAINING: str = "ratelimit-remaining"
HEADER_X_RATELIMIT_RESET: str = "x-ratelimit-reset"
HEADER_RATELIMIT_RESET: str = "ratelimit-reset"

# Sensitive headers to redact in logs and curl export
SENSITIVE_AUTH_HEADERS: frozenset[str] = frozenset(
    {"authorization", "x-api-key", "api-key", "token"}
)

# Default additive headers applied to outbound client requests
DEFAULT_HEADERS: dict[str, str] = {
    HEADER_USER_AGENT: DEFAULT_USER_AGENT,
    HEADER_ACCEPT: MIME_APPLICATION_JSON,
}

# --- HTTP Methods ---
HTTP_METHOD_GET: str = "GET"
HTTP_METHOD_POST: str = "POST"
HTTP_METHOD_PUT: str = "PUT"
HTTP_METHOD_PATCH: str = "PATCH"
HTTP_METHOD_DELETE: str = "DELETE"
HTTP_METHOD_HEAD: str = "HEAD"
HTTP_METHOD_OPTIONS: str = "OPTIONS"
HTTP_METHOD_TRACE: str = "TRACE"

# Methods that support idempotency injection
MUTATION_HTTP_METHODS: frozenset[str] = frozenset(
    {HTTP_METHOD_POST, HTTP_METHOD_PUT, HTTP_METHOD_PATCH, HTTP_METHOD_DELETE}
)

# Valid OpenAPI HTTP methods (lowercase)
VALID_HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options", "trace"}
)

# --- Filesystem Layout & Registry Defaults ---
PRIMARY_REGISTRY_FILENAME: str = "mapi-registry.json"
DEFAULT_DATA_DIR_NAME: str = "data"
DEFAULT_SOURCE: str = "openapi"
MAPI_EXT_JSON: str = ".mapi.json"
MAPI_EXT_ZST: str = ".mapi.json.zst"
MAPI_EXT_MSGPACK: str = ".mapi.msgpack"
MAPI_EXT_MSGPACK_ZST: str = ".mapi.msgpack.zst"
OPENAPI_EXT_JSON: str = ".openapi.json"
OPENAPI_EXT_YAML: str = ".openapi.yaml"
EXT_JSON: str = ".json"
EXT_YAML: str = ".yaml"
EXT_YML: str = ".yml"

# Packfile Binary Constants
PACKFILE_ZSTD_MAGIC: bytes = b"\x28\xb5\x2f\xfd"

# --- Operation Execution Statuses ---
STATUS_SUCCESS: Literal["success"] = "success"
STATUS_ERROR: Literal["error"] = "error"
STATUS_DRY_RUN: Literal["dry_run"] = "dry_run"

# --- Parameter Locations ---
PARAM_IN_PATH: Literal["path"] = "path"
PARAM_IN_QUERY: Literal["query"] = "query"
PARAM_IN_BODY: Literal["body"] = "body"
PARAM_IN_HEADER: Literal["header"] = "header"
PARAM_IN_COOKIE: Literal["cookie"] = "cookie"

# --- Environment Variable Keys ---
ENV_MAPI_DATA_DIR: str = "MAPI_DATA_DIR"
ENV_MAPI_REGISTRY_PATH: str = "MAPI_REGISTRY_PATH"
ENV_MAPI_CACHE_MAXSIZE: str = "MAPI_CACHE_MAXSIZE"
ENV_MAPI_PINNED_SERVICES: str = "MAPI_PINNED_SERVICES"
ENV_MAPI_SERVER_TAG: str = "MAPI_SERVER_TAG"
ENV_MAPI_SERVER_PATTERN: str = "MAPI_SERVER_PATTERN"

# --- Ergonomic & Control Kwarg Flags ---
FLAG_TYPE: str = "_type"
FLAG_TARGET_TYPE: str = "target_type"
FLAG_RAW: str = "_raw"
FLAG_RAW_ALT: str = "raw"
FLAG_DRY_RUN: str = "_dry_run"
FLAG_DRY_RUN_ALT: str = "dry_run"
FLAG_IDEMPOTENT: str = "_idempotent"
FLAG_IDEMPOTENT_ALT: str = "idempotent"
FLAG_STREAM: str = "_stream"
FLAG_STREAM_ALT: str = "stream"
FLAG_SERVER_TAG: str = "server_tag"
FLAG_SERVER_PATTERN: str = "server_pattern"

# --- Pagination Constants ---
PAGINATION_PAGE: str = "page"
PAGINATION_OFFSET: str = "offset"
PAGINATION_LIMIT: str = "limit"
PAGINATION_STARTING_AFTER: str = "starting_after"
PAGINATION_HAS_MORE: str = "has_more"
PAGINATION_CURSOR_KEYS: tuple[str, ...] = ("next_cursor", "next_token", "cursor", "next")
PAGINATION_ITEM_KEYS: tuple[str, ...] = ("data", "items", "results")
