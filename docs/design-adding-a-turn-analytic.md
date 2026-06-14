# Adding a turn analytic

Step-by-step guide for registering a new **turn analytic** in Planets Console. Read [design-analytics-structure.md](design-analytics-structure.md) first for layer roles and the BFF descriptor model. Cross-analytic queries: [design-analytic-exports.md](design-analytic-exports.md).

**Prerequisites:** the analytic computes from **TurnInfo** for a game id, **perspective**, and turn. The SPA must wait for **turn ensure** before fetching analytic data (see [design-frontend-and-backend-state.md](design-frontend-and-backend-state.md)).

**Worked example (map-only, layered UI, persisted toggles):** [design-stellar-cartography-analytic.md](design-stellar-cartography-analytic.md). Map appearance: [design-stellar-cartography-map-rendering.md](design-stellar-cartography-map-rendering.md).

**Domain + inference rules (homeworld locator):** [design-homeworld-locator-analytic.md](design-homeworld-locator-analytic.md) -- **required reading** for issues #33--#37 (Starmap settings, baseline/evidence signals, confidence tiers, layout constraints).

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
ANALYTIC_ID = "my-analytic"

def get_my_analytic(turn: TurnInfo, options: TurnAnalyticsOptions) -> dict:
    ...
    return {"analyticId": ANALYTIC_ID, ...}

REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=TurnAnalyticCatalogEntry(
        id=ANALYTIC_ID,
        name="My Analytic",
        supports_table=True,
        supports_map=False,
        type="selectable",
    ),
    handler=handler_from_turn_and_options(get_my_analytic),
)
```

Guidelines:

- Input is always `TurnInfo` + `TurnAnalyticsOptions` (see `api/analytics/options.py`) on the domain function; wire it with `handler_from_turn_and_options` (or `handler_from_turn` when options are unused). Handlers receive **`AnalyticComputeContext`** (`turn`, `options`, and later `query`) at runtime.
- Return a JSON-serializable dict with domain field names. BFF reshapes for the SPA if needed.
- Reuse **game concepts** from `api/concepts/` rather than duplicating rules.
- **Race-specific** mechanics (`raceid`, per-race caps, settings keyed to one race) go in **`api/concepts/races.py`** only -- do not add new race constants inside `api/analytics/<id>/`. See [design-analytics-structure.md](design-analytics-structure.md) (race-specific rules).
- Attach **request diagnostics** at meaningful boundaries (`diagnostics.child(...)`) when work is non-trivial.

### 2.2 Register in Core

Append the module's `REGISTRATION` to `TURN_ANALYTIC_REGISTRATIONS` in `packages/api/api/analytics/registrations.py`:

```python
from api.analytics.my_analytic import REGISTRATION as MY_ANALYTIC_REGISTRATION

TURN_ANALYTIC_REGISTRATIONS: tuple[TurnAnalyticRegistration, ...] = (
    ...
    MY_ANALYTIC_REGISTRATION,
)
```

`TURN_ANALYTIC_CATALOG` and `TURN_ANALYTICS` are derived from that tuple at import; a missing or extra registration raises `RuntimeError` on startup.

### 2.3 Core -- exports (required)

Every turn analytic registers an export catalog (may be **empty**). See [design-analytic-exports.md](design-analytic-exports.md) for the full mechanism.

Add `packages/api/api/analytics/<id>/exports.py` (or `exports.py` beside a single-file analytic):

```python
EXPORT_VALUE_SCHEMA = {
    "type": "object",
    "properties": {
        "meta": { "type": "object", "properties": { "searchStatus": { "enum": [...] } } },
        # … branches this analytic exposes
    },
}

PATH_PREFIX_SCOPE_RULES = [
    # e.g. {"prefix": "$.solution", "requires": ["player_id"]},
]

def materialize_export_tree(scope, ctx) -> dict:
    ...

EXPORT_CATALOG = {
    "schema": EXPORT_VALUE_SCHEMA,
    "path_prefix_scope_rules": PATH_PREFIX_SCOPE_RULES,
    "materialize": materialize_export_tree,
}
```

Register in `packages/api/api/analytics/exports/registry.py`. Import-time validation: every `TURN_ANALYTIC_CATALOG` id has an entry (use `EmptyExportCatalog` when nothing is queryable yet).

Guidelines:

- **One schema tree** per analytic; scope is on the query, not separate root shapes.
- **JSONPath** selectors (`$.solution.ships[0]`); document array ordering in the catalog.
- **Concept-shim:** delegate to `api/concepts/` inside `materialize_export_tree` (Connections pattern).
- Table/map handlers should call the same materializer (or shared helpers) where the tree is the source of truth.
- Consumers query only via **`AnalyticQueryContext`** passed into handlers -- not direct imports of other analytics.
- **`$.meta.searchStatus`:** use generic lifecycle values (`not_started`, `in_progress`, `paused`, `stopped`, `complete`); warn downstream consumers when not `complete`.

Empty catalog example:

```python
from api.analytics.exports.empty import EMPTY_EXPORT_CATALOG
EXPORT_CATALOG = EMPTY_EXPORT_CATALOG
```

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

Skip this section when generic shells suffice (Scores is the reference).

Add `src/analytics/<id>/` when you need any of:

| Need | Where |
|------|-------|
| Sidebar controls beyond enable/disable | `AnalyticsBar` delegates to `<Id>MapTile` or similar |
| Map GET query params not covered by generic fetch | Query builder in `src/analytics/<id>/api.ts`; wire names match BFF |
| Custom React Query keys | `MainArea.tsx` map fetch loop (see below) |
| Map layer merge rules | `src/analytics/mapLayers.ts` |

Generic paths (no frontend module required):

- **Table:** `MainArea` calls `fetchAnalyticTable(analyticId, analyticScope)`.
- **Map (no extra params):** `fetchAnalyticMap(analyticId, analyticScope)`.

After BFF response shape changes, regenerate OpenAPI types (`make generate` or `cd packages/frontend && npm run generate:api`). Produces per-router `schema-<slice>.ts` files; see [ADR 0003](adr/0003-frontend-bff-contract-codegen.md).

(Requires a running server with BFF OpenAPI endpoint.)

### 4.1 Map fetch orchestration (current vs future)

**Current design:** `MainArea` uses one generic map-fetch path for all map analytics except **Connections**, which has a dedicated branch for:

- React Query keys that include sidebar params (warp speed, flare mode, etc.)
- Re-fetch when those params change
- Wiring `fetchAnalyticMap('connections', scope, params)` via `src/analytics/connections/api.ts`

For a **new map analytic with no query params**, no `MainArea` edit is required -- the generic path is enough (same as base-map-style overlays).

For a **new map analytic with query params or custom cache behaviour**, the current process is:

1. Add query helpers under `src/analytics/<id>/`.
2. Add a **new `if (analyticId === '<id>')` branch** in `MainArea.tsx` (mirror Connections).

**Stop and reconsider architecture** if you are about to add a second branch of this kind, or if Connections and the new analytic share substantial fetch/key logic. Repeated `MainArea` special cases mean the shell owns analytic-specific orchestration that should move out.

**Possible future direction (not implemented):** extract a map-fetch plugin surface, e.g.:

| Piece | Responsibility |
|-------|----------------|
| `src/analytics/<id>/mapFetch.ts` | `mapQueryKey(scope, params)`, `fetchMap(scope, params)` |
| `src/analytics/mapFetchRegistry.ts` | `Record<analyticId, MapFetchPlugin \| undefined>` -- absent entry means generic fetch |
| `MainArea.tsx` | Looks up plugin by id; no per-analytic `if/elif` |

That would align frontend orchestration with the BFF **Analytic descriptor** model: one module per analytic, one registration line, generic dispatch in the shell. Until that refactor, treat each Connections-like analytic as a documented exception and track how many exist.

**Re-examination triggers** -- schedule or do the generalization work when any of these become true:

- Two or more map analytics with configurable query params
- A third distinct pattern in `MainArea` map fetch (beyond generic + Connections)
- Shared query-key or param-forwarding logic copied between analytic modules
- Sidebar tile + map fetch + merge rules for one analytic span four or more files with duplicated wiring

When triggered, prefer a small registry refactor over accumulating `MainArea` branches. Update this section and [design-analytics-structure.md](design-analytics-structure.md) when the plugin model is adopted.

### 4.2 Frontend checklist (when this section applies)

- [ ] Query wire names match BFF and `api/transport/` (if params cross layers)
- [ ] Map fetch uses generic path unless query params or custom keys are required
- [ ] If adding a `MainArea` branch: note it in the PR and confirm re-examination triggers above are not met
- [ ] If re-examination triggers **are** met: discuss map-fetch plugin refactor before adding another branch

---

## 5. End-to-end checklist

Use this before opening a PR:

- [ ] **Catalog:** `TurnAnalyticCatalogEntry` in `TURN_ANALYTIC_CATALOG`
- [ ] **Core:** module + `_HANDLERS_BY_ID` entry + unit tests
- [ ] **Core exports:** `exports.py` + export registry entry (empty allowed) + export tests when non-empty
- [ ] **Core:** router query params and `TurnAnalyticsOptions` (if applicable)
- [ ] **BFF:** module with `from_catalog_entry` descriptor + `_BFF_DESCRIPTORS_BY_ID` entry
- [ ] **BFF:** unit/integration tests for dispatch and HTTP shape
- [ ] **Frontend:** only if generic shells insufficient; query wire names aligned with BFF
- [ ] **Frontend:** if adding a `MainArea` map-fetch branch, confirm [§4.1 re-examination triggers](#41-map-fetch-orchestration-current-vs-future) are not met
- [ ] **Docs:** row in `design-analytics-structure.md` quick-reference table
- [ ] **`make test`** passes (lint + all package tests)
- [ ] Manual smoke: enable analytic in shell, confirm tabular and/or map output after turn ensure

---

## 6. Common mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Export registry missing for catalog id | Startup `RuntimeError` | Add `exports.py` (or `EMPTY_EXPORT_CATALOG`) + registry entry |
| Core handler registered, BFF descriptor missing | Startup `RuntimeError` or 422 on BFF GET | Add catalog entry + BFF module + `_BFF_DESCRIPTORS_BY_ID` |
| BFF lists analytic, Core handler missing | 422 from Core when BFF forwards | Add Core registry entry |
| `supportsMap: true` but no `get_map` | Registry validation test fails | Set handler on descriptor |
| Frontend query param names drift from BFF | Silent wrong results or ignored params | Share wire names via `api/transport/` |
| Second Connections-style `MainArea` branch | Shell accumulates analytic-specific fetch logic | See [§4.1 re-examination triggers](#41-map-fetch-orchestration-current-vs-future); generalize map fetch instead |
| New map analytic needs non-Connections query params | Shared map route would accept misleading or clashing params | See [map route query params](design-analytics-structure.md#map-route-query-params-intentional-gap); descriptor-driven parsing or split routes |
| Fetch before turn ensure | Empty/error flicker | Gate on `turnDataReady` in shell (see design-frontend-and-backend-state.md) |
| Map overlay without base-map | No planet nodes to attach to | Map mode always fetches `base-map` first |

---

## 7. Example walkthroughs

| Analytic | Kind | Read |
|----------|------|------|
| Scores | Table-only, generic frontend | `api/analytics/scores.py`, `bff/analytics/scores.py` |
| base-map | Always-on map layer | `api/analytics/base_map.py`, `bff/analytics/base_map.py` |
| Connections | Map overlay + query params + frontend controls | [design-connections-analytic.md](design-connections-analytic.md) |
