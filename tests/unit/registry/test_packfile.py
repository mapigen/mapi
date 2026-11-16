from __future__ import annotations

from mapi.models.domain import Components, Operation, Server, ServiceData
from mapi.models.registry import ApiInfo, ServiceRegistry
from mapi.registry.loader import DiskLoader
from mapi.registry.packfile import PackfileLoader, PackfileStorage


class TestPackfileStorageAndLoader:
    def test_packfile_build_and_query(self, tmp_path):
        db_path = tmp_path / "test_services.db"
        registry = ServiceRegistry(
            version="1.0.0",
            generated_at="2026-11-16T12:00:00Z",
            providers={
                "petstore": {
                    "REST": ApiInfo(
                        sources=["github"],
                        operation_count=1,
                        popularity_rank=1,
                        auth_types=[],
                        primary_auth="",
                    )
                }
            },
        )
        op = Operation(
            service="petstore/REST/github",
            path="/pets/{id}",
            method="GET",
            operation_id="get_pet",
            summary="Get pet by ID",
        )
        service = ServiceData(
            format_version=3,
            service_name="petstore/REST/github",
            servers=[Server(url="https://petstore.example.com/v2")],
            components=Components(parameters={}, schemas={}),
            operations={"get_pet": op},
        )

        PackfileStorage.create_packfile(
            db_path, registry, {("petstore", "REST", "github"): service}
        )
        assert db_path.exists()

        with PackfileLoader(db_path) as loader:
            reg = loader.load_registry()
            assert "petstore" in reg.providers

            sdata = loader.load_service("petstore", "REST", "github")
            assert sdata.service_name == "petstore/REST/github"

            op_loaded = loader.load_operation("petstore", "REST", "github", "get_pet")
            assert op_loaded is not None
            assert op_loaded.operation_id == "get_pet"
            assert op_loaded.method == "GET"

            op_ids = loader.list_operations("petstore", "REST", "github")
            assert op_ids == ["get_pet"]

            missing_op = loader.load_operation("petstore", "REST", "github", "non_existent")
            assert missing_op is None

    def test_disk_loader_with_packfile(self, tmp_path):
        db_path = tmp_path / "services.db"
        registry = ServiceRegistry(
            version="1.0",
            generated_at="now",
            providers={
                "myapi": {
                    "REST": ApiInfo(
                        sources=["src"],
                        operation_count=1,
                        popularity_rank=1,
                        auth_types=[],
                        primary_auth="",
                    )
                }
            },
        )
        op = Operation(
            service="myapi/REST/src", path="/status", method="GET", operation_id="get_status"
        )
        service = ServiceData(
            format_version=3,
            service_name="myapi/REST/src",
            servers=[Server(url="https://api.myapi.com")],
            components=Components(parameters={}, schemas={}),
            operations={"get_status": op},
        )
        PackfileStorage.create_packfile(db_path, registry, {("myapi", "REST", "src"): service})

        disk_loader = DiskLoader(registry_path=db_path)
        reg = disk_loader.load_registry()
        assert "myapi" in reg.providers
        sdata = disk_loader.load_service("myapi", "REST", "src")
        assert sdata.service_name == "myapi/REST/src"
        granular_op = disk_loader.load_operation("myapi", "REST", "src", "get_status")
        assert granular_op is not None
        assert granular_op.operation_id == "get_status"
