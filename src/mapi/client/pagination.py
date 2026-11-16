# src/mapi/client/pagination.py
from __future__ import annotations

import re
import urllib.parse
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

from ..models.response import MapiResult

if TYPE_CHECKING:
    from .client import Mapi


class PaginationService:
    """
    Automated pagination traversal engine supporting cursor-based,
    numeric page, offset-based, and RFC 5988 Link header pagination strategies.
    """

    def __init__(self, client: Mapi) -> None:
        self._client = client

    def paginate(
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        *,
        max_pages: int = 100,
        _type: Any = None,
        _raw: bool = False,
        **kwargs: Any,
    ) -> Iterator[MapiResult]:
        """
        Automatically paginate through results of an API operation synchronously.
        Yields each page as a MapiResult.
        """
        current_kwargs = dict(kwargs)
        page_count = 0

        while page_count < max_pages:
            result = self._client.execute(
                provider, api, source, operation, _type=_type, _raw=_raw, **current_kwargs
            )
            yield result
            page_count += 1

            next_kwargs = self.extract_next_pagination_kwargs(result, current_kwargs)
            if next_kwargs is None or next_kwargs == current_kwargs:
                break
            current_kwargs = next_kwargs

    async def apaginate(
        self,
        provider: str,
        api: str,
        source: str,
        operation: str,
        *,
        max_pages: int = 100,
        _type: Any = None,
        _raw: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[MapiResult]:
        """
        Asynchronously paginate through results of an API operation.
        Yields each page as a MapiResult.
        """
        current_kwargs = dict(kwargs)
        page_count = 0

        while page_count < max_pages:
            result = await self._client.aexecute(
                provider, api, source, operation, _type=_type, _raw=_raw, **current_kwargs
            )
            yield result
            page_count += 1

            next_kwargs = self.extract_next_pagination_kwargs(result, current_kwargs)
            if next_kwargs is None or next_kwargs == current_kwargs:
                break
            current_kwargs = next_kwargs

    @staticmethod
    def extract_next_pagination_kwargs(
        result: MapiResult, current_kwargs: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Extract next page parameters from Link header, cursor fields, or numeric page."""
        new_kwargs = dict(current_kwargs)
        data = result.data

        # 1. Check Link header (RFC 5988: <url>; rel="next")
        link_header = result.metadata.headers.get("link")
        if link_header:
            match = re.search(r'<([^>]+)>;\s*rel="next"', link_header, re.IGNORECASE)
            if match:
                next_url = match.group(1)
                parsed = urllib.parse.urlparse(next_url)
                params = urllib.parse.parse_qs(parsed.query)
                for k, v in params.items():
                    new_kwargs[k] = v[0] if len(v) == 1 else v
                return new_kwargs

        # 2. Inspect dict data for cursors
        if isinstance(data, dict):
            if data.get("has_more") is False:
                return None
            for cursor_key in ("next_cursor", "next_token", "cursor", "next"):
                cursor_val = data.get(cursor_key)
                if cursor_val and isinstance(cursor_val, str):
                    new_kwargs[cursor_key] = cursor_val
                    return new_kwargs

            items = None
            for key in ("data", "items", "results"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break

            if items and data.get("has_more") is True:
                last_item = items[-1]
                if isinstance(last_item, dict) and "id" in last_item:
                    new_kwargs["starting_after"] = last_item["id"]
                    return new_kwargs

        # 3. Numeric page pagination
        if "page" in current_kwargs and isinstance(current_kwargs["page"], int):
            if isinstance(data, list) and len(data) == 0:
                return None
            if isinstance(data, dict):
                items = None
                for key in ("data", "items", "results"):
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break
                if items is not None and len(items) == 0:
                    return None
            new_kwargs["page"] = current_kwargs["page"] + 1
            return new_kwargs

        # 4. Offset pagination
        if "offset" in current_kwargs and isinstance(current_kwargs["offset"], int):
            limit = current_kwargs.get("limit", 20)
            if isinstance(data, list):
                if len(data) == 0:
                    return None
                new_kwargs["offset"] = current_kwargs["offset"] + len(data)
                return new_kwargs
            elif isinstance(data, dict):
                items = None
                for key in ("data", "items", "results"):
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break
                if items is not None:
                    if len(items) == 0:
                        return None
                    new_kwargs["offset"] = current_kwargs["offset"] + len(items)
                    return new_kwargs
            new_kwargs["offset"] = current_kwargs["offset"] + limit
            return new_kwargs

        return None
