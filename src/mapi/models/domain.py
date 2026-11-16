# src/mapi/models/domain.py
from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional, Union
from typing_extensions import Annotated
import msgspec
from msgspec import Meta

HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE"]
ParameterLocation = Literal["query", "path", "header", "cookie", "body"]
NonEmptyStr = Annotated[str, Meta(min_length=1)]


class Parameter(msgspec.Struct, frozen=True, tag="inline"):
    """A fully defined API parameter."""
    name: NonEmptyStr
    in_: ParameterLocation = msgspec.field(name="in")
    schema_: Dict[str, Any] = msgspec.field(name="schema", default_factory=dict)
    description: str = ""
    required: bool = False


class ParameterRef(msgspec.Struct, frozen=True, tag="ref"):
    """A $ref pointer to a reusable parameter component."""
    ref: NonEmptyStr = msgspec.field(name="$ref")

    @property
    def component_name(self) -> str:
        return self.ref.split("/")[-1]


ParameterUnion = Union[Parameter, ParameterRef]


class Server(msgspec.Struct, frozen=True):
    url: NonEmptyStr
    description: str = ""
    variables: Optional[Dict[str, Any]] = None


class Operation(msgspec.Struct, frozen=True):
    """A single API operation."""
    service: NonEmptyStr
    path: NonEmptyStr
    method: HttpMethod
    operation_id: Optional[str] = msgspec.field(name="operationId", default=None)
    summary: str = ""
    description: str = ""
    parameters: List[ParameterUnion] = msgspec.field(default_factory=list)
    deprecated: bool = False


class Components(msgspec.Struct, frozen=True):
    """Reusable OpenAPI components (parameters, schemas)."""
    parameters: Dict[str, Parameter] = msgspec.field(default_factory=dict)
    schemas: Dict[str, Dict[str, Any]] = msgspec.field(default_factory=dict)


class ServiceData(msgspec.Struct, frozen=True):
    """Complete processed service definition (from utilize.json)."""
    format_version: Annotated[int, Meta(ge=3)]
    service_name: NonEmptyStr
    servers: List[Server]
    components: Components
    operations: Dict[str, Operation]
