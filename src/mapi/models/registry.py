# src/mapi/models/registry.py
from __future__ import annotations

from typing import Annotated

import msgspec
from msgspec import Meta

NonEmptyStr = Annotated[str, Meta(min_length=1)]


class MetadataFile(msgspec.Struct, frozen=True, gc=False):
    """Structure of a metadata.yml file on disk."""

    operation_count: int
    auth_types: list[str]
    primary_auth: str
    popularity_rank: int


class ApiInfo(msgspec.Struct, frozen=True, gc=False):
    """Metadata for a single API as stored in mapi-registry.json."""

    sources: list[str]
    operation_count: int
    popularity_rank: int
    auth_types: list[str]
    primary_auth: str


class ServiceRegistry(msgspec.Struct, frozen=True, gc=False):
    """Root object of mapi-registry.json."""

    version: NonEmptyStr
    generated_at: str
    providers: dict[str, dict[str, ApiInfo]]
