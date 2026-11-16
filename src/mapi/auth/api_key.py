from __future__ import annotations
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from niquests.auth import AuthBase
from niquests.models import PreparedRequest


class ApiKeyAuth(AuthBase):
    """Attaches an API key to requests via header, query parameter, or cookie."""

    def __init__(
        self,
        key: str,
        name: str,
        placement: Literal["header", "query", "cookie"] = "header",
    ) -> None:
        if not key:
            raise ValueError("API key cannot be empty.")
        if placement not in ("header", "query", "cookie"):
            raise ValueError("placement must be 'header', 'query', or 'cookie'.")
        self.key = key
        self.name = name
        self.placement = placement

    def __call__(self, r: PreparedRequest) -> PreparedRequest:
        if self.placement == "header":
            if r.headers is None:
                r.headers = {}
            r.headers[self.name] = self.key
        elif self.placement == "query" and r.url is not None:
            parsed = urlparse(r.url)
            params = parse_qs(parsed.query)
            params[self.name] = [self.key]
            r.url = urlunparse(parsed._replace(query=urlencode(params, doseq=True)))
        elif self.placement == "cookie":
            r.prepare_cookies({self.name: self.key})
        return r

    def __repr__(self) -> str:
        return f"ApiKeyAuth(name={self.name!r}, placement={self.placement!r})"
