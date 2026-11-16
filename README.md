<div align="center">
<picture>
  <source media="(prefers-color-scheme: light)" srcset="./docs/banner.svg">
  <img alt="mapi-logo" src="./docs/banner.svg" width="100%" height="100%">
</picture>

![Build Status](https://img.shields.io/badge/Build-passing-brightgreen?style=flat)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat)](./LICENSE)
[![API Ref-mapi](https://img.shields.io/badge/API%20Reference-mapi-blue?style=flat)](./docs/API_REFERENCE.md)
</div>

# Mapi

**Universal API execution engine and SDK for modern software and autonomous LLM agents.**

`mapi` compiles OpenAPI specifications into high-speed, Zstandard-compressed metadata catalogs, delivering sub-25µs typed Python access to any REST API with zero code-generation bloat.

---

## The Ecosystem

| Component | Role | Description |
| :--- | :--- | :--- |
| **`mapi`** | **Core SDK & Engine** | High-performance Python client, dynamic proxy, parameter validation, and HTTP/1.1–3 connection pooling. |
| **`mapi-cli`** | **Developer Toolchain & TUI** | Terminal interface to discover, search, compile, and download specifications into local storage. |
| **`Nodus` / `Mapidex`** | **LLM Agent Runner** | Autonomous tool-calling runtime using `mapi` for on-demand discovery and API execution without prompt bloat. |

---

## Key Features

* **Ultra-Low Latency Overhead**: Sub-25µs execution overhead per operation, achieving over 40,000 ops/sec.
* **Pre-Compiled Compressed Metadata**: OpenAPI schemas are parsed, canonicalized, and stored in Zstandard-compressed msgspec structs (~70% space savings).
* **Intuitive Dynamic Proxy**: Access any endpoint naturally via `client.<provider>.<api>(op_id, **params)` with IDE-friendly discovery.
* **Modern HTTP Transport**: Built on `niquests` with native HTTP/1.1, HTTP/2, and HTTP/3 multiplexing and connection pooling.
* **First-Class Async**: Native asynchronous execution (`aexecute`) with non-blocking lifecycle management.
* **Typed Security & Auth**: Built-in credential providers for Bearer tokens, API Keys (header/query/cookie), and custom scheme handlers.
* **Zero-Sprawl Local Discovery**: Project-first registry resolution with offline guarantees and on-demand spec compilation.

---

## Installation

```bash
# Core SDK
pip install mapi

# CLI Toolchain (includes interactive Textual TUI)
pip install mapi-cli
```

---

## Quickstart

```python
from mapi import Mapi

# 1. Initialize client
client = Mapi()

# 2. Discover available providers & APIs
print("Providers:", client.discovery.list_providers())
# -> ['pokeapi', 'stripe', 'github', 'discord', 'spotify', 'aws', 'asana']

# 3. Call an API via dynamic proxy
response = client.pokeapi.REST("pokemon_retrieve", id="pikachu")

if response.data:
    print(f"Name: {response.data.get('name')}")
    print(f"Latency: {response.metadata.duration_ms:.2f}ms (HTTP {response.metadata.http_status})")
```

---

## Usage Patterns

### 1. Proxy-Based Execution (Recommended)

Proxy calls provide clean, readable syntax and automatic argument mapping:

```python
# Synchronous call
res = client.pokeapi.REST("pokemon_retrieve", id="ditto")
print(res.data["name"], res.metadata.duration_ms)

# Asynchronous call
async with Mapi() as client:
    res = await client.pokeapi.REST.aexecute("pokemon_retrieve", id="bulbasaur")
    print(res.data["name"])
```

### 2. Dynamic Runtime `execute()`

When provider, service, or operation names are determined dynamically at runtime (e.g. from an LLM tool call or workflow graph):

```python
result = client.execute(
    provider="pokeapi",
    api="REST",
    operation="pokemon_retrieve",
    source="github",
    id="charizard",
)
```

### 3. Authentication Helpers

```python
from mapi import Mapi

# Automatic Bearer token conversion
client = Mapi(auth="ghp_personal_token_xyz")

# Explicit Bearer Auth
client = Mapi(auth=Mapi.Auth.Bearer("token_123", scheme="Bearer"))

# API Key (Header, Query parameter, or Cookie)
client = Mapi(auth=Mapi.Auth.ApiKey(key="secret_key", name="X-API-Key", placement="header"))
```

### 4. Transparent Online Spec Fetching

By default, `Mapi` runs fully offline using local storage. Enable transparent remote pulling for unpopulated catalog specs:

```python
# Enable via constructor or export MAPI_ONLINE=1
client = Mapi(online=True)
res = client.discord.REST("get_my_user")
```

---

## Companion Toolchain: `mapi-cli`

Pair `mapi` with `mapi-cli` for terminal-based exploration and specification management:

```bash
# Interactive TUI download manager with arrow navigation and live search
mapi download

# List all registered providers and local download status
mapi apis

# List operations for a provider, with method and fuzzy filtering
mapi apis discord -m post
mapi ops discord -m post,get message

# Search across all registered providers, APIs, paths, and methods
mapi search "create_message"

# Inspect detailed schema and parameters for an operation
mapi describe pokeapi REST pokemon_retrieve
```

---

## Architecture & Performance

`mapi` replaces heavy codegen pipelines with pre-compiled binary catalogs that load in constant time:

```
OpenAPI Spec (JSON / YAML)
       │
       ▼  (mapi-cli)
Canonical Normalizer & Fingerprinter
       │
       ▼
Compressed Catalog (.mapi.json.zst / msgpack)
       │
       ▼  (mapi SDK)
In-Memory LFU / LRU ServiceCache ──► Dynamic Proxy ──► Niquests (HTTP/1.1-2-3)
```

### Benchmarks

| Metric | Legacy Codegen | `mapi` Engine | Advantage |
| :--- | :--- | :--- | :--- |
| **Execution Overhead** | 67.6 µs / op | **24.7 µs / op** | **63.7% faster** |
| **Peak Throughput** | ~14,800 ops/sec | **~40,500 ops/sec** | **2.7x higher throughput** |
| **Parameter Validation** | ~26 ms (recompiling) | **~1 ms (cached structs)** | **26x faster** |
| **Memory per Service** | 15–40 MB (code classes) | **< 1.5 MB (compressed catalog)** | **> 90% memory reduction** |
| **Test Suite Execution** | ~1.5 s | **0.25 s** (154 tests) | **6x faster test iteration** |

---

## Contributing

```bash
# Run unit & generic test suite
pytest tests/

# Type check & lint
ruff check .
pyright
```

---

## License

Apache 2.0 License — see [LICENSE](./LICENSE) for details.
