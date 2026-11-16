from __future__ import annotations

from niquests.auth import AuthBase
from niquests.models import PreparedRequest
from niquests.structures import CaseInsensitiveDict


class BearerAuth(AuthBase):
    """Attaches a Bearer token to the Authorization header."""

    def __init__(self, token: str, scheme: str = "Bearer") -> None:
        if not token:
            raise ValueError("Token cannot be empty.")
        self.token = token
        self.scheme = scheme

    def __call__(self, r: PreparedRequest) -> PreparedRequest:
        if r.headers is None:
            r.headers = CaseInsensitiveDict()
        r.headers["Authorization"] = f"{self.scheme} {self.token}"
        return r

    def __repr__(self) -> str:
        return f"BearerAuth(scheme={self.scheme!r})"
