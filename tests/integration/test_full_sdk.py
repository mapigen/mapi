from __future__ import annotations
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import msgspec
import pytest

from mapi import Mapi, MapiResult, BearerAuth
from mapi.exceptions import (
    ClientError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from mapi.models.config import ClientConfig
from mapi.models.domain import ServiceData
from mapi.models.registry import ServiceRegistry


@pytest.fixture
def mock_sdk_environment(tmp_path: Path, sample_service_data: ServiceData, sample_registry: ServiceRegistry):
    """Sets up a complete real filesystem environment for integration testing."""
    data_dir = tmp_path / "data"
    registry_path = tmp_path / "services.json"

    # Write services.json
    registry_path.write_bytes(msgspec.json.encode(sample_registry))

    # Write pokeapi/openapi/REST/REST.utilize.json
    service_dir = data_dir / "pokeapi" / "openapi" / "REST"
    service_dir.mkdir(parents=True, exist_ok=True)
    (service_dir / "REST.utilize.json").write_bytes(msgspec.json.encode(sample_service_data))

    return data_dir, registry_path


def test_proxy_end_to_end_success(mock_sdk_environment):
    data_dir, registry_path = mock_sdk_environment
    client = Mapi(data_dir=data_dir, registry_path=registry_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 132, "name": "ditto"}

    with patch.object(client._transport._sync_session, "request", return_value=mock_resp):
        result = client.pokeapi.REST("get_user", user_id=132)

    assert isinstance(result, MapiResult)
    assert result.data == {"id": 132, "name": "ditto"}
    assert result.metadata.status == "success"
    assert result.metadata.service == "pokeapi/REST/openapi"
    assert result.metadata.operation == "get_user"
    assert result.metadata.http_status == 200
    assert result.metadata.network_duration_ms is not None


def test_proxy_non_existent_provider_raises_attribute_error(mock_sdk_environment):
    data_dir, registry_path = mock_sdk_environment
    client = Mapi(data_dir=data_dir, registry_path=registry_path)
    with pytest.raises(AttributeError, match="has no attribute 'non_existent_provider'"):
        _ = client.non_existent_provider


def test_proxy_non_existent_api_raises_attribute_error(mock_sdk_environment):
    data_dir, registry_path = mock_sdk_environment
    client = Mapi(data_dir=data_dir, registry_path=registry_path)
    with pytest.raises(AttributeError, match="API 'NON_EXISTENT' not found"):
        _ = client.pokeapi.NON_EXISTENT


def test_validation_error_on_missing_required_parameter(mock_sdk_environment):
    data_dir, registry_path = mock_sdk_environment
    client = Mapi(data_dir=data_dir, registry_path=registry_path)

    # get_user requires user_id
    with pytest.raises(ValidationError, match="user_id"):
        client.pokeapi.REST("get_user")


def test_validation_error_on_invalid_type(mock_sdk_environment):
    data_dir, registry_path = mock_sdk_environment
    client = Mapi(data_dir=data_dir, registry_path=registry_path)

    # user_id must be an integer
    with pytest.raises(ValidationError):
        client.pokeapi.REST("get_user", user_id="abc_not_an_int")


def test_string_auth_header_propagation(mock_sdk_environment):
    data_dir, registry_path = mock_sdk_environment
    client = Mapi(auth="ghp_mySecretToken", data_dir=data_dir, registry_path=registry_path)

    assert isinstance(client._auth, BearerAuth)
    assert client._auth.token == "ghp_mySecretToken"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"login": "octocat"}

    with patch.object(client._transport._sync_session, "request", return_value=mock_resp) as mock_req:
        client.pokeapi.REST("get_user", user_id=1)

    assert mock_req.call_args[1].get("auth") is client._auth


@pytest.mark.asyncio
async def test_async_proxy_end_to_end(mock_sdk_environment):
    data_dir, registry_path = mock_sdk_environment
    client = Mapi(data_dir=data_dir, registry_path=registry_path)

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"id": 25, "name": "pikachu"})
    mock_resp.raise_for_status = MagicMock()

    mock_session = MagicMock()
    mock_session.request = AsyncMock(return_value=mock_resp)
    mock_session.close = AsyncMock()
    client._transport._async_session = mock_session

    result = await client.pokeapi.REST.aexecute("get_user", user_id=25)

    assert isinstance(result, MapiResult)
    assert result.data == {"id": 25, "name": "pikachu"}
    assert result.metadata.status == "success"
    assert result.metadata.duration_ms >= 0


def test_discovery_integration(mock_sdk_environment):
    data_dir, registry_path = mock_sdk_environment
    client = Mapi(data_dir=data_dir, registry_path=registry_path)

    providers = client.discovery.list_providers()
    assert "pokeapi" in providers
    assert "github" in providers

    apis = client.discovery.list_apis("pokeapi")
    assert apis == ["REST"]

    ops = client.discovery.list_operations("pokeapi", "REST")
    assert "get_user" in ops


def test_context_manager_lifecycle(mock_sdk_environment):
    data_dir, registry_path = mock_sdk_environment
    client = Mapi(data_dir=data_dir, registry_path=registry_path)
    with patch.object(client._transport, "close") as mock_close:
        with client:
            assert client._transport is not None
        mock_close.assert_called_once()
