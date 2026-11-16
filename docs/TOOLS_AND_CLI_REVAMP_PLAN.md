# Mapi Tools & Utilities Revamp Plan: Model-First Architecture & CLI Suite

## 1. Executive Summary

The `mapi` repository currently contains two legacy utility directories at the workspace root:
* **`tools/`**: An ad-hoc pipeline for downloading, normalizing, extracting, compiling, and populating OpenAPI specifications into `.utilize.json.zst` files and `services.json`.
* **`utils/`**: Disjoint developer scripts for schema inspection, cProfile wrapping, and Jinja2-based integration test generation.

While the core `mapi` SDK runtime (`src/mapi`) has been fully modernized with `msgspec.Struct` models, direct C-level JSON decoders, and connection multiplexing, the toolchain has lagged behind: it relies heavily on untyped `dict[str, Any]` mutation, raw `print` debugging, fragile relative paths, and uncoordinated script execution.

This document outlines the blueprint to **revamp, model, optimize, and unify** all utilities into a production-grade Command-Line Interface (`mapi-cli` / `mapi.cli`).

---

## 2. Current Toolchain Audit & Anti-Pattern Analysis

### 2.1 File Inventory & Current Flaws

| File | Primary Responsibility | Current Anti-Patterns & Deficiencies | Target Architecture |
| :--- | :--- | :--- | :--- |
| **`tools/fetcher.py`** | Downloads OpenAPI specs from URLs via `niquests.Session` | Passes raw `dict[str, Any]`, untyped return values, hardcoded timeouts and user-agents | `SpecFetcher` engine with typed `FetchResult` and `FetchSource` structs |
| **`tools/extractor.py`** | Reduces raw OpenAPI specs to operations and parameter components | Manipulates nested Python dictionaries; ad-hoc string formatting; manually builds JSON refs | `SpecCompiler` engine building typed `Operation`, `Parameter`, and `Components` structs |
| **`tools/converter.py`** | Uncompresses and decodes YAML/JSON OpenAPI specs | Weak error handling, returns raw `Mapping[str, Any]` | Unified `SpecParser` with `msgspec.yaml` and `msgspec.json` decoders |
| **`tools/pipeline.py`** | Multiprocessing batch coordinator for spec extraction | Uses raw `dict` metrics, stringly-typed status indicators (`"success"`, `"failure"`) | `CompilePipeline` with typed `CompileTask` and `CompileMetrics` |
| **`tools/populate.py`** | End-to-end orchestration of fetch + compile + registry | 180 lines of script glue, relative filesystem assumptions, scattered global variables | `mapi spec sync` CLI orchestrator |
| **`tools/registry_builder.py`**| Compiles `services.json` from `metadata.yml` files | Good start using `ServiceRegistry`, but lacks incremental updates and CLI integration | `RegistryCompiler` engine + `mapi registry build` command |
| **`tools/validate.py`** | Validates generated `utilize.json` and `$ref` integrity | Standalone `argparse` script, duplicates discovery logic | `mapi validate` CLI command |
| **`tools/reporting.py`** | Generates markdown/text performance tables | Hardcoded string formatting, tightly coupled to `populate.py` | `ReportingEngine` supporting Rich terminal output + Markdown |
| **`utils/inspector.py`** | CLI utility to list providers, APIs, and operations | Duplicates `Mapi.discovery` logic; uses standard `json.dumps` | `mapi inspect` command tree |
| **`utils/profiler.py`** | Wrapper around `cProfile` and `pstats` | Spawns python subprocesses; crude terminal string matching | `mapi profile` CLI tool with native profiling hooks |
| **`utils/show_format.py`** | Displays `ResponseMetadata` schema and inspects JSON | Standalone script, manual type string conversion | Built into `mapi inspect schema` |
| **`utils/generate_integration_tests.py`** | Generates pytest test files via Jinja2 templates | Hardcoded sampling logic, direct `sys.path` injection | `mapi test generate` CLI command |
| **`utils/generate_integration_report.py`**| Formats test run results into Markdown | Reads raw filesystem outputs, manual markdown assembly | `mapi test report` CLI command |

---

## 3. Architectural Principles: Model First, Then Build

To mirror the performance and reliability of the `mapi` core SDK, the revamped toolchain will follow four foundational tenets:

```
  ┌────────────────────────────────────────────────────────┐
  │ 1. Model First (msgspec.Struct)                        │
  │    Typed source configs, tasks, metrics & reports      │
  └──────────────────────────┬─────────────────────────────┘
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 2. Pipeline Engines (Zero-Dict Mutation)               │
  │    SpecFetcher ──► SpecCompiler ──► RegistryCompiler   │
  └──────────────────────────┬─────────────────────────────┘
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 3. Direct Domain Struct Generation                     │
  │    Builds ServiceData, Operation, Parameter directly   │
  └──────────────────────────┬─────────────────────────────┘
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 4. Unified CLI Dispatcher (mapi / mapi-cli)            │
  │    Modern subcommands with rich interactive outputs    │
  └────────────────────────────────────────────────────────┘
```

1. **Strict Modeling with `msgspec.Struct`**:
   No raw `dict[str, Any]` across tool boundaries. All task configurations, spec sources, extraction states, and execution metrics must be defined as immutable, typed structs with `frozen=True` and `gc=False`.
2. **Direct Domain Struct Generation**:
   The compiler must assemble instances of `mapi.models.domain.ServiceData`, `Operation`, `Parameter`, and `Components` directly, validating schema constraints in C at instantiation rather than discovering syntax errors during client runtime.
3. **Dual-Format Emission (JSON + MessagePack)**:
   The compiler must be capable of emitting both `.utilize.json.zst` and binary `.utilize.msgpack.zst` for optimal decoding performance.
4. **First-Class CLI Integration**:
   Every capability must be exposed as a distinct subcommand under a cohesive CLI namespace (`mapi <subcommand>` or `mapi-cli <subcommand>`).

---

## 4. Target Data Models

All pipeline entities will be formalized in `mapi.cli.models` (or `mapi_cli.models`):

```python
from __future__ import annotations
from typing import Annotated, Literal
import msgspec
from msgspec import Meta

NonEmptyStr = Annotated[str, Meta(min_length=1)]


class SpecSourceConfig(msgspec.Struct, frozen=True, gc=False):
    """Specification of an upstream OpenAPI source."""

    provider: NonEmptyStr
    api: NonEmptyStr
    source: NonEmptyStr
    url: NonEmptyStr
    popularity_rank: int = 999
    primary_auth: str = "none"
    auth_types: list[str] = msgspec.field(default_factory=list)


class FetchResult(msgspec.Struct, frozen=True, gc=False):
    """Result of fetching an upstream specification."""

    provider: str
    api: str
    source: str
    url: str
    status: Literal["downloaded", "skipped", "failure"]
    bytes_downloaded: int = 0
    duration_sec: float = 0.0
    error_message: str | None = None
    output_path: str | None = None


class CompileConfig(msgspec.Struct, frozen=True, gc=False):
    """Configuration options for spec extraction and compilation."""

    format_version: int = 3
    emit_msgpack: bool = True
    emit_json: bool = True
    compress_zstd: bool = True
    zstd_level: int = 3
    force_recompile: bool = False


class CompileResult(msgspec.Struct, frozen=True, gc=False):
    """Metrics and artifacts from compiling a single service."""

    provider: str
    api: str
    source: str
    status: Literal["success", "failure", "skipped"]
    operation_count: int = 0
    parameter_component_count: int = 0
    parse_duration_sec: float = 0.0
    extract_duration_sec: float = 0.0
    output_paths: list[str] = msgspec.field(default_factory=list)
    error_message: str | None = None


class ValidationReport(msgspec.Struct, frozen=True, gc=False):
    """Results of service integrity validation."""

    total_services: int
    valid_services: int
    errors: dict[str, list[str]] = msgspec.field(default_factory=dict)
    warnings: dict[str, list[str]] = msgspec.field(default_factory=dict)
```

---

## 5. Unified Command-Line Interface (CLI) Structure

The revamped toolchain will expose a single executable entrypoint `mapi` (with an alias `mapi-cli`):

```
mapi
├── inspect                  # SDK and API inspection tools
│   ├── providers            # List all installed/known providers
│   ├── apis <provider>      # List APIs for a provider
│   ├── operations <prov> <api> # List operations for a service
│   ├── operation <prov> <api> <op> # Display full typed Operation schema
│   └── schema               # Display client response metadata contracts
│
├── spec                     # OpenAPI ingestion & compiler toolchain
│   ├── fetch                # Download upstream specifications concurrently
│   ├── compile              # Parse, normalize, and extract into utilize.json/msgpack
│   └── sync                 # Full pipeline (fetch -> compile -> build registry)
│
├── registry                 # Service registry management
│   ├── build                # Generate services.json from disk metadata
│   └── validate             # Comprehensive schema and $ref integrity check
│
├── profile                  # Performance diagnostics
│   ├── benchmark            # Run core SDK latency & throughput profiling
│   └── run <script.py>      # Profile arbitrary client scripts under cProfile
│
└── test                     # Test generation and automated verification
    ├── generate             # Generate functional integration test suites
    └── report               # Parse test outputs and emit markdown telemetry
```

### 5.1 CLI Command Specifications

#### `mapi inspect`
Replaces `utils/inspector.py` and `utils/show_format.py` by integrating directly with `Mapi.discovery`:
```bash
# List all providers in tabulated format:
mapi inspect providers

# Display details of an operation with colorized schema output:
mapi inspect operation pokeapi REST get_pokemon --json

# View ResponseMetadata schema definitions:
mapi inspect schema
```

#### `mapi spec fetch` & `mapi spec compile`
Replaces `tools/fetcher.py`, `tools/pipeline.py`, and `tools/populate.py`:
```bash
# Download specs with bounded concurrency (HTTP/2 / HTTP/3 session pool):
mapi spec fetch --sources registry/github_sources.yaml --concurrency 16

# Compile downloaded specs into dual JSON + MessagePack Zstandard artifacts:
mapi spec compile --provider pokeapi --format all --compress

# Run full end-to-end sync with progress bar and markdown summary:
mapi spec sync --all
```

#### `mapi registry build` & `mapi registry validate`
Replaces `tools/registry_builder.py` and `tools/validate.py`:
```bash
# Build services.json from local data directories:
mapi registry build --data-dir src/mapi/data --output src/mapi/services.json

# Validate integrity of all operation definitions and components:
mapi registry validate --strict
```

#### `mapi profile benchmark`
Replaces `utils/profiler.py` and root benchmark scripts:
```bash
# Run verified 1,000-op cProfile benchmark:
mapi profile benchmark --iterations 5000 --top 30 --sort cumtime
```

#### `mapi test generate`
Replaces `utils/generate_integration_tests.py`:
```bash
# Generate 5-point sampled integration tests for a service:
mapi test generate --provider github --api rest --output tests/integration/
```

---

## 6. Implementation Architecture

### 6.1 Recommended Directory Restructuring

To package the toolchain properly and decouple developer utilities from SDK core runtime, we propose the following directory reorganization:

```
mapi/
├── src/
│   └── mapi/
│       ├── __init__.py
│       ├── client/
│       ├── models/
│       ├── registry/
│       ├── transport/
│       ├── validation/
│       └── cli/                     # <-- NEW: First-class CLI package
│           ├── __init__.py
│           ├── main.py              # CLI entry point dispatcher
│           ├── models.py            # Typed msgspec structs for CLI/tools
│           ├── engines/             # Core re-usable pipeline engines
│           │   ├── fetcher.py       # SpecFetcher engine
│           │   ├── compiler.py      # SpecCompiler (extract + normalize)
│           │   ├── registry.py      # RegistryCompiler
│           │   ├── validator.py     # ServiceValidator
│           │   └── testgen.py       # TestGenerator
│           └── commands/            # Command implementations
│               ├── inspect.py
│               ├── spec.py
│               ├── registry.py
│               ├── profile.py
│               └── test.py
├── pyproject.toml                   # Adds [project.scripts] mapi = "mapi.cli.main:main"
```

*(Note: `mapi-cli` can either import directly from `mapi.cli` or be maintained as a lightweight distribution wrapper).*

---

## 7. Migration & Rollout Plan

### Phase 1: Struct Modeling & Engine Extraction
1. Define `SpecSourceConfig`, `FetchResult`, `CompileConfig`, `CompileResult`, and `ValidationReport` in `src/mapi/cli/models.py`.
2. Refactor `extractor.py` and `converter.py` into `SpecCompiler`, instantiating domain models (`ServiceData`, `Server`, `Operation`, `Parameter`) directly without raw dict intermediaries.
3. Add MessagePack binary serialization support (`.utilize.msgpack.zst`).

### Phase 2: CLI Command Layer & Dispatcher
1. Implement `src/mapi/cli/main.py` with structured `argparse` subparsers (zero external dependencies).
2. Wire `inspect`, `spec`, `registry`, `profile`, and `test` commands to the respective engines.
3. Configure `[project.scripts]` in `pyproject.toml` exposing `mapi = "mapi.cli.main:main"`.

### Phase 3: Unit Testing & Verification
1. Create comprehensive unit tests for each CLI subcommand under `tests/unit/test_cli.py`.
2. Verify formatting and type safety:
   * `ruff check src/mapi/cli tests`
   * `pyright src/mapi/cli`
3. Benchmark compilation speed: target a **3x–5x speedup** during spec compilation due to direct `msgspec.Struct` allocation and elimination of untyped dictionary roundtrips.

### Phase 4: Deprecation of Legacy Root Folders
1. Add deprecation warnings to legacy scripts in `tools/` and `utils/` forwarding to `mapi <command>`.
2. Safely retire old scripts once all automated test pipelines transition to the new CLI commands.

---

## 8. Expected Benefits & Performance Gains

| Dimension | Legacy `tools/` + `utils/` | Revamped Model-First CLI |
| :--- | :--- | :--- |
| **Type Safety** | Untyped `dict[str, Any]` with runtime `KeyError` risks | 100% strictly typed `msgspec.Struct` models (0 Pyright errors) |
| **Pipeline Performance** | Slow JSON serialization + dict copies (~5–10s per large spec) | Direct C-struct instantiation & MessagePack emission (~1–2s per large spec) |
| **Developer Experience** | 13 scattered scripts with inconsistent arguments | Single, discoverable `mapi` command with subcommands and `--help` |
| **Packaging & Distribution** | Unpackaged root scripts requiring explicit git checkouts | Bundled CLI executable installable via `pip install mapi` |
| **Maintenance Cost** | High duplicate code between SDK and tools | Unified: CLI directly reuses SDK models, loaders, and cache |
