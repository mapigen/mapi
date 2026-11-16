# tests/unit/client/test_pagination.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mapi import Mapi
from mapi.client.pagination import PaginationService


class TestPagination:
    def test_numeric_page_pagination(self):
        client = Mapi()
        responses = [
            {"data": [{"id": 1}, {"id": 2}]},
            {"data": [{"id": 3}, {"id": 4}]},
            {"data": []},
        ]

        with patch.object(client, "execute") as mock_exec:
            mock_exec.side_effect = [
                MagicMock(data=responses[0], metadata=MagicMock(headers={})),
                MagicMock(data=responses[1], metadata=MagicMock(headers={})),
                MagicMock(data=responses[2], metadata=MagicMock(headers={})),
            ]

            pages = list(client.paginate("prov", "api", "src", "list_op", page=1, max_pages=5))
            assert len(pages) == 3
            assert mock_exec.call_count == 3
            assert mock_exec.call_args_list[0][1]["page"] == 1
            assert mock_exec.call_args_list[1][1]["page"] == 2

    def test_cursor_pagination(self):
        client = Mapi()
        page1 = {"items": [{"id": "item_1"}], "has_more": True, "next_cursor": "cur_2"}
        page2 = {"items": [{"id": "item_2"}], "has_more": False}

        with patch.object(client, "execute") as mock_exec:
            mock_exec.side_effect = [
                MagicMock(data=page1, metadata=MagicMock(headers={})),
                MagicMock(data=page2, metadata=MagicMock(headers={})),
            ]

            pages = list(client.paginate("prov", "api", "src", "list_op", max_pages=5))
            assert len(pages) == 2
            assert mock_exec.call_args_list[1][1]["next_cursor"] == "cur_2"

    def test_link_header_pagination(self):
        client = Mapi()
        p1_headers = {"link": '<https://api.example.com/items?page=2&per_page=10>; rel="next"'}
        p2_headers = {}

        with patch.object(client, "execute") as mock_exec:
            mock_exec.side_effect = [
                MagicMock(data=[{"id": 1}], metadata=MagicMock(headers=p1_headers)),
                MagicMock(data=[{"id": 2}], metadata=MagicMock(headers=p2_headers)),
            ]

            pages = list(client.paginate("prov", "api", "src", "list_op", max_pages=5))
            assert len(pages) == 2
            assert mock_exec.call_args_list[1][1]["page"] == "2"
            assert mock_exec.call_args_list[1][1]["per_page"] == "10"

    @pytest.mark.asyncio
    async def test_async_apaginate(self):
        client = Mapi()
        page1 = {"items": [{"id": "item_1"}], "has_more": True, "next_cursor": "cur_2"}
        page2 = {"items": [{"id": "item_2"}], "has_more": False}

        with patch.object(client, "aexecute", new_callable=AsyncMock) as mock_aexec:
            mock_aexec.side_effect = [
                MagicMock(data=page1, metadata=MagicMock(headers={})),
                MagicMock(data=page2, metadata=MagicMock(headers={})),
            ]

            pages = []
            async for p in client.apaginate("prov", "api", "src", "list_op", max_pages=5):
                pages.append(p)

            assert len(pages) == 2
            assert mock_aexec.call_args_list[1][1]["next_cursor"] == "cur_2"

    def test_extract_next_pagination_kwargs_empty(self):
        res = MagicMock(data={}, metadata=MagicMock(headers={}))
        next_kwargs = PaginationService.extract_next_pagination_kwargs(res, {})
        assert next_kwargs is None
