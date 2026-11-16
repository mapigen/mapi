# tests/unit/client/conftest.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import msgspec
import pytest

from mapi import Mapi
from mapi.models.config import ClientConfig
from mapi.models.request import RequestConfig


def build_test_mapi(sample_service_data=None, sample_registry=None) -> Mapi:
    """Build a Mapi instance with mocked dependencies for isolated unit testing."""
    client = Mapi.__new__(Mapi)

    discovery = MagicMock()
    discovery.provider_exists.side_effect = lambda p: p in ("pokeapi", "github")
    discovery.api_exists.side_effect = lambda p, a: (
        (p, a)
        in (
            ("pokeapi", "REST"),
            ("github", "rest"),
        )
    )
    discovery.get_api_info.return_value = MagicMock(sources=["openapi"])
    client._discovery = discovery

    cache = MagicMock()
    if sample_service_data is not None:
        cache.get.return_value = sample_service_data
    client._cache = cache

    builder = MagicMock()
    builder.build.return_value = RequestConfig(method="GET", url="https://api.example.com/users/1")
    client._builder = builder

    transport = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/json", "X-RateLimit-Remaining": "4999"}
    mock_resp.content = b'{"id": 1, "name": "pikachu"}'
    mock_resp.json.return_value = {"id": 1, "name": "pikachu"}
    transport.request.return_value = mock_resp
    transport.arequest = AsyncMock(return_value=mock_resp)
    transport.aclose = AsyncMock()
    client._transport = transport

    client._auth = None
    client._config = ClientConfig()
    client._json_decoder = msgspec.json.Decoder()
    client._typed_decoders = {}
    return client


@pytest.fixture
def mock_client(sample_service_data, sample_registry) -> Mapi:
    return build_test_mapi(sample_service_data, sample_registry)
