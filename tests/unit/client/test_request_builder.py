# tests/unit/client/test_request_builder.py
from __future__ import annotations

from unittest.mock import MagicMock

import msgspec

from mapi.client.request_builder import RequestBuilder
from mapi.models.domain import Server


class TestRequestBuilder:
    def test_templated_server_url_resolution(self, sample_service_data):
        sample_service_data = msgspec.structs.replace(
            sample_service_data,
            servers=[
                Server(
                    url="https://{subdomain}.example.com:{port}/{version}",
                    variables={
                        "subdomain": {"default": "api"},
                        "port": {"default": "443"},
                        "version": {"default": "v1"},
                    },
                )
            ],
        )
        cache = MagicMock()
        cache.get.return_value = sample_service_data
        builder = RequestBuilder(cache)

        config = builder.build("mock_service", "REST", "openapi", "get_user", user_id=123)
        assert config.url == "https://api.example.com:443/v1/users/123"

        config2 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=123,
            subdomain="sandbox",
            port="8443",
        )
        assert config2.url == "https://sandbox.example.com:8443/v1/users/123"

    def test_default_headers_additive_and_overrides(self, sample_service_data):
        cache = MagicMock()
        cache.get.return_value = sample_service_data
        builder = RequestBuilder(cache)

        # 1. Base defaults applied
        c1 = builder.build("mock_service", "REST", "openapi", "get_user", user_id=1)
        assert c1.headers.get("User-Agent") == "mapi/0.1.0"
        assert c1.headers.get("Accept") == "application/json"

        # 2. Additive user headers
        c2 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=1,
            default_headers={"X-Custom-Tenant": "tenant-abc"},
        )
        assert c2.headers.get("User-Agent") == "mapi/0.1.0"
        assert c2.headers.get("Accept") == "application/json"
        assert c2.headers.get("X-Custom-Tenant") == "tenant-abc"

        # 3. User can override standard default header
        c3 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=1,
            default_headers={"User-Agent": "custom-agent/2.0"},
        )
        assert c3.headers.get("User-Agent") == "custom-agent/2.0"
        assert c3.headers.get("Accept") == "application/json"

    def test_server_tag_and_pattern_selection(self, sample_service_data):
        sample_service_data = msgspec.structs.replace(
            sample_service_data,
            servers=[
                Server(url="https://api.example.com/v1", description="Production"),
                Server(url="https://sandbox.example.com/v1", description="Sandbox Environment"),
                Server(url="https://eu.example.com/v1", description="European Union DC"),
            ],
        )
        cache = MagicMock()
        cache.get.return_value = sample_service_data
        builder = RequestBuilder(cache)

        # Default picks first server
        c0 = builder.build("mock_service", "REST", "openapi", "get_user", user_id=1)
        assert c0.url == "https://api.example.com/v1/users/1"

        # Match by description tag
        c1 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=1,
            server_tag="sandbox",
        )
        assert c1.url == "https://sandbox.example.com/v1/users/1"

        # Match by URL pattern
        c2 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=1,
            server_pattern="eu.example.com",
        )
        assert c2.url == "https://eu.example.com/v1/users/1"

        # Fallback to first if pattern unmatched
        c3 = builder.build(
            "mock_service",
            "REST",
            "openapi",
            "get_user",
            user_id=1,
            server_tag="nonexistent",
        )
        assert c3.url == "https://api.example.com/v1/users/1"
