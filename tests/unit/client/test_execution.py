# tests/unit/client/test_execution.py
from __future__ import annotations

import uuid
from typing import cast
from unittest.mock import MagicMock

import msgspec
import pytest
from niquests.exceptions import HTTPError

from mapi import BatchRequest, Mapi, MapiResult
from mapi.cache.hot_cache import HotOpCache
from mapi.client.request_builder import RequestBuilder
from mapi.exceptions import ClientError, RateLimitError, ServerError, TransportError
from mapi.models.domain import Components, Operation, Parameter, Server, ServiceData
from mapi.models.request import RequestConfig
from tests.unit.client.conftest import build_test_mapi


class TestMapiExecution:
    def test_sync_execute_success(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        result = client.execute("pokeapi", "REST", "openapi", "get_pokemon", id="pikachu")
        assert isinstance(result, MapiResult)
        assert result.data == {"id": 1, "name": "pikachu"}
        assert result.metadata.status == "success"
        assert result.metadata.http_status == 200
        assert result.metadata.network_duration_ms is not None
        assert result.metadata.duration_ms >= 0

    def test_proxy_call_syntax(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        result = client.pokeapi.REST("get_pokemon", id="pikachu")
        assert isinstance(result, MapiResult)
        assert result.data == {"id": 1, "name": "pikachu"}

    @pytest.mark.asyncio
    async def test_async_aexecute_success(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        result = await client.aexecute("pokeapi", "REST", "openapi", "get_pokemon", id="pikachu")
        assert isinstance(result, MapiResult)
        assert result.data == {"id": 1, "name": "pikachu"}
        assert result.metadata.network_duration_ms is not None

    @pytest.mark.asyncio
    async def test_proxy_async_aexecute_syntax(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        result = await client.pokeapi.REST.aexecute("get_pokemon", id="pikachu")
        assert isinstance(result, MapiResult)
        assert result.data == {"id": 1, "name": "pikachu"}

    def test_sync_execute_typed_model(self, sample_service_data, sample_registry):
        class Pokemon(msgspec.Struct):
            id: int
            name: str

        client = build_test_mapi(sample_service_data, sample_registry)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"id": 25, "name": "pikachu"}'
        mock_resp.json.return_value = {"id": 25, "name": "pikachu"}
        cast(MagicMock, client._transport.request).return_value = mock_resp

        result = client.pokeapi.REST("get_pokemon", id="pikachu", _type=Pokemon)
        assert isinstance(result.data, Pokemon)
        assert result.data.id == 25
        assert result.data.name == "pikachu"

    def test_sync_execute_raw_response(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"id": 25, "name": "pikachu"}'
        cast(MagicMock, client._transport.request).return_value = mock_resp

        result = client.pokeapi.REST("get_pokemon", id="pikachu", _raw=True)
        assert isinstance(result.data, msgspec.Raw)
        assert bytes(result.data) == b'{"id": 25, "name": "pikachu"}'

    def test_rate_limit_429_raises(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        resp = MagicMock()
        resp.status_code = 429
        cast(MagicMock, client._transport.request).side_effect = HTTPError(
            "Too Many Requests", response=resp
        )
        with pytest.raises(RateLimitError) as exc_info:
            client.pokeapi.REST("get_pokemon")
        assert exc_info.value.http_status == 429

    def test_server_error_503_raises(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        resp = MagicMock()
        resp.status_code = 503
        cast(MagicMock, client._transport.request).side_effect = HTTPError(
            "Service Unavailable", response=resp
        )
        with pytest.raises(ServerError) as exc_info:
            client.pokeapi.REST("get_pokemon")
        assert exc_info.value.http_status == 503

    def test_client_error_404_raises(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        resp = MagicMock()
        resp.status_code = 404
        cast(MagicMock, client._transport.request).side_effect = HTTPError(
            "Not Found", response=resp
        )
        with pytest.raises(ClientError) as exc_info:
            client.pokeapi.REST("get_pokemon")
        assert exc_info.value.http_status == 404

    def test_response_headers_captured(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        result = client.pokeapi.REST("get_pokemon", id="pikachu")
        assert result.metadata.headers.get("X-RateLimit-Remaining") == "4999"
        assert result.metadata.headers.get("Content-Type") == "application/json"

    @pytest.mark.asyncio
    async def test_abatch_execution(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        requests = [
            BatchRequest(
                provider="pokeapi", api="REST", operation="get_pokemon", kwargs={"id": "ditto"}
            ),
            ("pokeapi", "REST", "get_pokemon", {"id": "pikachu"}),
        ]
        results = await client.abatch(requests, max_concurrency=2)
        assert len(results) == 2
        assert all(isinstance(r, MapiResult) for r in results)


class TestDryRunAndErgonomics:
    @pytest.fixture
    def ergonomic_client(self):
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
        client._builder = RequestBuilder(client._cache, None, hot_cache=client._hot_op_cache)
        return client, mock_transport

    def test_dry_run_sync(self, ergonomic_client):
        client, transport = ergonomic_client
        res = client.execute("sample", "REST", "dynamic", "create_item", _dry_run=True, id="123")
        assert res.metadata.status == "dry_run"
        assert res.metadata.http_status is None
        assert isinstance(res.data, RequestConfig)
        assert res.data.method == "POST"
        assert res.data.url == "https://api.example.com/items/123"
        transport.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_async(self, ergonomic_client):
        client, transport = ergonomic_client
        res = await client.aexecute(
            "sample", "REST", "dynamic", "create_item", _dry_run=True, id="456"
        )
        assert res.metadata.status == "dry_run"
        assert isinstance(res.data, RequestConfig)
        assert res.data.url == "https://api.example.com/items/456"
        transport.arequest.assert_not_called()

    def test_idempotent_injects_uuid_on_post(self, ergonomic_client):
        client, _ = ergonomic_client
        res = client.execute(
            "sample", "REST", "dynamic", "create_item", _dry_run=True, _idempotent=True, id="123"
        )
        assert isinstance(res.data, RequestConfig)
        assert "Idempotency-Key" in res.data.headers
        uuid_val = res.data.headers["Idempotency-Key"]
        uuid.UUID(uuid_val)  # validates valid UUID v4 format

    def test_idempotent_skips_on_get(self, ergonomic_client):
        client, _ = ergonomic_client
        res = client.execute(
            "sample", "REST", "dynamic", "list_items", _dry_run=True, _idempotent=True
        )
        assert isinstance(res.data, RequestConfig)
        assert "Idempotency-Key" not in res.data.headers

    def test_stream_sync_passes_to_transport(self, ergonomic_client):
        client, transport = ergonomic_client
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

    def test_sync_batch_sequential(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"name": "ditto"}'
        mock_resp.json.return_value = {"name": "ditto"}
        cast(MagicMock, client._transport.request).return_value = mock_resp

        requests = [
            ("pokeapi", "REST", "get_pokemon", {"id": "ditto"}),
            BatchRequest(provider="pokeapi", api="REST", operation="get_pokemon", kwargs={"id": "ditto"}),
        ]
        results = client.batch(requests)
        assert len(results) == 2
        assert results[0].data == {"name": "ditto"}
        assert results[1].data == {"name": "ditto"}

    def test_sync_batch_return_exceptions(self, sample_service_data, sample_registry):
        client = build_test_mapi(sample_service_data, sample_registry)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"name": "ditto"}'
        mock_resp.json.return_value = {"name": "ditto"}
        cast(MagicMock, client._transport.request).side_effect = [mock_resp, HTTPError("Fail")]

        requests = [
            ("pokeapi", "REST", "get_pokemon", {"id": "ditto"}),
            ("pokeapi", "REST", "get_pokemon", {"id": "fail"}),
        ]
        # With return_exceptions=True
        results = client.batch(requests, return_exceptions=True)
        assert len(results) == 2
        assert results[0].data == {"name": "ditto"}
        assert isinstance(results[1], Exception)

        # Reset side effect
        cast(MagicMock, client._transport.request).side_effect = [mock_resp, HTTPError("Fail")]
        # With return_exceptions=False, raises
        with pytest.raises(TransportError):
            client.batch(requests, return_exceptions=False)
