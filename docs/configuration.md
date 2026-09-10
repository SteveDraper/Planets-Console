# Backend configuration

The backend process (API + BFF) uses an **amalgamated config** with sub-configs for the server process, Core API, and BFF. A default file is searched for automatically; any part of the config can be overridden from the command line.

## Default config file

- **Filename:** `.config.yaml`
- **Search order:** The process looks for `.config.yaml` in the current working directory, then in each parent directory (up to 10 levels). The first file found is used as the base config.
- **If none is found:** The base config is empty; defaults come from the `server`, `api`, and `bff` config dataclasses (see below).

The repository includes a default `.config.yaml` at the project root so that running the server from the repo uses it unless overrides are given. Packaged launch (`serve --packaged` / `load_packaged_config()`) skips this search.

## Config structure

The amalgamated config has three top-level keys:

| Section  | Purpose |
|----------|--------|
| `server` | Bind host and port |
| `api`    | Core REST API (storage backend, asset path) |
| `bff`    | BFF layer (CORS origins, SPA bootstrap options) |

### `server` (process)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `127.0.0.1` | Bind host for the HTTP server. |
| `port` | integer | 8000 | Bind port for the HTTP server. |

### `api` (Core API)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `storage_backend` | string | `ephemeral` | Backend identifier: `ephemeral` (in-memory) or `file` (durable JSON under `storage_root`). See [ADR 0001](adr/0001-breakpoint-file-storage.md). |
| `storage_root` | string | `./.data` | Root directory for the file backend. Ignored when `storage_backend` is `ephemeral`. Created on first write if missing. Gitignored in the repo. **Console package** launch does not use this default; see [Packaged console data directory](#packaged-console-data-directory). |
| `storage_asset_path` | string or null | null | **Ephemeral only:** path to a JSON file used to initialise the in-memory store. If null, the store starts empty. If set, the path must exist and be a file (otherwise startup fails). |
| `include_dummy_data` | bool | false | When true, seed sample game data (game 628580, turn 111) on startup **only for paths that are not already present** (idempotent skip-if-present). For development and testing only. |
| `credentials_obfuscation_secret` | string or null | null | Optional secret mixed into HKDF when wrapping **account API keys** at rest. When null, derivation uses the OS native machine id only. See [ADR 0007](adr/0007-account-api-key-and-silent-login.md) and [design-account-api-key-and-silent-login.md](design-account-api-key-and-silent-login.md). |
| `homeworld_locator` | object | see below | Server-side **homeworld locator config** (YAML, not SPA UI). Nested fields below. |
| `homeworld_locator.min_baseline_clans` | integer | `10000` | Floor clan count for **homeworld baseline profile** matching (below default `homeworldclans`, above casual colonies). |
| `homeworld_locator.origin_distance_evidence_lambda` | float | `0.95` | Absolute-turn soft-evidence update weight base λ: on nonempty turn `t`, `E = (E + w e_t) / (1 + w)` with `w = λ^t`. Empty turns leave `E` unchanged. Valid range `(0, 1]`. Default keeps useful mid-game updates (~T4-T20 standard / ~T5-T30 epic) while late updates stay weak. |
| `homeworld_locator.layout_prior_solver` | string | `anneal` | Layout-prior discrete solver: `anneal` (greedy + seeded SA + sample-grid refine, production default) or `enumerate` (`EnumeratingLayoutPriorSolver`, ≤4 nearest-mid product; emergency / regression). Switching solver is an ops concern and typically pairs with understanding `LAYOUT_PRIOR_ALGORITHM_VERSION` cache invalidation. |
| `homeworld_locator.layout_prior_budget_ms` | integer | `1000` | Wall-clock SA budget (ms) for `anneal` via `DeadlineStopGate`. Enumerate ignores this. **Default rationale:** enough wall-clock for budget-progress cooling to escape early local minima on dense circular maps (663307-class T10/T11); not a CI wall-clock assert. Lower only after measuring anneal quality vs latency on target hardware. |
| `homeworld_locator.cluster_fow_density_credit_multiplier` | float | `1.0` | Multiplier on **homeworld cluster constraint** FoW density credit: effective credit is `density × unobserved_band_area × multiplier`, then capped per band at the remaining map-gen deficit. Valid range `>= 0`. Absent YAML key uses `1.0`. |
| `homeworld_locator.use_player_homeworld_sidebar` | bool | `false` | When true, Core suppresses homeworld sector `regionOverlays` emission end-to-end (`build_homeworld_sector_overlays_for_turn` returns empty even when a viewpoint pin would otherwise make emission eligible). Circular/epic games then behave like no-sector games for map wedges. When sector wedges are absent (this flag or natural ineligibility), Core may still emit planet-centered `homeworld-planet-envelope` overlays for sidebar-qualifying candidates; FE **Show overlays** gates paint. Default false keeps legacy sector wedges. |

### `bff` (BFF)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cors_origins` | list of strings | `["http://localhost:5173", "http://127.0.0.1:5173"]` | Allowed CORS origins for the SPA. |
| `show_initial_game` | string, int, or null | null | When set to a non-empty string (numeric ids may be written unquoted in YAML), the SPA loads that **stored** game id without login via `GET /bff/shell/bootstrap` and stored game info. Requires the game (and turn) to exist in storage; pair with `api.include_dummy_data` for the sample game in dev. See [Frontend and backend state](design-frontend-and-backend-state.md). |

Example `.config.yaml`:

```yaml
server:
  host: "127.0.0.1"
  port: 8000

api:
  storage_backend: file
  storage_root: ./.data      # durable store (gitignored); use ephemeral in CI/tests
  storage_asset_path: null   # ephemeral only; ignored for file backend
  include_dummy_data: true   # seed sample paths if missing (set false for production)
  homeworld_locator:
    min_baseline_clans: 10000
    origin_distance_evidence_lambda: 0.95
    layout_prior_solver: anneal
    layout_prior_budget_ms: 1000
    cluster_fow_density_credit_multiplier: 1.0
    use_player_homeworld_sidebar: false

bff:
  cors_origins:
    - http://localhost:5173
    - http://127.0.0.1:5173
  # show_initial_game: "628580"   # optional SPA auto-load of a stored game id (dev)
```

## Command-line overrides

The server accepts one or more **`--config`** (or **`-c`**) options. Each value is an override spec. Specs are applied in order after loading the base config (from `.config.yaml` or from a full replacement; see below). **`--packaged`** skips `.config.yaml` discovery and loads via `load_packaged_config()`; extra `--config` specs still apply after the packaged defaults (later wins). `--config` alone is not packaged launch.

### Syntax

1. **Override a leaf value**  
   `--config key.path.to.leaf=<value>`  
   Sets a single field. The target must be a leaf (not a nested object or list); otherwise an error is raised.  
   `<value>` is parsed as a literal: `true`/`false`/`yes`/`no` → boolean; numeric → int/float; otherwise string.  
   Examples:  
   `--config server.port=9000`  
   `--config api.storage_asset_path=/path/to/store.json`

2. **Override a substructure from a file**  
   `--config key.path=@filepath`  
   Replaces (or sets) the config at `key.path` with the contents of the given YAML/JSON file. Use this to override a whole section (e.g. `bff=@bff-override.yaml`).  
   Example:  
   `--config bff=@bff-override.yaml`

3. **Replace the entire config**  
   `--config @filepath`  
   Ignores the default `.config.yaml` and uses the given file as the full config. If multiple `@filepath` specs are given, the last one wins.  
   Example:  
   `--config @production.yaml`

Options can be combined and repeated. Later specs override earlier ones for the same paths.

### Examples

Run with default config (`.config.yaml` from cwd or parents):

```bash
uv run serve
# or: python -m server.cli
```

Packaged console launch (file backend at the OS console data directory; no `.config.yaml` discovery):

```bash
uv run serve --packaged
```

Override bind port or API asset path:

```bash
uv run serve --config server.port=9000
uv run serve --config api.storage_asset_path=/var/data/store.json
```

Override the whole BFF section from a file:

```bash
uv run serve -c bff=@config/bff.yaml
```

Use a completely different config file:

```bash
uv run serve -c @/etc/planets-console/config.yaml
```

Multiple overrides (later wins for overlapping paths):

```bash
uv run serve -c api.storage_asset_path=/data/store.json -c bff=@bff.yaml
```

## How it’s used

- Config is loaded at server startup in the CLI (before uvicorn runs). The amalgamated config is built; then `server` host/port are used for the uvicorn bind, and `api` and `bff` sub-configs are passed into their layers via `set_config()`.
- The CLI uses `server.host` and `server.port` for `uvicorn.run(host=..., port=...)`, and passes `timeout_graceful_shutdown=5` so SIGTERM does not wait forever on NDJSON/MCP streams. That cap applies to every `serve` process, including deploy (`scripts/run_deploy.sh` execs `uv run serve`). The Core API uses `api` config for storage (e.g. `get_storage()` reads `storage_backend`, `storage_root`, and `storage_asset_path`). The BFF uses `bff` config (e.g. CORS middleware uses `cors_origins`).
- Repo `.config.yaml` uses `file` + `storage_root: ./.data` for local dev. Unit tests and CI fixtures set `storage_backend: ephemeral` explicitly. The **console package** does not load that file; see below.
- Implementation lives in: `packages/server/server/config.py` (loading, `load_packaged_config`, override parsing, and `ServerConfig`), `packages/api/api/config.py` (API sub-config), `packages/bff/bff/config.py` (BFF sub-config), `packages/server/server/console_data_directory.py` (OS console data directory Path helper), `packages/server/server/process_host/` (packaged **process host**), `scripts/bundle_console_package.py` (**bundler** collect policy).

## Packaged console data directory

A **console package** process points the **file backend** `storage_root` (and support logs) at the OS per-user **console data directory**, not `./.data` and not a next-to-exe store. Paths are expanded in process (`~` / `%LOCALAPPDATA%`); they are not frozen into YAML at CI time. There is no user-facing config file in this directory in v1. The **installer wrapper** does not write or patch config.

| OS | Console data directory |
|----|------------------------|
| macOS | `~/Library/Application Support/Planets Console/` |
| Windows | `%LOCALAPPDATA%\Planets Console\` |

Repo `.config.yaml` and `ApiConfig.storage_root` stay `./.data` for clone / `run_dev` / `run_deploy`. The code default does not change.

Packaged launch uses one loader: `load_packaged_config()` (CLI: `serve --packaged`). That call sets `api.storage_backend=file` and `api.storage_root` to the console data directory, and does not cwd-walk `.config.yaml`. Extra `--config` specs may still apply after the packaged defaults (later wins). `console_data_directory()` is the Path helper for logs and lock files; it does not load config. The **process host** (`python -m server.process_host`, and the PyInstaller freeze script `process_host_entry.py`) invokes this loader, forces bind `127.0.0.1`, tries port 8000 then the next free port, **listen-then-open**s `http://127.0.0.1:<port>/` after `GET /health`, and writes support logs plus a single-instance lock under this directory. Install-over and uninstall must not delete this directory.

## Process host and bundler

The v1 **console package** is a PyInstaller 6.15+ onedir `--windowed` tree plus a thin **process host** ([ADR 0027](adr/0027-console-package-bundler-and-process-host.md), [ADR 0029](adr/0029-console-package-identity-and-install-over.md)). The SPA stays in the default browser. OS Quit / Cmd-Q / taskbar Close / Alt-F4 set uvicorn `should_exit`. Closing the browser does not stop the server.

Local bundle (requires `cd packages/frontend && npm run build` first):

```bash
make bundle_console_package
```

That runs `scripts/bundle_console_package.py` / `scripts/console_package.spec`. Collect policy ships the prebuilt SPA (`packages/frontend/dist`), runtime `assets/analytics/`, and a one-line version sidecar -- not tests, `scripts/`, `docs/`, or frontend `src/`. Identity: display name **Planets Console**, `CFBundleIdentifier` `com.github.stevedraper.planets-console`, `AppUserModelID` `SteveDraper.PlanetsConsole`, version from root `pyproject.toml` (`0.1.0`, not `0.1`). Installer wrappers and CI are a separate ticket.

## Planets.nu client JavaScript (reference)

The live [planets.nu](https://planets.nu) browser client is not vendored in this repo. Host-aligned tooltip math and map rendering for Stellar Cartography (black holes, ion storms, nebulae, etc.) should be checked against the deployed client bundle when behaviour is unclear.

| Item | Value |
|------|--------|
| **Main bundle URL** | `https://app.planets.nu/1.24/nu.js` (version segment may change; discover it from the `<script src="...">` tag on [planets.nu](https://planets.nu/)) |
| **Fetch decompressed** | `curl -sL --compressed 'https://app.planets.nu/1.24/nu.js' -o /tmp/nu.js` |
| **Search examples** | `rg -i 'getBlackHoleBand|bandradius|coreradius' /tmp/nu.js` |

Useful symbols in the client include `getBlackHoleBand`, `blackholeScan`, `drawBlackHole`, and ship-order checks such as `blackholetoofast` on simulated `turnendpoints`. The help site ([help.planets.nu](https://help.planets.nu/)) documents player-facing rules but usually not field semantics or formulas.

## Unit tests

The config override system and CLI usage are covered by unit tests under `packages/server/tests/`. Run them with `make test_server` or as part of `make test`.

### Config loading and override parsing (`test_config.py`)

- **Override spec parsing (`_parse_override_spec`):** Full replace `@path`; leaf literal `key=value`; substructure from file `key=@path`; invalid spec (no `=`) raises `ValueError`.
- **Literal parsing (`_parse_literal`):** Boolean (`true`/`false`/`yes`/`no`); integer and float; string (including paths).
- **Override application (`_apply_override`):** Leaf literal updates a value; leaf override on a nested key raises `ValueError`; full-replace key `@` raises; substructure from file loads YAML and merges.
- **Load config (`load_config`):** With `default_config_path` to a fixture YAML, returns `RootConfig` with expected `server`, `api`, and `bff` values; leaf overrides (`server.port=9000`, `api.storage_asset_path=...`) apply correctly; full replace (`@file`) uses the given file; substructure override (`bff=@file`) merges the file into that section; with no config file (and `_find_default_config` returning `None`), uses internal defaults; later overrides win when keys repeat; full-replace "last wins" when multiple `@file` specs are given.
- **Packaged load (`load_packaged_config`):** File backend at the console data directory; ignores cwd `.config.yaml` (including `include_dummy_data`); extra override specs apply after packaged defaults; `ApiConfig().storage_root` remains `./.data`. Default `load_config` / `serve` still discover YAML.
- **Console data directory (`test_console_data_directory.py`):** macOS expands `Path.home()`; Windows expands `LOCALAPPDATA`; unsupported OS and missing `LOCALAPPDATA` raise; the Path helper ignores cwd `.config.yaml` / `./.data`; packaged override specs set `api.storage_backend=file` and `api.storage_root`.
- **Process host (`test_process_host_*.py`):** loopback URLs never use `localhost`; port scan skips an occupied preferred port; `GET /health` wait then `webbrowser.open` (no fixed sleep when health is already 200); per-user lock file; frozen `FRONTEND_DIST` from `sys._MEIPASS`; OS Quit sets uvicorn `should_exit`.
- **Launch contract (`test_process_host_launch.py`):** primary start waits for `GET /health` before opening `http://127.0.0.1:<port>/`; health timeout never opens the SPA and names the support log; packaged `storage_root` is the console data directory, not cwd `./.data`; `main()` shows the start-failure dialog and exits 1 (macOS osascript / Windows `MessageBoxW` contracts); missing SPA still writes `logs/process-host.log` under the data directory.
- **Single-instance (`test_process_host_single_instance.py`):** a held lock reopens the existing instance via the port sidecar and does not call `_run_as_primary` (a no-op `_run` fails this pin).
- **Install-over:** Bundler collect policy datas/dests and `console_package.spec` must not place the OS console data directory (`Library/Application Support/{display name}` / `%LOCALAPPDATA%\{display name}`) inside the freeze tree (`test_bundle_console_package.py`). That pin is always on. A secondary scan of explicit Inno paths (`scripts/console_package.iss`, `scripts/console_package.iss.in`) checks `[Files]` / `[UninstallDelete]` (and related sections) when those files are present; if they are absent the scan skips and points at [ADR 0028](adr/0028-console-package-ci-and-installer-wrappers.md) / [issue 429](https://github.com/SteveDraper/Planets-Console/issues/429) (`test_console_package_install_over.py`). Absence is not a pass.
- **Bundler collect policy (`scripts/tests/test_bundle_console_package.py`):** datas are SPA dist + `assets/analytics` + version sidecar; pytest excluded; macOS Info.plist identity and full pyproject version; freeze dests/spec cannot collect the console data directory.

### CLI (`test_cli.py`)

- **Help:** `serve --help` includes the `--config` / `-c` option, `--packaged`, and override syntax.
- **Config subcommand:** `serve config` prints the configuration and override-syntax documentation (e.g. "Configuration", "Override syntax", `server.host`, `server.port`, `--packaged`).
- **Config option wiring:** Invoking `serve --config server.port=9000` calls `load_config(override_specs=["server.port=9000"])` and passes the loaded `root.server.host` and `root.server.port` into `uvicorn.run`. `serve --packaged` calls `load_packaged_config` (discovery stays off); extra `--config` specs are passed through.
