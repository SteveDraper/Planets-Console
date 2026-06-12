# Design: Analytic exports (cross-analytic queries)

Turn analytics can query structured values from one another during Core computation. The mechanism is generic, self-describing (future analytic MCP), and independent of SPA enablement.

Related:

- [CONTEXT.md](../CONTEXT.md) -- glossary (**Analytic export**, **Analytic query context**, …)
- [Analytics module structure](design-analytics-structure.md) -- layer roles and registration
- [Adding a turn analytic](design-adding-a-turn-analytic.md) -- checklist including exports
- [Analytic persistence ADR](adr/0002-analytic-persistence.md) -- persisted slices merged by materializers
- [Military score build inference](design-military-score-build-inference.md) -- `$.solution` branch and streaming
- [Homeworld locator](design-homeworld-locator-analytic.md) -- `$.slots`, `$.evidence` branches

---

## Goals

1. **Generic** -- not tied to one consumer (fleet, exploration route, inference priors).
2. **Uniform access** -- consumers always use **Analytic query context**; providers may delegate to `api/concepts/` internally (**concept-shim analytic**).
3. **Self-describing** -- JSON Schema tree + path-prefix scope rules per analytic; MCP can list schema and query JSONPath + scope later.
4. **Separation** -- analytics stay independent except for explicit queries; game rules remain in **game concepts**.
5. **Scoped** -- turn, **perspective**, **Player** (and options such as connection settings) on the query; ambient defaults from enclosing compute.
6. **Author pattern** -- documented fourth registration touch point beside catalog, Core handler, BFF descriptor.

Non-goals (v1):

- Nested HTTP export routes (in-process only; MCP adapter later).
- Server knowledge of SPA sidebar enablement.
- BFF export endpoints.

---

## Architecture

```
TurnAnalyticService.get_turn_analytics(...)
  builds AnalyticQueryContext (game, turn, perspective, storage, options)
  handler(turn, options, ctx)  -- consumer may ctx.query(...)

export_registry.query(analytic_id, paths, scope, ctx)
  validate scope + path-prefix rules
  memo key: (analytic_id, normalized scope, normalized path set)
  cycle stack: same tuple re-entered -> hard error
  materialize_export_tree(scope, ctx)  -- once per memo key
  JSONPath resolve each path -> path result (value | none | invalid_path)
```

| Piece | Location |
|-------|----------|
| **AnalyticQueryContext** | `api/analytics/export_context.py` |
| **Analytic export registry** | `api/analytics/exports/registry.py` |
| Per-analytic catalog + materializer | `api/analytics/<id>/exports.py` |
| JSONPath engine | shared helper (e.g. `jsonpath-ng`) |

Table/map handlers receive the same `ctx` and should call the same **materialize_export_tree** (or shared helpers) where the export tree is the domain source of truth.

---

## One value schema tree per analytic

Each turn analytic publishes **one** JSON-shaped **Analytic export value schema** (JSON Schema dict in `exports.py`). Structure does **not** vary by scope -- scope selects which slice of the tree is populated.

Example branches (scores):

```json
{
  "meta": {
    "searchStatus": "complete",
    "solutionsHeld": 2,
    "hostTurn": 41
  },
  "solution": {
    "ships": [ { "hullId": 12, "engineId": 5, "…": "…" } ],
    "aggregates": [ { "id": "planet_defense_posts", "count": 3 } ]
  },
  "hullCatalogMask": { "enabledHullIds": [1, 2, 3] }
}
```

Example branches (homeworld locator):

```json
{
  "slots": [ … ],
  "orphans": [ … ],
  "evidence": [ … ]
}
```

**Concept-shim (connections):** tree wraps **Connections engine** output (routes, reachability) with connection **options** taken from scope/options, not duplicated concept logic.

---

## Scope

Scope parameters on each query:

| Param | Typical default | Notes |
|-------|-----------------|-------|
| `game_id` | ambient | Always from context |
| `turn` | ambient shell turn | Parametric for cross-turn chains |
| `perspective` | ambient | Whose stored turns are visible |
| `player_id` | often **required** for scoreboard rows | Does not default from viewpoint name |
| Connection options | from `TurnAnalyticsOptions` | Affect values, not tree shape |

**Path-prefix scope rules** in the catalog (examples):

| Prefix | Rule |
|--------|------|
| `$.solution.*` | requires `player_id` |
| `$.evidence.*` | uses ambient **perspective** only; override forbidden |
| `$.slots.*` | game-global; turn param ignored (baseline resolved inside materializer) |

Missing stored turn at requested **perspective** -> root **`unavailable`: `turn_not_stored`**. Do not silently fall back to ambient turn.

---

## JSONPath queries

- Dialect: **JSONPath** (RFC 9535-ish subset).
- Catalog documents **ordering semantics**: e.g. `$.solution.ships` sorted descending by **inference solution rank weight**, so `$.solution.ships[0]` is the top ship.
- **Batched export query:** one scope binding, multiple paths, e.g. `["$.solution.ships[0]", "$.solution.aggregates"]`.

### Path results (under root `ok`)

| Path result | Meaning |
|-------------|---------|
| **`value`** | Selector matched; JSON payload |
| **`none`** | Valid selector, zero matches (e.g. empty `ships` array -> `$.solution.ships[0]`) |
| **`invalid_path`** | Not allowed by catalog or bad syntax |

Root **`unavailable`** only when the tree cannot be established (turn not stored, persistence missing, invalid scope, etc.).

**Important:** `none` is not bad data. **`complete`** meta + `none` on ships = authoritative "no ship builds in explanation."

### Projections on empty arrays

| Path | `ships: []` |
|------|-------------|
| `$.solution.ships[0]` | **`none`** |
| `$.solution.ships[*].hullId` | **`none`** or **`value: []`** (pick one convention in implementation; document in catalog) |
| `$.solution.ships` | **`value: []`** (branch exists, empty) |

---

## Analytic export meta

`$.meta` carries **materialization lifecycle**, not solver-specific outcomes.

### `searchStatus` (generic)

| Status | Consumer action (e.g. fleet) |
|--------|--------------------------------|
| **`not_started`** | Warn; offer refresh |
| **`in_progress`** | Warn; offer refresh |
| **`paused`** | Warn; offer refresh / resume |
| **`stopped`** | Warn; partial or empty; offer refresh |
| **`complete`** | Trust path results, including **`none`** |

Do **not** warn on **`complete`** even when all solution paths are **`none`**.

Optional: **`solutionsHeld`**, **`hostTurn`**.

Solver-specific outcomes (`no_exact_solution`, band residual, accelerated segments) belong under **`$.solution.diagnostics`** (Scores UI / diagnostics panel), not in **`searchStatus`**.

When prior-turn inference has not run, materialize may trigger or attach to scheduler state; until **`complete`**, fleet treats prior-turn build paths as provisional and surfaces warning chrome.

---

## Cycle detection

Resolution stack key:

```
(analytic_id, normalized scope parameters, normalized path set)
```

- Re-entering the **same** key -> hard error (**`cycle_detected`**, exception).
- Cross-turn chains are **not** cycles: fleet turn *N* -> scores turn *N−1* -> fleet turn *N−1* -> scores turn *N−2* differ in scope.
- Different paths at same scope (`$.solution.ships` vs `$.aggregates`) are **not** a cycle.
- Per-request memoization for identical keys.

---

## Availability vs enablement

Export queries ignore SPA sidebar enablement (**client preference** in localStorage). Enablement controls table/map wire fetches only.

---

## Author registration

Fourth touch point (required; empty catalog allowed):

```
packages/api/api/analytics/<id>/exports.py
```

Each file exports:

| Symbol | Purpose |
|--------|---------|
| **`EXPORT_VALUE_SCHEMA`** | JSON Schema dict for the one tree |
| **`PATH_PREFIX_SCOPE_RULES`** | Scope validation by path prefix |
| **`ORDERING_SEMANTICS`** | Documented array ordering for index paths |
| **`materialize_export_tree(scope, ctx) -> dict`** | Build tree (memoized on ctx) |
| **`EXPORT_CATALOG`** | Bundle registered in **`export_registry.py`** |

Import-time validation: every `TURN_ANALYTIC_CATALOG` id has an export registry entry.

See [Adding a turn analytic -- Core exports](design-adding-a-turn-analytic.md#25-core--exports-required).

---

## Consumer examples

### Exploration route (future)

```python
# Connectivity via concept-shim connections analytic
routes = ctx.query(
    "connections",
    paths=["$.routes"],
    scope={"turn": ambient_turn},
    options=connection_options_from_shell,
)

# Homeworld constraint
hw = ctx.query(
    "homeworld-locator",
    paths=["$.slots[?(@.perspective==3)].planetId"],
    scope={},  # slots branch uses game-global rules
)
```

### Fleet analytic (future)

```python
prior = ctx.query(
    "scores",
    paths=["$.solution.ships[0]", "$.meta.searchStatus"],
    scope={"turn": turn - 1, "player_id": player_id},
)
if prior.paths["$.meta.searchStatus"].value != "complete":
    mark_row_warning("Prior-turn build inference not complete")
```

### Inference priors overlay (#87, future)

```python
composition = ctx.query(
    "fleet-analytic",
    paths=["$.composition.launcherTypes"],
    scope={"turn": turn - 1, "player_id": player_id},
)
# Uses composition only when meta complete; otherwise skip overlay
```

---

## Future MCP

Same materializers and catalog metadata; transport adapter exposes:

- `list_analytic_exports(analytic_id)` -- schema + path-prefix rules
- `query_analytic_export(analytic_id, scope, paths[])` -- same result envelope as in-process

No second implementation path.

---

## Testing

- Unit tests per `exports.py`: materialize against fixtures; JSONPath golden paths; **`none`** vs **`unavailable`**; path-prefix scope rejection.
- Cycle detection: same-scope re-entry throws; cross-turn chain does not.
- Meta: **`not_started`** / **`in_progress`** vs **`complete`** + empty ships.
- Registry: every catalog id has export entry; empty catalog validates.

---

## Open implementation order (suggested)

1. **export_types**, **export_context**, **export_registry** (no consumers).
2. **connections/exports.py** -- concept-shim reference.
3. **homeworld-locator/exports.py** -- persistence merge + path-prefix rules.
4. **scores/exports.py** -- `$.solution`, `$.meta`, ties to inference scheduler/stream state.
5. Wire `ctx` into handlers; document in adding-a-turn-analytic.
6. Fleet / exploration route analytics as consumers (separate features).
