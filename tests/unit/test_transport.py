from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mapi.auth import ApiKeyAuth, BearerAuth
from mapi.models.domain import HttpMethod
from mapi.models.request import RequestConfig
from mapi.transport import NiquestsTransport


class TestApiKeyAuth:
    def test_header_placement(self):
        auth = ApiKeyAuth("secret_key_123", "X-API-Key", placement="header")
        req = MagicMock()
        req.headers = {}
        auth(req)
        assert req.headers["X-API-Key"] == "secret_key_123"

    def test_query_placement(self):
        auth = ApiKeyAuth("secret_token", "api_key", placement="query")
        req = MagicMock()
        req.url = "https://api.example.com/v1/users?existing=true"
        req.headers = {}
        auth(req)
        assert "api_key=secret_token" in req.url
        assert "existing=true" in req.url

    def test_cookie_placement(self):
        auth = ApiKeyAuth("sess_xyz", "session_id", placement="cookie")
        req = MagicMock()
        auth(req)
        req.prepare_cookies.assert_called_once_with({"session_id": "sess_xyz"})

    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            ApiKeyAuth("", "X-Key")

    def test_invalid_placement_raises(self):
        with pytest.raises(ValueError, match="placement"):
            ApiKeyAuth("key", "name", placement="body")  # type: ignore

    def test_repr(self):
        auth = ApiKeyAuth("k", "X-Key", "header")
        assert "ApiKeyAuth" in repr(auth)
        assert "header" in repr(auth)


class TestBearerAuth:
    def test_sets_authorization_header(self):
        auth = BearerAuth("my_bearer_token")
        req = MagicMock()
        req.headers = {}
        auth(req)
        assert req.headers["Authorization"] == "Bearer my_bearer_token"

    def test_custom_scheme(self):
        auth = BearerAuth("tok_123", scheme="Token")
        req = MagicMock()
        req.headers = {}
        auth(req)
        assert req.headers["Authorization"] == "Token tok_123"

    def test_empty_token_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            BearerAuth("")

    def test_repr(self):
        auth = BearerAuth("t", scheme="Bearer")
        assert "BearerAuth" in repr(auth)


class TestNiquestsTransport:
    def _make_config(
        self, method: HttpMethod = "GET", url: str = "https://example.com", **kwargs: Any
    ) -> RequestConfig:
        return RequestConfig(method=method, url=url, **kwargs)

    def test_request_calls_session_and_raises_for_status(self):
        transport = NiquestsTransport()
        mock_response = MagicMock()
        with patch.object(transport._sync_session, "request", return_value=mock_response):
            res = transport.request(self._make_config())
        mock_response.raise_for_status.assert_called_once()
        assert res is mock_response

    def test_close_calls_session_close(self):
        transport = NiquestsTransport()
        with patch.object(transport._sync_session, "close") as mock_close:
            transport.close()
        mock_close.assert_called_once()

    def test_context_manager_calls_close(self):
        transport = NiquestsTransport()
        with patch.object(transport, "close") as mock_close, transport:
            pass
        mock_close.assert_called_once()

    def test_async_session_created_lazily(self):
        transport = NiquestsTransport()
        assert transport._async_session is None

    def test_post_sends_json_body(self):
        transport = NiquestsTransport()
        config = RequestConfig(method="POST", url="https://example.com", json_body={"name": "test"})
        mock_response = MagicMock()
        with patch.object(
            transport._sync_session, "request", return_value=mock_response
        ) as mock_req:
            transport.request(config)
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs.get("json") == {"name": "test"}

    def test_get_does_not_send_json_body(self):
        transport = NiquestsTransport()
        config = RequestConfig(method="GET", url="https://example.com", json_body={"name": "test"})
        mock_response = MagicMock()
        with patch.object(
            transport._sync_session, "request", return_value=mock_response
        ) as mock_req:
            transport.request(config)
        call_kwargs = mock_req.call_args[1]
        assert "json" not in call_kwargs

    def test_auth_passed_to_request(self):
        transport = NiquestsTransport()
        auth = BearerAuth("dummy_token")
        mock_response = MagicMock()
        with patch.object(
            transport._sync_session, "request", return_value=mock_response
        ) as mock_req:
            transport.request(self._make_config(), auth=auth)
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs.get("auth") is auth

    @pytest.mark.asyncio
    async def test_async_request_reuses_session(self):
        transport = NiquestsTransport()
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_session.request = AsyncMock(return_value=mock_response)
        transport._async_session = mock_session
        config = self._make_config()
        await transport.arequest(config)
        await transport.arequest(config)
        assert mock_session.request.call_count == 2

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        transport = NiquestsTransport()
        mock_async_session = AsyncMock()
        transport._async_session = mock_async_session
        async with transport:
            pass
        mock_async_session.close.assert_called_once()
        assert transport._async_session is None
