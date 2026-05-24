# Design: Analytics module structure

Analytics use generic HTTP routes but keep per-analytic implementation in layer-local modules.

Related docs:

- [Adding a turn analytic](design-adding-a-turn-analytic.md) -- step-by-step checklist for new analytics
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
- Turn loading stays in `TurnLoadService`; analytics dispatch in `GameService.get_turn_analytics(...)`.
- Per-analytic response construction lives under `packages/api/api/analytics/`:
  - `base_map.py`
  - `scores.py`
  - `connections.py`
  - `registry.py` -- `TURN_ANALYTICS` id-to-handler map

`get_turn_analytic(...)` loads `TurnInfo`, builds `TurnAnalyticsOptions`, and delegates to the registry.

**Core registry shape:** a flat `TURN_ANALYTICS` dict (id → handler). Core does not use BFF-style descriptors -- it only computes from `TurnInfo`. Catalog metadata and response shaping stay in BFF. The parity test in `test_analytics_registry.py` keeps Core ids aligned with BFF `REGISTERED_ANALYTICS`.

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
| `id`, `name`, `supports_table`, `supports_map`, `type` | Catalog entry (`type` is `base` or `selectable`) |
| `get_table` | Optional handler: Core fetch + BFF table shaping |
| `get_map` | Optional handler: Core fetch + BFF map shaping (receives `ConnectionsMapQuery`; ignore when unused) |
| `map_diagnostic_values` | Optional hook for request diagnostics on map GETs |
| `map_timing_section` | Diagnostics timing label (default `turn_analytics_from_core`) |

Adding a new analytic to the BFF requires:

1. Create `bff/analytics/<id>.py` with handlers and `DESCRIPTOR`.
2. Append `module.DESCRIPTOR` to `REGISTERED_ANALYTICS` in `registry.py`.

Dispatch is descriptor-driven -- no per-id `if/elif` chains in `registry.py`.

Unknown analytic ids and unsupported view modes return **422** (`BFFValidationError`).

**Registry parity:** `packages/bff/tests/test_analytics_registry.py` asserts BFF descriptor ids match Core `TURN_ANALYTICS` keys. Keep both registries in sync when adding or removing analytics.

### Map route query params (intentional gap)

`GET /bff/analytics/{analytic_id}/map` is a **single shared route** that always accepts Connections query params (`warpSpeed`, `flareMode`, `flareDepth`, etc.) and builds a `ConnectionsMapQuery` for every map GET. Analytics that do not use them (e.g. **base-map**) receive the query object but ignore it in `get_map`.

This is deliberate for now: one route, one OpenAPI shape, Connections works without router branching. Unused params on other analytics are harmless.

**Re-examine when adding a second map analytic with its own query contract** -- especially if param names would clash or OpenAPI would misdocument what each analytic accepts.

**Possible future direction (not implemented):** descriptor-driven query parsing -- e.g. each `AnalyticDescriptor` declares whether it uses map query params (and optionally a parser type); the router only binds/forwards params when declared. Alternatively, analytic-specific map sub-routes if contracts diverge sharply. Until then, new parametric map analytics follow the Connections pattern: extend the shared `ConnectionsMapQuery` / router params only when wire names are shared; otherwise trigger this re-examination.

## Registration touch points (target model)

Adding a **turn analytic** intentionally touches **two** registration points:

1. **Core** -- module + one line in `TURN_ANALYTICS`
2. **BFF** -- module + one line in `REGISTERED_ANALYTICS`

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
