# Design: Analytic exports (cross-analytic queries)

Turn analytics can query structured values from one another during Core computation. The mechanism is generic, self-describing (future analytic MCP), and independent of SPA enablement.

GitHub: issue **#93**.

Related:

- [CONTEXT.md](../CONTEXT.md) -- glossary (**Analytic export**, **Analytic query context**, **Analytic export ensure**, …)
- [Analytics module structure](design-analytics-structure.md) -- layer roles and registration
- [Adding a turn analytic](design-adding-a-turn-analytic.md) -- checklist including exports
- [Analytic persistence ADR](adr/0002-analytic-persistence.md) -- persisted slices merged by materializers
- [Military score build inference](design-military-score-build-inference.md) -- `$.solutions` branch and streaming
- [Homeworld locator](design-homeworld-locator-analytic.md) -- `$.slots`, `$.evidence` branches (exports ship with **#33**, not #93)

---

## Goals

1. **Generic** -- not tied to one consumer (fleet, exploration route, inference priors).
2. **Uniform access** -- consumers always use **Analytic query context**; providers may delegate to `api/concepts/` internally (**concept-shim analytic**).
3. **Self-describing** -- JSON Schema tree + path-prefix scope rules + ensure dependencies per analytic; MCP can list schema and query JSONPath + scope later.
4. **Separation** -- analytics stay independent except for explicit queries; game rules remain in **game concepts**.
5. **Scoped** -- turn, **perspective**, **Player** (and options such as connection settings) on the query; ambient defaults from enclosing compute.
6. **Author pattern** -- documented fourth registration touch point beside catalog, Core handler, BFF descriptor.

Non-goals (v1 / #93):

- Nested HTTP **export query** routes (in-process `ctx.query(...)` only; MCP adapter later).
- Server knowledge of SPA sidebar enablement.
- BFF JSONPath export-query endpoints.
- **Truncated pseudo-baseline unwind** (fast mode with neutral priors at turn *N−K*) -- deferred until **analytic export ensure provenance** and invalidation are designed.
- **Homeworld locator exports** -- ship with homeworld analytic (**#33**).
- **Fleet analytic** and other consumers -- separate features after framework + provider slices land.

---

## Architecture

```
TurnAnalyticService.get_turn_analytics(...)
  builds AnalyticQueryContext (game, turn, perspective, storage, options)
  handler(ctx)  -- consumer may ctx.query(...) or ctx.probe(...)

ctx.probe(root_scope)  -- DFS declared ENSURE_DEPENDENCIES; persistence/scheduler checks only
  ensure-graph cycle -> unavailable reason ensure_cycle (no ensure side effects)
ctx.query(analytic_id, paths, scope)
  -> ensure_export(scope)   -- idempotent; may run sync (prior turns) or attach async (current turn)
  -> export_registry materialize + JSONPath
  memo key: (analytic_id, normalized scope, normalized path set)
  resolution stack: same tuple re-entered during materialize -> hard error (exception)
  ensure-graph cycle during ensure walk -> hard error (exception)
  scope excludes TurnAnalyticsOptions connection fields (#108 skeleton; #110 keying)
```

| Piece | Location |
|-------|----------|
| **AnalyticQueryContext** | `api/analytics/export_context.py` |
| **Analytic export registry** | `api/analytics/exports/registry.py` -- **`EXPORT_REGISTRY` derived at import** from each `TurnAnalyticRegistration.export_catalog` in `TURN_ANALYTIC_REGISTRATIONS` (do not register catalogs manually here) |
| Per-analytic catalog + materializer | Wired on **`TurnAnalyticRegistration.export_catalog`**; non-empty implementations may live in `api/analytics/<id>/exports.py` |
| JSONPath engine | `api/analytics/exports/jsonpath.py` -- in-repo RFC 9535-ish subset (not `jsonpath-ng`) |
| **BFF export ensure orchestration** | `packages/bff/bff/routers/export_ensure.py` (probe + background job stream) |

Table/map handlers receive the same `ctx` and should call the same **materialize_export_tree** (or shared helpers) where the export tree is the domain source of truth.

### BFF transport (v1)

| Surface | In v1? | Purpose |
|---------|--------|---------|
| In-process `ctx.query(...)` | Yes | Cross-analytic reads during Core compute |
| BFF export **query** routes | **No** | JSONPath export queries stay Core-only |
| BFF export **ensure orchestration** | **Yes** | Probe missing steps, confirm UX, background unwind job + NDJSON progress |

---

## Analytic export ensure

Export materialization is **not** read-only. `ctx.query(...)` runs **analytic export ensure** before building the tree.

| Rule | Detail |
|------|--------|
| **Idempotent** | Re-ensure for an already terminal/persisted scope is cheap (read cache). |
| **In-flight attach** | If the same scope is already on the inference scheduler/stream, ensure attaches and reflects live state -- no duplicate jobs. |
| **Ensure scope** | Typically `(game_id, perspective, turn, player_id)` for row-scoped exports (e.g. **scores** `$.solutions.*`). No batch ensure API in v1. |
| **Unwind direction** | Turn *N* reads *N−1* only. Example chain: Fleet@N <- Scores@N <- Fleet@N−1 <- Scores@N−1 <- … |
| **Small probe** | Inline ensure allowed; prior turns may sync-ensure when step count is at or below threshold. |
| **Large probe** | Block inline ensure; user confirms; **background full-unwind job** with progress stream. |
| **Current shell turn** | Expensive work (e.g. scores inference) stays **async** -- attach stream / return `in_progress`. |
| **Persistence gate** | Only full-unwind authoritative results are persistable for chain use (no approximate rows in #93). |

Ensure does **not** rely on the user having opened each analytic in visit order.

---

## Analytic export ensure probe

Dry-run before expensive work:

1. DFS **provider-declared** `ENSURE_DEPENDENCIES` from the requested root scope.
2. Check persistence and scheduler status at each step (no CP-SAT, no full materialization).
3. Return missing steps `{ analytic_id, turn, player_id, status }` for confirm UI and progress denominator.

**#108 skeleton:** the in-process probe walk calls provider `is_persisted`
hooks and `is_scope_ensured` on the query context to **omit** already-satisfied
scopes from the walk. Baseline scopes are also skipped. It does not yet check
scheduler status. Steps that need work appear in `missing_steps` with
`status: "not_persisted"` only -- satisfied, in-progress, and baseline scopes
are omitted rather than returned with `persisted`, `in_progress`, or
`baseline`. Full status discrimination is planned for
[#109](https://github.com/SteveDraper/Planets-Console/issues/109) BFF export
ensure orchestration.

When `totalMissing` exceeds a tunable threshold, inline ensure is blocked; the SPA calls BFF orchestration to start a background job.

**Ensure-graph cycles:** if the declared `ENSURE_DEPENDENCIES` edges revisit the same
`(analytic_id, scope)` during the walk (e.g. A -> B -> A at the same turn), probe returns
root **`unavailable`** with reason **`ensure_cycle`** and performs no ensure work. BFF
orchestration should treat this as a configuration error, not an inline-able job. See
**Cycle detection** below for the distinction from resolution-stack cycles and from valid
cross-turn chains.

---

## Analytic export ensure dependencies

Each provider's `exports.py` declares upstream requirements -- **not** consumers.

```python
ENSURE_DEPENDENCIES = (
    EnsureDependency(analytic_id="fleet", turn_delta=-1, player_id="same"),
)
```

| Provider | Typical dependency |
|----------|-------------------|
| **scores** @ *N* | **fleet** @ *N−1*, same `player_id` (wired when fleet analytic ships; **empty in #93 scores slice**) |
| **fleet** @ *N* | **scores** @ *N*, same `player_id` (future) |

Probe and ensure unwind follow these edges. Cross-turn scopes differ, so unwind is **not** a cycle (see below).

### Ensure dependency target validation

Every **non-empty** provider catalog is checked at registry build time: each `ensure_dependencies` entry must reference an `analytic_id` that exists in the same registry and has a **non-empty** export catalog. Empty catalogs declare no queryable surface and are not valid ensure targets.

| When | Where | On failure |
|------|-------|------------|
| **Production import** | `EXPORT_REGISTRY` build in `exports/registry.py` (`validate_ensure_dependency_targets`, `role="production"`) | `RuntimeError` at process startup |
| **Test fixture merge** | `merge_export_registry(...)` after overlaying extra catalogs (`role="merged"`) | `RuntimeError` when the harness or test imports the merged registry |
| **Ensure walk** | `walk_dependency_tree` before recursing into each dependency (`validate_ensure_dependency_target`, `role="query"`) | `RuntimeError` -- miswired edges are not silently skipped |

Authors should treat miswired `ensure_dependencies` as a **configuration error** caught at import (or fixture merge), not as a deferred `ctx.query` failure. The query-time check is a fail-loud safety net if a registry is assembled without going through `validate_export_catalogs` / `merge_export_registry`.

Typical failure messages:

- `ensure_dependencies references missing analytic_id` -- target id not in the registry
- `ensure_dependencies references empty catalog` -- target exists but `is_empty` (e.g. `empty_export_catalog_for`)

Empty provider catalogs skip ensure-target validation entirely (no `ensure_dependencies` to validate).

### Ensure baseline

Unwind stops when:

1. **Already satisfied** -- step is persisted/terminal or in-flight with attachable state.
2. **Analytic-specific baseline** -- e.g. **fleet** @ turn 1 has implicit empty composition; **scores** @ turn 1 has no **fleet** @ turn 0 (game-start neutral priors).
3. **Storage floor** -- if turn *T−1* is not stored for the **perspective**, probe reports `turn_not_stored` (root **unavailable**), not a neutral baseline.

---

## One value schema tree per analytic

Each turn analytic publishes **one** JSON-shaped **analytic export value schema** (JSON Schema dict in `exports.py`). Structure does **not** vary by scope -- scope selects which slice of the tree is populated.

### Map the analytic's normal output shape

Export trees should **mirror the analytic's canonical domain output**, not ad hoc projections tuned for one consumer. Cross-analytic callers query the same structures the analytic already produces for row inference, table/map handlers, or persistence -- so a held top-K explanation stays one queryable solution object (ships, aggregates, arithmetic together), not flattened arrays that lose grouping.

Practical rules:

| Rule | Detail |
|------|--------|
| **Prefer existing wire/persistence shapes** | Reuse serializers and field names from the analytic's normal output (e.g. scores held `solutions[]` matches inference row wire). |
| **Lifecycle in `meta`** | Materialization status (`searchStatus`, `solutionsHeld`, …) lives under `$.meta`; domain payloads stay separate. |
| **Ordering semantics** | Document array ordering in the catalog (e.g. `$.solutions[0]` = top ranked explanation). |
| **Projections are queries, not schema** | Consumers may JSONPath into nested fields (`$.solutions[0].shipBuilds[0]`); the schema still owns full solution objects. |

### Self-describing field descriptions (#98)

Every property node in **`value_schema`** must carry a non-empty JSON Schema **`description`**. Registry import validates non-empty catalogs at startup (and fixture catalogs merged in tests). Future **analytic MCP** adapters (issue **#98**) surface these strings so clients can discover export trees without reading implementation code.

| Rule | Detail |
|------|--------|
| **Root + branches** | The schema root and every declared `properties` entry need descriptions. |
| **Array items** | When `items` is an object with `properties`, the items schema and each nested property are described too. |
| **Open objects** | Branches with evolving payloads (e.g. `diagnostics`) may use `additionalProperties`; document known top-level keys and describe the branch role. |
| **Wire names** | Descriptions explain semantics; renaming wire fields still requires a coordinated contract change. |

Example branches (scores):

```json
{
  "meta": {
    "searchStatus": "complete",
    "solutionsHeld": 2,
    "hostTurn": 41
  },
  "solutions": [
    {
      "objectiveValue": 99,
      "actions": [ { "actionId": "planet_defense_posts_added_total", "label": "…", "count": 3 } ],
      "shipBuilds": [ { "hullId": 12, "engineId": 5, "comboId": "…", "…": "…" } ],
      "militaryScoreArithmetic": { }
    }
  ],
  "diagnostics": { },
  "hullCatalogMask": { "enabledHullIds": [1, 2, 3] }
}
```

`$.solutions` uses the same held top-K shape as scores row inference wire/persistence. `$.solutions[0]` is the full top explanation (all `shipBuilds` and `actions` for that rank). `$.meta.searchStatus` carries lifecycle only.

**`objectiveValue` (Plausibility):** each solution's `objectiveValue` is the **inference solution rank weight** shown in the UI as *Plausibility*. Higher integer = more plausible. It is built from **scaled log-probability prior terms** (Laplace-smoothed histogram weights on magnitude bins and ship combos, composed additively in the solver objective) plus **non-likelihood ranking heuristics** (partial weapon-slot fill penalties, tier-overflow penalties). Consumers may treat it as **plausibility on a pseudo log-likelihood scale**: monotonic with prior support and useful for ordering held explanations, but **not** a calibrated probability, percentage, or exact joint log-likelihood (bucketed aggregates use one bin penalty per action, not per-unit iid terms). The wire field name `objectiveValue` is retained from the CP-SAT solver; do not rename without a coordinated contract change.

Example branches (homeworld locator -- **#33**, not #93):

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

### Connection options excluded from scope identity (#108)

The #108 export-framework skeleton defines **`ExportScope`** as
`(game_id, perspective, turn, player_id)` only. Connection fields on
**`TurnAnalyticsOptions`** (`connection_warp_speed`, `connection_gravitonic_movement`,
`connection_flare_mode`, `connection_flare_depth`, `connection_include_illustrative_routes`)
are ambient on **`AnalyticQueryContext.options`** and are **not** fingerprinted in:

- query memo keys (`ResolutionKey`)
- materialized-tree cache (`(analytic_id, ExportScope)`)
- ensure idempotency sets
- cycle-detection stack keys

That is intentional for the skeleton: most analytics do not depend on connection
settings, and scope stays small. **Connections exports ([#110](https://github.com/SteveDraper/Planets-Console/issues/110))**
must define correct cache keying (e.g. an options fingerprint on scope or a
connections-specific memo partition) before callers can vary connection options
within one request and get distinct cached export trees.

**Path-prefix scope rules** in the catalog (examples):

| Prefix | Rule |
|--------|------|
| `$.solutions.*` | requires `player_id` |
| `$.diagnostics.*` | requires `player_id` (scores row inference diagnostics) |
| `$.evidence.*` | uses ambient **perspective** only; override forbidden |
| `$.slots.*` | game-global; turn param ignored (baseline resolved inside materializer) |

Missing stored turn at requested **perspective** -> root **`unavailable`: `turn_not_stored`**. Do not silently fall back to ambient turn.

---

## JSONPath queries

- Dialect: **JSONPath** (RFC 9535-ish subset).
- Catalog documents **ordering semantics**: e.g. `$.solutions` sorted descending by **inference solution rank weight** (`objectiveValue`), so `$.solutions[0]` is the top held explanation.
- **Batched export query:** one scope binding, multiple paths, e.g. `["$.solutions[0]", "$.meta.searchStatus"]`.

### Path results (under root `ok`)

| Path result | Meaning |
|-------------|---------|
| **`value`** | Selector matched; JSON payload |
| **`none`** | Valid selector, zero matches (e.g. empty `solutions` array -> `$.solutions[0]`) |
| **`invalid_path`** | Not allowed by catalog or bad syntax |

Root **`unavailable`** when the tree cannot be established for scope. **`query`** returns an
envelope; **`probe`** uses the same reason strings where applicable.

| Reason | Typical cause |
|--------|----------------|
| **`turn_not_stored`** | Requested or dependency turn not in storage for **perspective** |
| **`invalid_scope`** | Path-prefix rule violated (e.g. `$.payload.*` without `player_id`) |
| **`empty_catalog`** | Analytic has no queryable export surface yet |
| **`ensure_blocked`** | Missing-step count exceeds inline threshold (`query` only) |
| **`ensure_cycle`** | `ENSURE_DEPENDENCIES` graph revisits the same `(analytic_id, scope)` (**`probe` only**; see **Cycle detection**) |
| **`unknown_analytic`** | `analytic_id` not in export registry |

**Important:** `none` is not bad data. **`complete`** meta + `none` on `$.solutions[0]` = authoritative "no held explanations."

### Projections on empty arrays

| Path | `solutions: []` |
|------|-----------------|
| `$.solutions[0]` | **`none`** |
| `$.solutions[0].shipBuilds[0]` | **`none`** |
| `$.solutions` | **`value: []`** (branch exists, empty) |

---

## Analytic export meta

`$.meta` carries **materialization lifecycle**, not solver-specific outcomes.

### `searchStatus` (generic)

| Status | Consumer action (e.g. fleet) |
|--------|--------------------------------|
| **`not_started`** | Warn; offer refresh / start background ensure |
| **`in_progress`** | Warn; offer refresh |
| **`paused`** | Warn; offer refresh / resume |
| **`stopped`** | Warn; partial or empty; offer refresh |
| **`complete`** | Trust path results, including **`none`** |

Do **not** warn on **`complete`** even when all solution paths are **`none`**.

Optional: **`solutionsHeld`**, **`hostTurn`**.

Solver-specific outcomes (`no_exact_solution`, band residual, accelerated segments) belong under **`$.diagnostics`** (scores row inference diagnostics), not in **`searchStatus`**.

---

## Cycle detection

Two mechanisms apply during in-process export resolution. They use different keys and
different surfaces.

### Resolution-stack cycles (`query` / materialize)

While materializing and resolving paths, the context keeps a **resolution stack** keyed by:

```
(analytic_id, normalized scope parameters, normalized path set)
```

Normalized scope parameters are **`ExportScope`** fields only; connection options
on **`TurnAnalyticsOptions`** are excluded (see **Connection options excluded from
scope identity** above).

- Re-entering the **same** key during one `query(...)` (e.g. materializer calls back into `query` with identical scope and paths) -> hard error (`ExportCycleDetectedError`, HTTP 422).
- Cross-turn chains are **not** cycles: fleet turn *N* -> scores turn *N−1* -> fleet turn *N−1* differ in scope.
- Different paths at same scope (`$.solutions[0]` vs `$.diagnostics`) are **not** a cycle.
- Per-request memoization for identical keys.

### Ensure-graph cycles (`ENSURE_DEPENDENCIES` walk)

The probe and pre-ensure walk DFS **provider-declared** `ENSURE_DEPENDENCIES`. Revisiting
the same `(analytic_id, ExportScope)` on the active walk stack is an **ensure-graph
cycle** (invalid catalog wiring). Cross-turn unwind is **not** a cycle: scopes differ by
turn.

| Surface | Ensure-graph cycle behavior |
|---------|----------------------------|
| **`probe(...)`** | Root **`unavailable`**, reason **`ensure_cycle`**; no ensure callbacks, no missing-step denominator |
| **`query(...)`** | `ExportCycleDetectedError` (same exception type as resolution-stack cycles) |

BFF export-ensure orchestration should call **probe** first; **`ensure_cycle`** means the
job cannot proceed until catalog dependencies are fixed, not that the user should confirm
inline ensure.

---

## Availability vs enablement

Export queries ignore SPA sidebar enablement (**client preference** in localStorage). Enablement controls table/map wire fetches only.

---

## Author registration

Fourth touch point (required; empty catalog allowed): set **`export_catalog`** on the analytic's **`TurnAnalyticRegistration`** in `packages/api/api/analytics/<id>.py`. **`EXPORT_REGISTRY`** in `exports/registry.py` is built automatically from those registrations -- **do not** add manual entries there.

```python
from api.analytics.exports.empty import empty_export_catalog_for

REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_my_analytic,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),  # or a real AnalyticExportCatalog
)
```

| Catalog state | Author action |
|---------------|---------------|
| **Empty (no queryable exports yet)** | `export_catalog=empty_export_catalog_for(ANALYTIC_ID)` inline on registration (no stub `exports.py` required) |
| **Non-empty** | Define catalog in `packages/api/api/analytics/<id>/exports.py`, import `EXPORT_CATALOG`, pass `export_catalog=EXPORT_CATALOG` on registration |

Non-empty `exports.py` modules typically export an **`AnalyticExportCatalog`** (or build one inline) with:

| Field / hook | Purpose |
|--------------|---------|
| **`value_schema`** | JSON Schema dict for the one tree; every declared property must include a non-empty `description` (validated at registry import; surfaced by future MCP -- #98) |
| **`path_prefix_scope_rules`** | Scope validation by path prefix |
| **`ordering_semantics`** | Documented array ordering for index paths |
| **`ensure_dependencies`** | Provider-declared upstream ensure edges |
| **`ensure_export(ctx, scope)`** | Idempotent ensure for this analytic's scope (optional if materialize-only) |
| **`materialize_export_tree(ctx, scope) -> dict`** | Build tree after ensure (memoized on ctx) |

Import-time validation in `exports/registry.py` (`validate_export_catalogs`):

1. Every `TURN_ANALYTIC_CATALOG` id must have a matching `export_catalog` on its registration (no missing or extra ids).
2. Every **non-empty** catalog's `ensure_dependencies` must point at registry ids with **non-empty** catalogs (see **Ensure dependency target validation** above).
3. Every **non-empty** catalog with `ensure_dependencies` must provide `ensure_export`.

`EXPORT_REGISTRY` is built once at import; any mismatch raises `RuntimeError` before the server accepts traffic. Tests that add fixture catalogs use `merge_export_registry`, which re-runs ensure-target validation on the merged map.

See [Adding a turn analytic -- Core exports](design-adding-a-turn-analytic.md#23-core--exports-required).

---

## Consumer examples (future)

### Exploration route

```python
routes = ctx.query(
    "connections",
    paths=["$.routes"],
    scope={"turn": ambient_turn},
)

hw = ctx.query(
    "homeworld-locator",
    paths=["$.slots[?(@.perspective==3)].planetId"],
    scope={},
)
```

### Fleet analytic

```python
prior = ctx.query(
    "scores",
    paths=["$.solutions[0]", "$.meta.searchStatus"],
    scope={"turn": turn - 1, "player_id": player_id},
)
if prior.paths["$.meta.searchStatus"].value != "complete":
    mark_row_warning("Prior-turn build inference not complete")
top_build = prior.paths["$.solutions[0]"].value  # full top explanation when present
```

### Inference priors overlay (#87)

```python
composition = ctx.query(
    "fleet",
    paths=["$.composition.launcherTypes"],
    scope={"turn": turn - 1, "player_id": player_id},
)
```

---

## Future MCP

Same materializers and catalog metadata; transport adapter exposes:

- `list_analytic_exports(analytic_id)` -- schema + path-prefix rules + ensure dependencies
- `query_analytic_export(analytic_id, scope, paths[])` -- same result envelope as in-process

No second implementation path.

### Deferred: truncated pseudo-baseline

Stopping unwind at turn *N−K* with neutral priors/empty fleet may return faster approximate results. **Not in #93.** Requires **analytic export ensure provenance** on persisted rows and invalidation when deeper history is later ensured -- separate design/ADR.

---

## Testing

### Framework fixture analytics (required)

Production catalog stays unchanged. Framework tests use **test-only** mutual-dependency fixture analytics under `packages/api/tests/fixtures/export_framework/` (e.g. `export-test-alpha` / `export-test-beta`), registered via a test harness -- **not** in `TURN_ANALYTIC_CATALOG`.

Must cover: probe step counts, threshold policy, inline vs background ensure, unwind to baseline, `turn_not_stored`, `ensure_cycle` on probe, resolution and ensure-graph cycle detection, diamond DAG dedupe, memoization, `none` vs `unavailable`, cross-turn chain allowed.

### Per-analytic and integration

- Unit tests per `exports.py`: materialize against fixtures; JSONPath golden paths; path-prefix scope rejection.
- **Connections** and **scores** export golden tests.
- Registry: every production catalog id has `export_catalog` on its registration; `EXPORT_REGISTRY` validates catalog sync and ensure dependency targets at import; `merge_export_registry` validates merged fixture catalogs; empty catalogs skip ensure-target checks.

---

## #93 implementation slices

| Slice | Issue | Deliverable |
|-------|-------|-------------|
| **#93a** | [#108](https://github.com/SteveDraper/Planets-Console/issues/108) | `export_types`, `export_context` (query, probe, ensure), `export_registry`, JSONPath resolver, handler plumbing, empty catalogs for current production analytics, **fixture pair tests** |
| **#93b** | [#109](https://github.com/SteveDraper/Planets-Console/issues/109) | BFF export ensure orchestration (probe + background job NDJSON stream) |
| **#93c** | [#110](https://github.com/SteveDraper/Planets-Console/issues/110) | `connections/exports.py` -- concept-shim reference |
| **#93d** | [#111](https://github.com/SteveDraper/Planets-Console/issues/111) | `scores/exports.py` -- `$.solutions`, `$.meta`, scheduler/persistence; **`ENSURE_DEPENDENCIES = ()`** until fleet ships |
| **Follow-on** | Homeworld exports (**#33**); fleet analytic + Scores fleet@N−1 edge; truncated unwind + provenance ADR |
