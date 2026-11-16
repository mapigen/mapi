# Architecture & Revamp Plan: Standalone `mapi-cli` & Model-First Toolchain

## 1. Executive Summary & Project Boundary Decision

**Decision: Yes, absolutely split the projects.**

We will establish a strict, clean architectural boundary between the **runtime SDK** (`mapi`) and the **developer CLI & toolchain** (`mapi-cli`):

```
┌────────────────────────────────────────────────────────┐
│                        mapi                            │
│  Repo: /home/meoya/code/mapigen/mapi/mapi              │
│  Role: Lightweight, high-performance runtime SDK      │
│  Deps: msgspec, niquests, zstandard (Zero CLI bloat)   │
└───────────────────────────▲────────────────────────────┘
                            │ (One-way public import only)
┌───────────────────────────┴────────────────────────────┐
│                      mapi-cli                          │
│  Repo: /home/meoya/code/mapigen/mapi/mapi-cli          │
│  Role: Developer CLI, interactive REPL, build pipeline │
│  Deps: mapi, typer, rich, platformdirs                 │
└────────────────────────────────────────────────────────┘
```

### Architectural Guardrails

1. **SDK Purity**: The `mapi` SDK repo stays strictly runtime-only (~30 µs/op overhead). It installs no executable and carries zero CLI/TUI dependencies (`typer`, `rich`, `click`, `prompt_toolkit`).
2. **One-Way Dependency**: `mapi-cli` imports `mapi` through public APIs (`from mapi import Mapi, ...`). `mapi` never imports `mapi-cli`.
3. **Relocation Target**: All 13 legacy scripts currently living in `mapi/tools/` and `mapi/utils/` will be moved into `mapi-cli/src/mapi_cli/tools/` and `mapi_cli/commands/`, clearing out non-runtime baggage from the SDK repository.
4. **Independent Release Cycles**: SDK and CLI have independent semantic versioning and changelogs. `mapi-cli` pins `mapi>=0.1,<0.2`.

---

## 2. Inventory & Migration Mapping

| Current Location in `mapi/` | Target in `mapi-cli/src/mapi_cli/` | Refactored Responsibility |
| :--- | :--- | :--- |
| **`utils/inspector.py`** | `commands/providers.py`<br>`commands/apis.py`<br>`commands/ops.py` | Runtime discovery commands rendering Rich tables on TTY and JSON when piped. |
| **`utils/show_format.py`** | `commands/describe.py` | Schema and metadata card inspector with colorized parameter tables. |
| **`utils/profiler.py`** | `commands/doctor.py`<br>`commands/profile.py` | System health checker (`doctor`) and `cProfile` benchmark runner. |
| **`utils/generate_integration_tests.py`**| `tools/testgen.py`<br>`commands/tools.py` | Jinja2 test generation using SDK `DiscoveryService`. |
| **`utils/generate_integration_report.py`**| `tools/reporting.py` | Test run telemetry and markdown report formatter. |
| **`tools/fetcher.py`** | `tools/fetch/` | Concurrently fetches upstream specs reusing SDK session pooling. |
| **`tools/converter.py`** | `tools/convert/` | Normalizes and decodes YAML/JSON into typed OpenAPI structures. |
| **`tools/extractor.py`** | `tools/extract/` | Extracts operations and deduplicates parameter components into `ServiceData`. |
| **`tools/pipeline.py`** | `tools/pipeline.py` | Multiprocessing pipeline coordinator. |
| **`tools/populate.py`** | `tools/populate.py` | End-to-end sync runner (`mapi tools populate`). |
| **`tools/registry_builder.py`** | `tools/registry_builder.py` | Compiles `metadata.yml` files into `services.json`. |
| **`tools/validate.py`** | `tools/validate.py` | Validates data directory schema and `$ref` integrity. |
| **`tools/utils.py`** | `tools/utils.py` | Zstd compression, hashing, and auth extraction utilities. |

---

## 3. Model-First Toolchain Revamp: "Use Models & Build Again"

### The Problem in Legacy `tools/`
The legacy tools pass around raw dictionaries (`dict[str, Any]`), mutate nested keys (`service_info["provider"]`, `processed_data["operations"]`), and perform manual string formatting for JSON references (`#/components/parameters/...`). This causes runtime `KeyError` regressions and slows down batch compilation.

### The Solution: Strong Typing via `msgspec.Struct`
All build-time objects will be modeled as strongly typed structs in `mapi_cli.tools.models`:

```
  ┌────────────────────────────────────────────────────────┐
  │ 1. Ingestion Config (SpecSourceConfig)                 │
  │    Typed provider, api, source, upstream URL & auth    │
  └──────────────────────────┬─────────────────────────────┘
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 2. Resumable State (StateManifest)                     │
  │    Tracks ETag, commit SHA & content hashes            │
  └──────────────────────────┬─────────────────────────────┘
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 3. Direct Domain Struct Generation                     │
  │    Builds ServiceData, Operation, Parameter directly   │
  └──────────────────────────┬─────────────────────────────┘
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 4. Dual-Format Emission (Zstandard Compressed)         │
  │    Outputs: utilize.json.zst + utilize.msgpack.zst     │
  └────────────────────────────────────────────────────────┘
```

#### New Build-Time Data Models

```python
from __future__ import annotations
from typing import Annotated, Literal
import msgspec
from msgspec import Meta

NonEmptyStr = Annotated[str, Meta(min_length=1)]


class SpecSourceConfig(msgspec.Struct, frozen=True, gc=False):
    """Upstream OpenAPI specification entry."""

    provider: NonEmptyStr
    api: NonEmptyStr
    source: NonEmptyStr
    url: NonEmptyStr
    popularity_rank: int = 999
    primary_auth: str = "none"
    auth_types: list[str] = msgspec.field(default_factory=list)


class FetchResult(msgspec.Struct, frozen=True, gc=False):
    """Result of downloading an upstream specification."""

    provider: str
    api: str
    source: str
    status: Literal["downloaded", "skipped", "failure"]
    bytes_downloaded: int = 0
    duration_sec: float = 0.0
    output_path: str | None = None
    error_message: str | None = None


class CompileConfig(msgspec.Struct, frozen=True, gc=False):
    """Options governing extraction and serialization."""

    format_version: int = 3
    emit_msgpack: bool = True
    emit_json: bool = True
    zstd_level: int = 3
    force: bool = False


class CompileMetrics(msgspec.Struct, frozen=True, gc=False):
    """Telemetry captured during service compilation."""

    provider: str
    api: str
    source: str
    status: Literal["success", "failure", "skipped"]
    operation_count: int = 0
    reusable_param_count: int = 0
    parse_duration: float = 0.0
    extract_duration: float = 0.0
    utilize_path: str | None = None
    error_message: str | None = None


class ValidationResult(msgspec.Struct, frozen=True, gc=False):
    """Integrity check report for services and components."""

    total_services: int
    valid_services: int
    broken_refs: dict[str, list[str]] = msgspec.field(default_factory=dict)
    schema_errors: dict[str, list[str]] = msgspec.field(default_factory=dict)
```

#### Direct Domain Struct Assembly
Instead of assembling untyped dictionaries, the compiler directly constructs `mapi.models.domain` instances:
* `Parameter(name=..., in_=..., schema_=..., required=...)`
* `ParameterRef(ref=f"#/components/parameters/{fingerprint}")`
* `Operation(service=api, path=..., method=..., parameters=[...])`
* `ServiceData(format_version=3, service_name=api, servers=[...], components=..., operations=...)`

This enforces compile-time schema conformance and allows direct serialization via `msgspec.json.encode` and `msgspec.msgpack.encode` without dict transformations.

---

## 4. `mapi-cli` Repository Structure

The target repository structure inside `/home/meoya/code/mapigen/mapi/mapi-cli`:

```
mapi-cli/
├── pyproject.toml                   # Hatchling packaging, defines `mapi` script
├── README.md
├── src/
│   └── mapi_cli/
│       ├── __init__.py
│       ├── __main__.py              # Enables python -m mapi_cli
│       ├── app.py                   # Root Typer application & global options
│       ├── context.py               # CliContext (Lazy Mapi construction)
│       ├── output.py                # Renderer: Auto / Table / JSON / Raw
│       ├── errors.py                # MapiError -> Exit code mapping (0-8)
│       ├── logging.py               # RichHandler configuration
│       ├── completion.py            # Fast sub-150ms shell completers
│       │
│       ├── ui/                      # Visual presentation layer (Zero SDK logic)
│       │   ├── theme.py             # Semantic styles (dark/light/mono/NO_COLOR)
│       │   ├── console.py           # Per-stream stdout/stderr consoles
│       │   ├── tables.py            # Rich Table builders for providers/apis/ops
│       │   ├── panels.py            # Operation describe cards & error panels
│       │   └── progress.py          # Spinners & multi-task progress bars
│       │
│       ├── interactive/             # Optional [interactive] extra
│       │   ├── pickers.py           # Fuzzy provider -> api -> op selection
│       │   ├── prompts.py           # Schema-driven parameter input prompts
│       │   └── shell.py             # `mapi shell` persistent REPL
│       │
│       ├── commands/                # Thin runtime commands (call SDK methods)
│       │   ├── providers.py         # mapi providers
│       │   ├── apis.py              # mapi apis <provider>
│       │   ├── ops.py               # mapi ops <provider> <api>
│       │   ├── describe.py          # mapi describe <provider> <api> <op>
│       │   ├── call.py              # mapi call <p> <a> <o> key=val [--dry-run]
│       │   ├── search.py            # mapi search <query>
│       │   ├── doctor.py            # mapi doctor (checks data/registry sanity)
│       │   └── shell.py             # mapi shell
│       │
│       └── tools/                   # Relocated & revamped build-time pipeline
│           ├── __init__.py          # `mapi tools ...` Typer sub-app
│           ├── models.py            # Typed msgspec structs for build tools
│           ├── state.py             # Resumable manifest (ETag / SHA / content hash)
│           ├── fetch/               # SpecFetcher (GitHub, Postman, URLs)
│           ├── extract/             # SpecCompiler (produces ServiceData)
│           ├── convert/             # SpecParser (YAML/JSON normalization)
│           ├── populate.py          # End-to-end sync runner
│           ├── pipeline.py          # Multiprocess worker pool
│           ├── registry_builder.py  # Assembles services.json
│           ├── validate.py          # Structural & $ref integrity validator
│           ├── reporting.py         # Markdown and Rich performance reports
│           └── testgen.py           # Integration test generator
│
└── tests/
    ├── cli/                         # Runtime command tests with CliRunner
    ├── tools/                       # SpecCompiler & pipeline tests with fixtures
    └── contract/                    # Round-trip: CLI writes -> SDK DiskLoader reads
```

---

## 5. Command-Line Taxonomy

### 5.1 Runtime Commands (`mapi ...`)

```bash
# Discovery
mapi providers                                       # List all providers (Rich table on TTY, JSON on pipe)
mapi apis <provider>                                 # List APIs for a provider
mapi ops <provider> <api> [--filter TEXT]            # List operations with colored HTTP method badges
mapi describe <provider> <api> <operation>           # Formatted card with parameters, descriptions & example call
mapi search <query>                                  # Fuzzy search across providers, APIs, and operations

# Execution
mapi call <provider> <api> <operation> [PARAM=VAL...] # Execute operation (JSON on stdout, logs on stderr)
mapi call <provider> <api> <operation> --dry-run     # Inspect prepared URL, headers, and params without sending
mapi call <provider> <api> <operation> --curl        # Emit equivalent curl command

# Interactive & System
mapi call                                            # Interactive fuzzy picker & parameter prompts (TTY only)
mapi shell                                           # Full REPL with history, auto-suggest & context switching
mapi doctor                                          # Verify SDK, data version, paths & registry integrity
mapi completion install                              # Install shell completion (bash, zsh, fish, powershell)
```

### 5.2 Build & Maintainer Commands (`mapi tools ...`)

```bash
# Ingestion & Extraction
mapi tools fetch <source> [--provider P] [--out DIR] # Download upstream specs concurrently
mapi tools extract <raw-spec> [--out FILE]          # Extract operations & parameters into ServiceData
mapi tools convert <extracted> [--format msgpack]   # Compress into .utilize.json.zst or .msgpack.zst

# Pipeline Orchestration
mapi tools populate [--provider P] [--jobs N]       # Run full fetch + extract + convert cycle
mapi tools pipeline [--from fetch] [--to registry]  # Resumable end-to-end pipeline using state.py
mapi tools registry build                           # Compile services.json from disk metadata
mapi tools validate [--strict]                      # Validate schema and reference integrity
mapi tools testgen --provider <P> --api <A>         # Generate functional integration tests
```

---

## 6. Packaging & Dependencies (`pyproject.toml`)

The `pyproject.toml` in `/home/meoya/code/mapigen/mapi/mapi-cli`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mapi-cli"
version = "0.1.0"
description = "Universal API CLI and toolchain built on the mapi SDK"
requires-python = ">=3.11"
dependencies = [
    "mapi>=0.1.0,<0.2.0",
    "typer>=0.12.0",
    "rich>=13.0.0",
    "platformdirs>=4.0.0",
]

[project.optional-dependencies]
interactive = [
    "prompt_toolkit>=3.0.0",
]
tui = [
    "textual>=0.80.0",
]
tools = [
    "jinja2>=3.1.0",
    "openapi-spec-validator>=0.7.0",
]
all = [
    "mapi-cli[interactive,tui,tools]",
]

[project.scripts]
mapi = "mapi_cli.app:main"
mapi-cli = "mapi_cli.app:main"

[tool.hatch.build.targets.wheel]
packages = ["src/mapi_cli"]
```

---

## 7. Migration & Execution Checklist

### Phase 1: Environment & Project Setup in `mapi-cli`
- [ ] Initialize `mapi-cli/pyproject.toml` with `typer`, `rich`, `platformdirs`, and editable link to `../mapi`.
- [ ] Create `src/mapi_cli/__init__.py`, `__main__.py`, `app.py`, and `context.py`.
- [ ] Implement `mapi_cli.ui` foundation: `theme.py`, `console.py`, and `output.py` (enforcing stdout=data, stderr=logs).
- [ ] Implement exit code hierarchy (0 to 8) mapping to `MapiError` in `errors.py`.

### Phase 2: Runtime Commands Implementation
- [ ] Implement `mapi providers`, `mapi apis`, and `mapi ops` using `Mapi.discovery`.
- [ ] Implement `mapi describe` rendering parameter cards.
- [ ] Implement `mapi call` supporting positional `key=value` params, `--dry-run`, `--curl`, and JSON parsing.
- [ ] Implement `mapi doctor` and fast completion scripts (`completion.py`).

### Phase 3: Move & Revamp Build Tools
- [ ] Create `mapi_cli.tools.models` with typed `msgspec.Struct` definitions.
- [ ] Move `tools/converter.py` and `tools/extractor.py` into `mapi_cli/tools/`, refactoring them to produce `ServiceData` directly.
- [ ] Move `tools/fetcher.py`, `pipeline.py`, and `populate.py`, integrating `state.py` for resumable caching.
- [ ] Move `tools/registry_builder.py` and `tools/validate.py` under `mapi tools registry build` and `mapi tools validate`.
- [ ] Move `utils/generate_integration_tests.py` under `mapi tools testgen`.

### Phase 4: Clean SDK & Contract Testing
- [ ] Add contract tests in `mapi-cli/tests/contract/`: verify that artifacts written by `mapi tools` load flawlessly in `mapi.registry.loader.DiskLoader`.
- [ ] Remove legacy root folders `mapi/tools/` and `mapi/utils/` from the `mapi` repository once all functionality is active in `mapi-cli`.
- [ ] Run test suite, `ruff`, and `pyright` across both repositories with 0 errors.
