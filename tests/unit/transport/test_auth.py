from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mapi.auth import ApiKeyAuth, BearerAuth


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
