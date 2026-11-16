# Mapi API Reference

## 1. Introduction

This document provides a detailed technical reference for the `mapi` Universal API Client SDK. It covers all core client classes, dynamic proxies, authentication strategies, data models, error taxonomies, and performance characteristics.

For installation instructions and quickstart examples, see the [README.md](../README.md) and [BEST_PRACTICES.md](../BEST_PRACTICES.md).

---

## 2. The `Mapi` Client

The `mapi.Mapi` class is the primary entry point for all operations.

### 2.1 Initialization

```python
from mapi import Mapi, ClientConfig, BearerAuth

# Default initialization (reads services.json from bundled registry)
client = Mapi()

# Custom configuration with Bearer token
client = Mapi(
    auth=BearerAuth("ghp_myToken"),
    base_url="https://api.github.com",
    config=ClientConfig(default_timeout=15.0, log_level="DEBUG"),
)
```

**Constructor Parameters:**
* **`config`** (`Optional[ClientConfig]`): Immutable client configuration.
* **`auth`** (`Optional[Union[AuthBase, str]]`): An authentication object (`BearerAuth`, `ApiKeyAuth`) or raw token string (automatically wrapped in `BearerAuth`).
* **`transport`** (`Optional[NiquestsTransport]`): Custom HTTP transport (defaults to a managed `NiquestsTransport` instance).
* **`data_dir`** (`Optional[Path]`): Override path for service definitions (`utilize.json.zst`).
* **`registry_path`** (`Optional[Path]`): Override path for `services.json`.
* **`base_url`** (`Optional[str]`): Override default server URL declared in OpenAPI specifications.
* **`**transport_kwargs`**: Arbitrary arguments forwarded to underlying `niquests.Session` / `AsyncSession` (e.g., `verify=False`).

---

### 2.2 Executing Operations

#### Dynamic Proxy Calls (Sync & Async)
The recommended, IDE-friendly method for executing operations:

* **Synchronous:**
  ```python
  # client.<provider>.<api>(<operation>, **kwargs)
  result = client.pokeapi.REST("pokemon_retrieve", id="ditto")
  print(result.data["name"])  # "ditto"
  print(result.metadata.duration_ms)  # SDK ops time (ms)
  print(result.metadata.network_duration_ms)  # HTTP wire round-trip time (ms)
  ```

* **Asynchronous:**
  ```python
  result = await client.pokeapi.REST.aexecute("pokemon_retrieve", id="ditto")
  ```

* **Explicit Source Selection:**
  ```python
  result = client.pokeapi.REST.github("pokemon_retrieve", id="ditto")
  ```

#### Strongly-Typed Returns (`_type=MyStruct`)
You can direct Mapi to deserialize and validate directly into strongly-typed `msgspec.Struct` models at C-speed:

```python
import msgspec


class Pokemon(msgspec.Struct):
    id: int
    name: str


result = client.pokeapi.REST("pokemon_retrieve", id="pikachu", _type=Pokemon)
assert isinstance(result.data, Pokemon)
print(result.data.id, result.data.name)
```

#### Deferred Raw Parsing (`_raw=True`)
For high-volume pipelines, proxies, or file streaming where JSON deserialization into Python dictionaries is unneeded:

```python
result = client.pokeapi.REST("pokemon_retrieve", id="pikachu", _raw=True)
# result.data is msgspec.Raw without Python dict allocation
raw_bytes = bytes(result.data)
```

#### Direct Execution
For dynamic workflow orchestrators and LLM tool executors where service identifiers are resolved at runtime:

```python
# Sync
result = client.execute("pokeapi", "REST", "github", "pokemon_retrieve", id="pikachu")

# Async
result = await client.aexecute("pokeapi", "REST", "github", "pokemon_retrieve", id="pikachu")
```

---

### 2.3 Service Discovery

Access discovery metadata via `client.discovery`:

* **`list_providers() -> List[str]`**: Returns all registered providers.
* **`provider_exists(provider: str) -> bool`**: Checks if a provider exists.
* **`list_apis(provider: str) -> List[str]`**: Lists APIs for a provider.
* **`get_api_info(provider: str, api: str) -> ApiInfo`**: Returns API metadata (sources, operation count, popularity rank, auth schemes).
* **`list_operations(provider: str, api: str, source: Optional[str] = None) -> List[str]`**: Lists all operations.
* **`get_operation(provider: str, api: str, source: str, operation: str) -> Operation`**: Returns typed operation metadata.

---

### 2.4 Authentication

Authentication strategies inherit from `niquests.auth.AuthBase`:

* **`BearerAuth(token: str, scheme: str = "Bearer")`**: Attaches an `Authorization: <scheme> <token>` header.
* **`ApiKeyAuth(key: str, name: str, placement: Literal["header", "query", "cookie"])`**: Injects an API key into requests.

```python
from mapi import ApiKeyAuth

auth = ApiKeyAuth(key="sec_12345", name="X-API-Key", placement="header")
client = Mapi(auth=auth)
```

---

### 2.5 Error Handling

All SDK exceptions inherit from `mapi.exceptions.MapiError`:

```text
MapiError
├── ConfigurationError
├── ServiceNotFoundError
├── ValidationError
└── TransportError
    ├── RateLimitError (HTTP 429)
    ├── ServerError (HTTP 5xx)
    └── ClientError (HTTP 4xx)
```

All `TransportError` exceptions expose `http_status`, `service`, and `operation` attributes.

---

## 3. Core Return Models

All calls return an immutable `MapiResult`:

```python
class MapiResult(msgspec.Struct, frozen=True):
    data: Optional[Any]
    metadata: ResponseMetadata
```

### `ResponseMetadata` Telemetry Schema

```python
class ResponseMetadata(msgspec.Struct, frozen=True, gc=False):
    service: str  # "provider/api/source"
    operation: str  # operation identifier
    duration_ms: int  # Mapi SDK operations only (prep + parse)
    network_duration_ms: Optional[int]  # HTTP roundtrip latency over the wire
    status: Literal["success", "error"]
    http_status: Optional[int]  # HTTP status code (200, 404, etc.)
    timestamp: str  # ISO 8601 UTC timestamp
    error_type: Optional[str]  # Error class name if failed
    error_category: Optional[str]  # "validation", "transport", "system"
```

---

## 4. Performance & Runtime Complexity

| Operation | Time Complexity | Space Complexity | Description |
| :--- | :--- | :--- | :--- |
| `Mapi.__init__` | $O(1)$ | $O(1)$ | Lazy loading; registry decoded on first access. |
| `client.<provider>.<api>` | $O(1)$ | $O(1)$ | Light `__slots__` proxy construction without heap allocation. |
| `ServiceCache.get` | $O(1)$ amortized | $O(S)$ | Native 3-tuple hash lookup; fast-path for pinned services. |
| `ParameterValidator.validate` | $O(P)$ | $O(1)$ | Uses compiled C Structs cached per operation. |
| `execute` / `aexecute` | $O(P + R)$ | $O(R)$ | Parameter preparation + direct C decoding via `msgspec`. |
