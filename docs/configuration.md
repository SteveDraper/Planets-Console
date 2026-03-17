# Backend configuration

The backend process (API + BFF) uses an **amalgamated config** with sub-configs for the server process, Core API, and BFF. A default file is searched for automatically; any part of the config can be overridden from the command line.

## Default config file

- **Filename:** `.config.yaml`
- **Search order:** The process looks for `.config.yaml` in the current working directory, then in each parent directory (up to 10 levels). The first file found is used as the base config.
- **If none is found:** The base config is empty; defaults come from the `server`, `api`, and `bff` config dataclasses (see below).

The repository includes a default `.config.yaml` at the project root so that running the server from the repo uses it unless overrides are given.

## Config structure

The amalgamated config has three top-level keys:

| Section  | Purpose |
|----------|--------|
| `server` | Bind host and port |
| `api`    | Core REST API (storage backend, asset path) |
| `bff`    | BFF layer (CORS origins, etc.) |

### `server` (process)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `127.0.0.1` | Bind host for the HTTP server. |
| `port` | integer | 8000 | Bind port for the HTTP server. |

### `api` (Core API)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `storage_backend` | string | `ephemeral` | Backend identifier. Currently only `ephemeral` is supported. |
| `storage_asset_path` | string or null | null | Path to a JSON file used to initialise the in-memory store. If null or omitted, the store starts empty. If set, the path must exist and be a file (otherwise startup fails). |
| `include_dummy_data` | bool | false | When true, seed the store with sample game data (game 628580, turn 111) on startup. For development and testing only. |

### `bff` (BFF)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cors_origins` | list of strings | `["http://localhost:5173", "http://127.0.0.1:5173"]` | Allowed CORS origins for the SPA. |

Example `.config.yaml`:

```yaml
server:
  host: "127.0.0.1"
  port: 8000

api:
  storage_backend: ephemeral
  storage_asset_path: null   # store starts empty
  include_dummy_data: true   # seed sample game data (set false for production)

bff:
  cors_origins:
    - http://localhost:5173
    - http://127.0.0.1:5173
```

## Command-line overrides

The server accepts one or more **`--config`** (or **`-c`**) options. Each value is an override spec. Specs are applied in order after loading the base config (from `.config.yaml` or from a full replacement; see below).

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
- The CLI uses `server.host` and `server.port` for `uvicorn.run(host=..., port=...)`. The Core API uses `api` config for storage (e.g. `get_storage()` reads `storage_backend` and `storage_asset_path`). The BFF uses `bff` config (e.g. CORS middleware uses `cors_origins`).
- Implementation lives in: `packages/server/server/config.py` (loading, override parsing, and `ServerConfig`), `packages/api/api/config.py` (API sub-config), `packages/bff/bff/config.py` (BFF sub-config).

## Unit tests

The config override system and CLI usage are covered by unit tests under `packages/server/tests/`. Run them with `make test_server` or as part of `make test`.

### Config loading and override parsing (`test_config.py`)

- **Override spec parsing (`_parse_override_spec`):** Full replace `@path`; leaf literal `key=value`; substructure from file `key=@path`; invalid spec (no `=`) raises `ValueError`.
- **Literal parsing (`_parse_literal`):** Boolean (`true`/`false`/`yes`/`no`); integer and float; string (including paths).
- **Override application (`_apply_override`):** Leaf literal updates a value; leaf override on a nested key raises `ValueError`; full-replace key `@` raises; substructure from file loads YAML and merges.
- **Load config (`load_config`):** With `default_config_path` to a fixture YAML, returns `RootConfig` with expected `server`, `api`, and `bff` values; leaf overrides (`server.port=9000`, `api.storage_asset_path=...`) apply correctly; full replace (`@file`) uses the given file; substructure override (`bff=@file`) merges the file into that section; with no config file (and `_find_default_config` returning `None`), uses internal defaults; later overrides win when keys repeat; full-replace “last wins” when multiple `@file` specs are given.

### CLI (`test_cli.py`)

- **Help:** `serve --help` includes the `--config` / `-c` option and override syntax.
- **Config subcommand:** `serve config` prints the configuration and override-syntax documentation (e.g. “Configuration”, “Override syntax”, `server.host`, `server.port`).
- **Config option wiring:** Invoking `serve --config server.port=9000` calls `load_config(override_specs=["server.port=9000"])` and passes the loaded `root.server.host` and `root.server.port` into `uvicorn.run`.
