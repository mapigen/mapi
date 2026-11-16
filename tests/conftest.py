# tests/conftest.py
from __future__ import annotations
import pytest
import msgspec

from mapi.models import (
    ServiceData, Components, Server, Operation, Parameter, ParameterRef,
    ServiceRegistry, ApiInfo,
)


@pytest.fixture(scope="session")
def sample_parameter() -> Parameter:
    return Parameter(name="user_id", in_="path", schema_={"type": "integer"}, required=True)


@pytest.fixture(scope="session")
def sample_service_data() -> ServiceData:
    data_dict = {
        "format_version": 3,
        "service_name": "mock_service",
        "servers": [{"url": "https://api.example.com", "description": "Test Server"}],
        "components": {
            "parameters": {
                "abc123": {
                    "type": "inline",
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "default": 10},
                    "required": False,
                }
            },
            "schemas": {},
        },
        "operations": {
            "get_user": {
                "service": "mock_service",
                "path": "/users/{user_id}",
                "method": "GET",
                "parameters": [
                    {"type": "inline", "name": "user_id", "in": "path", "schema": {"type": "integer"}, "required": True},
                    {"type": "ref", "$ref": "#/components/parameters/abc123"},
                ],
            }
        },
    }
    return msgspec.json.decode(msgspec.json.encode(data_dict), type=ServiceData)


@pytest.fixture(scope="session")
def sample_registry() -> ServiceRegistry:
    return ServiceRegistry(
        version="1.0",
        generated_at="2025-01-01T00:00:00Z",
        providers={
            "pokeapi": {
                "REST": ApiInfo(
                    sources=["openapi"],
                    operation_count=50,
                    popularity_rank=1,
                    auth_types=[],
                    primary_auth="none",
                )
            },
            "github": {
                "rest": ApiInfo(
                    sources=["openapi", "postman"],
                    operation_count=500,
                    popularity_rank=2,
                    auth_types=["bearer_token"],
                    primary_auth="bearer_token",
                )
            },
        },
    )
