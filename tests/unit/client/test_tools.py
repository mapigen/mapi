# tests/unit/client/test_tools.py
from __future__ import annotations

import pytest

from mapi import Mapi


class TestToolService:
    def test_to_tool_schema_and_call_tool(self):
        client = Mapi()
        # Test with real pokeapi registered in the built-in data
        tool_spec = client.to_tool("pokeapi", "REST", "pokemon_retrieve")
        assert tool_spec["type"] == "function"
        fn = tool_spec["function"]
        assert fn["name"] == "pokeapi_REST_pokemon_retrieve"
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"
        assert "id" in fn["parameters"]["properties"]

        # Also via ApiProxy
        proxy_spec = client.pokeapi.REST.to_tool("pokemon_retrieve")
        assert proxy_spec == tool_spec

    def test_call_tool_invalid_name(self):
        client = Mapi()
        with pytest.raises(ValueError, match="Invalid tool_name format"):
            client.call_tool("invalid_tool")
