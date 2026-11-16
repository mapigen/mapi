# tests/unit/test_next_gen_features.py
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from mapi import Mapi, RequestConfig, SpecUpdateAvailableWarning
from mapi.cache.hot_cache import HotOpCache
from mapi.models.domain import Components, Operation, Parameter, Server, ServiceData
from mapi.models.registry import ApiInfo, ServiceRegistry
from mapi.registry.loader import DiskLoader
from mapi.registry.packfile import PackfileLoader, PackfileStorage


class TestRequestConfigToCurl:
    def test_to_curl_basic_get(self):
        cfg = RequestConfig(method="GET", url="https://api.example.com/v1/users")
        curl_str = cfg.to_curl()
        assert curl_str == "curl -X GET 'https://api.example.com/v1/users'"

    def test_to_curl_with_query_params(self):
        cfg = RequestConfig(
            method="GET",
            url="https://api.example.com/search",
            params={"q": "ditto", "limit": 10},
        )
        curl_str = cfg.to_curl()
        assert "curl -X GET 'https://api.example.com/search?q=ditto&limit=10'" in curl_str

    def test_to_curl_redact_auth_default(self):
        cfg = RequestConfig(
            method="POST",
            url="https://api.example.com/data",
            headers={
                "Authorization": "Bearer secret_tok_123",
                "X-Api-Key": "my_secret_key",
                "Content-Type": "application/json",
            },
        )
        curl_str = cfg.to_curl()
        assert "-H 'Authorization: [REDACTED]'" in curl_str
        assert "-H 'X-Api-Key: [REDACTED]'" in curl_str
        assert "-H 'Content-Type: application/json'" in curl_str

    def test_to_curl_no_redact_auth(self):
        cfg = RequestConfig(
            method="POST",
            url="https://api.example.com/data",
            headers={"Authorization": "Bearer secret_tok_123"},
        )
        curl_str = cfg.to_curl(redact_auth=False)
        assert "-H 'Authorization: Bearer secret_tok_123'" in curl_str

    def test_to_curl_with_json_body_and_escaping(self):
        cfg = RequestConfig(
            method="POST",
            url="https://api.example.com/users",
            json_body={"name": "O'Connor", "age": 30},
        )
        curl_str = cfg.to_curl()
        assert "-X POST 'https://api.example.com/users'" in curl_str
        assert "-d '" in curl_str
        assert "O'\\''Connor" in curl_str


class TestDryRunAndErgonomics:
    def _build_client(self, tmp_path):
        client = Mapi.__new__(Mapi)
        client._config = MagicMock()
        client._config.base_url = "https://api.example.com"
        client._config.server_variables = {}
        client._config.default_headers = {"User-Agent": "mapi/0.1.0"}
        client._config.server_pattern = None
        client._config.server_tag = None
        client._config.default_timeout = 30.0
        client._auth = None
        mock_transport = MagicMock()
        client._transport = mock_transport

        sample_op = Operation(
            service="sample/REST/dynamic",
            path="/items/{id}",
            method="POST",
            operation_id="create_item",
            summary="Create Item",
            description="",
            parameters=[Parameter(name="id", in_="path")],
        )
        sample_get_op = Operation(
            service="sample/REST/dynamic",
            path="/items",
            method="GET",
            operation_id="list_items",
            summary="List Items",
            description="",
            parameters=[],
        )
        sample_service = ServiceData(
            format_version=3,
            service_name="sample/REST/dynamic",
            servers=[Server(url="https://api.example.com")],
            components=Components(parameters={}, schemas={}),
            operations={"create_item": sample_op, "list_items": sample_get_op},
        )

        mock_cache = MagicMock()
        mock_cache.get.return_value = sample_service
        client._cache = mock_cache
        client._hot_op_cache = HotOpCache()

        from mapi.client.request_builder import RequestBuilder

        client._builder = RequestBuilder(client._cache, None, hot_cache=client._hot_op_cache)
        return client, mock_transport

    def test_dry_run_sync(self, tmp_path):
        client, transport = self._build_client(tmp_path)
        res = client.execute("sample", "REST", "dynamic", "create_item", _dry_run=True, id="123")
        assert res.metadata.status == "dry_run"
        assert res.metadata.http_status is None
        assert isinstance(res.data, RequestConfig)
        assert res.data.method == "POST"
        assert res.data.url == "https://api.example.com/items/123"
        transport.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_async(self, tmp_path):
        client, transport = self._build_client(tmp_path)
        res = await client.aexecute(
            "sample", "REST", "dynamic", "create_item", _dry_run=True, id="456"
        )
        assert res.metadata.status == "dry_run"
        assert isinstance(res.data, RequestConfig)
        assert res.data.url == "https://api.example.com/items/456"
        transport.arequest.assert_not_called()

    def test_idempotent_injects_uuid_on_post(self, tmp_path):
        client, _ = self._build_client(tmp_path)
        res = client.execute(
            "sample", "REST", "dynamic", "create_item", _dry_run=True, _idempotent=True, id="123"
        )
        assert isinstance(res.data, RequestConfig)
        assert "Idempotency-Key" in res.data.headers
        uuid_val = res.data.headers["Idempotency-Key"]
        uuid.UUID(uuid_val)  # validates valid UUID v4 format

    def test_idempotent_skips_on_get(self, tmp_path):
        client, _ = self._build_client(tmp_path)
        res = client.execute(
            "sample", "REST", "dynamic", "list_items", _dry_run=True, _idempotent=True
        )
        assert isinstance(res.data, RequestConfig)
        assert "Idempotency-Key" not in res.data.headers

    def test_stream_sync_passes_to_transport(self, tmp_path):
        client, transport = self._build_client(tmp_path)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/event-stream"}
        mock_resp.iter_content.return_value = iter([b"data: chunk 1\n\n", b"data: chunk 2\n\n"])
        transport.request.return_value = mock_resp

        res = client.execute("sample", "REST", "dynamic", "list_items", _stream=True)
        transport.request.assert_called_once()
        _, kwargs = transport.request.call_args
        assert kwargs.get("stream") is True
        assert res.metadata.status == "success"
        assert res.data is not None
        chunks = list(res.data)
        assert len(chunks) == 2


class TestHotOpCache:
    def test_hot_op_cache_hit_and_score(self):
        cache = HotOpCache(maxsize=3)
        op1 = Operation(service="s1", path="/p1", method="GET")
        key1 = ("prov", "api", "src", "op1")

        assert cache.get(key1) is None
        cache.put(key1, op1)
        assert key1 in cache
        assert len(cache) == 1

        # Retrieve and verify score increases
        cached = cache.get(key1)
        assert cached is op1
        assert cache._frequencies[key1] == 2

    def test_hot_op_cache_eviction_lfu(self):
        cache = HotOpCache(maxsize=2)
        op1 = Operation(service="s", path="/1", method="GET")
        op2 = Operation(service="s", path="/2", method="GET")
        op3 = Operation(service="s", path="/3", method="GET")

        k1 = ("p", "a", "s", "1")
        k2 = ("p", "a", "s", "2")
        k3 = ("p", "a", "s", "3")

        cache.put(k1, op1)
        cache.put(k2, op2)
        # Boost k1 frequency
        cache.get(k1)
        cache.get(k1)
        assert cache._frequencies[k1] == 3
        assert cache._frequencies[k2] == 1

        # Insert 3rd item; k2 (lowest frequency) should be evicted
        cache.put(k3, op3)
        assert len(cache) == 2
        assert k1 in cache
        assert k3 in cache
        assert k2 not in cache

    def test_hot_op_cache_clear_matching(self):
        cache = HotOpCache(maxsize=10)
        cache.put(("github", "REST", "src1", "op1"), Operation(service="s", path="/", method="GET"))
        cache.put(("github", "REST", "src1", "op2"), Operation(service="s", path="/", method="GET"))
        cache.put(("stripe", "REST", "src1", "op3"), Operation(service="s", path="/", method="GET"))

        assert len(cache) == 3
        cache.clear_matching("github", "REST", "src1")
        assert len(cache) == 1
        assert ("stripe", "REST", "src1", "op3") in cache


class TestPackfileStorageAndLoader:
    def test_packfile_build_and_query(self, tmp_path):
        db_path = tmp_path / "test_services.db"
        registry = ServiceRegistry(
            version="1.0.0",
            generated_at="2026-11-16T12:00:00Z",
            providers={
                "petstore": {
                    "REST": ApiInfo(
                        sources=["github"],
                        operation_count=1,
                        popularity_rank=1,
                        auth_types=[],
                        primary_auth="",
                    )
                }
            },
        )
        op = Operation(
            service="petstore/REST/github",
            path="/pets/{id}",
            method="GET",
            operation_id="get_pet",
            summary="Get pet by ID",
        )
        service = ServiceData(
            format_version=3,
            service_name="petstore/REST/github",
            servers=[Server(url="https://petstore.example.com/v2")],
            components=Components(parameters={}, schemas={}),
            operations={"get_pet": op},
        )

        PackfileStorage.create_packfile(
            db_path, registry, {("petstore", "REST", "github"): service}
        )
        assert db_path.exists()

        with PackfileLoader(db_path) as loader:
            reg = loader.load_registry()
            assert "petstore" in reg.providers

            sdata = loader.load_service("petstore", "REST", "github")
            assert sdata.service_name == "petstore/REST/github"

            op_loaded = loader.load_operation("petstore", "REST", "github", "get_pet")
            assert op_loaded is not None
            assert op_loaded.operation_id == "get_pet"
            assert op_loaded.method == "GET"

            op_ids = loader.list_operations("petstore", "REST", "github")
            assert op_ids == ["get_pet"]

            missing_op = loader.load_operation("petstore", "REST", "github", "non_existent")
            assert missing_op is None

    def test_disk_loader_with_packfile(self, tmp_path):
        db_path = tmp_path / "services.db"
        registry = ServiceRegistry(
            version="1.0",
            generated_at="now",
            providers={
                "myapi": {
                    "REST": ApiInfo(
                        sources=["src"],
                        operation_count=1,
                        popularity_rank=1,
                        auth_types=[],
                        primary_auth="",
                    )
                }
            },
        )
        op = Operation(
            service="myapi/REST/src", path="/status", method="GET", operation_id="get_status"
        )
        service = ServiceData(
            format_version=3,
            service_name="myapi/REST/src",
            servers=[Server(url="https://api.myapi.com")],
            components=Components(parameters={}, schemas={}),
            operations={"get_status": op},
        )
        PackfileStorage.create_packfile(db_path, registry, {("myapi", "REST", "src"): service})

        disk_loader = DiskLoader(registry_path=db_path)
        reg = disk_loader.load_registry()
        assert "myapi" in reg.providers
        sdata = disk_loader.load_service("myapi", "REST", "src")
        assert sdata.service_name == "myapi/REST/src"
        granular_op = disk_loader.load_operation("myapi", "REST", "src", "get_status")
        assert granular_op is not None
        assert granular_op.operation_id == "get_status"


class TestLLMToolCalling:
    def test_to_tool_schema_and_call_tool(self, tmp_path):
        client = Mapi()
        # Test with real pokeapi registered in the built-in data
        tool_spec = client.to_tool("pokeapi", "REST", "pokemon_retrieve")
        assert tool_spec["type"] == "function"
        fn = tool_spec["function"]
        assert fn["name"] == "pokeapi_REST_pokemon_retrieve"
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"
        assert "id" in fn["parameters"]["properties"]

        # Also via ApiProxy
        proxy_spec = client.pokeapi.REST.to_tool("pokemon_retrieve")
        assert proxy_spec == tool_spec

    def test_call_tool_invalid_name(self):
        client = Mapi()
        with pytest.raises(ValueError, match="Invalid tool_name format"):
            client.call_tool("invalid_tool")


class TestDynamicSpecLifecycle:
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


class TestPagination:
    def test_numeric_page_pagination(self):
        client = Mapi()
        # Mock execute to return 2 pages then empty
        responses = [
            {"data": [{"id": 1}, {"id": 2}]},
            {"data": [{"id": 3}, {"id": 4}]},
            {"data": []},
        ]

        with patch.object(client, "execute") as mock_exec:
            mock_exec.side_effect = [
                MagicMock(data=responses[0], metadata=MagicMock(headers={})),
                MagicMock(data=responses[1], metadata=MagicMock(headers={})),
                MagicMock(data=responses[2], metadata=MagicMock(headers={})),
            ]

            pages = list(client.paginate("prov", "api", "src", "list_op", page=1, max_pages=5))
            assert len(pages) == 3
            assert mock_exec.call_count == 3
            assert mock_exec.call_args_list[0][1]["page"] == 1
            assert mock_exec.call_args_list[1][1]["page"] == 2

    def test_cursor_pagination(self):
        client = Mapi()
        page1 = {"items": [{"id": "item_1"}], "has_more": True, "next_cursor": "cur_2"}
        page2 = {"items": [{"id": "item_2"}], "has_more": False}

        with patch.object(client, "execute") as mock_exec:
            mock_exec.side_effect = [
                MagicMock(data=page1, metadata=MagicMock(headers={})),
                MagicMock(data=page2, metadata=MagicMock(headers={})),
            ]

            pages = list(client.paginate("prov", "api", "src", "list_op", max_pages=5))
            assert len(pages) == 2
            assert mock_exec.call_args_list[1][1]["next_cursor"] == "cur_2"

    def test_link_header_pagination(self):
        client = Mapi()
        p1_headers = {"link": '<https://api.example.com/items?page=2&per_page=10>; rel="next"'}
        p2_headers = {}

        with patch.object(client, "execute") as mock_exec:
            mock_exec.side_effect = [
                MagicMock(data=[{"id": 1}], metadata=MagicMock(headers=p1_headers)),
                MagicMock(data=[{"id": 2}], metadata=MagicMock(headers=p2_headers)),
            ]

            pages = list(client.paginate("prov", "api", "src", "list_op", max_pages=5))
            assert len(pages) == 2
            assert mock_exec.call_args_list[1][1]["page"] == "2"
            assert mock_exec.call_args_list[1][1]["per_page"] == "10"
