# src/mapi/models/domain.py
from __future__ import annotations

from typing import Annotated, Any, Literal

import msgspec
from msgspec import Meta

HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE"]
ParameterLocation = Literal["query", "path", "header", "cookie", "body"]
NonEmptyStr = Annotated[str, Meta(min_length=1)]


class Parameter(msgspec.Struct, frozen=True, tag="inline", gc=False, cache_hash=True):
    """A fully defined API parameter."""

    name: NonEmptyStr
    in_: ParameterLocation = msgspec.field(name="in")
    schema_: dict[str, Any] = msgspec.field(name="schema", default_factory=dict)
    description: str = ""
    required: bool | list[str] = False

    @property
    def is_required(self) -> bool:
        """Return True if parameter itself is required."""
        if isinstance(self.required, bool):
            return self.required
        return self.name in self.required


class ParameterRef(msgspec.Struct, frozen=True, tag="ref", gc=False, cache_hash=True):
    """A $ref pointer to a reusable parameter component."""

    ref: NonEmptyStr = msgspec.field(name="$ref")

    @property
    def component_name(self) -> str:
        return self.ref.split("/")[-1]


ParameterUnion = Parameter | ParameterRef


class Server(msgspec.Struct, frozen=True, gc=False):
    url: NonEmptyStr
    description: str = ""
    variables: dict[str, Any] | None = None


class Operation(msgspec.Struct, frozen=True, gc=False):
    """A single API operation."""

    service: NonEmptyStr
    path: NonEmptyStr
    method: HttpMethod
    operation_id: str | None = msgspec.field(name="operationId", default=None)
    summary: str = ""
    description: str = ""
    parameters: list[ParameterUnion] = msgspec.field(default_factory=list)
    deprecated: bool = False


class Components(msgspec.Struct, frozen=True, gc=False):
    """Reusable OpenAPI components (parameters, schemas)."""

    parameters: dict[str, Parameter] = msgspec.field(default_factory=dict)
    schemas: dict[str, dict[str, Any]] = msgspec.field(default_factory=dict)


class ServiceData(msgspec.Struct, frozen=True, gc=False):
    """Complete processed service definition (from mapi.json)."""

    format_version: Annotated[int, Meta(ge=3)]
    service_name: NonEmptyStr
    servers: list[Server]
    components: Components
    operations: dict[str, Operation]


class SpecDiffResult(msgspec.Struct, frozen=True):
    """Result of checking differences between an active spec and a candidate/upstream spec."""

    has_diff: bool
    provider: str
    api: str
    added_operations: list[str] = msgspec.field(default_factory=list)
    removed_operations: list[str] = msgspec.field(default_factory=list)
    modified_operations: list[str] = msgspec.field(default_factory=list)
    current_hash: str | None = None
    remote_hash: str | None = None
    details: str = ""
