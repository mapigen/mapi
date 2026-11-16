# src/mapi/client/pagination.py
from __future__ import annotations

import re
import urllib.parse
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

from ..constants import (
    HEADER_LINK_LOWER,
    PAGINATION_CURSOR_KEYS,
    PAGINATION_HAS_MORE,
    PAGINATION_ITEM_KEYS,
    PAGINATION_LIMIT,
    PAGINATION_OFFSET,
    PAGINATION_PAGE,
    PAGINATION_STARTING_AFTER,
)
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
        link_header = result.metadata.headers.get(HEADER_LINK_LOWER)
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
            if data.get(PAGINATION_HAS_MORE) is False:
                return None
            for cursor_key in PAGINATION_CURSOR_KEYS:
                cursor_val = data.get(cursor_key)
                if cursor_val and isinstance(cursor_val, str):
                    new_kwargs[cursor_key] = cursor_val
                    return new_kwargs

            items = None
            for key in PAGINATION_ITEM_KEYS:
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break

            if items and data.get(PAGINATION_HAS_MORE) is True:
                last_item = items[-1]
                if isinstance(last_item, dict) and "id" in last_item:
                    new_kwargs[PAGINATION_STARTING_AFTER] = last_item["id"]
                    return new_kwargs

        # 3. Numeric page pagination
        if PAGINATION_PAGE in current_kwargs and isinstance(current_kwargs[PAGINATION_PAGE], int):
            if isinstance(data, list) and len(data) == 0:
                return None
            if isinstance(data, dict):
                items = None
                for key in PAGINATION_ITEM_KEYS:
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break
                if items is not None and len(items) == 0:
                    return None
            new_kwargs[PAGINATION_PAGE] = current_kwargs[PAGINATION_PAGE] + 1
            return new_kwargs

        # 4. Offset pagination
        if PAGINATION_OFFSET in current_kwargs and isinstance(current_kwargs[PAGINATION_OFFSET], int):
            limit = current_kwargs.get(PAGINATION_LIMIT, 20)
            if isinstance(data, list):
                if len(data) == 0:
                    return None
                new_kwargs[PAGINATION_OFFSET] = current_kwargs[PAGINATION_OFFSET] + len(data)
                return new_kwargs
            elif isinstance(data, dict):
                items = None
                for key in PAGINATION_ITEM_KEYS:
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break
                if items is not None:
                    if len(items) == 0:
                        return None
                    new_kwargs[PAGINATION_OFFSET] = current_kwargs[PAGINATION_OFFSET] + len(items)
                    return new_kwargs
            new_kwargs[PAGINATION_OFFSET] = current_kwargs[PAGINATION_OFFSET] + limit
            return new_kwargs

        return None
