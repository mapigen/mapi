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

# Default initialization (reads mapi-registry.json from bundled registry)
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
* **`registry_path`** (`Optional[Path]`): Override path for `mapi-registry.json`.
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
    headers: HeadersDict  # Case-insensitive response headers dictionary
    timestamp: str  # ISO 8601 UTC timestamp
    error_type: Optional[str]  # Error class name if failed
    error_category: Optional[str]  # "validation", "transport", "system"

    # Convenience Header Properties:
    @property
    def content_type(self) -> Optional[str]: ...

    @property
    def etag(self) -> Optional[str]: ...

    @property
    def retry_after(self) -> Optional[float]: ...

    @property
    def rate_limit_limit(self) -> Optional[int]: ...

    @property
    def rate_limit_remaining(self) -> Optional[int]: ...

    @property
    def rate_limit_reset(self) -> Optional[int]: ...
```

---

## 4. Client Configuration & Server Selection

```python
class ClientConfig(msgspec.Struct, frozen=True, gc=False):
    base_url: Optional[str] = None
    default_timeout: float = 30.0
    validate_on_execute: bool = True
    pinned_services: tuple[str, ...] = ()
    cache_maxsize: int = 64
    log_level: str = "INFO"
    multiplexed: bool = True
    retries: int = 0
    server_variables: dict[str, str] = msgspec.field(default_factory=dict)
    default_headers: dict[str, str] = msgspec.field(default_factory=_default_headers)
    server_pattern: Optional[str] = None
    server_tag: Optional[str] = None
```

* **Additive Default Headers**: `ClientConfig(default_headers={"X-Custom": "123"})` automatically preserves standard `User-Agent: mapi/0.1.0` and `Accept: application/json` while appending custom headers.
* **Server Environment Matching**: Set `server_tag="sandbox"` or `server_pattern="eu.example.com"` to automatically match target OpenAPI server blocks by description or URL substring.

---

## 5. Performance & Runtime Complexity

| Operation | Time Complexity | Space Complexity | Description |
| :--- | :--- | :--- | :--- |
| `Mapi.__init__` | $O(1)$ | $O(1)$ | Lazy loading; registry decoded on first access. |
| `client.<provider>.<api>` | $O(1)$ | $O(1)$ | Light `__slots__` proxy construction without heap allocation. |
| `ServiceCache.get` | $O(1)$ amortized | $O(S)$ | Native 3-tuple hash lookup; fast-path for pinned services. |
| `ParameterValidator.validate` | $O(P)$ | $O(1)$ | Uses compiled C Structs cached per operation. |
| `execute` / `aexecute` | $O(P + R)$ | $O(R)$ | Parameter preparation + direct C decoding via `msgspec`. |

---

## 6. Advanced Developer & Agent Operations

### 6.1 Dry-Run Execution & cURL Export
Generate executable, copy-pasteable `curl` commands or validate parameter resolution without firing HTTP requests:
```python
result = client.pokeapi.REST("pokemon_retrieve", id="ditto", _dry_run=True)
config: RequestConfig = result.data

print(config.to_curl())
# curl -X GET 'https://pokeapi.co/api/v2/pokemon/ditto' \
#      -H 'User-Agent: mapi/0.1.0' \
#      -H 'Accept: application/json'
```

### 6.2 Automatic Idempotency
Protect against duplicate mutations on retries by injecting unique UUID v4 idempotency keys:
```python
client.stripe.REST("charges_create", amount=2000, currency="usd", _idempotent=True)
# Injects 'Idempotency-Key: <uuid4>' into headers for POST/PUT/PATCH/DELETE
```

### 6.3 LLM Tool Calling (OpenAI / Anthropic / Gemini Schema)
Export JSON Schema function calling definitions directly from operation metadata:
```python
# 1. Export schema for AI Agent
tool_def = client.pokeapi.REST.to_tool("pokemon_retrieve")
# {"type": "function", "function": {"name": "pokeapi_REST_pokemon_retrieve", ...}}

# 2. Dispatch LLM function call arguments
result = client.call_tool("pokeapi_REST_pokemon_retrieve", id="pikachu")
```

### 6.4 Dynamic Runtime Spec Ingestion & In-Place Updates
Register, validate diffs, and update OpenAPI specs at runtime with optional auto-inferred providers:
```python
# Ingest spec with auto-inferred provider from server URL / title
provider = client.register_spec("https://api.acme.com/v1/openapi.json")

# Check for upstream changes (emits SpecUpdateAvailableWarning on diff)
diff: SpecDiffResult = client.check_spec_diff("acme")
if diff.has_diff:
    print(f"Added operations: {diff.added_operations}")
    client.update_spec("acme", force=True)
```

### 6.5 Auto-Pagination
Iterate seamlessly across cursor, numeric, offset, or RFC 5988 `Link` header paginated APIs:
```python
# Sync pagination
for page in client.stripe.REST.paginate("charges_list", limit=100):
    print(page.data)

# Async pagination
async for page in client.stripe.REST.apaginate("charges_list", limit=100):
    print(page.data)
```

### 6.6 SQLite Packfile & Granular Operation Storage
In production, compile loose specifications into a single bundled SQLite B-Tree packfile (`services.db`) for microsecond point lookups and minimal memory footprint:
```python
from mapi.registry.packfile import PackfileLoader, PackfileStorage

# Compile into packfile
PackfileStorage.create_packfile("services.db", registry, services_data)

# Read from packfile
with PackfileLoader("services.db") as loader:
    op = loader.load_operation("stripe", "REST", "github", "charges_create")
```
