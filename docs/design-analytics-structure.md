# Design: Analytics module structure

Analytics use generic HTTP routes but keep per-analytic implementation in layer-local modules.

Related docs:

- [Adding a turn analytic](design-adding-a-turn-analytic.md) -- step-by-step checklist for new analytics
- [Analytic exports](design-analytic-exports.md) -- cross-analytic queries, JSONPath, materializers
- [Connections analytic](design-connections-analytic.md) -- reference for a map analytic with query params
- [Frontend/backend state](design-frontend-and-backend-state.md) -- shell context and turn ensure gating

## Layer responsibilities

| Layer | Owns | Does not own |
|-------|------|--------------|
| **Core** | Turn-scoped computation from `TurnInfo`; domain response shapes | SPA field names; UI semantics |
| **BFF** | Catalog metadata, response shaping, query forwarding to Core | Business logic; direct storage |
| **Frontend** | Shell orchestration, generic table/map shells, optional per-analytic UI | Core computation; bypassing BFF |

## Core API

- Shared route: `GET /api/v1/games/{game_id}/{perspective}/turns/{turn_number}/analytics/{analytic_id}`.
- Turn loading stays in `TurnLoadService`; analytics dispatch in `TurnAnalyticService.get_turn_analytics(...)` (`packages/api/api/services/turn_analytic_service.py`).
- Per-analytic response construction lives under `packages/api/api/analytics/`:
  - `base_map.py`
  - `scores.py`
  - `connections.py`
  - `stellar_cartography.py`
  - `catalog.py` -- `TurnAnalyticCatalogEntry` and catalog-order alignment helpers
  - `registration.py` -- `TurnAnalyticRegistration`; each analytic module exports `REGISTRATION` with a ctx-first `compute` handler
  - `registry.py` -- `TURN_ANALYTIC_REGISTRATIONS` tuple, derived `TURN_ANALYTIC_CATALOG` and `TURN_ANALYTICS`, `catalog_entry()` lookup, `get_turn_analytic` dispatch
  - `compute_context.py` -- `AnalyticComputeContext` passed into compute handlers (`turn`, `options`, `diagnostics`, and later `query`)

`TurnAnalyticService` loads `TurnInfo`, builds `TurnAnalyticsOptions`, and delegates to `get_turn_analytic(...)` in the registry.

**Shared catalog:** `TURN_ANALYTIC_CATALOG` is derived from Core **turn analytic registration** objects (`TURN_ANALYTIC_REGISTRATIONS`). Each registration bundles catalog metadata, a compute handler, and an export-catalog placeholder. BFF attaches table/map shaping via `AnalyticDescriptor.from_catalog_entry(...)`. `dict_aligned_with_turn_analytic_catalog` / `tuple_aligned_with_turn_analytic_catalog` in `catalog.py` validate BFF descriptor keys against the catalog and preserve catalog order at import. Id or metadata drift raises `RuntimeError` on startup. Core handlers and BFF descriptors remain registered separately (cross-layer); within Core, catalog and handlers are derived from one registration tuple.

### Fixed analytic assets

Some analytics load static YAML or other files from the repo (distinct from `packages/api/api/storage/assets/` seed JSON).

| Rule | Detail |
|------|--------|
| **Directory** | `assets/analytics/{analytic_id}/` at repo root |
| **Id match** | The subdirectory name must equal the analytic's canonical `ANALYTIC_ID` exactly |
| **Resolution** | Subclass `FixedAssetAnalytic` (`api/analytics/fixed_asset_analytic.py`), set `ANALYTIC_ID`, and resolve paths only via `Subclass.assets_dir()` |
| **No ad-hoc strings** | Do not call `analytics_assets_dir(...)` with a string literal outside the `FixedAssetAnalytic` subclass that owns that id |

The asset directory name is always the **catalog turn analytic id** (e.g. `scores`), not a Python subpackage folder name. Features implemented in subpackages (e.g. military score build inference under `api/analytics/military_score_inference/`) load fixed assets via the parent analytic's `FixedAssetAnalytic` subclass (`Scores` in `scores_assets.py`).

Shared helper: `analytics_assets_dir(analytic_name)` in `api/analytics/assets.py` (repo-root walk-up). Only `FixedAssetAnalytic.assets_dir()` should call it for a given analytic.

### Race-specific rules vs analytic modules

Planets.nu mechanics that depend on **`raceid`** belong in **`packages/api/api/concepts/races.py`**, not inside individual analytic packages (for example `military_score_inference/accelerated_start.py`). Analytics import helpers such as `is_evil_empire()` or `evil_empire_free_starbase_fighters_per_host_turn()` from that module.

| Kind of rule | Where it lives |
|--------------|----------------|
| Per-race ids, caps, and formulas | `api/concepts/races.py` |
| Game-wide homeworld / accelerated-start baselines | The module that owns that cross-race behavior (e.g. `accelerated_start.py`) |
| Geometry / reachability shared across features | Other `api/concepts/` modules (`warp_well`, `flare_points`, …) |

See [CONTEXT.md](../CONTEXT.md) (**Race-specific game concept**) and [design-adding-a-turn-analytic.md](design-adding-a-turn-analytic.md) (reuse game concepts).

## BFF

- Shared routes in `packages/bff/bff/routers/analytics.py`.
- Per-analytic modules under `packages/bff/bff/analytics/` export one **`AnalyticDescriptor`** each.
- `registry.py` aggregates descriptors into `REGISTERED_ANALYTICS` and provides generic dispatch (`get_table_response`, `get_map_response`, ...).
- The router stays thin: parse HTTP query params, build diagnostics, call the registry.
- BFF modules must not import Core concept modules directly. HTTP enums and query parsing live in BFF; wire values pass through to Core.

See [Analytic descriptor](#analytic-descriptor-bff) below.

## Frontend

- Generic shell components in `src/components/`.
- Analytic-specific UI, query helpers, and map-layer behavior in `src/analytics/`.
- `AnalyticsBar` renders generic tiles and delegates specialized controls (e.g. Connections) to analytic modules.
- `MainArea` owns tabular/map orchestration; map layer combination is in `src/analytics/mapLayers.ts`.
- The analytics **list** comes from `GET /bff/analytics` -- the SPA does not maintain a parallel registry.

## Analytic descriptor (BFF)

Each BFF analytic module exports a single `DESCRIPTOR: AnalyticDescriptor` (`bff/analytics/descriptor.py`):

| Field | Purpose |
|-------|---------|
| `id`, `name`, `supports_table`, `supports_map`, `type` | From `TurnAnalyticCatalogEntry` via `from_catalog_entry` (`type` is `base` or `selectable`) |
| `get_table` | Optional handler: Core fetch + BFF table shaping |
| `get_map` | Optional handler: Core fetch + BFF map shaping (receives `ConnectionsMapQuery`; ignore when unused) |
| `map_diagnostic_values` | Optional hook for request diagnostics on map GETs |
| `map_timing_section` | Diagnostics timing label (default `turn_analytics_from_core`) |

Adding a new analytic to the BFF requires:

1. Add a Core `TurnAnalyticRegistration` in `api/analytics/<id>.py` and append it to `TURN_ANALYTIC_REGISTRATIONS` in `api/analytics/registry.py` (catalog metadata is on the registration; `TURN_ANALYTIC_CATALOG` is derived).
2. Create `bff/analytics/<id>.py` with handlers and `DESCRIPTOR = AnalyticDescriptor.from_catalog_entry(catalog_entry(...), ...)` (`catalog_entry` from `api.analytics.catalog`).
3. Register the module descriptor in `_BFF_DESCRIPTORS_BY_ID` in `bff/analytics/registry.py`.

Dispatch is descriptor-driven -- no per-id `if/elif` chains in `registry.py`.

Unknown analytic ids and unsupported view modes return **422** (`BFFValidationError`).

### Map route query params (intentional gap)

`GET /bff/analytics/{analytic_id}/map` is a **single shared route** that always accepts Connections query params (`warpSpeed`, `flareMode`, `flareDepth`, etc.) and builds a `ConnectionsMapQuery` for every map GET. Analytics that do not use them (e.g. **base-map**) receive the query object but ignore it in `get_map`.

This is deliberate for now: one route, one OpenAPI shape, Connections works without router branching. Unused params on other analytics are harmless.

**Re-examine when adding a second map analytic with its own query contract** -- especially if param names would clash or OpenAPI would misdocument what each analytic accepts.

**Possible future direction (not implemented):** descriptor-driven query parsing -- e.g. each `AnalyticDescriptor` declares whether it uses map query params (and optionally a parser type); the router only binds/forwards params when declared. Alternatively, analytic-specific map sub-routes if contracts diverge sharply. Until then, new parametric map analytics follow the Connections pattern: extend the shared `ConnectionsMapQuery` / router params only when wire names are shared; otherwise trigger this re-examination.

## Registration touch points

Adding a **turn analytic** touches:

1. **Core registration** -- one `TurnAnalyticRegistration` in the analytic module (`catalog_entry`, ctx-first `compute` handler, `export_catalog` placeholder); append to `TURN_ANALYTIC_REGISTRATIONS` in `registry.py`
2. **Core exports** -- `analytics/<id>/exports.py` + entry in export registry (may be empty until wired in #95); see [design-analytic-exports.md](design-analytic-exports.md)
3. **BFF** -- module with `from_catalog_entry` descriptor + entry in `_BFF_DESCRIPTORS_BY_ID` (`registry.py`)

`TURN_ANALYTIC_CATALOG` and `TURN_ANALYTICS` are derived from registrations at import; do not edit them directly.

Frontend registration is **optional** and only needed when generic shells are insufficient (custom sidebar controls, non-default query keys, bespoke map merge logic). See [design-adding-a-turn-analytic.md](design-adding-a-turn-analytic.md).

### Frontend map fetch (intentional gap)

The SPA does **not** mirror BFF descriptor dispatch for map GETs. Today:

- **Generic path:** `MainArea` calls `fetchAnalyticMap(analyticId, analyticScope)` for map analytics with no extra query params (base-map overlays other than Connections).
- **Connections exception:** `MainArea` branches on `analyticId === 'connections'` for React Query keys, scope + param forwarding, and refetch when sidebar controls change.

This is deliberate for now (one special case, known location). **Re-examine when adding a second map analytic that needs configurable query params or custom cache keys** -- copying the Connections branch in `MainArea` is a signal to generalize instead.

**Possible future direction (not implemented):** a small frontend map-fetch plugin registry under `src/analytics/` where parametric analytics export `mapQueryKey(...)` and `fetchMap(...)`; `MainArea` dispatches by id without growing `if/elif` chains. See [design-adding-a-turn-analytic.md §4](design-adding-a-turn-analytic.md#4-frontend-optional) for the decision checklist when that trigger fires.

## Quick reference: existing analytics

| id | Core module | BFF module | Table | Map | Frontend extras |
|----|-------------|------------|-------|-----|-----------------|
| `base-map` | `base_map.py` | `base_map.py` | no | yes (base layer) | none |
| `scores` | `scores.py` | `scores.py` | yes | no | none |
| `connections` | `connections.py` | `connections.py` | no | yes (overlay) | `src/analytics/connections/` |
| `stellar-cartography` | `stellar_cartography.py` | `stellar_cartography.py` | no | yes (overlay + edges) | `src/analytics/stellar-cartography/` |
