# src/mapi/models/request.py
from __future__ import annotations

from typing import Any

import msgspec

from ..constants import SENSITIVE_AUTH_HEADERS
from .domain import HttpMethod


class RequestConfig(msgspec.Struct, frozen=True, gc=False):
    """Fully resolved HTTP request parameters."""

    method: HttpMethod
    url: str
    params: dict[str, Any] = msgspec.field(default_factory=dict)
    headers: dict[str, str] = msgspec.field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    timeout: float = 30.0

    def to_curl(self, redact_auth: bool = True) -> str:
        """
        Format the request configuration as an executable curl command.

        :param redact_auth: If True, redacts values for Authorization and API key headers.
        :return: Multi-line string formatted for bash/sh execution.
        """
        import urllib.parse

        url = self.url
        if self.params:
            query_string = urllib.parse.urlencode(self.params, doseq=True)
            joiner = "&" if "?" in url else "?"
            url = f"{url}{joiner}{query_string}"

        parts = [f"curl -X {self.method} '{url}'"]
        for k, v in self.headers.items():
            val = v
            if redact_auth and k.lower() in SENSITIVE_AUTH_HEADERS:
                val = "[REDACTED]"
            parts.append(f"-H '{k}: {val}'")

        if self.json_body is not None:
            body_str = msgspec.json.encode(self.json_body).decode("utf-8")
            # Escape single quotes in JSON string for bash
            escaped_body = body_str.replace("'", "'\\''")
            parts.append(f"-d '{escaped_body}'")

        return " \\\n     ".join(parts)


class BatchRequest(msgspec.Struct, frozen=True, gc=False):
    """An operation request specification for abatch execution."""

    provider: str
    api: str
    operation: str
    source: str | None = None
    kwargs: dict[str, Any] = msgspec.field(default_factory=dict)
    type: Any | None = None
    raw: bool = False
