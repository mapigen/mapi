<div align="center">
<picture>
  <source media="(prefers-color-scheme: light)" srcset="./docs/banner.svg">
  <img alt="mapi-logo" src="./docs/banner.svg" width="100%" height="100%">
</picture>

![Build Status](https://img.shields.io/badge/Build-passing-brightgreen?style=flat)
![PyPI Version](https://img.shields.io/badge/PyPI-not--released-lightgrey?style=flat)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat)](./LICENSE)
[![API Ref-mapi](https://img.shields.io/badge/API%20Reference-mapi-blue?style=flat)](./docs/API_REFERENCE.md)
</div>

> Notes: Working on auto-updates, adding support for templated URLs for dynamic endpoint configuration.

`mapi` is a high-performance Python framework that transforms OpenAPI specifications into lightweight, normalized metadata, enabling efficient, typed, and dynamic API access.

## Overview

`mapi` acts as a universal API client. It processes OpenAPI specifications, creating an optimized, compressed metadata catalog. The `Mapi` client then uses this metadata to provide a dynamic, ready-to-use Python interface for any API, complete with authentication and schema validation.

This approach is ideal for workflow orchestrators, node executors, and LLM tool integrations where performance, strong typing, and adaptability are critical.

## Installation

To get started, install `mapi` from PyPI:

```bash
pip install mapi
```

## Quickstart

`mapi` comes with a set of pre-processed APIs, so you can use it right out of the box.

```python
from mapi import Mapi

# Initialize the client
client = Mapi()

# 1. Discover available services
print(f"Available providers: {client.discovery.list_providers()}")
# Expected output: ['github', 'discord', 'pokeapi', 'stripe']

# 2. Call an API using the dynamic proxy
try:
    response = client.pokeapi.REST("api_v2_pokemon_retrieve", id="pikachu")
    if response.data:
        print(f"Successfully fetched data for {response.data.get('name')}")
except Exception as e:
    print(f"An error occurred: {e}")
```

## Usage Patterns

`mapi` is designed for both synchronous and asynchronous applications and provides detailed metadata with every call.

### The `Mapi` Client and Caching

When you initialize the `Mapi` client, it sets up an efficient in-memory caching system. The first time you access a service (e.g., `client.github`), its processed metadata is loaded from disk and cached in a thread-safe LRU cache. All subsequent operations for that service during the client's lifetime will use the cached data, making them extremely fast.

### Return Value: Data and Metadata

Every call to `execute` or `aexecute` returns a strongly typed, immutable `MapiResult`:
-   `data`: The deserialized JSON response from the API, or `None` on error.
-   `metadata`: A `ResponseMetadata` object containing useful information about the call, such as `duration_ms`, `http_status`, `status`, and `timestamp`.

### Synchronous Usage

#### 1. Proxy-Based Calls (Recommended)

This is the most intuitive and IDE-friendly method. It's great for interactive use and when you know the service and operation names beforehand.

```python
# Retrieve a specific pokemon
response = client.pokeapi.REST("api_v2_pokemon_retrieve", id="ditto")

# The response is an immutable MapiResult object
ditto_data = response.data
call_metadata = response.metadata

print(f"Fetched data for: {ditto_data['name']}")
print(
    f"Call took {call_metadata.duration_ms}ms with status: {call_metadata.status} (HTTP {call_metadata.http_status})"
)
```

#### 2. Direct `execute()` Calls

The `execute()` method is perfect for dynamic scenarios where the service and operation names are determined at runtime, such as from a UI form or a variable.

```python
# These values could come from a web form or variables
provider = "pokeapi"
api = "REST"
source = "openapi"
operation_id = "api_v2_pokemon_retrieve"
params = {"id": "snorlax"}

# Execute the call dynamically
response = client.execute(provider, api, source, operation_id, **params)
if response.data:
    print(f"Successfully fetched {response.data['name']}")
```

### Asynchronous Usage

For high-performance applications, `mapi` provides native asynchronous methods powered by `niquests` with connection pooling across HTTP/1.1, HTTP/2, and HTTP/3. All `execute` methods have an `aexecute` counterpart.

```python
import asyncio
from mapi import Mapi


async def fetch_all_pokemon():
    async with Mapi() as client:
        # 1. Async Proxy-Based Calls
        # Use the .aexecute() method and await the result
        response = await client.pokeapi.REST.aexecute("api_v2_pokemon_retrieve", id="bulbasaur")
        if response.data:
            print(f"Async fetch successful for: {response.data['name']}")

        # 2. Async Direct `aexecute()` Calls
        response = await client.aexecute(
            "pokeapi", "REST", "openapi", "api_v2_pokemon_retrieve", id="charmander"
        )
        if response.data:
            print(f"Async fetch successful for: {response.data['name']}")


asyncio.run(fetch_all_pokemon())
```

### Authentication

`mapi` provides dedicated authentication helpers:

```python
from mapi import Mapi

# Bearer Token (string convenience)
client = Mapi(auth="ghp_yourPersonalAccessToken")

# Bearer Token (explicit)
client = Mapi(auth=Mapi.Auth.Bearer("token_xyz", scheme="Bearer"))

# API Key (Header, Query parameter, or Cookie)
client = Mapi(auth=Mapi.Auth.ApiKey(key="api_key_123", name="X-API-Key", placement="header"))
```

## Adding New APIs

While `mapi` comes with bundled API data, you can easily add custom API specifications.

1.  **Add your source:** Add your OpenAPI specification URL to `src/mapi/registry/custom_sources.yaml`.
    ```yaml
    - provider: my_provider
      api: my_api
      url: https://api.example.com/openapi.json
    ```
2.  **Point the client to your data:** Specify custom directories when instantiating `Mapi` or via environment variables:
    ```python
    client = Mapi(data_dir="/path/to/data", registry_path="/path/to/services.json")
    ```
    Or set `MAPI_DATA_DIR` and `MAPI_REGISTRY_PATH` environment variables.

## Future Work

Continuous improvements on the `mapi` roadmap:
-   **Dynamic Updates:** Distributed checks for ensuring all API registries are refreshed automatically.
-   **CLI:** A command-line interface for configuration and data inspection.
-   **Local Web Server:** A local UI for faster discovery, configuration, and testing.

## Performance & Benchmarks

`mapi` is engineered for ultra-low latency execution paths (ideal for microservices, workflow engines, and LLM tool calling):

| Metric | Legacy `mapigen` | Current `mapi` | Improvement |
| :--- | :--- | :--- | :--- |
| **SDK Overhead per Operation** | 67.6 µs / op | **24.7 µs / op** | **63.7% faster** |
| **Peak Throughput** | ~14,800 ops/sec | **~40,500 ops/sec** | **2.7x throughput** |
| **Parameter Schema Validation** | ~26 ms (recompiling) | **~1 ms (cached structs)** | **26x faster** |
| **Test Suite Execution (149 tests)** | ~1.5 s | **0.26 s** | **5.7x faster** |
| **Type Check & Lint Status** | N/A | **0 errors, 0 warnings** (Ruff & Pyright) | Strict Compliance |

See [BEST_PRACTICES.md](./BEST_PRACTICES.md) for detailed architectural standards and optimization patterns.

## Contributing

1.  **Testing**:
    ```bash
    pytest tests/
    ```
2.  **Coverage**:
    ```bash
    pytest --cov=mapi tests/
    ```

## License

This project is licensed under the Apache 2.0 License - see the [LICENSE](./LICENSE) file for details.
