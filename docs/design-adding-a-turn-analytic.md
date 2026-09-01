# Adding a turn analytic

Step-by-step guide for registering a new **turn analytic** in Planets Console. Read [design-analytics-structure.md](design-analytics-structure.md) first for layer roles and the BFF descriptor model. Cross-analytic queries: [design-analytic-exports.md](design-analytic-exports.md).

**Prerequisites:** the analytic computes from **TurnInfo** for a game id, **perspective**, and turn. The SPA must wait for **turn ensure** before fetching analytic data (see [design-frontend-and-backend-state.md](design-frontend-and-backend-state.md)).

**Worked example (map-only, layered UI, persisted toggles):** [design-stellar-cartography-analytic.md](design-stellar-cartography-analytic.md). Map appearance: [design-stellar-cartography-map-rendering.md](design-stellar-cartography-map-rendering.md).

**Domain + inference rules (homeworld locator):** [design-homeworld-locator-analytic.md](design-homeworld-locator-analytic.md) -- **required reading** for issues #33--#37 (Starmap settings, baseline/evidence signals, confidence tiers, layout constraints).

**Domain + inference rules (fleet):** [design-fleet-analytic.md](design-fleet-analytic.md) -- fleet ledger, constraints, persistence, scores coupling, map/table contracts.

---

## 1. Choose an `analytic_id`

- Lowercase, hyphen-separated wire id (e.g. `scores`, `base-map`, `connections`).
- Same string in Core registry, BFF descriptor, and BFF HTTP paths (`/bff/analytics/{analytic_id}/...`).
- Add a row to the quick-reference table in `design-analytics-structure.md` when the analytic ships.

---

## 2. Core -- computation (required)

### 2.1 Create the analytic module

Add `packages/api/api/analytics/<id>.py`:

```python
from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.registration import TurnAnalyticRegistration

ANALYTIC_ID = "my-analytic"

def compute_my_analytic(ctx: AnalyticComputeContext) -> dict:
    turn = ctx.turn
    options = ctx.options
    ...
    return {"analyticId": ANALYTIC_ID, ...}

REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_my_analytic,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),  # or EXPORT_CATALOG from exports.py
)
```

Guidelines:

- Each registration's `compute` is a `TurnAnalyticHandler`: `Callable[[AnalyticComputeContext], dict]`. Read `ctx.turn`, `ctx.options`, `ctx.diagnostics`, and (when wired) `ctx.query` from the carrier; do not reach through `ctx.options.diagnostics`.
- Return a JSON-serializable dict with domain field names. BFF reshapes for the SPA if needed.
- Reuse **game concepts** from `api/concepts/` rather than duplicating rules.
- **Race-specific** mechanics (`raceid`, per-race caps, settings keyed to one race) go in **`api/concepts/races.py`** only -- do not add new race constants inside `api/analytics/<id>/`. See [design-analytics-structure.md](design-analytics-structure.md) (race-specific rules).
- Attach **request diagnostics** at meaningful boundaries (`ctx.diagnostics.child(...)`) when work is non-trivial.

### 2.1a Add catalog metadata

In `packages/api/api/analytics/catalog.py`, append a `TurnAnalyticCatalogEntry` to the `TURN_ANALYTIC_CATALOG` tuple (id, name, `supports_table`, `supports_map`, `type`). This is the single source of truth for the analytic's identity, metadata, and order; the registration references it via `catalog_entry(ANALYTIC_ID)`.

### 2.2 Register in Core

Append the module's `REGISTRATION` to `TURN_ANALYTIC_REGISTRATIONS` in `packages/api/api/analytics/registry.py`:

```python
from api.analytics.my_analytic import REGISTRATION as MY_ANALYTIC_REGISTRATION

TURN_ANALYTIC_REGISTRATIONS: tuple[TurnAnalyticRegistration, ...] = (
    ...
    MY_ANALYTIC_REGISTRATION,
)
```

`TURN_ANALYTICS` is derived from that tuple at import and the registrations are aligned to `TURN_ANALYTIC_CATALOG` (the same helper the BFF uses); a missing or extra registration raises `RuntimeError` on startup.

### 2.3 Core -- exports (required)

Every turn analytic wires an export catalog on its **`TurnAnalyticRegistration`** (may be **empty**). See [design-analytic-exports.md](design-analytic-exports.md) for the full mechanism (issue **#93**).

**`EXPORT_REGISTRY`** in `exports/registry.py` is derived automatically from `TURN_ANALYTIC_REGISTRATIONS` at import. **Do not** register catalogs manually in `exports/registry.py`.

**Empty catalog** (nothing queryable yet) -- set inline on registration; no stub `exports.py` required:

```python
from api.analytics.exports.empty import empty_export_catalog_for

REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_my_analytic,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),
)
```

**Non-empty catalog** -- add `packages/api/api/analytics/<id>/exports.py`, build an **`AnalyticExportCatalog`**, and pass it on registration:

```python
from api.analytics.export_types import EnsureDependency, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog

EXPORT_VALUE_SCHEMA = {
    "type": "object",
    "properties": {
        "meta": { "type": "object", "properties": { "searchStatus": { "enum": [...] } } },
        # … branches this analytic exposes
    },
}

PATH_PREFIX_SCOPE_RULES = (
    # e.g. PathPrefixScopeRule(prefix="$.solutions", requires=("player_id",)),
)

ENSURE_DEPENDENCIES = (
    # Provider-declared upstream ensures (probe + ensure unwind follow these edges).
    # e.g. EnsureDependency(analytic_id="fleet", turn_delta=-1, player_id="same"),
)

def ensure_export(ctx, scope) -> bool:
    """Idempotent: persist/scheduler attach for this scope before materialize.

    Return True when the scope needs no further ensure work (already satisfied or
    terminal with no persistable row). ctx.query marks the scope ensured only on True.
    Expensive solve work (e.g. scores CP-SAT) must not run on the ensure/materialize
    thread -- schedule a RowRun so orchestrator ``tier_solve`` owns it.
    """
    ...

def materialize_export_tree(ctx, scope) -> dict:
    ...

EXPORT_CATALOG = AnalyticExportCatalog(
    analytic_id=ANALYTIC_ID,
    value_schema=EXPORT_VALUE_SCHEMA,
    path_prefix_scope_rules=PATH_PREFIX_SCOPE_RULES,
    ensure_dependencies=ENSURE_DEPENDENCIES,
    ensure_export=ensure_export,
    materialize_export_tree=materialize_export_tree,
)
```

Then in `<id>.py`:

```python
from api.analytics.my_analytic.exports import EXPORT_CATALOG

REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_my_analytic,
    export_catalog=EXPORT_CATALOG,
)
```

Import-time validation (`exports/registry.py`):

1. Every `TURN_ANALYTIC_CATALOG` id must have a matching `export_catalog` on its registration.
2. For **non-empty** catalogs, each `ensure_dependencies` target must exist in `EXPORT_REGISTRY` and must itself be **non-empty**. Miswired edges raise `RuntimeError` at import, not on first `ctx.query`. See [Ensure dependency target validation](design-analytic-exports.md#ensure-dependency-target-validation) in the exports design doc.

Guidelines:

- **One schema tree** per analytic; scope is on the query, not separate root shapes.
- **JSONPath** selectors (`$.solutions[0]`); document array ordering in the catalog.
- **`ensure_dependencies`:** declared by the **provider** (upstream requirements). Each target must be a registered analytic with a **non-empty** export catalog. Do not reference analytics that are not yet in `TURN_ANALYTIC_CATALOG`, and do not point at `empty_export_catalog_for(...)` placeholders -- both fail import-time validation. When the upstream analytic ships, wire a real `AnalyticExportCatalog` on its registration first, then add the dependency edge.
- **`ctx.query(...)`** runs ensure then materialize (not read-only). Large missing-step probes use BFF **export ensure orchestration** (background job), not blocking HTTP.
- **Concept-shim:** delegate to `api/concepts/` inside `materialize_export_tree` (Connections pattern).
- Table/map handlers should call the same materializer (or shared helpers) where the tree is the source of truth.
- Consumers query only via **`AnalyticQueryContext`** passed into handlers -- not direct imports of other analytics.
- **`$.meta.searchStatus`:** use generic lifecycle values (`not_started`, `in_progress`, `paused`, `stopped`, `complete`); warn downstream consumers when not `complete`.

### 2.4 Core tests

Add `packages/api/tests/test_<id>_analytic.py` (or extend an existing file):

- Handler behaviour against fixture `TurnInfo` (storage assets or builders).
- Export materializer + JSONPath golden paths when `exports.py` is non-empty.
- Unknown `analytic_id` still raises `ValidationError` via registry (existing test pattern).

### 2.5 Core router query params (if needed)

If the analytic accepts query knobs (like Connections):

- Extend `TurnAnalyticsOptions` and parsing in `api/analytics/options.py`.
- Expose matching query params on `GET .../analytics/{analytic_id}` in `api/routers/games.py`.
- Prefer shared wire names in `api/transport/` when params cross layers (see `connections_options.py`).

---

## 3. BFF -- catalog and shaping (required)

### 3.1 Create the BFF module with a descriptor

Add `packages/bff/bff/analytics/<id>.py` exporting **`DESCRIPTOR`**.

**Table-only example (Scores pattern):**

```python
from api.analytics.catalog import catalog_entry
from bff.analytics.descriptor import AnalyticDescriptor

ANALYTIC_ID = "my-table-analytic"

def get_table(scope, load_core, diagnostics) -> dict:
    core_data = load_core_analytic(load_core, scope, ANALYTIC_ID, diagnostics=diagnostics)
    return shape_for_spa(core_data)

DESCRIPTOR = AnalyticDescriptor.from_catalog_entry(
    catalog_entry(ANALYTIC_ID),
    get_table=get_table,
)
```

**Map overlay example (base-map pattern -- no query params):**

```python
def get_map(scope, _query, load_core, diagnostics) -> dict:
    return load_core_analytic(load_core, scope, ANALYTIC_ID, diagnostics=diagnostics)

DESCRIPTOR = AnalyticDescriptor.from_catalog_entry(
    catalog_entry(ANALYTIC_ID),
    get_map=get_map,
)
```

**Map with query params (Connections pattern):**

- The shared map route in `bff/routers/analytics.py` already parses Connections wire params for **all** map GETs; handlers that need them use the `ConnectionsMapQuery` argument, others ignore it (see [design-analytics-structure.md § Map route query params](design-analytics-structure.md#map-route-query-params-intentional-gap)).
- Forward kwargs to Core via `load_core_analytic(..., **kwargs)`.
- Set `map_diagnostic_values` on the descriptor for the Diagnostics modal.
- Document wire names in `api/transport/` and mirror in frontend query helpers.

If a new analytic needs **different** query params (not an extension of the Connections contract), stop and read the re-examination triggers in [design-analytics-structure.md](design-analytics-structure.md#map-route-query-params-intentional-gap) before adding params to the shared route.

### 3.2 Register in BFF

In `packages/bff/bff/analytics/registry.py`, add the module descriptor to `_BFF_DESCRIPTORS_BY_ID`:

```python
_BFF_DESCRIPTORS_BY_ID: dict[str, AnalyticDescriptor] = {
    ...
    my_analytic.DESCRIPTOR.id: my_analytic.DESCRIPTOR,
}
```

`REGISTERED_ANALYTICS` is ordered from `TURN_ANALYTIC_CATALOG` at import. Catalog metadata comes from `from_catalog_entry`; handlers stay in the BFF module.

### 3.3 BFF tests

Add or extend tests under `packages/bff/tests/`:

| Test | Purpose |
|------|---------|
| `test_analytics_registry.py` | Dispatch forwards to Core with correct kwargs; metadata flags match handlers |
| `test_analytics.py` | HTTP route returns expected SPA shape (integration with TestClient) |

Registry tests should mock `load_core` rather than hitting storage when testing shaping only.

Registry tests assert each layer follows `TURN_ANALYTIC_CATALOG` order; catalog/handler/descriptor mismatch fails at import or in those tests.

### 3.4 Verify catalog

`GET /bff/analytics` must list the new entry with correct `supportsTable`, `supportsMap`, and `type`:

- **`base`** -- always fetched in map mode; omitted from sidebar (see base-map).
- **`selectable`** -- user enables/disables in the analytics bar.

---

## 4. Frontend (optional)

Skip this section when **generic shells** suffice: sidebar checkbox, generic MainArea table body, no extra GET query params, no GameInfo inactivity, no table stream.

Custom Shell chrome is a sparse **shell analytic registration** ([ADR 0026](adr/0026-shell-analytic-registration.md)), keyed by **turn analytic catalog** id. Add `src/analytics/<id>/shell.tsx` exporting a `ShellAnalyticRegistration` and one entry in `shellAnalyticRegistry.ts`. **Do not** add analytic-id branches in `App.tsx`, `AnalyticsBar.tsx`, `MainArea.tsx`, or generic `fetchAnalyticTable` / `fetchAnalyticMap` in `bff.ts`.

An unregistered selectable id is not an error: generic checkbox + generic table.

| Need | Slot |
|------|------|
| Sidebar controls beyond enable/disable | `renderSidebar(ctx)` -- return `null` in a **view mode** that should use the generic checkbox |
| Custom MainArea table body | `TableView` |
| Extra GET query params on generic table/map fetch | Appender in `shellAnalyticQueryParams.ts` (`SHELL_TABLE_QUERY_APPENDERS` / `SHELL_MAP_QUERY_APPENDERS`). The shell registry composes `queryParams` onto the registration. `bff.ts` imports that module so it does not pull React chrome. Do not set `queryParams` on `shell.tsx`. |
| GameInfo inactivity (grey/disable without dropping persisted enablement) | `availability(gameInfo) => string \| null` |
| Table stream | `stream`: `shellLivedStream({ hook, Provider })` (shell-lived) or `{ lifetime: 'tile' }` |

`renderSidebar` receives `ShellAnalyticSidebarContext`: `viewMode`, `catalogItem`, `enabled`, `onToggle`, plus shell-owned `turnDataReady` and `analyticScope` so tiles do not re-derive ensure/scope.

Generic paths (no frontend module required):

- **Table:** `MainArea` uses `TableView` when registered, otherwise `GenericTableTile` calling `fetchAnalyticTable(analyticId, analyticScope)`.
- **Map (no extra params):** `fetchAnalyticMap(analyticId, analyticScope)` via the map fetch/merge registry.

A caller that must **not** pick up store-backed table params (e.g. race/player labels with `includeBuildInference: false`) passes `extraAppend` to `fetchAnalyticTable` and skips the registered appender.

After BFF response shape changes, regenerate OpenAPI types (`make generate` or `cd packages/frontend && npm run generate:api`). Produces per-router `schema-<slice>.ts` files; see [ADR 0003](adr/0003-frontend-bff-contract-codegen.md).

(Requires a running server with BFF OpenAPI endpoint.)

### 4.1 Map fetch vs Shell chrome

These are sibling registries, not one mega plugin table:

| Concern | Owner |
|---------|--------|
| Sidebar, table view, GameInfo availability, stream lifetime | **Shell analytic registration** (`shellAnalyticRegistry.ts`); `queryParams` is composed onto it |
| Extra GET query-string adapters | **`shellAnalyticQueryParams.ts`** (only write site; `bff.ts` imports this module) |
| Map GET query keys, fetch, merge into combined map data | **Map fetch/merge registry** (`mapAnalyticRegistry.ts` + `useMapAnalyticQueries`) |
| Map paint (React Flow node/edge components) | Not a registry slot yet ([#383](https://github.com/SteveDraper/Planets-Console/issues/383)) |

Parametric map knobs (Connections warp/flare) live in an **ephemeral** Zustand store under `src/analytics/connections/` -- not in `App.tsx`, **not persisted**. `buildQuerySpec` and the query-param adapter read `getState()`; `useMapAnalyticQueries` subscribes so query keys update when knobs change. Generic `fetchAnalyticMap` appends the map appender from `shellAnalyticQueryParams.ts`.

Do not add `if (analyticId === ...)` in `MainArea` for map fetch. A new parametric map analytic registers an appender in `shellAnalyticQueryParams.ts` and, when the query key must include those knobs, a map-registry `buildQuerySpec`.

**Re-examination triggers** -- map **paint** (#383) or a deeper map-registry slot, not a new MainArea fetch branch:

- A second map analytic whose paint cannot live in `MapGraph` without an id switch
- Query-key or param-forwarding logic copied between analytic modules instead of `queryParams` / `buildQuerySpec`
- Sidebar tile + map fetch + merge + paint for one analytic spanning duplicated wiring

### 4.2 Frontend checklist (when this section applies)

- [ ] Query wire names match BFF and `api/transport/` (if params cross layers)
- [ ] Custom chrome is a `ShellAnalyticChrome` plus one registry line; extra GET params go in `shellAnalyticQueryParams.ts`; `App` / `AnalyticsBar` / `MainArea` / generic fetch stay id-switch free
- [ ] Unregistered selectable ids fall back to generic checkbox + generic table (not an error)
- [ ] Map fetch/merge stays on `mapAnalyticRegistry`; map paint remains [#383](https://github.com/SteveDraper/Planets-Console/issues/383)
- [ ] Connections-style knobs: analytic-owned ephemeral store, not `App` `useState` and not persisted unless the product asks for it

---

## 5. End-to-end checklist

Use this before opening a PR:

- [ ] **Core:** module with `TurnAnalyticRegistration` (`catalog_entry` + ctx-first `compute` handler) appended to `TURN_ANALYTIC_REGISTRATIONS` in `registry.py` + unit tests
- [ ] **Catalog:** `TurnAnalyticCatalogEntry` in `TURN_ANALYTIC_CATALOG` (`catalog.py`)
- [ ] **Core exports:** `export_catalog` on `TurnAnalyticRegistration` (`empty_export_catalog_for` or `exports.py` + `AnalyticExportCatalog`; empty allowed) + export tests when non-empty; non-empty `ensure_dependencies` targets must be registered non-empty catalogs (validated at import)
- [ ] **Core:** router query params and `TurnAnalyticsOptions` (if applicable)
- [ ] **BFF:** module with `from_catalog_entry` descriptor + `_BFF_DESCRIPTORS_BY_ID` entry
- [ ] **BFF:** unit/integration tests for dispatch and HTTP shape
- [ ] **Frontend:** only if generic shells insufficient; register Shell chrome ([§4](#4-frontend-optional)); query wire names aligned with BFF
- [ ] **Frontend:** do not add analytic-id branches in `App` / `AnalyticsBar` / `MainArea` / generic table/map fetch; confirm [§4.1](#41-map-fetch-vs-shell-chrome) if map paint or a second parametric map contract is involved
- [ ] **Docs:** row in `design-analytics-structure.md` quick-reference table
- [ ] **`make test`** passes (lint + all package tests)
- [ ] Manual smoke: enable analytic in shell, confirm tabular and/or map output after turn ensure

---

## 6. Common mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Export catalog missing for catalog id | Startup `RuntimeError` | Set `export_catalog=empty_export_catalog_for(ANALYTIC_ID)` on registration, or wire `EXPORT_CATALOG` from `exports.py` |
| `ensure_dependencies` references missing or empty catalog | Startup `RuntimeError` (`missing analytic_id` / `empty catalog`) | Register the upstream analytic with a non-empty `export_catalog` before adding the edge; see [Ensure dependency target validation](design-analytic-exports.md#ensure-dependency-target-validation) |
| Core handler registered, BFF descriptor missing | Startup `RuntimeError` or 422 on BFF GET | Add BFF module + `_BFF_DESCRIPTORS_BY_ID` entry |
| BFF lists analytic, Core handler missing | 422 from Core when BFF forwards | Append `REGISTRATION` to `TURN_ANALYTIC_REGISTRATIONS` in `registry.py` |
| `supportsMap: true` but no `get_map` | Registry validation test fails | Set handler on descriptor |
| Frontend query param names drift from BFF | Silent wrong results or ignored params | Share wire names via `api/transport/` |
| Analytic-id branch in `App` / `AnalyticsBar` / `MainArea` / generic fetch | Shell accumulates chrome that belongs on the registration | Register `renderSidebar` / `TableView` / an appender in `shellAnalyticQueryParams.ts` / `availability` / `stream` instead |
| New map analytic needs non-Connections query params | Shared map route would accept misleading or clashing params | See [map route query params](design-analytics-structure.md#map-route-query-params-intentional-gap); descriptor-driven parsing or split routes |
| Fetch before turn ensure | Empty/error flicker | Gate on `turnDataReady` in shell (see design-frontend-and-backend-state.md) |
| Map overlay without base-map | No planet nodes to attach to | Map mode always fetches `base-map` first |

---

## 7. Example walkthroughs

| Analytic | Kind | Read |
|----------|------|------|
| Scores | Table-only, custom sidebar + tile-lived inference | `api/analytics/scores.py`, `bff/analytics/scores.py`, `src/analytics/scores/shell.tsx` |
| base-map | Always-on map layer | `api/analytics/base_map.py`, `bff/analytics/base_map.py` |
| Connections | Map overlay + query params + frontend controls | [design-connections-analytic.md](design-connections-analytic.md) |
