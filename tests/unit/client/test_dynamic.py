# tests/unit/client/test_dynamic.py
from __future__ import annotations

import pytest

from mapi import Mapi, RequestConfig, SpecUpdateAvailableWarning


class TestDynamicSpecService:
    def test_register_spec_and_execute_dry_run(self):
        client = Mapi()
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Acme Widgets API", "version": "1.0.0"},
            "servers": [{"url": "https://api.acme.com/v1"}],
            "paths": {
                "/widgets": {
                    "get": {
                        "operationId": "list_widgets",
                        "summary": "List all widgets",
                        "parameters": [
                            {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                        ],
                    }
                }
            },
        }

        # Auto-infer provider
        provider = client.register_spec(spec)
        assert provider == "acme"
        assert client.discovery.provider_exists("acme")
        assert client.discovery.api_exists("acme", "REST")
        assert "list_widgets" in client.discovery.list_operations("acme", "REST")

        # Dry-run call via fluent proxy
        res = client.acme.REST("list_widgets", limit=50, _dry_run=True)
        assert res.metadata.status == "dry_run"
        assert isinstance(res.data, RequestConfig)
        assert res.data.url == "https://api.acme.com/v1/widgets"
        assert res.data.params == {"limit": 50}

    def test_check_spec_diff_and_update(self):
        client = Mapi()
        spec_v1 = {
            "openapi": "3.0.0",
            "info": {"title": "FastTrack API", "version": "1.0.0"},
            "servers": [{"url": "https://api.fasttrack.io"}],
            "paths": {"/orders": {"get": {"operationId": "get_orders", "summary": "Get orders"}}},
        }
        provider = client.register_spec(spec_v1, provider="fasttrack")
        assert provider == "fasttrack"

        spec_v2 = {
            "openapi": "3.0.0",
            "info": {"title": "FastTrack API", "version": "2.0.0"},
            "servers": [{"url": "https://api.fasttrack.io"}],
            "paths": {
                "/orders": {"get": {"operationId": "get_orders", "summary": "Get orders"}},
                "/orders/new": {"post": {"operationId": "create_order", "summary": "Create order"}},
            },
        }

        # Diff check should warn and detect added operation
        with pytest.warns(SpecUpdateAvailableWarning, match="Specification update available"):
            diff = client.check_spec_diff("fasttrack", "REST", spec_source=spec_v2)

        assert diff.has_diff is True
        assert diff.added_operations == ["create_order"]
        assert diff.removed_operations == []

        # Update spec in place
        updated = client.update_spec("fasttrack", "REST", spec_source=spec_v2)
        assert updated is True
        assert "create_order" in client.discovery.list_operations("fasttrack", "REST")
