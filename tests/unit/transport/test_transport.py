from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mapi.auth import BearerAuth
from mapi.models.domain import HttpMethod
from mapi.models.request import RequestConfig
from mapi.transport import NiquestsTransport


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

    def test_stream_flag_forwarded_to_session(self):
        transport = NiquestsTransport()
        mock_response = MagicMock()
        with patch.object(
            transport._sync_session, "request", return_value=mock_response
        ) as mock_req:
            transport.request(self._make_config(), stream=True)
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs.get("stream") is True

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
