# mapi-cli: a standalone CLI project built on `mapi`

`mapi-cli` is its own project and repo. It depends on the `mapi` SDK like any other consumer (the same way a node runner or any app would). The extractors, fetchers and build-time tooling from `mapigen` move here, so the SDK repo stays runtime-only.

> Assumption: `mapi` (see `refactor-plan.md`) exposes `Mapi`, `MapiResult`, `MapiError` and its subclasses, `Mapi.discovery` (`DiscoveryService`), `ClientConfig`, the `models` package, and `DiskLoader`. If names differ, adjust only the adapter layer (section 7).

---

## 1. Project split

| Project | Repo | PyPI name | Contains | Depends on |
|---|---|---|---|---|
| **mapi** | `mapigen/mapi` | `mapi` | SDK: models, client, discovery, auth, transport, validation | `msgspec`, `niquests`, `zstandard` |
| **mapi-cli** (this guide) | `mapigen/mapi-cli` | `mapi-cli` | `mapi` command + build-time tools (fetch/extract/convert/populate/validate/report) | `mapi`, `typer`, `rich` |

Rules:

1. **One-way dependency.** `mapi-cli` imports `mapi`. `mapi` never imports `mapi-cli`. The SDK has no CLI dependencies and installs no executable.
2. **Public API only.** The CLI uses what `mapi` exports (`from mapi import ...`, `mapi.models`). No reaching into private modules (`_client`, `_cache`). If the CLI needs something, add it to the SDK's public API.
3. **Independent releases.** SDK and CLI have their own versions and changelogs. The CLI pins a compatible range: `mapi>=X.Y,<X.(Y+1)` while the SDK is 0.x.
4. **Naming.** Distribution `mapi-cli`, import package `mapi_cli`, installed command `mapi`. Check that `mapi` and `mapi-cli` are free on PyPI; if not, publish under another distribution name (the import name and command can stay).

---

## 2. Stack

| Concern | Choice | Why |
|---|---|---|
| CLI framework | **Typer** (Click underneath) | Type-hint driven, subcommand groups, completion built in. Alternative: `cyclopts`. |
| Rendering | **Rich** | Tables, panels, JSON/code highlighting, Markdown, progress bars, themes, pretty tracebacks. |
| Interactive prompts / REPL | **prompt_toolkit** (optional `[interactive]` extra) | Fuzzy pickers, validated prompts, `mapi shell` with history, auto-suggest and completion menus. |
| Full-screen TUI | **Textual** (optional `[tui]` extra, later phase) | `mapi browse`: a three-pane API explorer with a "try it" form. |
| Paths/config | **platformdirs** | Cross-platform config, cache and history locations. |
| Serialization | **msgspec** | Comes with `mapi`; use `msgspec.json.encode` for `--json`. |
| Env/packaging | **uv** + `pyproject.toml` (hatchling) | Lockfile, fast CI, `uv tool install`. |
| Tests | `pytest` + `typer.testing.CliRunner` | In-process, assert exit code/stdout/stderr separately. |
| Lint/types | `ruff`, `pyright` | |
| Tasks | `just` (replaces old `make populate`/`make validate`) | |

---

## 3. Repository layout

```
mapi-cli/
├── pyproject.toml
├── uv.lock
├── justfile
├── README.md
├── src/
│   └── mapi_cli/
│       ├── __init__.py
│       ├── __main__.py              # python -m mapi_cli
│       ├── app.py                   # root Typer app, global options, main()
│       ├── context.py               # CliContext (lazy Mapi construction)
│       ├── output.py                # render(): json / table / raw (delegates to ui/)
│       ├── errors.py                # exception -> exit code mapping
│       ├── logging.py               # RichHandler config (CLI owns logging)
│       ├── completion.py            # dynamic completers (cached, fast)
│       │
│       ├── ui/                      # everything visual (see section 6)
│       │   ├── theme.py             # Theme: semantic styles, light/dark/mono, NO_COLOR
│       │   ├── console.py           # shared stdout/stderr Consoles, TTY/width detection
│       │   ├── tables.py            # providers/apis/ops table builders
│       │   ├── panels.py            # describe card, request/response panels, error panels
│       │   ├── progress.py          # spinners + progress bars (stderr)
│       │   ├── syntax.py            # JSON / body highlighting, truncation, paging
│       │   └── banner.py            # optional logo for --version / first run
│       │
│       ├── interactive/             # optional [interactive] extra
│       │   ├── pickers.py           # fuzzy provider -> api -> operation picker
│       │   ├── prompts.py           # param prompts built from operation schema
│       │   └── shell.py             # `mapi shell` REPL
│       │
│       ├── tui/                     # optional [tui] extra (later phase)
│       │   └── browse.py            # `mapi browse` Textual app
│       │
│       ├── config.py                # user config file (platformdirs): theme, defaults, aliases
│       │
│       ├── commands/                # runtime commands (thin wrappers over mapi)
│       │   ├── providers.py
│       │   ├── apis.py
│       │   ├── ops.py
│       │   ├── describe.py
│       │   ├── call.py
│       │   ├── search.py
│       │   ├── shell.py             # `mapi shell` entry
│       │   ├── browse.py            # `mapi browse` entry
│       │   ├── config_cmd.py        # `mapi config get|set|path|edit`
│       │   ├── history.py           # `mapi history`, `mapi replay`
│       │   └── doctor.py
│       │
│       └── tools/                   # build-time: moved from mapigen
│           ├── __init__.py          # `mapi tools ...` Typer sub-app
│           ├── fetch/               # github.py, postman.py, url.py (was metadata/fetcher.py)
│           ├── extract/             # extractor.py
│           ├── convert/             # converter.py
│           ├── populate.py
│           ├── pipeline.py
│           ├── validate.py
│           ├── deep_validate.py
│           ├── registry_builder.py  # was services/registry_service.py
│           ├── reporting.py
│           └── state.py             # resumable manifest (ETag/SHA/hash)
└── tests/
    ├── cli/                         # runtime command tests
    ├── tools/                       # extractor/pipeline tests with fixture specs
    ├── contract/                    # CLI-writes -> SDK-reads round-trip
    └── fixtures/
        ├── specs/                   # small raw OpenAPI files
        └── data/                    # tiny expected data dir + services.json
```

`pyproject.toml`:

```toml
[project]
name = "mapi-cli"
dynamic = ["version"]
requires-python = ">=3.10"
dependencies = [
    "mapi>=0.1,<0.2",
    "typer>=0.12",
    "rich>=13",
    "platformdirs>=4",
]

[project.optional-dependencies]
interactive = ["prompt_toolkit>=3.0"]   # fuzzy pickers, param prompts, `mapi shell`
tui = ["textual>=0.80"]                 # `mapi browse`
tools = [                               # heavy / maintainer-only deps
    "openapi-spec-validator",
    "psutil",
]
all = ["mapi-cli[interactive,tui,tools]"]

[project.scripts]
mapi = "mapi_cli.app:main"

[dependency-groups]
dev = ["pytest", "ruff", "pyright", "import-linter"]

[tool.uv.sources]
# local development against an unreleased SDK checkout
mapi = { path = "../mapi", editable = true }
```

Install paths:

- End users: `uv tool install "mapi-cli[interactive]"` (colors, completion, pickers, `mapi shell`). Plain `mapi-cli` also works and is fully colored and completable; it just lacks the interactive extras.
- Power users: `uv tool install "mapi-cli[interactive,tui]"` adds `mapi browse`.
- Maintainers: `uv tool install "mapi-cli[tools]"` (adds extractors' validators), or `[all]`.
- Commands that need an extra detect it missing and print an install hint (`uv tool install "mapi-cli[interactive]"`) instead of a traceback.

Keep `[tool.uv.sources]` out of published builds (it only affects local dev), and make CI run once against the pinned/released `mapi` and once against `mapi` main.

---

## 4. Command design

### 4.1 Runtime commands

```
mapi providers                                  # list providers
mapi apis <provider>                            # list APIs for a provider
mapi ops <provider> <api> [--source S] [--filter TEXT]
mapi describe <provider> <api> <operation>      # params, method, path, servers
mapi call <provider> <api> <operation> [PARAM=VALUE ...] [--data JSON|@file|-]
mapi search <query>                             # fuzzy search across providers/apis/operations
mapi call                                       # no args on a TTY: interactive picker + param prompts
mapi shell                                      # REPL with history, auto-suggest, completion menu   [interactive]
mapi browse                                     # full-screen API explorer                            [tui]
mapi history [--limit N]                        # recent calls (secrets redacted)
mapi replay <id|last> [--edit]                  # re-run a call from history
mapi config get|set|path|edit                   # user config (theme, defaults, aliases)
mapi doctor                                     # SDK + data versions, data dir, registry sanity
mapi completion install|show|status             # friendly wrapper over Typer's completion
mapi --version
```

Conventions:

- `call` takes positional path plus `key=value` params: `mapi call github repos get-repo owner=psf repo=requests`. Values parse as JSON when valid (`limit=10` is an int, `draft=true` a bool), otherwise strings.
- `--data` accepts inline JSON, `@file.json`, or `-` for stdin.
- Auth never goes on the command line by default (shell history). Resolution order: `--auth-env VAR` / `--auth-file PATH` > `MAPI_<PROVIDER>_TOKEN` env > optional keyring > none. `--bearer` / `--api-key NAME` choose between `BearerAuth` and `ApiKeyAuth`.
- `--dry-run` builds the request via the SDK's `RequestBuilder` and prints method, URL, params and headers (secrets redacted) without sending.
- `--validate / --no-validate` maps to `ClientConfig.validate_on_execute`.

Global options (root callback):

| Option | Env var | Meaning |
|---|---|---|
| `--data-dir PATH` | `MAPI_DATA_DIR` | Data directory (arg > env > SDK default) |
| `--base-url URL` | `MAPI_BASE_URL` | Override server URL |
| `--timeout SEC` | `MAPI_TIMEOUT` | Request timeout |
| `--output, -o {auto,json,table,raw}` | `MAPI_OUTPUT` | Renderer |
| `--verbose, -v` (count) / `--quiet, -q` | `MAPI_LOG_LEVEL` | Log level (stderr) |
| `--color {auto,always,never}` / `--no-color` | `NO_COLOR`, `FORCE_COLOR`, `MAPI_COLOR` | Color policy (see section 6.2) |
| `--theme NAME` | `MAPI_THEME` | `auto`, `dark`, `light`, `mono`, or a user theme |
| `--no-interactive` | `MAPI_NO_INTERACTIVE=1` | Never prompt or launch pickers (CI/scripts) |
| `--pager / --no-pager` | `MAPI_PAGER` | Page long output through `less -R` on a TTY |

### 4.2 Tools commands (`mapi tools ...`)

Mirror the pipeline stages so each runs alone or chained:

```
mapi tools fetch     <source> [--provider P] [--out DIR]       # github | postman | url
mapi tools extract   <raw-spec> [--out FILE]                   # raw OpenAPI -> normalized ops
mapi tools convert   <extracted> [--compress/--no-compress]    # -> utilize.json[.zst]
mapi tools populate  [--provider P] [--jobs N] [--force]       # fetch+extract+convert for services.json
mapi tools pipeline  [--from fetch] [--to registry]            # end-to-end, resumable
mapi tools validate  [--provider P]                            # structural validation of the data dir
mapi tools deep-validate [--provider P]                        # openapi-spec-validator pass
mapi tools registry build                                      # regenerate services.json
mapi tools report    [--format md|json|html] [--out FILE]
```

Rules:

- Every command is idempotent with `--dry-run` and `--force`.
- Progress uses `rich.progress` on stderr and turns off when not a TTY.
- `--jobs` for parallelism (default bounded CPU count); fetching reuses the SDK's async transport session.
- `validate` / `deep-validate` exit non-zero on any failure and support `--format json` for CI.
- `--fail-fast / --keep-going` (default keep-going, summary at the end).
- Tools write into an explicit `--data-dir` (the checkout/location of the data), never into the installed SDK package.

---

## 5. Architecture inside the CLI

### 5.1 Lazy composition root

```python
# mapi_cli/context.py
from dataclasses import dataclass
from pathlib import Path
from mapi import Mapi
from mapi.models.config import ClientConfig


@dataclass
class CliContext:
    data_dir: Path | None
    base_url: str | None
    timeout: float
    output: str
    _client: Mapi | None = None

    @property
    def client(self) -> Mapi:  # lazy: --help and completion stay instant
        if self._client is None:
            cfg = ClientConfig(base_url=self.base_url, default_timeout=self.timeout)
            self._client = Mapi(config=cfg, data_dir=self.data_dir)
        return self._client
```

### 5.2 App skeleton

```python
# mapi_cli/app.py
app = typer.Typer(name="mapi", no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(tools_app, name="tools", help="Maintainer tools (fetch, extract, validate...)")

@app.callback()
def root(ctx: typer.Context, data_dir: Path | None = ..., ...):
    configure_logging(verbose, quiet)       # the CLI is an application: it owns logging
    ctx.obj = CliContext(data_dir, base_url, timeout, output)

def main():
    from mapi_cli.errors import run
    run(app)
```

### 5.3 Output layer

- **stdout is data only; stderr is logs, progress, warnings and errors.**
- `auto` mode: table when stdout is a TTY, JSON when piped.
- `MapiResult` renders as its `data`; `--show-meta` emits `{data, metadata}`.
- The `--json` shape is a public contract: snapshot-test it and version it.

### 5.4 Exit codes

| Exit | Meaning | SDK source |
|---|---|---|
| 0 | Success | |
| 1 | Unexpected error | other `Exception` |
| 2 | Usage error | Click/Typer |
| 3 | Not found (provider/api/operation) | `ServiceNotFoundError` |
| 4 | Parameter validation failed | `ValidationError` |
| 5 | Configuration/data problem | `ConfigurationError` |
| 6 | Network/transport error | `TransportError` |
| 7 | HTTP error response (4xx/5xx) | `TransportError` with `http_status` |
| 8 | Rate limited | `RateLimitError` |

Map exceptions to codes in one place (`errors.run`), print a "did you mean ...?" suggestion on not-found (use `difflib` over `discovery` lists), exit 130 on Ctrl-C, and show a traceback only with `MAPI_DEBUG=1`.

### 5.5 Completion

Use Typer's built-in completion plus dynamic completers for provider, api and operation, reading from `client.discovery`. Provider/api completion must only read `services.json` (via a cached names-only index); only operation completion may load service data. Full design, including `key=` parameter completion, descriptions, install flow and speed budget, is in section 6.4.

---

## 6. Polish and UX: pretty, interactive, discoverable

The goal: on a terminal, `mapi` feels like a modern tool (think `gh`, `uv`, `httpie`): colorful, helpful, completable. Piped or in CI, it is plain, stable and scriptable. Everything in this section lives in `ui/`, `interactive/`, `tui/` and `completion.py`; none of it touches SDK logic.

### 6.1 Principles

1. **Pretty on a TTY, plain when piped.** Decorations (colors, boxes, spinners, pagers, prompts) only when the relevant stream is a terminal. Data on stdout stays parseable.
2. **Semantic styles, never raw colors.** Code says `style="method.get"` or `"error"`, never `"green"`. Themes map meaning to color in one place.
3. **Never color alone.** Status, method and severity also carry a word or symbol (`GET`, `✓`, `✗`), so output works in mono, for color-blind users, and in logs.
4. **Fast.** `mapi --help`, `mapi providers` and every completion return in well under 150 ms. Heavy imports (`rich.table`, `prompt_toolkit`, `textual`, `niquests`) happen inside the command that needs them.
5. **Discoverable.** Every screen tells you the next step (a hint line, an example, a "did you mean").

### 6.2 Color and theme system

`ui/theme.py` defines one Rich `Theme` of semantic styles:

| Semantic style | Used for | Dark default |
|---|---|---|
| `brand` | logo, headings, prompts | bold cyan |
| `provider` / `api` / `op` | names in tables and paths | magenta / blue / green |
| `method.get` `.post` `.put` `.patch` `.delete` `.other` | HTTP method badges | green / blue / yellow / yellow / red / dim |
| `status.ok` `.redirect` `.client_err` `.server_err` | HTTP status badges | green / cyan / yellow / red |
| `param.required` / `param.optional` | parameter names | bold yellow / default |
| `deprecated` | deprecated operations | dim + strike |
| `hint` / `muted` | tips, secondary text | italic dim cyan / dim |
| `error` / `warning` / `success` | messages | bold red / yellow / green |
| `json.key` `.string` `.number` `.null` | body highlighting (via Pygments theme) | blue / green / magenta / dim |

Rules:

- **Policy precedence** (highest first): `--color always|never` / `--no-color` > `MAPI_COLOR` > `NO_COLOR` (off) > `FORCE_COLOR` (on) > auto (on if the stream is a TTY and `TERM != dumb`). Rich already honors `NO_COLOR`/`FORCE_COLOR`; wrap it so the flag and `MAPI_COLOR` win.
- **Per-stream decisions.** stdout and stderr each have their own `Console`. `mapi providers > out.txt` is plain; error panels on stderr stay colored if stderr is still a TTY.
- **Graceful degradation.** Truecolor, 256-color, then 16-color, then mono. Use named/ANSI colors in the default themes so they follow the user's terminal palette; reserve hex colors for an opt-in `--theme rich` style.
- **Light and dark.** `--theme auto` picks dark unless `COLORFGBG` says otherwise; `light` uses darker hues with no `dim` on important text; `mono` uses only bold/underline/reverse.
- **User themes.** `~/.config/mapi/themes/<name>.toml` (via `platformdirs`) maps semantic names to Rich style strings; `mapi config set theme <name>`. Unknown keys are ignored, missing keys fall back to the default theme.
- **ASCII fallback.** `MAPI_ASCII=1` (or a non-UTF-8 locale) swaps box-drawing and symbols (`✓ ✗ ▶ …`) for `[ok] [x] > ...` and uses `box.ASCII` tables.

```python
# mapi_cli/ui/console.py
from rich.console import Console
from mapi_cli.ui.theme import build_theme


def make_consoles(color: str, theme: str):
    force = {"always": True, "never": False}.get(color)  # None = auto
    kw = dict(theme=build_theme(theme), force_terminal=force, no_color=(color == "never"))
    return Console(**kw), Console(stderr=True, **kw)  # out, err
```

### 6.3 Rendering recipes

| Command | Pretty (TTY) | Piped / `-o json` |
|---|---|---|
| `providers` | Table: name, API count, op count, primary auth badge, popularity; sorted by popularity; footer "N providers, try `mapi apis <provider>`" | JSON array of objects |
| `apis <provider>` | Table: api, sources, ops, auth types, popularity | JSON array |
| `ops <provider> <api>` | Table: colored **METHOD** badge, operation id, path, summary; deprecated rows dimmed with strike; `--filter` highlights matches | JSON array |
| `describe` | Card (Rich `Panel` + `Group`): title, `METHOD /path`, servers, description (Markdown), parameter table (name, `in`, type, required, enum/default, description), "Example" line with a ready-to-run `mapi call ...` | JSON of the `Operation` |
| `call` | Status line `200 OK  ·  184 ms  ·  github.repos.get-repo`, then syntax-highlighted JSON body in a panel; long bodies go through the pager | Raw `data` JSON only (metadata with `--show-meta`) |
| `call --dry-run` | Request panel: method, URL, query, headers (redacted), body | JSON of the `RequestConfig` with secrets redacted |
| `search` | Ranked results with the matched substring highlighted, grouped by provider | JSON array with scores |
| `doctor` | Checklist with `✓ / ! / ✗` and a one-line fix per failure | JSON `{checks: [...]}` |
| errors | Red panel on stderr: what failed, why, **hint** ("did you mean `get-repo`?", "run `mapi ops github repos`"), exit code | One-line `error: ...` on stderr |

Method badge colors (dark theme): `GET` green, `POST` blue, `PUT`/`PATCH` yellow, `DELETE` red, others dim. Render as fixed-width (`GET   `) so columns line up.

Progress and activity:

- **Spinner** (`console.status`) on stderr for any network call longer than ~150 ms; cleared before output is printed.
- **Progress bars** for `mapi tools populate/pipeline` with per-provider tasks, ETA, and a live "ok / skipped / failed" counter. Disabled when stderr is not a TTY; then emit one log line per item.
- **Pager** for output longer than the terminal height when on a TTY (`console.pager(styles=True)`, which keeps colors via `less -R`). `--no-pager` or `MAPI_PAGER=0` turns it off; never page when piped.
- **Large JSON** bodies: pretty-print with a sensible width, collapse long arrays in table mode with "... N more (use `-o json` for all)".

Help screens (Typer + Rich):

- Group options into `rich_help_panel`s ("Connection", "Output", "Auth", "Debug") and commands into panels ("Discover", "Call", "Interactive", "Maintainers").
- Add an `epilog` with 2 to 3 real examples per command; keep examples copy-pasteable.
- `mapi` with no arguments prints a short, colorful overview (logo optional, quick-start examples, the next 3 commands to try), not a bare usage error.

### 6.4 Autocomplete

What should complete:

| Position | Completes | Source | Cost |
|---|---|---|---|
| `mapi <TAB>` | commands, subcommands | Typer | free |
| `<provider>` | provider names, with the API count as help text | `services.json` index | cached index |
| `<api>` | APIs of the chosen provider, help text: op count | cached index | cached index |
| `<operation>` | operation ids of that API, help text: `METHOD path summary` | loads that one service | one file read, then LRU |
| `--source` | sources available for that API | cached index | cached index |
| `call ... <TAB>` | parameter names as `key=`, required first; then enum values after `key=` | the operation's parameters | already loaded for operation |
| `--theme`, `--output`, `--color` | fixed choices | static | free |
| `config get/set <TAB>` | config keys | static | free |
| `replay <TAB>` | recent history ids | history file | tiny file read |

Mechanics:

- **Shells:** bash, zsh, fish and PowerShell via Typer. Provide `mapi completion install` that detects `$SHELL`, writes the completion script to the right place (or prints exactly what to add), and tells the user to restart the shell; `mapi completion status` verifies it. Do not silently edit rc files without telling the user which file and why.
- **Descriptions in menus.** Return `(value, help)` tuples from completers so zsh and fish show the description beside each candidate.
- **Speed budget.** A completion call must not import `niquests`, `rich` or `msgspec` decoding of service data when avoidable. Build a small names-only index (`providers -> apis -> ops count`) in the cache dir (`platformdirs.user_cache_dir("mapi")`), keyed on the registry's `generated_at` and `mapi` version, and rebuild it lazily when stale. Operation completion reads just that service through the SDK cache.
- **Silent.** Completers never print, log or prompt. Any exception returns an empty list.
- **Context aware.** Completers read earlier arguments from `ctx.params` / `ctx.args` so `mapi ops github <TAB>` completes GitHub's APIs only, and `--data-dir` given earlier on the line is respected.
- **Typo help.** When a user runs an unknown provider/api/operation, the error shows the 3 closest names (`difflib.get_close_matches`) and the exact command to list valid ones.

```python
# mapi_cli/completion.py  (sketch)
def complete_provider(ctx: typer.Context, incomplete: str):
    try:
        idx = load_index(ctx)  # cached names-only index
        return [(p, f"{n} APIs") for p, n in idx.providers() if p.startswith(incomplete)]
    except Exception:
        return []  # completion must never break the shell


def complete_operation(ctx: typer.Context, incomplete: str):
    try:
        provider, api = ctx.params.get("provider"), ctx.params.get("api")
        ops = ctx.obj.client.discovery.list_operations(provider, api)
        return [(o, "") for o in ops if o.startswith(incomplete)]
    except Exception:
        return []
```

### 6.5 Interactive mode (`[interactive]` extra)

All interactive features are gated: they run only when **stdin and stdout are TTYs**, `--no-interactive` is not set, and `CI` is not set. Otherwise the command fails with a normal usage error that names the missing argument.

- **Fuzzy picker.** `mapi call` (or `mapi describe`) with no arguments opens a type-to-filter list: provider, then API, then operation, with a live preview pane showing `METHOD path` and the summary. Esc cancels with exit 130 and no traceback.
- **Parameter prompts.** After choosing an operation, prompt only for missing required parameters, built from the operation schema: label with type and description, default shown, enum values as a menu, booleans as yes/no, inline validation errors from the SDK's `ParameterValidator` (re-prompt instead of failing). Optional parameters are skipped unless the user opts in ("Add optional parameters? [y/N]").
- **Final command echo.** After prompts, print the equivalent non-interactive command (`mapi call github repos get-repo owner=psf repo=requests`) in a dim hint line so users learn the scriptable form. Offer to run it.
- **Confirmations.** For `DELETE` and other destructive methods, require confirmation on a TTY (`--yes` to skip; in non-interactive mode, require `--yes` or fail with a clear message).
- **Secrets.** Prompt for tokens with hidden input; never echo or write them to history.

**`mapi shell` (REPL):**

- Persistent history (`~/.local/state/mapi/history`), up-arrow search, and fish-style auto-suggest from history.
- Same completers as the shell, shown as a popup menu with descriptions.
- Context navigation: `use github repos` sets the prompt to `mapi github/repos ›`, after which `get-repo owner=psf repo=requests` works without repeating the path; `..` goes up; `ls` lists what is at the current level.
- Bottom toolbar: current context, data dir/version, last status code and latency.
- Built-ins: `help`, `?op` (describe), `history`, `set`/`unset` for session defaults (e.g. `set output json`), `exit` / Ctrl-D.
- Every command inside the shell reuses the same command functions and renderers as the CLI. The shell only parses lines and keeps context; it adds no logic.

### 6.6 Full-screen explorer: `mapi browse` (`[tui]` extra, later phase)

A Textual app for exploring and trying APIs:

- Left: provider and API tree with a filter box (`/` to search). Middle: operations list with colored method badges. Right: description and parameter table.
- "Try it": a form generated from the parameter schema (required fields marked, enums as selects), `Enter`/`Ctrl-R` to send, response pane below with status, latency and highlighted JSON, `y` to copy the equivalent `mapi call` command (or `--curl`).
- Keys: arrows/vim keys, `Tab` between panes, `?` for a help overlay, `q` to quit. Theme follows `--theme`.
- It is an optional extra and a later phase: ship the CLI, completion and `mapi shell` first.

### 6.7 Quality-of-life features

- **`--curl`** on `call`/`--dry-run`: print the equivalent `curl` command (secrets replaced by `$MAPI_TOKEN`-style placeholders). Great for sharing and debugging.
- **`--save FILE` / `-O`**: write the response body to a file; progress bar for large downloads.
- **History and replay:** each `call` appends a redacted record (id, time, command, status, latency) to the history file; `mapi history` shows a table, `mapi replay last --edit` opens the command in `$EDITOR` before re-running. History can be disabled in config (`history = false`).
- **Aliases:** `mapi config set alias.gh "call github"` so `mapi gh repos get-repo ...` works; aliases appear in completion.
- **Defaults per provider:** config can set a default `--base-url`, auth env var and output format per provider.
- **Update notice (opt-in):** at most once a day, only on a TTY, only for interactive commands, cached, and fully disabled by `MAPI_NO_UPDATE_CHECK=1` or non-TTY. Off by default if you want zero network surprises.
- **First-run tip:** one friendly line suggesting `mapi completion install`, shown once (flag stored in the state dir), never in non-TTY.
- **Friendly versions:** `mapi --version` shows CLI, SDK, data version, Python, and the data directory in a small panel; `-o json` for scripts.

### 6.8 Accessibility and robustness

- Honor `NO_COLOR`, `FORCE_COLOR`, `TERM=dumb`, and non-TTY streams everywhere; provide `--plain` (no color, no boxes, no spinners, ASCII only) as a single switch for screen readers and logs.
- Adapt to terminal width: tables switch to a vertical key/value layout under ~60 columns; truncate with `…` and offer `--wide` / `-o json` for full data.
- Windows: works in Windows Terminal and PowerShell; legacy console falls back to ASCII and 16 colors. Test paths with spaces and non-ASCII characters.
- Ctrl-C always exits cleanly (130) without a traceback; spinners and live displays are restored on exit (use context managers/`finally`).
- Pretty tracebacks (`rich.traceback.install`) only with `MAPI_DEBUG=1`; normal users see the friendly error panel.

### 6.9 Testing the UI

- **Visual snapshots:** render with `Console(record=True, width=100, force_terminal=True)` and compare `export_text()` (plain) and `export_svg()` or `export_html()` (styled) against stored snapshots for `providers`, `ops`, `describe`, the response panel and the error panel. Fix width and theme in tests so snapshots are stable.
- **No-color/piped tests:** assert there are no ANSI escapes (`\x1b[`) on stdout when piped or `NO_COLOR` is set, and that stdout is valid JSON in `-o json`.
- **Completion tests:** invoke Typer's completion protocol in-process (set the `_MAPI_COMPLETE` env var and capture output) and assert candidates and help text for provider/api/operation/`key=` positions; assert the completion path imports neither `niquests` nor `prompt_toolkit` (check `sys.modules`).
- **Interactive tests:** drive pickers, prompts and the REPL in a pseudo-terminal with `pexpect` (or `prompt_toolkit`'s pipe input) in a small, separate test group; keep them out of the default fast run if flaky.
- **Performance test:** assert `mapi --help`, `mapi providers` and a completion call stay under the time budget on the fixture data.

---

## 7. Staying compatible with the SDK

Because the CLI is a separate project, the SDK contract is the main risk.

1. **Adapter layer.** Keep all `mapi` imports in a small number of places (`context.py`, `errors.py`, and the tools' writers). If the SDK renames something, one file changes.
2. **Data-format contract.** The tools write `data/<provider>/<source>/<api>/utilize.json[.zst]` and `services.json`; the SDK's `DiskLoader` reads them. This is the most fragile boundary.
   - Write using the SDK's own models (`ServiceData`, `ServiceRegistry`) and `msgspec` so the format is defined once, in `mapi`.
   - Check `format_version` on write and refuse to run against an SDK that doesn't support it.
   - Add `tests/contract/`: run tools on fixture specs, then load the result with the SDK's `DiskLoader` and compare.
3. **Version pinning.** Compatible range on `mapi` in `pyproject.toml`; CI matrix runs the lowest supported and latest `mapi`, plus `mapi` main as an allowed-to-fail job to catch upcoming breaks.
4. **Import boundary.** Add an `import-linter` contract forbidding imports of private `mapi` modules (anything with a leading underscore or not in `mapi.__all__`).
5. **Release order.** Ship the SDK change first, then bump the CLI's lower bound. Document in the changelog which CLI versions need which SDK versions.

---

## 8. Moving the extractors in

| From (mapigen) | To (`mapi_cli/tools/`) |
|---|---|
| `metadata/fetcher.py` | `fetch/` (split per source) |
| `metadata/extractor.py` | `extract/extractor.py` |
| `metadata/converter.py` | `convert/converter.py` |
| `tools/populate_data.py` | `populate.py` |
| `tools/pipeline.py` | `pipeline.py` |
| `tools/validate_data.py`, `deep_validate.py` | `validate.py`, `deep_validate.py` |
| `tools/reporting.py` | `reporting.py` |
| `services/registry_service.py` | `registry_builder.py` |

Guidelines:

- **Pure core, CLI edge.** Each stage exposes `run(inputs, *, options) -> Result`; the Typer command only parses options and prints a summary. Stages are testable without Typer and composable in `pipeline`.
- **Reuse the SDK transport** (`NiquestsTransport` or an injected `Transport`) for fetching instead of adding a second HTTP stack; tests inject a fake.
- **Resumable state.** `state.py` records source URL, ETag/commit SHA and content hash so `populate` / `pipeline` skip unchanged specs.
- **Drop `memory_manager.py`** as decided in the refactor plan; replace `tqdm` with Rich progress.
- **Where the data lives is decided elsewhere.** The tools take `--data-dir`; whether that directory is a data repo, a `mapi-data` package source, or a cache is a separate decision (section 13).

---

## 9. Testing

```
tests/
├── cli/        # providers/apis/ops/describe/call/search/doctor via CliRunner
├── tools/      # each stage on fixture specs; pipeline resume behavior
├── contract/   # tools output -> SDK DiskLoader round-trip
└── fixtures/
```

- `CliRunner(mix_stderr=False)` to assert stdout and stderr separately.
- Inject a `Mapi` built with a fake `Transport` into `CliContext`; no network in tests.
- Snapshot-test `--json` output for `providers`, `ops`, `describe`.
- Test every exit code in the table.
- CI smoke test on the built wheel: `uv build && uv tool install dist/*.whl && mapi --version && mapi doctor`.
- Startup budget: keep `mapi --help` fast (check with `python -X importtime`); import heavy modules inside command functions.

---

## 10. Release and CI

- GitHub Actions: lint (ruff), types (pyright), tests on 3.10–3.13, contract tests against min/latest/main `mapi`, build wheel, smoke-test install.
- Publish with trusted publishing (PyPI OIDC) on tags; version from git tags (`hatch-vcs`).
- `mapi doctor` and `mapi --version` print CLI version, SDK version, data/registry version and `generated_at`, and Python version.
- Changelog notes the supported `mapi` range for each release.

---

## 11. Implementation order

1. Create the `mapi-cli` repo with `pyproject.toml`, uv, CI, and a `mapi --version` stub.
2. **UI foundation first** (cheap now, painful to retrofit): `ui/theme.py`, `ui/console.py` (color policy, per-stream consoles), `output.py` render layer, `errors.py` with the error panel, `--plain`/`--color`/`--theme`, ASCII fallback.
3. Runtime read-only commands: `providers`, `apis`, `ops`, `describe` (needs only `DiscoveryService`) using the table/panel builders, plus exit codes and Rich help panels with examples.
4. **Completion:** names-only cached index, dynamic completers for provider/api/operation/`--source`, `mapi completion install|status`, speed and import-purity tests.
5. `call` with `--dry-run`, `--curl`, auth options, `--data`, response panel, spinner and pager; then `search` and `doctor`.
6. **Interactive extra:** fuzzy picker, parameter prompts, destructive-call confirmation, `history` / `replay`, user config and themes.
7. `mapi shell` REPL.
8. Move `validate` and `registry build` into `tools/` first (smallest; they exercise the loader and the contract tests), with progress UI.
9. Move `fetch -> extract -> convert`, then `populate` and `pipeline`, then `report`.
10. Later: `mapi browse` TUI, aliases and per-provider defaults, opt-in update notice, docs generated from Typer, first PyPI release.

---

## 12. Checklist

- [ ] `mapi-cli` depends on `mapi` only through its public API
- [ ] `mapi` has no CLI dependency or entry point
- [ ] Commands are thin (under ~30 lines); logic lives in the SDK or tool stages
- [ ] stdout is data only; logs and progress go to stderr
- [ ] `--json` shape documented and snapshot-tested
- [ ] Exit-code table implemented and tested
- [ ] Secrets never accepted as plain args by default; redacted in `--dry-run` and logs
- [ ] `mapi --help` and completion don't load service data or open sessions
- [ ] Contract test: tools write, SDK reads
- [ ] CI covers min, latest and main versions of `mapi`
- [ ] Optional `[tools]`, `[interactive]` and `[tui]` extras give a friendly install hint when missing
- [ ] Entry point verified from a built wheel in CI
- [ ] All colors go through semantic theme styles; no hard-coded color names in commands
- [ ] Color policy honors `--color`, `MAPI_COLOR`, `NO_COLOR`, `FORCE_COLOR` and per-stream TTY detection
- [ ] No ANSI escapes on piped stdout; `-o json` is always valid JSON
- [ ] Meaning is never color-only (methods and statuses also carry text or symbols); `--plain` and `MAPI_ASCII` work
- [ ] Shell completion works in bash, zsh, fish and PowerShell, with descriptions, and `mapi completion install|status` is tested
- [ ] Completion is silent, fast, and imports neither `niquests` nor `prompt_toolkit`
- [ ] Interactive features run only on a TTY and never in CI or with `--no-interactive`
- [ ] Destructive calls (e.g. `DELETE`) need confirmation or `--yes`
- [ ] History and logs never contain secrets
- [ ] Visual snapshot tests (fixed width and theme) cover providers, ops, describe, response and error panels

---

## 13. Open decisions

1. **One executable or two.** This guide uses `mapi` plus `mapi tools ...` in a single package, with heavy deps behind the `[tools]` extra. If you'd rather keep maintainer commands completely out of end-user installs, split `mapi-tools` into a third project.
2. **Typer vs cyclopts.** Pick before writing commands; switching later touches every file.
3. **Data distribution.** Bundled with the SDK, a separate `mapi-data` package, or downloaded on first use. This decides what `--data-dir` means for the tools and what `doctor` reports.
4. **`call` syntax.** `key=value` as primary; whether to also accept `--param key=value` for scripts that want unambiguous parsing.
5. **Credential storage.** Env vars only, or optional `keyring` with a `mapi auth login/logout` group.
6. **Interactive stack.** `prompt_toolkit` for pickers and the REPL (recommended, since it also powers completion menus) vs lighter `questionary`/`InquirerPy`; Textual only for the later `mapi browse`.
7. **Interactive extra vs default.** Keep `[interactive]` optional (smaller install, faster startup) or make it a default dependency so every user gets pickers out of the box.
8. **Theme scope.** Ship only `auto/dark/light/mono`, or also user-defined theme files from day one.
9. **Update checks and telemetry.** Recommendation: no telemetry; update notice opt-in and off in non-TTY.
