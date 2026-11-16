from __future__ import annotations

from mapi.registry.spec_compiler import compile_spec, infer_provider


class TestSpecCompiler:
    def test_infer_provider_from_servers_url(self):
        spec = {"servers": [{"url": "https://api.github.com/v3"}]}
        assert infer_provider(spec) == "github"

        spec2 = {"servers": [{"url": "https://sandbox.stripe.com/v1"}]}
        assert infer_provider(spec2) == "stripe"

    def test_infer_provider_from_info_title(self):
        spec = {"info": {"title": "Acme Widgets API"}}
        assert infer_provider(spec) == "acme"

    def test_infer_provider_from_path(self):
        spec = {}
        assert infer_provider(spec, url_or_path="/path/to/pokeapi.openapi.json") == "pokeapi"

    def test_compile_spec_basic(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Sample API", "version": "1.0.0"},
            "servers": [{"url": "https://api.sample.com"}],
            "paths": {
                "/users/{id}": {
                    "get": {
                        "operationId": "get_user",
                        "summary": "Get User",
                        "parameters": [
                            {
                                "name": "id",
                                "in": "path",
                                "schema": {"type": "string"},
                                "required": True,
                            }
                        ],
                    }
                }
            },
        }
        sdata = compile_spec(spec, service_name="sample/REST/dynamic")
        assert sdata.service_name == "sample/REST/dynamic"
        assert len(sdata.servers) == 1
        assert sdata.servers[0].url == "https://api.sample.com"
        assert "get_user" in sdata.operations
        op = sdata.operations["get_user"]
        assert op.method == "GET"
        assert op.path == "/users/{id}"
        assert len(op.parameters) == 1
