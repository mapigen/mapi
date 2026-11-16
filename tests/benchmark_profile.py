# tests/benchmark_profile.py
"""Benchmark and profiling script for mapi SDK core execution."""
from __future__ import annotations
import cProfile
import pstats
import time
from unittest.mock import MagicMock

from mapi import Mapi
from mapi.models import ServiceData, Server, Operation, Parameter, ServiceRegistry, ApiInfo


def create_mock_client() -> Mapi:
    """Create a client with mocked in-memory loader and transport."""
    service_data = ServiceData(
        format_version=3,
        service_name="REST",
        servers=[Server(url="https://api.example.com", description="")],
        components={"parameters": {}, "schemas": {}},
        operations={
            "get_pokemon": Operation(
                service="REST",
                path="/pokemon/{id}",
                method="GET",
                parameters=[Parameter(name="id", in_="path", schema_={"type": "string"}, required=True)],
            )
        },
    )

    registry = ServiceRegistry(
        version="1.0",
        generated_at="2025-01-01T00:00:00Z",
        providers={
            "pokeapi": {
                "REST": ApiInfo(
                    sources=["openapi"],
                    operation_count=1,
                    popularity_rank=1,
                    auth_types=[],
                    primary_auth="none",
                )
            }
        },
    )

    client = Mapi()
    client._loader.load_registry = MagicMock(return_value=registry)
    client._loader.load_service = MagicMock(return_value=service_data)

    # Mock transport response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"id": 25, "name": "pikachu"}'
    mock_response.json = MagicMock(return_value={"id": 25, "name": "pikachu"})
    client._transport.request = MagicMock(return_value=mock_response)

    return client


def run_benchmark(iterations: int = 1000):
    client = create_mock_client()

    # Warmup
    for _ in range(10):
        client.pokeapi.REST("get_pokemon", id="pikachu")

    # Profile
    pr = cProfile.Profile()
    pr.enable()

    t0 = time.perf_counter()
    for _ in range(iterations):
        res = client.pokeapi.REST("get_pokemon", id="pikachu")
    total_time = time.perf_counter() - t0

    pr.disable()

    print(f"\n================ BENCHMARK RESULTS ================")
    print(f"Iterations: {iterations}")
    print(f"Total time: {total_time:.4f}s")
    print(f"Per call:   {(total_time / iterations) * 1000:.3f}ms ({(total_time / iterations) * 1_000_000:.1f}µs)")
    print(f"Throughput: {iterations / total_time:.1f} ops/sec")
    print(f"===================================================\n")

    stats = pstats.Stats(pr)
    stats.strip_dirs().sort_stats("cumtime").print_stats(25)


if __name__ == "__main__":
    run_benchmark(1000)
