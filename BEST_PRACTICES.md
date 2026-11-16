# Mapi Engineering Standards & Best Practices

This document outlines the coding, architectural, and performance standards enforced across the `mapi` codebase. All future contributions and refactors must adhere to these guidelines and pass all automated quality gates.

---

## 1. Documentation & Core Library References

The `mapi` core architecture is built upon two high-performance libraries. Refer to their official documentation for patterns, performance characteristics, and APIs:

* **msgspec (Data Modeling, Validation & Serialization)**:
  * Official Documentation: [https://msgspec.dev/](https://msgspec.dev/)
  * Source Repository: [https://github.com/jcrist/msgspec](https://github.com/jcrist/msgspec)
  * Primary role in `mapi`: High-throughput C-extension models (`msgspec.Struct`), zero-copy schema validation (`msgspec.defstruct` + `msgspec.convert`), typed decoders (`msgspec.json.Decoder`), and zero-deserialization views (`msgspec.Raw`).

* **niquests (HTTP Transport & Connection Pooling)**:
  * Official Documentation: [https://niquests.readthedocs.io/](https://niquests.readthedocs.io/)
  * Source Repository: [https://github.com/jawah/niquests](https://github.com/jawah/niquests)
  * Primary role in `mapi`: Advanced HTTP transport supporting HTTP/1.1, HTTP/2, and HTTP/3 (QUIC) multiplexing, connection pooling, and unified sync (`Session`) and async (`AsyncSession`) request lifecycles.

---

## 2. msgspec Design Guidelines & Patterns

`msgspec` is significantly faster than standard Python `dataclasses`, `pydantic`, or standard `json` (5x–60x speedups) because serialization, deserialization, and schema validation execute concurrently within C-extensions. To preserve this speed:

### 2.1 Struct Configuration Rules
* **Immutability by Default**: All domain models and telemetry records should declare `frozen=True`.
* **Disable Cyclic Garbage Collection (`gc=False`)**:
  ```python
  class Parameter(msgspec.Struct, frozen=True, tag="inline", gc=False, cache_hash=True):
      name: NonEmptyStr
      in_: ParameterLocation = msgspec.field(name="in")
  ```
  * Python's cyclic garbage collector introduces allocation tracking overhead and stop-the-world sweep pauses.
  * For acyclic data structures (such as API definitions, parameters, config, and telemetry), pass `gc=False` to exclude instances from Python's GC tracking list. Reference counting handles deterministic deallocation immediately when ref counts reach zero.
* **Pre-compute Hash Values (`cache_hash=True`)**:
  * For frozen structs placed into dictionaries, sets, or LRU caches, pass `cache_hash=True` so that the 64-bit hash is computed once and cached on the struct slot.

### 2.2 Reusable Decoders and Encoders
* **Never call `msgspec.json.decode(data, type=T)` in hot execution paths**:
  ```python
  # CORRECT: Instantiate once and reuse across calls
  self._service_decoder = msgspec.json.Decoder(ServiceData)
  return self._service_decoder.decode(raw_bytes)

  # AVOID: Re-analyzing schemas on every invocation
  return msgspec.json.decode(raw_bytes, type=ServiceData)
  ```
* Top-level functions allocate internal type schemas and parsing buffers on every call. Pre-allocated `Decoder` instances retain compiled state and yield higher throughput.

### 2.3 Direct Response Decoding (`response.content`)
* Avoid using `response.json()` in transport layers because it internally calls `response.text` (allocating a Python string and copying memory) before running standard library `json.loads`.
* Instead, pass raw `response.content` bytes directly to a shared `msgspec.json.Decoder()` instance.

### 2.4 Cached Dynamic Struct Compilation
* When validating dynamic parameters against OpenAPI schemas, never re-invoke `msgspec.defstruct()` for every API call.
* Compile the dynamic parameter struct **once per operation**, cache the class object by operation key `(provider, api, source, operation)`, and perform subsequent validations using `msgspec.convert(kwargs, cached_struct, strict=False)`.

### 2.5 Strongly-Typed Return Models (`_type=MyStruct`)
* Callers can direct the SDK to deserialize and validate responses directly into a user-defined `msgspec.Struct` or dataclass at C-speed:
  ```python
  class Pokemon(msgspec.Struct):
      id: int
      name: str


  result = client.pokeapi.REST("pokemon_retrieve", id="ditto", _type=Pokemon)
  assert isinstance(result.data, Pokemon)
  ```
* The client caches typed `msgspec.json.Decoder(target_type)` instances in `self._typed_decoders` to avoid schema re-parsing across repeated calls.

### 2.6 Deferred Parsing via `msgspec.Raw` (`_raw=True`)
* For large response payloads, proxies, or file-dumping pipelines where full deserialization into Python dictionaries is unnecessary, pass `_raw=True` or `raw=True`:
  ```python
  result = client.pokeapi.REST("pokemon_retrieve", id="ditto", _raw=True)
  assert isinstance(result.data, msgspec.Raw)
  ```
* This returns a zero-copy byte view of the response payload without allocating Python heap objects.

### 2.7 Automatic Input Model Conversion
* When users pass `msgspec.Struct` instances into operation kwargs, `RequestBuilder` automatically converts them via `msgspec.to_builtins(value)`:
  ```python
  client.provider.api("create_item", item=ItemStruct(name="Widget"))
  ```

### 2.8 Headers Telemetry & Case-Insensitive `HeadersDict`
* Response headers are encapsulated in `HeadersDict`, a specialized `dict[str, str]` subclass that preserves original server casing while enabling $O(1)$ case-insensitive access:
  ```python
  result = client.pokeapi.REST("pokemon_retrieve", id="ditto")
  # Access via exact or case-insensitive keys:
  assert result.metadata.headers["content-type"] == result.metadata.headers["Content-Type"]
  # Convenience properties for common headers:
  print(result.metadata.content_type)
  print(result.metadata.etag)
  print(result.metadata.retry_after)
  print(result.metadata.rate_limit_remaining)
  ```

---

## 3. Client Configuration & Server Selection Guidelines

### 3.1 Additive Default Request Headers
* `ClientConfig.default_headers` supplies global headers (defaulting to `{"User-Agent": "mapi/0.1.0", "Accept": "application/json"}`).
* User-provided headers are **additive** with standard defaults:
  ```python
  client = Mapi(config=ClientConfig(default_headers={"X-Organization-ID": "org_123"}))
  # Sends User-Agent, Accept, and X-Organization-ID.
  ```

### 3.2 Dynamic Server Environment Selection
* When OpenAPI schemas expose multiple servers (e.g. Production vs. Sandbox vs. Regional), select destinations by URL pattern or description tag:
  ```python
  # Globally in configuration:
  client = Mapi(config=ClientConfig(server_tag="sandbox"))

  # Or per-operation override:
  result = client.stripe.charges.create(..., server_tag="sandbox")
  ```

### 3.3 Registry, Caching & Decompression Optimizations
* **Discovery Cache Sharing**: `DiscoveryService` reuses `ServiceCache` to eliminate redundant disk reads and zstandard decompression when listing or validating operations.
* **DiskLoader Path Cache**: `DiskLoader` caches resolved service file paths, skipping repeated `stat()` filesystem syscalls.
* **Binary Serialization Readiness**: `DiskLoader` natively supports binary MessagePack (`.utilize.msgpack.zst`), yielding 2x–4x faster deserialization than JSON.

---
* For large response payloads, proxies, or file-dumping pipelines where full deserialization into Python dictionaries is unnecessary, pass `_raw=True` or `raw=True`:
  ```python
  result = client.pokeapi.REST("pokemon_retrieve", id="ditto", _raw=True)
  assert isinstance(result.data, msgspec.Raw)
  ```
* This returns a zero-copy byte view of the response payload without allocating Python heap objects.

### 2.7 Automatic Input Model Conversion
* When users pass `msgspec.Struct` instances into operation kwargs, `RequestBuilder` automatically converts them via `msgspec.to_builtins(value)`:
  ```python
  client.provider.api("create_item", item=ItemStruct(name="Widget"))
  ```

---

## 3. niquests Transport Guidelines

### 3.1 Connection Management & Lifecycle
* **Session Reuse**: Always reuse `niquests.Session` and `niquests.AsyncSession` across requests to maintain persistent TCP/TLS connection pools and keep-alive sockets.
* **Lazy Async Initialization**: Instantiate `AsyncSession` lazily upon the first async call to avoid unattached event loop warnings during sync initialization.
* **Context Manager & Cleanup**: Always implement explicit `close()` and `aclose()` methods and support `with client:` / `async with client:` lifecycles.

### 3.2 Header & Auth Handling
* When modifying request headers inside `AuthBase` implementations, use `CaseInsensitiveDict` from `niquests.structures`:
  ```python
  if r.headers is None:
      r.headers = CaseInsensitiveDict()
  r.headers["Authorization"] = f"{self.scheme} {self.token}"
  ```

---

## 4. Telemetry Standard

All API execution responses return an immutable `MapiResult`:
* `data`: The decoded response payload (or `None` on empty responses).
* `metadata`: An instance of `ResponseMetadata` strictly adhering to the following schema:
  ```json
  {
    "metadata": {
      "service": "pokeapi/REST/github",
      "operation": "pokemon_retrieve",
      "duration_ms": 1,
      "network_duration_ms": 78,
      "status": "success",
      "http_status": 200,
      "timestamp": "2026-11-16T19:04:00Z",
      "error_type": null,
      "error_category": null
    }
  }
  ```
* **Separation of Durations**:
  * `duration_ms`: Measures **SDK operations only** (request preparation, validation, serialization, and response parsing).
  * `network_duration_ms`: Measures the **HTTP transport round-trip time** over the wire.
  * `duration_ms` must **never** include `network_duration_ms`.

---

## 5. SWE Design Patterns & Architecture

* **Factory Pattern**: Centralized client instantiation (`Mapi()`) configuring transports, caches, and discovery modules.
* **Dynamic Proxy Pattern**: Lightweight slot-based proxies (`ProviderProxy`, `ApiProxy`) providing idiomatic attribute access (`client.<provider>.<api>(<operation>, **kwargs)`) without allocating overhead per method call.
* **Singleton / Shared Transports**: Transports and persistent C decoders are initialized once per client instance.
* **Strategy Pattern**: Abstracted authentication schemes (`ApiKeyAuth`, `BearerAuth`) inheriting from `AuthBase`.
* **Repository Pattern**: `DiskLoader` encapsulates disk I/O and `.zst` decompression away from cache and discovery services.

---

## 6. Code Quality Gates & Automated Tooling

Every commit and pull request must pass the following four automated checks without warnings or errors:

### 6.1 Ruff (Linting)
```bash
ruff check .
```
* Enforces pycodestyle (`E`, `W`), pyflakes (`F`), isort (`I`), pyupgrade (`UP`), flake8-bugbear (`B`), and flake8-simplify (`SIM`).
* Run auto-fixes when applicable: `ruff check --fix .`

### 6.2 Ruff (Formatting)
```bash
ruff format --check .
```
* Line length: 100 characters.
* Target Python version: Python 3.11+.

### 6.3 Pyright (Type Checking)
```bash
pyright
```
* Must pass with **0 errors, 0 warnings**.
* Uses configuration in `pyrightconfig.json` pointing to `.venv`.

### 6.4 Pytest (Test Suite)
```bash
pytest
```
* Full test suite must pass with zero failures.
* Tests should maintain unit test isolation with fast execution (< 0.5s total runtime).

### 6.5 Core Performance Profiling
```bash
python tests/benchmark_profile.py
```
* Measures 1,000 operation iterations under `cProfile`.
* Core SDK prep + post execution overhead must remain under **35 µs / op** (> 25,000 ops/sec).

---

## 7. Verified Performance Benchmarks & Current Stats

Live profiling benchmarks measured with `cProfile` over 1,000 operations (`tests/benchmark_profile.py`):

| Metric | Legacy / Baseline | Current `mapi` | Improvement |
| :--- | :--- | :--- | :--- |
| **Total Benchmark Time (1,000 ops)** | 0.068 s | **0.0247 s** | **63.7% faster** |
| **Per-Operation SDK Overhead** | 67.6 µs / op | **24.7 µs / op** | **2.74x throughput** |
| **Peak Execution Throughput** | 14,792 ops/sec | **40,478 ops/sec** | **+173.6% ops/sec** |
| **Total Function Calls (1,000 ops)** | 277,000 calls | **79,003 calls** | **71.5% fewer calls** |
| **Parameter Validation Time** | ~26 ms | **~1 ms** | **26x faster** |
| **Test Suite Execution (158 tests)** | ~1.5 s | **0.28 s** (117 passed, 41 skipped) | **~5.4x faster test run** |
| **Linter / Type-Checker Status** | Untracked | **0 errors, 0 warnings** | Full strict compliance |
