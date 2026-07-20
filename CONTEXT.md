# Planets Console

An analytic console for Planets.nu game state. Contributors and agents use this glossary for project-specific terms across the SPA, BFF, Core REST API, and logical JSON store.

## Language

### Application layers

**Core REST API**:
The domain layer mounted at `/api/v1/...`. Owns dataclass models, business logic, storage access, turn analytics, and game-concept rules. Response shapes reflect the domain, not the SPA.
_Avoid_: API layer (ambiguous with BFF), backend (when meaning the whole Python stack)

**BFF**:
The Backend-for-Frontend mounted at `/bff/...`. Aggregates and reshapes Core responses into SPA-oriented contracts. The frontend calls only the BFF, never Core routes directly.
_Avoid_: API gateway, middleware layer

**BFF contract codegen slice**:
A domain-scoped generated TypeScript module produced from part of the BFF OpenAPI document. Slices exist so **regeneration** after a route change rewrites only the contract types for that domain, not the entire SPA API surface in one file.
_Avoid_: schema chunk (implementation), splitting by line count

**Regeneration boundary**:
The line between two **BFF contract codegen slices** (or between a slice and a Zod-owned wire module). A change on one side of the boundary must not require regenerating or re-validating types on the other unless the wire contract itself changed.
_Avoid_: file size limit (as the primary reason to split)

**Shell**:
The SPA chrome -- header bar, analytics selector, and main display area -- plus the **shell context** that scopes what is being analyzed.
_Avoid_: layout, chrome (without "shell" context)

**Shell context**:
The working set that scopes turn-scoped work: selected **game id**, **turn**, and **perspective** (resolved **viewpoint**). Held in client state; each HTTP request is handled without server-side session memory of the user's selection.
_Avoid_: session context (ambiguous with login credentials), query scope (implementation term)

### Login and shell controls

**Login identity**:
The planets.nu account **name** (and in-session **password**) used to call upstream APIs. Distinct from **viewpoint** -- login determines what data may be fetched; viewpoint determines whose position is shown.
_Avoid_: user, account (when meaning planets.nu login specifically)

**Session credentials**:
Login name and password held **in memory** for the current page load only. Never persisted to localStorage, cookies, URLs, or any durable store.
_Avoid_: auth token, saved login

**Viewpoint**:
The player whose position is analyzed and displayed. Resolved to a **perspective** slot; defaults from **login identity** and may be overridden in the header when the game allows.
_Avoid_: perspective (when meaning the UI choice -- use viewpoint), player slot (use perspective)

**Game info refresh**:
Fetching current **GameInfo** from **Planets.nu upstream** (or confirming it is already in storage) and updating **shell context** -- max turn, player order, finished state, sector display name.
_Avoid_: sync game, reload header

**Shell error bar**:
Full-width strip below the **shell** header that stacks user-visible BFF failure messages. Each row is dismissible; multiple concurrent errors may appear. Primary SPA pattern for surfacing fetch and mutation failures.
_Avoid_: toast, snackbar, error banner (without "shell")

**Diagnostics modal**:
Developer UI (opened from the header) that lists recent **request diagnostics** from the BFF buffer and can enable session-wide `includeDiagnostics=true` on BFF calls so later requests populate that buffer.
_Avoid_: debug panel (generic), profiler

**Compute diagnostics**:
Developer capability to observe and control the **compute orchestrator** DAG for one **shell context** (game, perspective, turn). Distinct from **request diagnostics** (per-BFF-call timing trees). Primarily an **observer** of orchestration: diagnostic code attaches at thin boundaries on the **compute orchestrator** and global worker pool (dequeue filter, dispatch gate, completion callbacks, stream-binding registry) and must stay **analytic-agnostic** -- no fleet-, scores-, or other analytic-specific hooks; such coupling is a design smell. Live snapshot includes the global **pool work queue**, **in-flight** pool executions (dequeued but not yet complete), every orchestrator **analytic compute node** in **compute diagnostic scope** (state, step_kind, step_index, priority band, **orchestrator registration id** -- duplicate scope keys across background warm and table-stream bindings are expected), the ordered orchestrator **ready queue** (dispatch order before pool enqueue), and live pool occupancy fields (configured workers, in-flight count, ready depth, backend mix) used with the **compute concurrency timeline** to classify orchestration bottlenecks. Also surfaces **compute completion history**, the **compute concurrency timeline**, **connected stream status** (generic table-stream registry bindings on the server plus client connection lifecycle from the shared per-player stream hook when the SPA is open -- each analytic prefixes its own ``streamId`` into the client ``connectionKey`` so fleet and scores do not overwrite each other), and optional **compute diagnostic mode** controls. In-flight pool rows are keyed by orchestrator registration id; a finished worker always clears its own slot (including abort/early-return). Interpreter/process backends complete via done callbacks so a stuck remote future cannot pin a pool worker. Snapshots purge in-flight orphans with no matching ``running`` DAG node, take one pool-queue capture for both ``poolQueue`` and held ``nextSingleStep``, and Run ignores held targets that are no longer in ``poolQueue``. Run also stops with a stall error when the same would-dispatch focus target returns unchanged with an empty pool and no live in-flight work. Snapshot refresh is on-demand: tab open, manual Refresh, and after control mutations -- not continuous polling in v1. Timeline recording is always on whenever compute diagnostics are enabled in process config (not gated on tab open or a separate arm). v1 containment is shell-scoped; other shell contexts are out of view unless the operator switches shell context. **Compute diagnostic scope** includes the shell turn plus ancestor turns reachable via registered `ENSURE_DEPENDENCIES` for work rooted at that shell (e.g. `fleet@(N-1)` when diagnosing `scores@N`); not every turn for an allowed **Player**.
_Avoid_: request diagnostics (timing trees), debug panel (generic), pool-queue-only snapshot (misses DAG vertex state and in-flight workers), server-only stream status (misses browser reconnect/sleep-wake), diagnostic branches inside analytic `run_step` implementations, per-analytic diagnostic hooks (fleet/scores special cases), per-scheduler stream binding aggregation in diagnostics routers, continuous snapshot polling in v1, treating missing OS child processes as proof the pool is idle (fleet/scores use thread and interpreter backends in-process)

**Compute diagnostic scope**:
The set of **compute scope** nodes and pool work visible and controllable under **compute diagnostics** for one **shell context**: same `game_id` and **perspective**, shell `turn`, plus dependency ancestor turns on registered `ENSURE_DEPENDENCIES` edges. Per-player filtering applies within this set.
_Avoid_: literal shell turn only (misses cross-turn warm chains), all turns for a player (too broad)

**Compute completion history**:
Ring buffer (v1 default cap ~500 entries) of terminal **compute step** executions within **compute diagnostic scope**: compute scope key, execution surface (`pool` or `inline`), terminal state, `step_kind`, `step_index`, priority band, completion timestamp, and (when available) backend plus wall duration from the paired timeline start event. Appended from the same finish sink as **compute concurrency timeline** `complete` events -- one writer, two projections. Shell-scoped; cleared on process restart.
_Avoid_: unbounded process log, process-wide completion mix without scope filter, a second independent complete-timestamp path that can drift from the timeline

**Compute concurrency timeline**:
Shell-scoped ring buffer of schedulable orchestration events (ready, pool enqueue, pool start/dequeue, step complete, and inline start/complete) recorded while **compute diagnostics** are enabled. Default capacity ~5000 events (configurable); wraps by dropping oldest. Each event carries timestamp, **compute scope** identity (including player), backend when known, and occupancy gauges at that instant: **compute diagnostic scope** ready depth / in-flight count, plus global pool in-flight (and queue depth when useful), alongside configured worker count -- so an operator can classify a run as serial ready-set, dispatch starvation (including cross-shell worker contention), backend/GIL ceiling, and/or scope under-submission. Snapshot also exposes a thin derived rollup of those events (depth/occupancy percentiles, unique players, backend histogram, duration by backend) to assist classification -- not an auto-labeled bottleneck verdict. Complements point-in-time snapshot occupancy fields; not a substitute for **compute completion history** (terminal outcomes only).
_Avoid_: Activity Monitor as the primary classifier, continuous snapshot polling as the timeline mechanism, per-analytic timeline hooks, process-wide unfiltered event soup without shell / diagnostic-scope filtering, auto-declaring the bottleneck class in the rollup, scoped-only gauges that hide cross-shell pool saturation

**Compute diagnostic mode**:
Shell-scoped developer state that pauses default compute dispatch for the active **shell context** so work can be released one **compute step** at a time within a focus set of **Player**s. Distinct from merely opening **compute diagnostics** for observation: the Compute tab is read-only until the operator explicitly arms freeze mode, or the process starts frozen via `api.compute_diagnostics_start_frozen` (only meaningful when compute diagnostics are enabled). When freeze mode is armed, every **Player** in **compute diagnostic scope** stays frozen for automatic dispatch and dequeue -- including allowlisted players. The **allowlist** is a **focus set** for observation and **single-step** / **Run** (and for narrowing per-player stream subscriptions); it does **not** free-run those players. **Single-step** advances exactly one schedulable **compute step** within the focus set, then re-freezes; with an empty allowlist, single-step is a no-op (operator must name a focus player first). **Run** repeatedly single-steps (refreshing the diagnostics snapshot after each step, and polling while focus pool work is in flight) until the focus set has nothing steppable and no pending pool work. Selection approximates unfrozen global-pool order: among focus held pool items and focus ready nodes, prefer higher **priority band** (`stream_attached` before `interactive_ensure` before `background`), then initial steps before continuations; on a tie prefer an already-held pool item. The chosen scope, priority band, and orchestrator registration id are pinned for that release so another bound DAG (or lower-band ready node) cannot steal the dispatch slot. A would-dispatch target arms one focus ready-node dispatch slot plus a paired dequeue grant (inline steps clear an unused grant so it cannot orphan); dispatch gates stay side-effect free and slot consume happens only after every gate passes. **Freeze armed** is sticky across **shell context** changes within the same game (turn or **perspective** shift): a new context enters frozen when freeze was left on, so computation does not start before the operator is ready; the player allowlist resets on each context change (focus set empty again). **Freeze armed** disarms on game change. With **start-frozen**, the first contact with a game (shell notify or orchestrator bind) arms freeze with an empty allowlist without an Arm freeze click; operator disarm remains sticky for that game id within the process. While freeze is armed for a game, the server treats new shell contexts under that game as default-frozen at the orchestrator diagnostic boundary (no client race required for compute gating). Client freeze controls rehydrate from freeze-status / snapshot after SPA reload (server in-process registry is source of truth; not durable across process restart beyond start-frozen). **Compute completion history** is per shell context. Freeze uses both an orchestrator **dispatch gate** (blocks new pool submissions and **inline** steps) and a pool **dequeue hold** (workers do not dequeue frozen-scope items already queued). In-flight pool work for frozen scope runs to completion in v1; no mid-step cancellation. When freeze mode is active, per-player stream subscriptions narrow to allowlisted players through the generic table-stream / shell layer (not per-analytic hooks). Enabled only when the server process opts in via configuration (off by default). Distinct from scores-only **inference global pause** (tier-ladder hold within one stream scope).
_Avoid_: allowlist free-run (unfreeze selected players), global pause (scores inference only), stream debug player filter (client-only narrowing), pool-only freeze (misses inline steps), single-node completion (one full analytic compute node per click), freeze on tab open, always-on diagnostic controls in production, start-frozen without compute diagnostics, duplicate sessionStorage player filter alongside server allowlist, freeze dropping on shell context change while still armed, carrying allowlist across context changes, sticky freeze across game change (unless start-frozen re-arms the new game), single-step with empty allowlist releasing non-focus work, single-step bind-order ignoring priority bands, burning a single-step slot when a later dispatch gate rejects

### Game data

**GameInfo**:
Domain model for the planets.nu **Load Game Info** response -- players, settings, schedule, win conditions, and related metadata for a game. Stored as one document at logical path `games/{gameId}/info`.
_Avoid_: game metadata (too vague), loadinfo payload

**TurnInfo**:
Domain model for the **`rst`** object from planets.nu **Load Turn Data** -- planets, ships, scores, and the rest of a single turn from one **perspective**. Primary input to **turn analytics**.
_Avoid_: turn blob (informal), RST (use TurnInfo in project prose; `rst` is the upstream field name)

**Perspective**:
A **1-based player slot number** in a game (`1` .. `11`). Used in storage paths and Core routes (`games/{gameId}/{perspective}/turns/{turn}`). Stable for a given player for the life of the game.
_Avoid_: player id (ambiguous with in-game entity ids), viewpoint (the UI-facing player choice)

**Player**:
A participant entity in **GameInfo** or **TurnInfo** (the `Player` dataclass) -- username, race, resources, and related fields. Identified by in-payload ids and names; located in the game by **perspective** slot, not by those ids alone.
_Avoid_: perspective, viewpoint, player slot

**Planets.nu upstream**:
The live planets.nu JSON API the console calls to refresh **GameInfo** and load missing turns. Distinct from Core, BFF, and local storage.
_Avoid_: external API (too generic), host (when meaning the web service, not game rules)

**Turn ensure**:
The operation that guarantees **TurnInfo** exists in storage for a **shell context** scope. If the turn document is already present, returns immediately; otherwise loads from **Planets.nu upstream** and writes storage. Analytics must not run until ensure succeeds for that scope.
_Avoid_: prefetch, lazy load (without "ensure" semantics)

**Storage-only load**:
Opening a game already present in storage without **login identity**, for dev or demo. **Turn ensure** may skip upstream credentials when the turn is already stored; otherwise login is required.
_Avoid_: offline mode, cached game

### Analytics

**Analytic**:
A registered analysis feature the user can enable -- tabular output, a map overlay, or both. Each has an `analytic_id`, Core computation, and BFF shaping for the SPA. Which analytics are enabled is a **client preference** persisted globally in localStorage (survives reload; not scoped per game).
_Avoid_: widget, report, metric

**Turn analytic**:
An **analytic** computed from **TurnInfo** for a specific game, turn, and **perspective**. Invoked through the shared Core route `.../turns/{turn}/analytics/{analytic_id}` and corresponding BFF routes.
_Avoid_: query, dashboard tile

**Generic analytics route**:
The BFF paths `GET /analytics/{analytic_id}/table` and `.../map` shared by every **turn analytic**. The path parameter selects the handler; response bodies are shaped per analytic in code, not as separate OpenAPI paths per id.
_Avoid_: per-analytic endpoint (when meaning this shared route pattern)

**Turn analytic wire contract**:
The JSON table or map payload one **turn analytic** returns through the **generic analytics route** (or any analytic-specific BFF route). Default: owned in the SPA under `src/analytics/<analytic_id>/` (hand types, Zod, normalizers) -- not in central OpenAPI codegen. Per-analytic OpenAPI models are optional when a strict shared contract is required.
_Avoid_: analytics schema.ts (implies all analytics share one generated file)

**Central BFF contract codegen (default layout)**:
Generated TypeScript from OpenAPI is split by BFF router **regeneration boundary** (e.g. games, shell, diagnostics, analytics catalog). Each slice OpenAPI dump includes **full `$ref` closure** for its paths (duplicate cross-router schemas across slices is acceptable in v1). Turn analytic table/map payloads stay out of those slices unless explicitly promoted to OpenAPI. See [ADR 0003](docs/adr/0003-frontend-bff-contract-codegen.md).
_Avoid_: one schema.ts for the whole BFF, splitting generated files by line count only

**Filtered OpenAPI dump**:
A build step that subsets the full BFF OpenAPI document by path prefix (and pulled-in component schemas) before `openapi-typescript` runs, producing one generated module per slice. Preferred v1 mechanism for **central BFF contract codegen** (over multiple live OpenAPI endpoints or Redocly-only workflows).
_Avoid_: hand-editing generated TypeScript to split it after the fact

**BFF OpenAPI filter script**:
Python under repo `scripts/` (e.g. `filter_bff_openapi.py`) subsets the dumped BFF spec before `openapi-typescript`; invoked from `npm run generate:api` after `generate:api:dump`. Keeps JSON `$ref` walking in the same toolchain as the OpenAPI dump, not in `packages/frontend`.
_Avoid_: fragile shell-only filters without component closure

**OpenAPI slice closure (v1)**:
Each filtered slice includes every `components.schemas` entry reachable from that slice's paths. Cross-router schemas may be duplicated in multiple slice dumps and generated TypeScript modules; a separate shared slice is deferred until import duplication becomes a problem.
_Avoid_: schema-shared as a required v1 dependency for every slice to compile

**Generated slice CI**:
CI verifies committed `schema-<slice>.ts` files match the filtered OpenAPI dumps (`make check_frontend_api_slices`) and fails if monolithic `src/api/schema.ts` reappears (`make check_frontend_api_no_monolithic_schema`; both run in `make ci`).
_Avoid_: relying on reviewers to notice stale or monolithic generated types

**Generated schema import rule**:
Application code imports the smallest matching `schema-<slice>.ts` module for types; `bff.ts` remains the facade for HTTP calls. Do not add a barrel `schema.ts` that re-exports every slice (that recreates a single monolith in git and in review).
_Avoid_: `import from './schema'` as the default in feature folders

**Turn analytic catalog**:
`TURN_ANALYTIC_CATALOG` in `api/analytics/catalog.py` is the single declarative source of truth for turn analytic ids, SPA-facing metadata (`name`, `supports_table`, `supports_map`, `type`), and order. `catalog.py` imports no Core compute, so BFF descriptors and `catalog_entry()` read it without dragging in the compute graph. Core **turn analytic registration** objects (`TURN_ANALYTIC_REGISTRATIONS` in `registry.py`) reference catalog entries via `catalog_entry(analytic_id)` and bundle the context `compute` handler plus an export-catalog placeholder. `registry.py` derives only the `TURN_ANALYTICS` handler map from registrations and aligns them to the catalog with `tuple_aligned_with_turn_analytic_catalog` -- the same helper the BFF uses for its descriptors -- so a missing or extra registration fails at import and the public order follows the catalog. There is no second, registry-owned catalog. Adding an analytic requires: one `TurnAnalyticCatalogEntry` in `catalog.py`, one Core **registration** (catalog entry reference + context `compute` handler + export catalog placeholder) appended to `TURN_ANALYTIC_REGISTRATIONS` in `registry.py`, one BFF `_BFF_DESCRIPTORS_BY_ID` entry (table/map shaping), and -- once exports ship (#93) -- wiring the registration's export catalog into the export registry. The catalog prevents metadata and id drift between Core and BFF.
_Avoid_: editing derived `TURN_ANALYTICS` directly (append one registration instead); re-deriving or re-publishing a second catalog from registrations (the catalog is the source, not a derivation); maintaining separate catalog and handler maps in Core; merging Core handlers with BFF shapers into one cross-layer list; inline duplicate catalog metadata in registrations instead of `catalog_entry()`

**Analytic descriptor**:
The BFF registration object for one **turn analytic** -- optional table/map handlers and diagnostic hooks, with catalog metadata from `TURN_ANALYTIC_CATALOG` via `from_catalog_entry`. Aggregated in `REGISTERED_ANALYTICS`; the SPA catalog comes from this list via `GET /bff/analytics`.
_Avoid_: METADATA dict, handler registry (when meaning the consolidated descriptor)

**Analytic export**:
A queryable surface one **turn analytic** exposes as a single **analytic export value schema** tree, queried with JSONPath **analytic export paths** and scope parameters (game, turn, **perspective**, optional **Player**). Scope binds on the query with ambient defaults; path-prefix rules override where defaults are wrong or forbidden. Distinct from the **turn analytic wire contract** and from direct **game concept** imports -- consumers use the **analytic query context** even when the provider delegates to `api/concepts/`.
_Avoid_: analytic API, internal getter, wire payload reuse, flat scalar export per field

**Analytic export catalog**:
The self-describing **analytic export value schema** tree and path-prefix scope rules registered by one **turn analytic**. One schema tree per analytic; scope is not baked into separate root shapes. Every turn analytic implements the pattern; an empty catalog is valid. Aggregated at the Core layer for discovery (future analytic MCP: describe tree, query JSONPath + scope).
_Avoid_: multiple scope-specific root schemas per analytic, OpenAPI per path (v1)

**Concept-shim analytic**:
A **turn analytic** whose primary job is to expose **game concept** results as **analytic exports** with a stable catalog id, while its SPA table/map surface may be thin or absent. **Connections** is the reference shape: reachability math lives in **Connections engine** (`concepts/`); the analytic adds export entry points and UI-facing options. Allows arbitrary Core information to enter the uniform export graph without duplicating concept code inside unrelated analytics.
_Avoid_: fake analytic, concept wrapper module (when meaning the registered turn analytic)

**Analytic query context**:
The in-process Core facility passed into **turn analytic** computation through which one analytic requests **analytic exports** from another. Owns scope validation (game, turn, **perspective**, optional **Player**), per-request memoization, **analytic export ensure**, **analytic export ensure probe**, and cycle detection. `query(...)` runs ensure then materialize; `probe(...)` walks declared export dependencies and reports missing steps without starting expensive compute. v1: export queries run only through this context during Core compute -- not nested HTTP export-query routes. A future analytic MCP reuses the same export handler implementations with an HTTP/JSON adapter. The **compute orchestrator** does not own a long-lived **analytic query context**; callers supply per-**compute request** orchestration needs (see **compute orchestrator** -- orchestration bundle on the node). Full query-context memoization remains a caller/session concern, not the process-wide scheduler's bound state.
_Avoid_: export microservice, cross-analytic REST (v1); binding one **analytic query context** for the lifetime of the **compute orchestrator**

**Analytic export ensure**:
Idempotent producer step before materialization: bring one **analytic export** scope to the best terminal state available (read persistence, attach/schedule in-flight work, or cheap non-solve terminals). Invoked by **analytic query context** `query(...)`, not by ad hoc cross-imports. Ensure scope is typically `(game_id, perspective, turn, player_id)` for row-scoped exports such as **scores** `$.solutions.*`. For **scores**, ensure schedules a **inference row run** so orchestrator ``tier_solve`` owns CP-SAT (ambient and historical); it must not sync-solve on the materialize/ensure thread. Does not start duplicate work when the same scope is already in flight. Cross-turn chains unwind one prior turn at a time (turn *N* reads *N−1* only). Large missing-step counts use a background ensure job with progress feedback, not a single blocking HTTP request. Truncated pseudo-baseline unwind is out of scope until **fleet materialization provenance** ships ([ADR 0004](docs/adr/0004-fleet-per-player-persistence-and-ensure-provenance.md)); truncation markers are a follow-on.
_Avoid_: mutating query (vague), read-only export materializer, user visit order as prerequisite, sync CP-SAT inside scores ensure/materialize

**Analytic export ensure baseline**:
The point where an ensure-unwind chain stops without further **analytic export ensure dependencies**. **Analytic-specific:** e.g. **fleet** at turn 1 has no prior fleet (implicit empty composition); **scores** at turn 1 does not require **fleet** at turn 0 -- game-start neutral priors apply. **Accelerated-start floor:** when `acceleratedturns = N` (`N > 0`) and the requesting scope is at or above **N**, turn **N** is the ensure/materialization baseline (deps on turns `1..N-1` are skipped). **Storage floor:** if a dependency turn at or above the ensure floor is not stored for the **perspective**, probe reports `turn_not_stored` (root **unavailable**), not a neutral baseline -- distinct from authoritative empty export data at turn 1 / accelerated turn N.
_Avoid_: global turn-1 shortcut without per-analytic rules, silent fallback to ambient turn when a prior turn is missing

**Analytic export ensure dependency**:
A provider-declared upstream requirement in one analytic's **analytic export catalog** (e.g. in `exports.py`): which other **turn analytic** export must be ensured before this analytic's export can be ensured for a scope. Declared by the **provider** (not consumers). Probe DFS and ensure unwind follow these edges -- e.g. **scores** at turn *N* declares **fleet** at *N−1* for the same `player_id`; **fleet** at *N* declares **scores** at *N* for the same `player_id`. Cross-turn unwind stops when a step is already persisted/terminal or the chain reaches an analytic-specific **ensure baseline** (no further dependencies).
_Avoid_: consumer-declared dependency lists, central dependency graph file, materializer-inferred chains

**Analytic export ensure probe**:
Dry-run dependency walk for a requested consumer scope: **analytic export ensure dependency** edges plus persistence and scheduler status checks only -- no CP-SAT or full materialization. Returns missing ensure steps (e.g. per `analytic_id`, turn, `player_id`) for confirmation UI, progress denominators, and threshold policy (block inline ensure when step count is high). v1 SPA access: dedicated BFF **export ensure orchestration** routes (probe and background job progress stream) -- not HTTP export-query routes; in-process `query(...)` remains Core-only.
_Avoid_: route-probe (implementation jargon), running ensure during probe, BFF JSONPath export query endpoints (v1)

**Analytic export scope**:
Scope parameters on an export query (game, turn, **perspective**, `player_id`, connection **options**, etc.). Unspecified dimensions default to the ambient compute scope (shell turn, **perspective**, and related context). **Path-prefix scope rules** in the **analytic export catalog** declare where defaults are wrong or forbidden (e.g. `$.evidence.*` uses ambient **perspective** only; `$.solutions.*` requires explicit `player_id`). The **analytic query context** validates scope, enforces **perspective**-visible stored turns for cross-turn reads, and merges **analytic persistence** when needed. Missing stored turns or unknown players yield root **unavailable** -- not silent fallback.
_Avoid_: scope baked into separate root schemas, omniscient cross-perspective reads

**Analytic export cycle detection**:
While resolving exports in-process, the **analytic query context** maintains a resolution stack keyed by `(analytic_id, normalized scope parameters, normalized path set)`. Re-entering the same key is a hard error (true cycle). Cross-turn chains differ in scope (e.g. turn *N* vs *N−1*) and are not cycles. Different paths at the same scope (`$.ships` vs `$.aggregates`) are not a cycle. Per-request memoization applies for identical keys.
_Avoid_: analytic-id-only cycle check, treating path variants as re-entrant cycles

**Analytic export availability**:
Whether a Core **analytic export** query can be satisfied for the requested scope. Independent of SPA sidebar enablement (**client preference** in localStorage) -- enablement controls which table/map wire payloads the SPA fetches, not whether Core may resolve exports during compute or future MCP calls. An export may still return unavailable when data is missing (turn not stored, persistence not populated, invalid scope, **analytic export cycle detection** trip, etc.).
_Avoid_: enabled analytic check, client toggle gate

**Analytic export value schema**:
The single self-describing JSON-shaped type tree one **turn analytic** publishes in the **analytic export catalog**. Structure is independent of scope -- scope selects which slice of the tree is populated. Top-level branches may differ in role (e.g. `solutions`, `hullCatalogMask`, `slots`, `evidence`) with **path-prefix scope rules** per branch. Catalog documents array **ordering semantics** (e.g. `$.solutions` sorted descending by **inference solution rank weight** so `$.solutions[0]` is the top held explanation). Wire values are JSON-serializable for future MCP adapters.
_Avoid_: flat scalar-only catalog, separate schema per scope, SPA table row as the schema

**Analytic export path**:
A JSONPath selector into the analytic's **value schema** tree -- e.g. `$`, `$.solutions`, `$.solutions[0]`, `$.solutions[0].shipBuilds[0]`. One **analytic query context** request binds scope once, materializes the tree (memoized), then resolves one or more paths (**batched export query**). Zero matches yield **analytic export path none**, not root **unavailable**.
_Avoid_: custom path dialect, treating empty index as query failure

**Analytic export result**:
Discriminated outcome of one path query through the **analytic query context**. Top level: **`ok`** when the export tree can be established for scope; **`unavailable`** when it cannot (e.g. `turn_not_stored`, `invalid_scope`, `persistence_empty`). Under **`ok`**, each path gets a **path result**: **`value`**, **`none`** (zero matches -- e.g. `$.solutions[0]` when `solutions` is `[]`), or **`invalid_path`**. Batched paths do not fail the whole query when one path is **`none`**. **`cycle_detected`** is a hard error (exception).
_Avoid_: top-level failure for path none, conflating none with turn_not_stored

**Analytic export path none**:
A **path result** status: root available, JSONPath valid, zero nodes matched. Distinct from a matched JSON **`null`** and from root **unavailable**. No ships in a solution is **`none`**, not an error.
_Avoid_: path miss as query failure

**Batched export query**:
One **analytic query context** request resolving multiple JSONPath selectors under one scope binding -- e.g. `["$.solutions[0]", "$.meta.searchStatus"]` without re-materializing the tree.
_Avoid_: N sequential queries when one tree pass suffices

**Analytic export materializer**:
The per-**turn analytic** function (`materialize_export_tree`) registered in Core that builds the JSON tree for a validated **analytic export scope** on first path touch (memoized on the **analytic query context**). Declared alongside **`EXPORT_VALUE_SCHEMA`** (JSON Schema dict), **path-prefix scope rules**, and ordering semantics in `analytics/<id>/exports.py`. Table/map handlers and **concept-shim analytic** providers should call the same materializer (or shared helpers it uses) so wire output and export queries stay one source of truth. When materialization can be incomplete (e.g. **military score build inference** still running or not yet started for that scope), the tree includes a documented **`meta`** branch with explicit status so consumers can warn users -- not only best-so-far data with no signal.
_Avoid_: duplicate domain logic in handler vs exports, silent partial data without status

**Analytic export meta**:
A documented branch of the export value tree (e.g. `$.meta`) carrying **materialization lifecycle** status independent of path **`none`** / **`value`**. Generic **`searchStatus`** values: **`not_started`**, **`in_progress`**, **`paused`**, **`stopped`**, **`complete`**. Consumers warn users when status is not **`complete`** (e.g. fleet analytic: prior-turn inference not ready). **`complete`** with path **`none`** is authoritative empty data, not bad data. Solver-specific outcomes (e.g. inference `no_exact_solution`, band residual) live under domain branches (e.g. `$.diagnostics`), not in **`searchStatus`**. Optional **`solutionsHeld`** counts held rows under **`complete`** / in-progress partial trees.
_Avoid_: inference-only statuses in generic meta, inferring quality from empty paths alone

**Analytic export registry**:
Core aggregation of every turn analytic's export catalog (`analytics/exports/registry.py`). Import-time validation: each `TURN_ANALYTIC_CATALOG` id has a registry entry (empty catalog allowed). Dispatches materialize + JSONPath resolution for **analytic query context** queries.
_Avoid_: per-consumer ad hoc import of analytic modules

**Base map**:
The always-on map layer (`type: base`, id `base-map`) that renders planet nodes from **TurnInfo**. Fetched automatically in **map mode** and omitted from the analytics sidebar; other map analytics overlay it.
_Avoid_: background layer, planet layer (without "base map")

**View mode**:
Shell display mode for the main area: **tabular** (stacked analytic tables) or **map** (React Flow graph). Analytics grey out in the selector when they do not support the active mode.
_Avoid_: layout mode, display type

**Map display retention**:
While map data for the current **shell context** is loading, the SPA may keep showing the last displayable **combined map** and leave **MapGraph** mounted so the viewport is preserved. Clears synchronously when **game id** or **perspective** changes; still applies across **turn** steps within the same game and viewpoint. No loading overlay while a retained map is shown -- the stale frame is intentional and silent. Owned by `useRetainedMapDisplay` in the frontend; TanStack Query does not retain across turn or ensure gaps.
_Avoid_: keepPreviousData (implementation detail; not the product concept), stale map cache

**Map layer**:
One analytic's contribution to the combined map graph -- nodes and/or edges merged with **base map** and other enabled map analytics via id-prefixing.
_Avoid_: overlay (acceptable informally; prefer map layer in docs)

**Stellar Cartography**:
NuHost optional map geography (star clusters, nebulae, wormholes, black holes, debris disks, and related ion-storm behavior). Exposed in the console as one map-only **turn analytic** with per-element layer toggles.
_Avoid_: SC (in user-facing copy), space hazards (too broad)

**Ion storm layer**:
A **Cartography layer** for `ionstorms[]` inside the **Stellar Cartography** analytic. Shown in the sidebar only when game settings enable ion storms; when shown but the current turn has no `ionstorms[]`, the toggle is inactive (greyed, with hint).
_Avoid_: ion storms analytic (separate registration)

**Cartography layer**:
One toggleable element family inside the **Stellar Cartography** analytic (e.g. nebulae, wormholes). Layer on/off is a **client preference** persisted globally in localStorage (not per game). Geometry comes from **TurnInfo** via the analytic.
_Avoid_: overlay type, map feature (without cartography context)

**Cartography sample**:
Host-aligned numeric or label values (ion voltage, star radiation, black hole max warp, etc.) at a map coordinate for the current turn. Computed in Core **game concepts**; the SPA requests a **batched** sample for hover and shows every applicable layer in one tooltip.
_Avoid_: hover popup (generic)

**Debris disk** (map):
A destroyed-system field centered on a seed planet (`debrisdisk > 1` on the turn snapshot; value is border radius in ly). **Planetoids** (`debrisdisk == 1`) always render on the **base map**. The **Stellar Cartography** analytic adds an optional **Debris disk borders** layer (outline only) for towing and minefield context; warp-well rules unchanged.
_Avoid_: debris disks checkbox (use **Debris disk borders**)

**Star cluster** (map):
A lethal core plus halo in `stars[]`, keyed by shared cluster `name` across one or more bodies. Radiation and neutron clusters share the same wire shape today; the console renders them under one **Cartography layer** until cluster kind can be classified reliably.
_Avoid_: neutron star (as a separate layer id before classification exists)

**Homeworld locator**:
A **turn analytic** (map and tabular) that heuristically infers each **Player**'s starting **homeworld planet** and visualizes **homeworld candidates** on the map. Uses **GameInfo** settings (e.g. `hwdistribution`, cluster counts) plus turn planet data; may emit **slot-anchored candidates** and **orphan homeworld candidates**. Sidebar **homeworld locator panel** for annotation; main-area tabular tile mirrors candidate rows when **view mode** is tabular. Inference signals and Starmap layout constraints: [design-homeworld-locator-analytic.md](docs/design-homeworld-locator-analytic.md).
_Avoid_: HW finder, start planet analytic

**Homeworld planet**:
The starting planet assigned to a **Player** slot at map creation. Distinct from **Officer Homeworld** (account metagame UI on planets.nu). Not a boolean flag in **TurnInfo** exports; inferred by the **homeworld locator** or confirmed manually.
_Avoid_: Officer Homeworld, home planet (without "homeworld" qualifier)

**Homeworld candidate**:
One inferred or confirmed **homeworld planet** position (or constrained region) with a confidence tier. Either **slot-anchored** (tied to a **perspective** / **Player** slot) or an **orphan homeworld candidate** (location-first when slot assignment is ambiguous).
_Avoid_: HW guess, probable start

**Slot-anchored homeworld candidate**:
A **homeworld candidate** tied to a specific **perspective** slot from **GameInfo**. Primary output mode when player count and map settings support one homeworld per slot.
_Avoid_: player HW, slot HW (in docs without "candidate")

**Orphan homeworld candidate**:
A **homeworld candidate** not yet tied to a **perspective** slot -- a planet or region that looks like a homeworld under heuristics or geometry, pending slot assignment or manual race annotation.
_Avoid_: unassigned HW, floating candidate

**Homeworld inference baseline**:
The earliest available **TurnInfo** (typically turn 1) used as the primary source for planet ownership, population, climate, and map-gen geometry signals in the **homeworld locator**. When turn 1 is not stored, the locator **auto-ensures** turn 1 when credentials allow; if ensure fails, falls back to the earliest stored turn with **baseline degraded** warning in the **homeworld locator panel**. Baseline facts are not recomputed from the shell turn alone.
_Avoid_: inference turn, T1-only mode

**Baseline degraded**:
**Homeworld locator** state computed from a baseline turn other than turn 1 (or before turn 1 ensure completes). Baseline-profile **definite** matches are treated cautiously; the panel shows which turn was used and prompts loading turn 1 when possible.
_Avoid_: weak baseline flag, stale T1 warning

**Homeworld inference evidence**:
A later-turn signal that increases or decreases confidence in a **homeworld candidate** without replacing the **homeworld inference baseline**. Examples: first sighting of a player's ships, ships at characteristic distances from a planet (81 LY pod hop, warp-8 range), or cluster geometry matching `verycloseplanets` / `closeplanets` settings.
_Avoid_: secondary heuristic, turn N guess

**Homeworld confidence tier**:
How strongly the locator treats a candidate as the **homeworld planet** for a slot or orphan location. **Definite** when a baseline profile matches, geometry leaves no plausible alternative, cumulative **homeworld inference evidence** promotes the candidate, or the user manually confirms. **Possible** when consistent with settings and spacing but not unique. Orphans default to **possible** until anchored or confirmed.
_Avoid_: probability score (until a scoring model is defined)

**Homeworld baseline profile**:
Turn-1 planet signals used for **definite** rule matching: owned by the slot's **Player**, clan count at or above a configured minimum (below default `homeworldclans` to allow RGA and population loss), starbase present when `homeworldhasstarbase`, and climate matching the slot's race **preferred temperature** from the race climate catalog (50 deg W default; 100 deg W for Crystals when desert advantage applies -- adjusted per game from **GameSettings** / race flags when available).
_Avoid_: temp-50 rule, 1M pop heuristic (use configured threshold and race-aware climate)

**Race climate catalog**:
Core **game concept** mapping **race id** to preferred planet temperature for **homeworld baseline profile** checks. Static defaults (e.g. Crystal 100 deg W) adjusted per game when settings disable race-specific advantages (Crystal desert advantage off -> 50 deg W like other races).
_Avoid_: HW temp table, climate lookup (generic)

**Homeworld locator config**:
Server-side **analytic policy** for the **homeworld locator**, loaded from amalgamated YAML under the Core API config (not exposed in the SPA UI). Includes minimum clan count for **homeworld baseline profile** matching and evidence-promotion thresholds (e.g. independent sightings required for **possible → definite**). Origin-distance checks use host-aligned constants from **game concepts** (81 LY pod hop, warp-speed range table) -- not ad-hoc YAML distance lists.
_Avoid_: HW settings panel, client-side heuristic config

**Homeworld locator state**:
Persisted server-side record for a **homeworld locator** run -- cached **homeworld candidates**, confidence tiers, slot assignments, and user overrides. Split across **homeworld locator state (game-global)** and **homeworld locator evidence (perspective)**. Not recomputed every session; refreshed when **homeworld locator invalidation** rules fire or the user requests **homeworld locator refresh**. **User-asserted** records are preserved across recomputes.
_Avoid_: HW cache blob, analytic snapshot (generic)

**Homeworld locator invalidation**:
When inferred **homeworld locator** state is stale and must recompute or append evidence. Triggers: a new **TurnInfo** stored for the shell **perspective** beyond the cached evidence horizon; **GameInfo** re-fetch with changed homeworld-relevant settings (`hwdistribution`, `homeworldclans`, `nohomeworld`, etc.). Does not remove **user-asserted** records -- those merge back after inference.
_Avoid_: cache TTL, automatic refresh timer

**Homeworld locator refresh**:
Explicit user action (sidebar control in the **homeworld locator** analytic) that forces recomputation of inferred state regardless of invalidation triggers. **User-asserted** records are preserved and re-merged.
_Avoid_: reload button (generic), force recompute

**Homeworld candidate record**:
One entry in **homeworld locator state** -- a **homeworld candidate** with the same shape whether **inferred** or **user-asserted**. Includes planet id or region, **perspective** slot (when slot-anchored), confidence tier, and **homeworld attribution**.
_Avoid_: override object, manual tag DTO

**Homeworld attribution**:
Whether a **homeworld candidate record** came from the locator heuristics (**inferred**) or from explicit user confirmation (**user-asserted**). User-asserted slot resolution, race tag, or promotion to **definite** uses the same record shape as inferred results; only attribution differs.
_Avoid_: source flag, manual flag

**Homeworld assertion**:
A user-initiated upsert of a **homeworld candidate record** with **user-asserted** attribution. Submitted via Core `POST .../analytics/homeworld-locator/assertions` (BFF exposes SPA-shaped equivalent). Core merges into **homeworld locator state (game-global)**; inference recomputes must not overwrite unless the user revokes the assertion.
_Avoid_: override POST, manual save endpoint

**Homeworld evidence scope**:
Which **TurnInfo** snapshots supply **homeworld inference evidence** after the baseline. **Baseline** planet signals come from the earliest stored turn for the shell **perspective**; **later-turn evidence** (e.g. ship sightings, origin-distance signals) uses only turns stored at the current **viewpoint**'s **perspective** -- not a union across all slots.
_Avoid_: omniscient evidence, all-perspectives merge

**Homeworld locator state (game-global)**:
Cached slot assignments, orphan candidates, and user-asserted records shared across viewers. Stored at `games/{gameId}/analytics/homeworld-locator` under the **analytic persistence** path convention.
_Avoid_: games/{gameId}/homeworld-locator (collides with other top-level game keys)

**Homeworld locator evidence (perspective)**:
Per-**perspective** evidence accumulation and evidence-driven confidence promotions. Stored at `games/{gameId}/{perspective}/analytics/homeworld-locator/evidence`. Merged with **homeworld locator state (game-global)** when serving the analytic.
_Avoid_: per-viewer HW file, evidence cache (generic)

**Homeworld map marker**:
Map decoration on a **base map** planet node for a **homeworld candidate** at a known planet id. **Definite** tiers use a solid marker; **possible** tiers use a lighter or dashed marker. **User-asserted** **definite** uses the same definite marker with a distinct attribution cue (border or badge).
_Avoid_: HW node (separate graph node), duplicate planet

**Homeworld region overlay**:
Map geometry for a slot or orphan when no planet is pinned -- e.g. circular `hwdistribution` ring arc, or 81/162 LY cluster envelope from **GameSettings**. Rendered as analytic **overlayCircles** or arc overlays (same pattern as **Stellar Cartography**), slot-labeled where applicable.
_Avoid_: possible zone (vague), sector blob (informal)

**Homeworld locator panel**:
The **homeworld locator** analytic details UI -- slot and orphan table (assign slot, set race, tier override), plus **homeworld locator refresh**. Map-primary: context menu on **homeworld map marker** or **homeworld region overlay** for quick asserts; table for bulk review with map highlight on row focus.
_Avoid_: HW settings drawer, annotation modal (generic)

**Homeworld locator availability**:
Whether the **homeworld locator** can run for the loaded game. Inactive (greyed in the analytics selector with hint) when **GameInfo** rules out traditional **homeworld planet** setups -- e.g. `nohomeworld`, **Wandering Tribes** (`wanderingtribescount > 0`), or scenario overrides with no HW planets. No inference, no **analytic persistence** writes.
_Avoid_: disabled analytic (generic), HW not applicable toast

**Homeworld region geometry (v1)**:
Settings-driven **homeworld region overlay** math shipped for **`hwdistribution=2` (Circular)** on round maps (`mapshape=0`) only. Other distributions remain active for baseline profile, evidence, and manual annotation, but skip sector/ring overlay geometry until extended.
_Avoid_: full hwdistribution support (v1 claim)

**Fleet analytic**:
A **turn analytic** (tabular and map) that maintains each **Player**'s inferred fleet composition as of the shell turn. Computed at `(game, turn T, perspective P)` using turns `1..T` stored at **perspective** `P` only -- not an omniscient merge across slots. Combines **fleet observed ship** sightings from `TurnInfo.ships` with **fleet inferred acquisition** rows from **military score build inference** (and later trade/capture sources). Map layers are per-player, individually color-coded and toggleable; tabular output is one ship list per **Player**. v1 may leave many **fleet field constraint** branches empty; the wire and export schema must still represent partial knowledge when available. See [design-fleet-analytic.md](docs/design-fleet-analytic.md) ([#114](https://github.com/SteveDraper/Planets-Console/issues/114)).
_Avoid_: omniscient fleet, viewpoint-player-only fleet (unless explicitly scoped)

**Fleet observation scope**:
Which stored turns and visibility feed the **fleet analytic** for one shell context. Direct evidence: ships appearing in `turn.ships` on turns `1..T` at the shell **perspective**. Build evidence: **scores** inference per `player_id` on host turns in that same turn range. Cross-perspective union is out of scope. Location constraints from starbase builds may later consume **homeworld locator** or planet-ownership analytics when those exist; v1 may record unconstrained location.
_Avoid_: all-perspectives merge, single-turn-only fleet

**Fleet ship record**:
One row in a **Player**'s fleet table -- a single acquired ship tracked across turns until reconciled or retired. Carries **fleet field constraint** values for id, hull, launcher, beam, engine, built turn, and last known or inferred location. May originate as **fleet observed ship** or **fleet inferred acquisition**; reconciliation merges evidence onto one record when observation matches inference.
_Avoid_: ship snapshot (implies no cross-turn identity), fleet entry (informal)

**Fleet observed ship**:
A **fleet ship record** backed by a direct sighting in `TurnInfo.ships` at the shell **perspective**. When the host assigns a stable ship id visible in the snapshot, id is known (or upper-bounded by sequential allocation rules). Position and fitted components come from the sighting turn unless later sightings refine them.
_Avoid_: inferred-only row, ghost ship (without evidence class)

**Fleet inferred acquisition**:
A **fleet ship record** attributed to a **Player** from scoreboard build counts (**military score build inference** `shipBuilds` on a host turn) when no matching **fleet observed ship** exists yet. Hull and component fields may be fixed (from a held solution), a set of options (top-K ambiguity), or unknown. Id may be unknown, range-bounded (e.g. max id from prior game ship count plus builds that turn), or fixed after first sighting. Initial location may be constrained to the builder's starbases (or a region envelope) when planet positions are known; v1 may emit **unknown** until locator/planet analytics supply coordinates.
_Avoid_: proved build history (implies unique solution), scoreboard row (solve-time grain)

**Fleet field constraint**:
How one attribute on a **fleet ship record** is represented when knowledge is partial. **Known** -- single definite value. **Unknown** -- no constraint (`?` in UI). **Bounded** -- numeric range (e.g. ship id `<= maxId`). **Options** -- finite candidate set on one field only when other fields are already known or fixed. **Region** -- location constrained to a set of planet ids, starbase coordinates, or a map overlay (not necessarily a single x/y). Producers may leave constraints empty in v1; consumers and export schema must accept all shapes for forward compatibility.
_Avoid_: nullable-only (collapses bounded vs options), string `?` in API (use structured constraint objects)

**Fleet build option set**:
One feasible fitted-ship specification -- hull + engine + beam + launcher types and slot fills as a consistent tuple. On **fleet inferred acquisition** rows, entries come from **military score build inference** held `shipBuilds`; when top-K solutions disagree, the row exposes a list of option sets (not per-field Cartesian products). UI may show the highest-**inference solution rank weight** set as the display default while listing alternates. On **fleet observed ship** rows, ingest attaches a **single confirmed** option set so beam/launcher slot fills (`ship.beams` / `ship.torps`) are available for display while `fields.beams` / `fields.launchers` stay type-id constraints. Fog-unknown weapon axes keep null type ids and null counts on that option set (display as `?`); confirmed empty weapons use count `0`. Observation reconciliation matches a sighting to at most one option set before collapsing fields to **known**.
_Avoid_: component Cartesian product, independent field options, combo row (use inference glossary **ship build combo** for solver catalog ids)

**Fleet evidence event**:
One append-only fact in a **fleet ship record** or player fleet summary timeline -- e.g. scoreboard `+1 warship` on a host turn, inference solution update, direct sighting, id bound tightened, option-set match chosen, disposition change, **fleet alibi**, **fleet possibly lost** candidacy, **fleet count discrepancy**, or countervailing sighting. Report-derived facts (when ingested) are first-class evidence sources alongside scoreboard and `TurnInfo.ships`. Reconciliation decisions are recorded as events (including which **fleet build option set** index matched and tie-break rule used), not overwritten silently. Prior events stay available so a later **fleet reconciliation correction** can reassign a sighting to a different row or revert a collapsed field to **options** without losing history. v1 may not expose correction UI; Core/export representation must support it.
_Avoid_: mutable snapshot only, last-write-wins merge

**Fleet reconciliation correction**:
Re-opening or reversing an earlier observation-to-row link when new evidence contradicts it -- e.g. a second sighting fits a different **fleet build option set**, or scoreboard reconciliation shows one too many **active** rows. Emits new **fleet evidence event**s and adjusts current field constraints and disposition; does not delete prior events. User-facing correction workflow is a follow-on ticket; **fleet acquisition ledger** and exports must retain enough structure to apply corrections deterministically later.
_Avoid_: edit row in place (without audit), manual override (generic)

**Fleet count discrepancy**:
Player-level state when scoreboard ship-count deltas (or future report evidence) imply fewer **active** ships than the ledger shows, but no **strong evidence** identifies which **fleet ship record** was destroyed or traded. v1 does **not** flip row **fleet ship disposition** on guesswork (no FIFO demotion). The discrepancy is recorded explicitly (`activeRowCount` vs `scoreboardImpliedCount`, host turn, optional report refs) and surfaced in UI chrome. Row-level status may use **fleet possibly lost** and **fleet alibi** without changing disposition until resolved.
_Avoid_: silent FIFO demotion, forced `unknown` disposition

**Fleet possibly lost**:
Row-level qualifier (not a **fleet ship disposition** change) when a ship-count decrease or report makes this row a candidate for destruction or trade but selection is not strongly evidenced. Displayed as a warning icon or badge; row stays **`active`** in the ledger until disposition changes with strong evidence. Distinct from **`lost`** disposition and from **fleet count discrepancy** (player-level).
_Avoid_: `unknown` disposition (too strong for v1 guess), lost badge (implies confirmed)

**Fleet alibi**:
Row-level qualifier: evidence proves this **fleet ship record** still existed after a given host turn -- e.g. direct sighting on turn *T+k* after a scoreboard `-1 warship` on turn *T*. Excludes this row from **fleet possibly lost** candidacy for that event. Recorded as **fleet evidence event** with turn and source.
_Avoid_: confirmed active (use disposition `active` only), safe ship (informal)

**Fleet ship disposition**:
Whether a **fleet ship record** still counts toward a **Player**'s active fleet as of the shell turn. Values include **`active`** (still in fleet accounting), **`lost`** (destroyed or otherwise removed with evidence), **`traded`** (transferred to another **Player** when trade evidence exists), and **`unknown`** (no longer active but removal cause not resolved). Inferred-only rows may flip to **`lost`** or **`unknown`** when scoreboard ship-count reconciliation says they are gone without a sighting. Distinct from **fleet field constraint** -- disposition is record lifecycle, not attribute uncertainty.
_Avoid_: status (generic), deleted flag (implies hard purge)

**Fleet acquisition ledger**:
The full set of **fleet ship record**s for one **Player**, including non-**active** dispositions and the evidence timeline (built turn, sightings, inference source). Core and **analytic export** materializers own the ledger; the SPA tabular v1 defaults to **`active`** rows only. Map v1 shows **active** records with known or region-constrained position; lost or unknown rows stay off the map unless a follow-on layer requests them.
_Avoid_: current fleet table (when meaning the filtered view only), ship history log (generic)

**Analytic export ensure provenance**:
Metadata on persisted analytic output that records which upstream ensure legs were closed when materialization ran, distinct from mere file existence. **Fleet materialization provenance** (ADR 0004) is the first production instance: per `player_id` at `fleet@N`, a pair `(turnEvidenceAtN, priorLedgerAtNMinus1)`; both `true` means ensure may short-circuit that scope. Partial provenance keeps the scope on probe missing-step lists and queues ensure work. Enables deduped outstanding-work sets for background ensure ([#109](https://github.com/SteveDraper/Planets-Console/issues/109)) and truncated pseudo-baseline unwind (future).
_Avoid_: persisted equals final, snapshot file as ensure gate

**Fleet ledger persistence**:
Per-**Player** persisted **fleet acquisition ledger** at one `(game_id, perspective, turn)` scope. Stored at in-document key `ledgers/{playerId}` under `games/{gameId}/{perspective}/turns/{turn}/analytics/fleet`. Carries **fleet materialization provenance** and per-ledger `materializationVersion`. Independent invalidation per player when that player's scores inference evidence changes. See [ADR 0004](docs/adr/0004-fleet-per-player-persistence-and-ensure-provenance.md).
_Avoid_: monolithic all-players fleet blob as ensure-final, perspective-wide invalidation for one player's scores update

**Fleet materialization provenance**:
Per-player pair at `fleet@N`: `turnEvidenceAtN` (turn-*N* RST ingest + `scores@N` ensure-satisfied for that player) and `priorLedgerAtNMinus1` (`fleet@(N-1)` for that player is provenance-final, or turn-1 baseline). Both `true` --> persisted ledger is ensure-final. Either `false` --> probe/ensure continues the dependency walk for that `player_id`. Set honestly at write time. See [ADR 0004](docs/adr/0004-fleet-per-player-persistence-and-ensure-provenance.md).
_Avoid_: inferring finality from cache hit, global provenance for all players

**Fleet turn snapshot**:
Legacy name for the turn-scoped fleet persistence document at `games/{gameId}/{perspective}/turns/{turn}/analytics/fleet`. **Current model (ADR 0004):** the document holds per-player **fleet ledger persistence** entries, not one undifferentiated all-players snapshot. Materialize each player by chaining from that player's prior ledger plus turn-*T* evidence. Shared global id-bound inputs are read from RST per turn, not stored as a cross-player ledger. Turn document replace at *T* invalidates all players' ledgers at turns `>= T`; scores row updates invalidate per player from the affected host turn.
_Avoid_: perspective-wide single ledger file as ensure-final, recompute 1..T on every GET

**Fleet ensure baseline**:
**Analytic export ensure baseline** for **fleet**: turn 1 has implicit empty fleet per **Player** (no prior snapshot). Unwind stops at turn 1; no fleet@turn 0.
_Avoid_: neutral fleet priors (scores vocabulary)

**Fleet map layer**:
The **map layer** contribution of the **fleet analytic** -- ship markers and optional region geometry for one shell turn. **Known position:** a ship **fleet map node** at last sighted `x/y` (stable id `fleet:{playerId}:{recordId}`). **Region only:** optional **overlayCircles** or starbase markers when **fleet field constraint** **region** is populated (v1 may omit). **No position:** excluded from map payload. Only **`active`** rows with known point or region appear in v1.
_Avoid_: duplicate ship graph (separate from base map planets)

**Fleet player visibility**:
Single per-**Player** enablement preference (localStorage, global) controlling whether that **Player**'s fleet appears in both **view mode**s -- one **fleet table tile** and the same player's **fleet map layer** ships and region overlays. Default on for viewpoint **Player**; others off until toggled in the **fleet analytic** sidebar. Same **client preference** pattern as **Cartography layer** toggles.
_Avoid_: separate map-only and table-only player toggles (v1), per-player analytic id

**Fleet table tile**:
One tabular sub-tile per **fleet player visibility**-enabled **Player** in **view mode** tabular -- TanStack Table of **`active`** **fleet ship record** rows with columns for id, hull, engine, beams, launchers, built turn, last seen, and status icons (**fleet alibi**, **fleet possibly lost**). Ambiguous fit shows default **fleet build option set** in row cells; row expander lists alternates. Tile header carries **fleet count discrepancy** banner when set. Viewpoint **Player** tile first, then **GameInfo** player order.
_Avoid_: master fleet table (all players one grid), scores table reuse

**Fleet table stream**:
Single NDJSON connection for all **fleet player visibility**-enabled players on one game / turn / **perspective** scope (`GET .../fleet/table-stream`). Connect admits every requested player (cached final ledgers may replay immediately), then multiplexes per-player scheduler queues onto one wire; the frontend demuxes on `playerId`. Progress (`ledger_updated`, `record_refined`, `provenance`) from any admitted player reaches the SPA as gap-fill legs complete -- not serialized behind the prior player's host-turn `complete`. Fairness "one submission per player" is orchestrator submit grain only. Shares the [table-stream session framework](docs/adr/0004-addendum-table-stream-session-framework.md) with **inference table stream**.
_Avoid_: per-player HTTP connections, admission-order wire drain (one player to complete before the next is multiplexed)

**Military score build inference**:
Core **turn analytic** behavior (optional on the **Scores** analytic) that explains one player's scoreboard deltas on a turn as a ranked set of feasible build and load actions, not a single proved history. Requests run **per scoreboard row** with top-K **20**. No fixed row time budget once **#71** ships -- SPA runs continue until the ladder finishes, **inference global pause** freezes them, or the stream is **cancelled** (scope change, disable build inference, explicit cancel/recompute -- **not** disconnect). Disconnect is detach-only; see **Inference stream cancellation**. See [design-military-score-build-inference.md](docs/design-military-score-build-inference.md).
_Avoid_: build solver, score guesser, treating disconnect as cancel

**Inference search tier**:
One staged step in **military score build inference** catalog construction and solving. The ladder has no fixed length; each tier declares how much of the action inventory is in play for that attempt. Later tiers are strict supersets of earlier ones on every dimension they control (permitted actions, per-action caps, ship-build component eligibility, constraint strictness). The solver walks the list until time runs out or a tier adds no new distinct exact explanation signatures to **inference merged top-K** (the ladder continues when K is full; see K-best retention there).
_Avoid_: ship build tier (too narrow; implies only hull combos), phase

**Fine-grained slack action**:
An aggregate inference action with a small per-unit military-score increment that can pad an explanation without changing the main build story -- e.g. planet or starbase defense posts and ship torpedo loads. Deferred to higher **inference search tiers** so lower tiers prioritize ship-build explanations. Large-increment loads (starbase fighters, ship fighters) and race-specific exceptions (e.g. Evil Empire free starbase fighters) are not fine-grained slack actions unless a tier policy explicitly treats them as such.
_Avoid_: noise action, filler variable

**Tier aggregate allowlist**:
Per **inference search tier**, the set of aggregate actions permitted at that step, each with a maximum count. Each tier's allowlist is a strict superset of the previous tier's (new action ids and/or relaxed caps). Ship-build combos are governed by the same tier policy, not a separate fixed four-step ladder.
_Avoid_: noisy action list, tier catalog

**Inference tier policy**:
The declarative record for one **inference search tier** on the unified ladder -- constraints on the full action catalog (ship-build component filters such as permitted tech levels, **tier aggregate allowlist** and caps, military-score band tolerance `alpha` in 2x units, seed budget, optional `allowShipOnlyExactEarlyStop`, and optional `hullCollisionTwinWiden`). Later tiers loosen constraints; the final tier uses `alpha = 0`. Policies are loaded from a static asset (YAML). Runtime catalog widens (e.g. **hull collision twin** `includeComponentIds` when `hullCollisionTwinWiden` is set) are step-local, not a global resolve-time overlay. Fleet-informed torp admission and ranking tunables live in the same YAML file under `fleetInferenceTuning` (**#87**, **#156**; section 8.8 of implementation doc) -- a separate merge path from component-filter widens.
_Avoid_: tier config, search phase

**Hull collision twin**:
A checked-in `(lowHullId, highHullId, militaryChange)` triple recording that a single-warship build of the low-tech hull can score-collide with a higher-tech hull at that military change, so ship-only exact early-stop on the low hull alone would miss the twin. Assets are per game category under `hull_collision_twins_*.yaml`; the inference search tier with `hullCollisionTwinWiden: true` (`collision_hull_widen`) admits only matching high-tech partners for emitted lows (#226).
_Avoid_: high-tech allowlist, early-stop hull list

**Inference catalog constraint**:
A filter applied at an **inference search tier** to shrink the full turn catalog. Ship-build filters use **explicit tech-level allowlists** per axis -- hulls, engines, beams, and **launcher torpedo types** (tube ammunition tech levels; not hull launcher slot counts). Component ids are derived at runtime by intersecting those tech levels with the turn catalog and player active lists. Aggregate actions use **tier aggregate allowlist** entries with max counts. Tier 0 reflects early-game tech bands from policy, not lowest component id.
_Avoid_: component eligibility (implementation name), preset, torp id list

**Inference near-solution seed**:
A band-feasible action multiset from tier *n* (exact pass at that tier was infeasible) carried into tier *n+1* to narrow search: fix ship-build counts from the seed, admit newly unlocked aggregate actions to close residual, then widen to a neighborhood if still infeasible before free search. Multiple seeds may be carried forward (capped per tier). An exact-feasible tier *n* result is emitted immediately; it is not a seed because there is no military-score remainder to refine.
_Avoid_: warm start, hint

**Inference score band**:
Relaxed military-score constraint `explained_2x >= observed_2x - alpha` with `alpha` from the tier policy. Warship and freighter equalities stay exact. The final **inference search tier** always uses `alpha = 0`. Each tier tries exact constraints first; **inference score band** applies only on retry after an infeasible exact pass at that tier. Band-feasible results seed the next tier only; they are never user-facing explanations. **Exact** solutions from any tier merge into **inference merged top-K**. If the full ladder yields zero exact solutions, status is `no_exact_solution` with band residual in diagnostics.
_Avoid_: slack constraint, approximate solve

**Inference explanation signature**:
Identity of one feasible explanation as the sorted multiset of aggregate action ids with counts plus ship-build combo ids with counts. Two ranked rows with the same signature are the same explanation for merge dedup and **inference solution streaming** -- regardless of display labels or which **inference search tier** found them. Re-discovery at a later tier is suppressed; first discovery wins.
_Avoid_: solution hash, fingerprint

**Inference merged top-K**:
Up to K distinct exact explanations held across the full **inference search tier** ladder, ranked by **inference solution rank weight**. When K is full the ladder still climbs: a new signature evicts the current worst held row only if its weight is higher. Distinctness is by **inference explanation signature**.
_Avoid_: per-tier top-K, solution buffer

**Inference solution rank weight**:
The solver maximize objective attached to one explanation, expressed in inverted penalty space (higher is better). Legacy positive marginal weights map to penalties via `(max_marginal - weight)` so more plausible bins and actions score higher. Prior terms come from `SCALE * log(p)` (Laplace-smoothed counts) on magnitude bins and ship combos; the total behaves as **plausibility on a pseudo log-likelihood scale** -- monotonic with prior support, not a calibrated probability or exact joint log-likelihood. Every aggregate action is a **bucketed aggregate action** and contributes exactly one rescaled bin penalty for its single active magnitude bin, where the bins include a leading **occurrence (none) bin** (`count == 0`); choosing the `none` bin costs `0`, and any active bin carries the **occurrence cost** that subsumes the old standalone parsimony penalty -- not a sum of all bucket marginals and not per unit in the bin. **Ship build combos** contribute inverted probability weights (per combo count). The only non-bucketed candidate (`evil_empire_free_starbase_fighters`) contributes no ranking term. **Inference ranking heuristics** layer on top: flat tier-overflow when count exceeds **inference aggregate admission cap**, and partial weapon-slot fill penalties. Orders the merged top-K and each streamed `solution` event; the consumer may maintain final ranked order incrementally from this weight without waiting for the full ladder to finish. Serialized on the wire as `objectiveValue` per solution row.
_Avoid_: probability score, objective value (implementation field name)

**Inference solution plausibility (display)**:
The integer shown in the **inference solution detail modal** solution header (`Solution n · Plausibility X`). Maps to wire field `objectiveValue` (**inference solution rank weight**). Higher means more plausible on the pseudo log-likelihood scale described above; not a percentage or calibrated probability. A future probability-only field and relative-vs-best ratios (#88) may drive solution-list pruning separately.
_Avoid_: likelihood percent, log probability (in modal copy without qualification)

**Inference solution detail modal**:
Player-facing dialog opened from the **inference solution count indicator** when **N > 0** on a `success` or `paused` row. Shows observed constraint deltas, ranked solutions (icon | action | military subtotal tables, plausibility headers, reconciliation footers), and live updates while search continues. Does not surface `accelerated_segments`, `appliedEqualities`, priority-point constraint notes, spectator delta-source notes, or other developer diagnostics (those belong in the Scores diagnostics panel). Spec: [design-military-score-inference-solution-modal.md](docs/design-military-score-inference-solution-modal.md). Tracker: #48.
_Avoid_: inference detail dialog (generic), diagnostic modal

**Inference occurrence prior (none bin)**:
The leading **none bin** (`count == 0`) present in every aggregate **probability bucket** set. It carries a data-derived occurrence pseudo-count (asset `0:` key, or `none_bin_pseudo_count` for implicit-uniform tables) so that each aggregate contributes a self-normalised `log P(observed bin)` term including the "did not happen" outcome. The `none` bin is the max-weight bin (cost `0`); any active bin sits below it by the **occurrence cost**, reproducing the legacy flat parsimony penalty (`LEGACY_PARSIMONY_OCCURRENCE_PENALTY = SCALE // 2 = 50`) within +/-1. This replaces the former standalone parsimony penalty and the degenerate `counts` aggregate shape (both removed). Distinct from count-dependent positive **probability buckets**, **inference tier-overflow bands**, and **inference action-family diversity caps**.
_Avoid_: parsimony penalty (removed), complexity score, moving-parts penalty

**Inference action-family diversity cap**:
Hard CP-SAT constraint: at most N distinct catalog members from a **superclass** may be non-zero in one explanation (indicator `count > 0`, then `sum(indicators) <= cap`). Used where the **inference occurrence prior (none bin)** alone does not stop degeneracy -- e.g. many distinct torpedo-load types padding score. Not applied to defense-post slack (planet + starbase posts together are plausible; the occurrence cost alone governs there). v1 superclasses: **torpedo loads** (`ship_torps_loaded_{id}`, cap 2); **fighter channel** (`starbase_fighters_added_total`, `ship_fighters_added_total`, `fighters_starbase_to_ship`, `fighters_ship_to_starbase`, cap 2). **`evil_empire_free_starbase_fighters`** is excluded from diversity caps and, being non-bucketed, contributes no ranking term (race-specific high-prior action).
_Avoid_: superclass limit (without "inference"), defense cap

**Inference tier-overflow band**:
When tier policy raises an action's upper bound above its **inference aggregate admission cap**, one flat boolean overflow indicator fires when count exceeds the admission cap and adds one fixed marginal penalty (`tier_overflow_marginal_weight`, not per unit above the cap). Penalizes explanations that need slack volume only unlocked on later **inference search tier** steps (e.g. planet defense posts 17+ when admission cap was 16). Probability bins are not clamped to the admission cap; overflow is modeled separately in the solver objective. One count variable per action; not duplicate catalog entries.
_Avoid_: overflow penalty (generic), duplicate tier action

**Inference aggregate admission cap**:
For one aggregate action id, the `aggregateAllowlist` cap at the **inference search tier** where that action first entered the ladder. Later tiers may raise the cap (superset rule); counts at or below the admission cap are more plausible than counts that require a later tier's raised cap. Ranking encodes this via a flat boolean overflow indicator in the solver objective, not duplicate catalog entries.
_Avoid_: first-tier cap, allowlist origin

**Inference tier policy asset**:
Static YAML ladder under `assets/analytics/scores/` (repo root). Defines ordered **inference tier policy** steps: per-axis tech-level allowlists, aggregate allowlists and caps, `alpha`, beam/launcher slot-count widening at named steps, and flags such as use-player-active-lists. Loaded at solve time via `resolve_tier_policies`. Step-local runtime widens (e.g. `includeComponentIds` for **hull collision twin** admission) apply after load; there is no global resolve-time **inference tier policy overlay** (#78 cancelled). Not mixed with storage seed fixtures.
_Avoid_: tier_policy.yaml (filename in prose only when citing path)

**Inference build prior**:
Population-level weights that feed **inference solution rank weight** via additive log-probability composition at catalog-build time. The **inference build prior asset** (selected by **inference game category**) stores **un-normalized empirical count distributions**; a runtime step converts counts to integer log-probability weights when the catalog is built for a solve. Ship builds compose as `log P(hull) + log P(components | hull category) + optional sparse overrides`; aggregate actions use histogram-derived magnitude-bin distributions. Within each asset, partition keys: **inference ship-limit band** on all families; **race** modifiers on hull marginals only. Distinct from **inference fleet probability overlay** (#87).
_Avoid_: probability score, prior_weights.yaml (filename in prose only when citing path)

**Inference fleet probability overlay** (#87):
Per-player, per-solve adjustments merged on top of **inference build prior** weights at catalog-build time (log-additive). Primary use: suppress **inference torpedo load noise** via **inference torp misalignment penalty** on `ship_torps_loaded_{id}` when torp id ∉ **inference fleet launcher belief set**; also **inference component tech-gap prior** on ship-build combos. Does not replace static priors or change hard constraints. Works with **inference aggregate admission** (belief-set narrowing on early torp tiers). Tuning constants for fleet torp ranking may live in the **inference tier policy asset** YAML for operator convenience.
_Avoid_: fleet prior (unqualified), fleet penalty channel

**Inference torp misalignment penalty**:
Fixed log-space down-weight (v1: one constant for all non-belief torp types) applied to active `ship_torps_loaded_{id}` bins when the torp id is outside the **inference fleet launcher belief set**. Also applies to every torp type when the belief set is empty and types appear on **inference torp escape tier**. Tunable via **`fleetInferenceTuning.torpMisalignmentLogPenalty`** in the **inference tier policy asset** YAML. Goal: non-belief torp padding ranks below plausible ship-build explanations in top-K unless it is the only feasible closure.
_Avoid_: per-torp-type penalty table (v1), distance-aware torp penalty (v1)

**Inference fleet inference tuning**:
Operator-tunable ranking constants in the **inference tier policy asset** YAML (`fleetInferenceTuning` block). v1 fields: `torpMisalignmentLogPenalty` (**inference torp misalignment penalty**, #87), `componentTechGapLogPenaltyPerLevel` (**inference component tech-gap prior**, #156). Colocated with the ladder for easy tuning without a second asset.
_Avoid_: overlay YAML file, hardcoded solver constants

**Inference fleet launcher alignment**:
The rule that aggregate torpedo-load explanations should prefer torpedo types fitted on ships the player is believed to own -- from **fleet observed ship** sightings and **fleet inferred acquisition** rows (scores inference), not sightings alone. `torpedoid` / launcher type on a fitted ship is the alignment key. Loading a torp type with no matching launchers in that belief set is very unlikely but not impossible. When the belief set is empty (no launcher-fitted ships yet), early tiers admit no torp-load actions and the **inference fleet probability overlay** applies the same strong down-weight to every torp type when they unlock on a later escape tier. When non-empty, early torp-admitting tiers materialize only belief-set types; others unlock on escape tier with strong down-weight. Ambiguous **fleet build option set** rows are handled separately (see grilling / #87); they are not excluded just because launchers are not **known** from a sighting.
_Avoid_: torp compatibility filter (generic), turn-1 special case, known-sighting-only launcher histogram

**Inference fleet launcher belief set**:
The torpedo type ids counted as "in fleet" for **inference fleet launcher alignment** and **inference aggregate admission** -- derived from prior-turn fleet exports feeding #87. Includes launcher types on inferred builds (scores-held solutions), not only **known** launchers from direct sightings. For ambiguous **fleet build option set** rows, the belief set is the **union** of launcher/torp ids across all option sets on active rows (consistent tuples only, no per-field Cartesian product). Empty when no active row carries a positive launcher/torp type in any option set.
_Avoid_: launcherTypes (wire field name in prose unless citing path), known-only fleet composition, top-1 option set only

**Inference fleet torp input status**:
Provenance label on scores inference `complete` diagnostics (`diagnostics.fleetTorpInputStatus`) for whether prior-turn fleet overlay input was authoritative when a row finished: `not_applicable` (host turn 1), `pending` (prior-turn RST present but `fleet@(host_turn - 1)` not yet terminal when the row's first `tier_solve` wire was built), `applied` (overlay taken from completed `fleet@(host_turn - 1)` on the orchestrator **dependency outputs** slice), `unavailable` (fleet services missing). Distinct from row `displayStatus` / solver completion. When `applied`, `diagnostics.fleetTorpOverlay.beliefSetTorpIds` may list the belief-set torp ids used. Stream open kicks orchestrator `background`-band `fleet@(host_turn - 1)` submissions per player instead of ad-hoc warm threads; first-pass rows may still run tiers with `pending` overlay. When `fleet@(host_turn - 1)` completes, fleet invalidation epoch discards in-flight `scores@host_turn` work for that player and the adapter reschedules so later `tier_solve` wires read overlay from **dependency outputs**; a later `complete` can report `applied` without reconnect. SPA shows a scope banner and badge affordance while any row is `pending`.
_Avoid_: conflating with build-inference row pending/searching, calling `ensure_fleet_export` inside `tier_solve` workers, treating `ConflictError` as two different fleet states

**Analytic compute node**:
One DAG vertex of analytic work at a **compute scope** (see **Compute scope**). For row-scoped exports this is typically `(analytic_id, game_id, perspective, turn, player_id)`. A node completes only when its registered step(s) signal terminal success -- for scores inference, one `scores@t,P` node runs the full **inference search tier** ladder as repeated **compute step** continuations before persist. Execution scheduling, parallelism, and step continuations are defined in [design-compute-orchestrator.md](docs/design-compute-orchestrator.md) ([#190](https://github.com/SteveDraper/Planets-Console/issues/190)).
_Avoid_: perspective-batch materialization for one-player ensure, treating all-roster snapshot completeness as one player's cache hit, completing the node after one tier when the ladder is unfinished

**Compute scope**:
Canonical identity for one cacheable orchestrator work unit: `analytic_id`, `game_id`, and per-analytic scope axes (`perspective`, `turn`, `player_id`, each concrete or **WILDCARD**), plus optional sorted **parameters** fingerprint (e.g. connection options). Declared per analytic via `ScopeKeySpec` on registration. Export `ExportScope` is the row-scoped projection used by cross-analytic query. See [design-compute-orchestrator.md](docs/design-compute-orchestrator.md).
_Avoid_: using nullable axes alone without WILDCARD semantics; duplicating connection options in memo keys outside declared parameter_fields

**Compute orchestrator**:
Core API unified execution layer: one process-wide scheduler owning the dependency DAG from `ENSURE_DEPENDENCIES`, singleflight (`attach_inflight`), declarative step backends (`inline`, `thread`, `interpreter`, `process`), global priority pool, job wire with explicit dependency outputs, and epoch-checked persist coordination. Analytics own persistence policy hooks. Duplicate work for the same **compute scope** is deduped only by in-orchestrator singleflight -- not by a separate process-wide scope lease across multiple orchestrator bindings. When a higher-priority **compute request** attaches to an in-flight node (for example `stream_attached` joining `background` warm), the node's priority band may adopt upward under the same not-yet-executing rule the former scope lease used. Callers submit **compute request**s; orchestration-plane work (wire build, ensure/materialize side effects, `invalidation_generation`, `persist`) uses a per-node retained **orchestration bundle** from the submitting leader -- analytic export service injections and ensure-memo ownership -- not a long-lived bound **analytic query context** and not into parallel compute workers. The bundle outlives the submitting stream session: stream teardown unregisters listeners and gates only; in-flight **analytic compute node**s keep their bundle until terminal. Table-stream adapters attach via process-wide observer registration on the singleton (scoped filters in the listener), not by owning a per-stream orchestrator instance. Perspective-visible turn loading is keyed by `(game_id, perspective)` / shell, not by which caller submitted; the orchestration-plane turn cache is process-wide and keyed by `(game_id, perspective, turn)`. Fleet ledger persist notifications correlate to in-DAG completion via **compute scope** and materialization/generation identity, not `AnalyticQueryContext` object identity. A request may name an entry `step_kind` so one registration profile serves multiple callers (e.g. scores `materialize` for export ensure, `tier_solve` for inference stream). By default duplicate submissions reuse terminal (`complete`/`failed`) node outcomes; `force_fresh=True` supersedes terminal nodes and re-plans the DAG without breaking singleflight for in-flight work. Repeatable step kinds (scores `tier_solve`) re-queue the same step until the result wire signals terminal completion; `step_index` counts within-node executions for pool fairness. Each step returns a **compute step outcome** on the result wire: `continue` (re-queue same step), `persist` (invoke analytic `persist` then complete the node), or `complete` (terminal node completion without `persist`). Analytics own what `persist` writes and how readers gate on terminal quality (e.g. fleet `provenance.is_final`, scores persistable statuses only). North-star uniform compute API for ensure, streams, table/map compute, BFF, and MCP. [design-compute-orchestrator.md](docs/design-compute-orchestrator.md), [ADR 0005](docs/adr/0005-compute-orchestrator.md).
_Avoid_: per-analytic worker schedulers as the platform model; one orchestrator instance per stream / **analytic query context**; process-wide scope lease / `parked` cross-binding claims once a single DAG owns singleflight; `ctx.query()` inside parallel workers; orchestrator-owned persistence schemas; assuming every submission runs from profile step 0 when callers need a later step_kind; completing a node after one repeatable step when the ladder is unfinished; always calling `persist` on every pool step completion; holding the orchestrator lock across `pool.submit`, job-wire builders / inline execution, or `PersistencePolicy.persist` (deadlocks with pool→diagnostics controller and with inference scheduler→orchestrator); stamping fleet persist notifications with `id(AnalyticQueryContext)` as causal origin

**Compute step**:
One schedulable pool unit inside a **compute node** (e.g. one **inference search tier** execution for scores, fleet one-turn materialization leg). A **compute step continuation** is the next pool submission for the same node after the prior step returns (e.g. scores tier *n+1*). For repeatable step kinds such as scores `tier_solve`, the orchestrator re-queues the same `step_kind` until the result wire signals terminal completion; `step_index` counts executions within the node (0 = tier-1, greater = continuations) for pool fairness. Backend declared on `ComputeStepSpec`; not hardcoded in orchestrator.
_Avoid_: one pool job spanning multiple compute nodes; blocking ensure inside pool workers; treating `step_index` as index into a fixed multi-entry profile when the ladder length is dynamic

**Fleet gap-fill coordinator** (#161, per-player scope #179, epoch abort #233):
Per-`(gameId, perspective, playerId)` singleflight around multi-turn fleet ledger materialization so concurrent callers for the **same player** (fleet table tile, scores ensure, inference stream prior-turn fleet warm) share one in-flight unwind. Exposes an **epoch** aligned with fleet invalidation generation; mid-chain generation bumps abort the leg with `FleetGapFillEpochInvalidated` (no sync rematerialization spin). Orchestrator discards/re-queues on epoch mismatch; `ensure_fleet_export` returns unsatisfied so a later submit can complete when scores evidence is stable. Waiters short-circuit on a peer-written ensure-final ledger. Forward unwind runs `scores@t,P` before `fleet@t,P` for each gap turn. See [design-fleet-analytic.md](docs/design-fleet-analytic.md) section 5.1.
_Avoid_: treating non-final fleet provenance as ensure-complete after epoch abort; spinning N synchronous gap-fill rematerializations on one worker
_Avoid_: semantic merge of competing fleet snapshots, cross-process locking, `iter_turn_players` inside a single-player coordinator unwind

**Inference fleet launcher option ambiguity** (#87):
When top-K inference yields multiple **fleet build option set**s on one row, early torp admission uses the full belief-set **union**; types outside the union defer to escape tier and receive strong prior down-weight. Types inside the union keep population prior; types appearing only in non-top-rank alternates may receive an optional mild log down-weight vs top-default option sets. Top-1-only admission is not used.
_Avoid_: reconcile before overlay, independent per-field launcher unions

**Inference component tech-gap prior**:
Fleet-informed log-prior reduction on ship-build combo components whose catalog **techlevel** exceeds the per-axis fleet ceiling derived from the **inference fleet launcher belief set** generalized to all component axes. For each axis (`hulls`, `engines`, `beams`, `launchers`): collect component ids from active rows (sightings plus all **fleet build option set** tuples on inferred rows), take the max `techlevel` in the turn catalog as the ceiling; omit an axis with no ids (no gap penalty on that axis). Penalty sums per fitted component: `componentTechGapLogPenaltyPerLevel * max(0, component_tech - ceiling)` from **`fleetInferenceTuning`** in the **inference tier policy asset**. No positive histogram boosts beyond **inference build prior**.
_Avoid_: tech unlock prior, fleet histogram boost, hull-id ceiling (use tech level)

**Inference aggregate admission** (fleet-informed, #87):
On **inference search tier** steps that admit template torpedo-load actions (`ship_torps_per_type`), restrict which `ship_torps_loaded_{id}` catalog members are materialized to torpedo types in the **inference fleet launcher belief set**. Empty belief set: early torp-admitting tiers materialize **none**; **inference torp escape tier** admits all `eligible_torp_ids`. Non-empty: early tiers admit belief-set types only; non-belief types unlock on escape tier. Absent overlay behaves like empty belief set. Belief set includes inferred launcher types from scores, not sightings-only.
_Avoid_: torp allowlist (without "inference"), turn-1 fallback to full admission

**Inference torp escape tier**:
The **inference search tier** policy step (penultimate on the ladder, still `alpha > 0`) where non-belief torpedo types first enter the catalog alongside belief-set types -- before `full_catalog_exact`. Unlocks torp-load explanations that need types outside the **inference fleet launcher belief set** while band retry remains available. Distinct from the first torp-admitting tiers (belief-set only or none when belief set empty).
_Avoid_: full_catalog_exact as first non-belief unlock

**Game category** (`api.concepts.game_category.GameCategory`):
Immutable label for a class of games (e.g. campaign, standard, epic, blitz) derived from loaded game settings via `GameCategory.from_game_settings()`. Used among other consumers to select which **inference build prior asset** the console loads. Ordered predicates in Core (first match wins): `campaignmode` → campaign; else `endturn <= 30` → blitz; else `shiplimit >= 500` → epic; else standard. Categories have stable unique identifiers; once defined they do not change meaning. If no asset exists for the resolved category, fall back to the `standard` asset. Separate assets per category avoid runtime cross-partition overhead.
_Alias_: inference game category (prior-weights context only)
_Avoid_: game mode (unqualified), gametype int alone (wire field -- not the category id unless a rule maps it)

**Inference prior mining patterns config**:
Committed YAML pattern files under `assets/analytics/scores/` (e.g. `prior_mining_patterns_standard.yaml`) listing **inference prior mining pattern** rows per category or run. CLI requires `--patterns` pointing at the file for that run.

**Inference prior mining pattern**:
One declarative row in the prior-miner config (replacing a hand-maintained game-id manifest). Required stable **`id`** (unique in file; used in miner report provenance). **`earliest_date`** in config uses ISO calendar date (`YYYY-MM-DD`) compared against upstream `datecreated` after parsing host date strings. Fields: **game category** id (must match `GameCategory` / `from_game_settings`), **max games** total cap for that pattern across all incremental runs (not a per-run batch), **minimum difficulty** (`Game.difficulty` from upstream list/loadinfo), and **earliest date** (`datecreated` lower bound). The miner calls Planets.nu **`GET /games/list`** (finished games, public scope), filters candidates client-side, then **`loadinfo`** per survivor to resolve category via `GameCategory.from_game_settings` (list payload lacks `settings.endturn` / `shiplimit` / `campaignmode`). Discovery stops for that pattern when `max games` ids that pattern has contributed are recorded (per-pattern provenance in miner report; optional pattern-keyed metadata in asset). The asset holds one global **inference prior contributing games** list for dedup -- any id already present is skipped by every pattern. Patterns targeting the same category file have **independent** `max games` caps (e.g. two `standard` patterns may contribute 30 + 20 distinct games). Newly mined ids are loadall-processed and counts merged into the category asset. Candidate ordering after filters: **`dateended` descending** (newest finished games first), tie-break **`game.id` ascending** for determinism.
_Avoid_: static game-id manifest as the primary input, inferring blitz/epic from `gametype` alone

**Inference prior contributing games**:
Ordered list of game ids already folded into a **inference build prior asset** for a category, stored as **`contributingGameIds`** (camelCase) in the asset YAML. Monotonic: miner appends on merge, never removes. Incremental runs skip these ids so observations are not double-counted. Parsed into `PriorWeightsAsset` as metadata; **ignored** by `resolve_prior_weights_catalog` (provenance only, not prior weights).
_Avoid_: implicit full re-sample every run without provenance, using contributing ids as Laplace table keys

**Inference prior player-host-turn**:
The atomic traversal unit for **inference prior miner** sampling: one `(game_id, player_id, host_turn N)` where turn documents `N` and `N+1` exist at the owning player's **perspective** slot (`GameService.perspective_for_player_id`), the player is not eliminated on or before turn `N+1` (`is_eliminated_at_turn` / `last_meaningful_turn`), and **inference ship-limit band** is derived from turn `N+1` (score turn), matching `InferenceObservation.is_after_ship_limit` at solve time. From each unit the miner may emit **inference prior ship-build observation**s (order on `N`, validate on `N+1`) and per-action aggregate histogram increments on `(N, N+1)`. Aggregate sampling is a **single traversal**: for every aggregate action id, compute the inventory delta on that unit (0 when none) and increment that histogram key -- including `0:` for zero-delta turns. **Unconditional marginal:** v1 mining does not condition on asset ownership or other per-turn feasibility predicates; every aggregate action is sampled on every unit (still excluding eliminated players via the player-host-turn definition). The solver applies the same static prior whenever an action enters the catalog (tier allowlist + residual bounds -- not ownership); mined marginals match that contract. Runtime conditioning (e.g. fleet-informed masks) is a follow-on overlay (#87), not a mining-time filter. Trade-off: marginals dilute `0:` with turns where the action was physically impossible (e.g. pre-starbase), which slightly cheapens occurrence when the action later enters catalog -- accepted for v1 in favour of avoiding eligibility/catalog drift. **Adjunct exclusion:** skip player-host-turns classified `adjunct` by the inference corpus complexity signals (losses, trades, unmodeled military swing, etc.) for both aggregate and ship-build sampling; remaining turns still use unconditional per-action marginals. Skipped counts appear in the miner report. Not one row per perspective slot (avoids double-counting); not omniscient multi-perspective merge (regression corpus adjunct territory).
_Avoid_: corpus case (regression harness id), scoreboard row (solve-time observation grain)

**Inference build prior asset**:
Static YAML under `assets/analytics/scores/` holding un-normalized count tables for hull marginals, **inference conditional component prior** cells, and **inference aggregate prior** histograms. One file per **inference game category** (e.g. category id in filename). At catalog-build time the console resolves category from the loaded game, loads the matching file, normalizes each table with Laplace smoothing (`alpha = 1`), converts to integer log-probability weights, and composes additively in log space for ship combos. Real freighter hull ids stay in the asset; Core collapses eligible true-freighter hull counts into the solver's generic freighter combo during catalog resolution. v1 hand-seeds pseudo-counts; structure accepts mined replacements without solver changes.
_Avoid_: normalized probabilities in the asset, hardcoded weights in Python, single monolithic asset for all game types

**Inference hull category**:
A role label derived from hull characteristics and build configuration (not a hand-maintained hull-id table) that keys **inference conditional component prior** cells. Assignment uses priority predicates with sparse hull-id overrides (`concepts/` or equivalent). v1 categories:

| Category | Predicate (summary) |
|----------|----------------------|
| **true freighter** | No fighter bays, beams, or launcher slots |
| **weaponless hull** | Has weapon slots but built empty (counts as freighter on scoreboard; Fed refit relevance) |
| **alchemy ship** | Override / `special` (explicit rules) |
| **carrier** | `fighterbays > 0` |
| **battleship** | `beams > 0`, `launchers > 0`, and `mass >` fixed hand-tuned constant in Core (v1; verified against anchor hulls in the standard roster) |
| **torpedo ship** | `launchers > 0` (beams allowed) |
| **beam-ship** | `beams > 0`, `launchers == 0` |
| **utility** | Sparse overrides only; priority list should not reach this in normal cases |

`techlevel` is not a category axis in v1. Shared resolver lives in Core (alongside hull classification helpers), not in the prior YAML.
_Avoid_: hull class (unqualified), ship type preset, freighter (unqualified -- use **true freighter** or **weaponless hull**)

**Inference conditional component prior**:
Un-normalized count distribution over engine, beam, torpedo type, and slot-fill pattern conditioned on `(inference hull category, inference ship-limit band)`, composed additively in log space into each **ship build combo**'s rank-weight contribution at catalog-build time. Race-agnostic in v1 (pooled across races).
_Avoid_: combo prior, factored weight table

**Inference aggregate prior**:
Un-normalized count distribution over aggregate inference actions, stored as raw magnitude histograms in the **inference build prior asset**. Mined keys are **observed integer deltas**: `0:` for zero occurrence samples; positive keys are the raw load/build total for that player-host-turn (loader maps into fixed **probability bucket** ranges via `magnitude_bin_index` at catalog build -- miner does not pre-bin). Fighter transfers are occurrence-only 2-bin histograms (`0:` plus `1:` for any positive transfer). There is a single histogram shape (the degenerate `counts` shape was removed); an optional `0:` key carries the **inference occurrence prior (none bin)**. At catalog-build time the loader aggregates histogram counts into the solver's fixed **probability bucket** ranges (including the leading `none` bin) and converts via the same Laplace log rule as other tables. Partitioned by **inference ship-limit band**. v1 hand-seeds use pseudo-counts on histogram edges chosen so runtime bucketing reproduces intended modest/heavy/extreme ratios (mapping is not unique), plus a computed `0:` occurrence seed. Fighter transfers are occurrence-only 2-bin histograms. Mined from per-turn-player inventory-delta observations.
_Avoid_: bin-level-only asset (without histogram layer), per-unit aggregate weights

**Inference hull marginal prior**:
Un-normalized count distribution over real hull ids for **inference prior ship-build observation** mining, including actual freighter hull ids. Partitioned by **inference ship-limit band**; optional per-race count slices in the asset schema, with global pooled tables as default and sparse per-race rows for race-exclusive or strongly race-characteristic hulls. v1 hand-seeds global + overrides only; full race-stratified tables filled by mining later. Component conditionals do not cross race. Solver-only compression rows, such as the generic freighter combo, are derived from these real hull counts at catalog build and do not appear as synthetic hull ids in the asset.
_Avoid_: race-conditioned engine priors (v1 -- see fleet overlay #87)

**Inference ship-limit band**:
Coarse partition for **inference build prior** tables: whether ship-limit queue rules apply on the observation turn (`before_ship_limit` vs `after_ship_limit`). Derived from the same signal as `InferenceObservation.is_after_ship_limit` (game-total or per-player limit per `shiplimittype`). All prior families -- hull, component, aggregate -- split on this band in v1.
_Avoid_: turn band, early/mid/late game (for priors v1)

**Inference prior miner**:
Offline pipeline (#92) driven by **inference prior mining pattern** config, upstream game discovery, and turn extraction; writes **inference build prior asset** count YAML with **inference prior contributing games** provenance. Incremental runs **merge in place** into `assets/analytics/scores/prior_weights_{category}.yaml` (add histogram/hull/component counts, append new game ids); `--dry-run` emits discovery/mining report only. Extraction and accumulation live in Core under `api/analytics/military_score_inference/prior_mining/` (unit-tested, importable). A thin Typer CLI in `scripts/` (pattern: `run_inference_corpus.py`) configures file storage (`--storage-root`), invokes the miner, and writes output. For each newly discovered game: **`loadall`** via `PlanetsNuClient`, import through existing loadall archive parsing into storage, then extract from `TurnLoadService`; skip download when storage already has a complete finished-game turn set for that id. Shared inventory-delta helpers move from the inference corpus harness into Core as part of this work; ship-build validation uses starbase order + T+1 spec match only (not corpus inventory-diff ship detection).
_Avoid_: tests-only miner (regression harness pattern), BFF route for mining

**Inference prior ship-build observation**:
One counted ship build for **inference build prior** mining. On turn *T*, take a player-owned **starbase** with `isbuilding == true` and read its build order (`buildhullid`, `buildengineid`, `buildbeamid`, `buildtorpedoid`, `buildbeamcount`, `buildtorpcount`). On turn *T+1*, validate by a **new** ship (ship id absent on turn *T*) at that starbase's planet whose fitted spec **exactly matches** the order. Reject pre-existing ships that moved to the same coordinates with an identical spec. Excludes inventory-diff detection (trades, destruction noise) and unvalidated queued orders. Distinct from inference corpus inventory ground truth (#64).
_Avoid_: new ship diff, build queue snapshot alone, hull-only match

**Inference solution streaming**:
NDJSON wire protocol (**#71**, Phase 1H). The SPA opens **one multiplexed table stream** (`GET .../inference/table-stream`) for all scoreboard rows on the current shell scope; events carry an optional `playerId` tag (except `globalPause`). Emits whenever a **new** **inference explanation signature** is admitted to **inference merged top-K** -- within-tier enumeration and cross-tier ladder progress -- so the dashed-zero badge transitions to a solid count before top-K is full. Admission is incremental-only: the solver `on_solution` callback merges into held top-K; there is no post-solve re-merge. Each `solution` event carries the **full held top-K** for that row (ranked by **inference solution rank weight**); the consumer replaces local held state from the event (no client-side merge). Follows the load-all progress stream pattern (Zod-owned events). Batch JSON remains for the inference corpus harness. On stream open, rows with valid **scores inference row persistence** are **replayed on the stream** as a single terminal `complete` event (with full held solutions embedded) -- not a full `solution` history -- and are not scheduled for new tier jobs. Rows without valid persistence are scheduled normally. **Stream disconnect** is detach-only for scores row shells (in-flight DAG work may finish and late-persist); it clears **inference global pause**. Persisted terminal rows survive disconnect for later replay. Explicit cancel (scope change, disable build inference, recompute) aborts in-flight work -- see **inference stream cancellation**.
_Avoid_: websocket inference

**Inference table stream**:
Single NDJSON connection for all scoreboard rows on one game / turn / **perspective** scope. The backend multiplexes per-row scheduler event queues onto one wire; the frontend demuxes on `playerId`. Chosen over parallel per-row HTTP connections so **inference global pause** can freeze all rows on one scope without juggling N client abort controllers. The build-inference column header hosts the global pause control. After singleton orchestrator migration (**#209**), streams register process-wide **scope-outcome listeners** and dispatch gates on the one **compute orchestrator** (unregister on disconnect); they do not own an orchestrator instance. DAG submissions use that singleton; teardown detaches row shells and observers without cancelling in-flight solve tokens. Cancel / detach / persist / drain ownership: [ADR 0006](docs/adr/0006-table-stream-lifecycle-invariants.md).
_Avoid_: turn-level inference job queue in the SPA, per-stream orchestrator binding

**Inference global pause**:
User-initiated **soft** freeze of build inference for the current shell scope (game, turn, **perspective**) **while the inference table stream is connected**. **Pause** broadcasts `globalPause` on the open stream and blocks new `tier_solve` **compute step** dispatches via an orchestrator **dispatch gate** (adapter pause state checked before `_submit_pool_step` for `stream_attached` `tier_solve`); deferred tier-1 and continuation steps stay in the adapter **inference row run** held buffer. **In-flight `tier_solve` pool work already running continues until the current tier step completes** and may still emit `solution` events. Rows already held in top-K stay visible with `paused` chrome. **Resume** requeues held tier work through the orchestrator on the same connection. Background-band fleet warm and gap-fill `materialize` / fleet legs are not gated by inference pause. Open streams drive the pause-control chrome via `globalPause` events (single source of truth with REST pause/resume). **Stream disconnect** clears server-side global pause and **detaches** row shells (does not cancel solve tokens or abort DAG nodes); reconnect may replay persisted terminals and re-adopt or reschedule remaining rows. Implicit scope change **cancels** in-flight work (distinct from disconnect).
_Avoid_: confusing global pause with implicit stream cancellation, treating disconnect as cancel, adapter-only submission gates that miss orchestrator-driven tier continuations

**Inference row run**:
Per-scoreboard-row mutable ladder state for one open **inference table stream** row: `PolicyLadderState`, optional accelerated-admission **inference stream orchestration**, and held tier work while **inference global pause** is active. Owned by the inference stream adapter (successor to **inference row scheduler**), keyed by `run_id` and linked to one `InferenceRowStreamSession` for wire events. Orchestrator `tier_solve` steps resolve the row run by `run_id` on the job wire; ladder progress stays in the adapter between **compute step** continuations on the same `scores@t,P` **analytic compute node**. Stream detach retains the shell as `DETACHED` for late persist; cancel drops the shell and records compact `CANCEL_DENY` admission ([ADR 0006](docs/adr/0006-table-stream-lifecycle-invariants.md)).
_Avoid_: storing ladder state only on serializable job wire, orchestrator-owned session/event queues

**Inference row scheduler**:
Thin stream adapter (**#200**) over the process-wide **compute orchestrator** for the active **inference table stream**. Retains scope guard, per-row **inference row run** registry, **inference global pause** dispatch gate, and stream event emission via orchestrator **scope-outcome listeners**; submits orchestrator `tier_solve` **compute step**s instead of draining a private worker queue. Terminal row persistence is owned by **`ScoresPersistencePolicy.persist`** gated by **`PersistDecision`**, not adapter callbacks (fleet-aligned). One schedulable step = one full **inference search tier** for one scoreboard row. Cross-row tier-1-before-continuations fairness moves to the global orchestrator pool. Soft non-durable terminals **park** the DAG node (scores-owned wake); they do not hot-continue. The legacy private `threading.Thread` worker pool and `_work_queue` dequeue path are removed.
_Avoid_: frontend job queue, per-solve queue jobs, treating the adapter as the platform scheduling model, per-stream orchestrator instance

**Inference solve interrupt boundary**:
Where stream **cancel** (scope change, disable build inference, explicit abort) and **inference global pause** can take effect without losing tier progress. Disconnect is **not** this boundary -- disconnect detaches shells and leaves in-flight tokens alone. v1 (**#71**): cooperative checks at sub-step boundaries inside a tier job -- top-K no-good iterations, seed attempts, exact vs band passes -- plus `StopSearch()` in a CP-SAT callback when cancel fires mid-`Solve()`. OR-Tools CP-SAT cannot resume internal search state across `Solve()` calls; only complete solutions can warm-start the next pass via hints. **Known gap:** a single long first-feasible `Solve()` on a huge catalog may block cancel until that call returns. **Follow-on (if needed):** retry `UNKNOWN` sub-steps until feasible or cancelled (logical continuation; CP-SAT restarts internally each retry).
_Avoid_: routine short-solve slice loops (wastes search), assuming CP-SAT pause/resume, treating disconnect as cancel

**Inference solution count indicator**:
Per scoreboard row chrome replacing the binary green tick: a green outlined badge showing **N** = the number of rows currently held in **inference merged top-K** (not cumulative discoveries above K). While search is in flight and **N = 0**, show a **dashed-border badge with 0** (same count-badge chrome, not a separate hourglass icon); in-progress search adds an animation affordance on the badge. When **N > 0**, use a solid border; **N** rises toward K then plateaus while eviction swaps membership. Red cross when the row completes with no exact explanation. Global pause/resume is controlled from the column header only. Click on the badge (or row chrome when **N > 0**) opens the ranked modal.
_Avoid_: green tick, checkmark column

**Accelerated-start inference row** (SPA):
A scoreboard row whose host turn falls in an accelerated-start window may run multiple internal **inference accelerated segments** (accel window + reported host turn). v1 **#71** uses the same table-stream scheduler path as other rows; segments stay inside the row's inference path with no per-segment SPA time split (natural completion or implicit stream cancellation ends the row). The **inference solution detail modal** uses only the top-level row payload for the segment matching that scoreboard row; `diagnostics.accelerated_segments` is internal and appears in the Scores diagnostics panel, not in the modal.
_Avoid_: per-segment stream, segment-level halt (v1), accelerated modal sections

**Inference stream cancellation**:
Abort of in-flight build inference when the shell scope changes (game, turn, **perspective**), build inference is disabled, or an explicit cancel/recompute path runs. There is no per-row halt control in the SPA; use **inference global pause** to freeze all rows while the stream stays open. **Cancel** (not disconnect) drops the scores row shell, records compact `CANCEL_DENY` persist admission, seals stream drain, cancels the session token, and aborts the orchestrator scope -- late persist must refuse. **Stream disconnect** is detach-only: shells become `DETACHED`, solve tokens stay live so workers may finish and late-persist, and server-side **inference global pause** clears; **scores inference row persistence** retains completed rows for replay on reconnect. Rows without a valid persisted terminal state still recalculate from scratch after cancel or fresh schedule. A terminal wire `complete` with `status: stopped` may carry the last held top-K on the way out without persisting it. Distinct from failure (`no_exact_solution`, solver error), from natural completion (`exact` when final-catalog equalities pass), from soft **park**, and from **inference global pause** (all rows frozen on an open stream, resumable via the column header). Ownership matrix: [ADR 0006](docs/adr/0006-table-stream-lifecycle-invariants.md).
_Avoid_: per-row halt (removed from SPA), treating disconnect as cancel, time_limited (as the primary SPA stop mechanism)

**Scores inference recompute**:
Explicit user action (control in the **Scores** build-inference column header, beside **inference global pause**) that forces a fresh **military score build inference** run for every scoreboard row on the current shell scope. Invokes `POST .../inference/recompute` on the BFF/Core path: clears **scores inference row persistence** for the current **inference host turn**, clears **inference global pause** if active, and **in-place full-table reschedule** on the open **inference table stream** -- not a client-side stream abort or `refreshInference()` token bump. Rows return to in-progress only via subsequent stream events. Distinct from mask-driven **in-place row reschedule** (one **Player**) and from automatic **scores inference row invalidation** on turn replace.
_Avoid_: `refreshInference()` stream teardown, recompute all as the only way to refresh after mask save, requiring resume before recompute

**Scores inference row invalidation**:
When a stored **scores inference row persistence** entry must be dropped or recomputed. v1 triggers: hull catalog mask save or reset for that **Player** (invalidates and **in-place row reschedule** on the open **inference table stream** -- cancel that row's tier jobs and enqueue fresh work without tearing down the stream or disturbing other rows); **turn document replace** at the shell **perspective** -- when **TurnInfo** is written to `games/{gameId}/{perspective}/turns/{T}`, delete inference persistence at `.../turns/{T}/analytics/scores` and, when *T-1 >= 1*, also `.../turns/{T-1}/analytics/scores` (pair-aware: host turn *T* uses turns *T* and *T+1*; host turn *T-1* uses *T-1* and *T*). Hook on any turn `put`, not only first-time ensure. If the open **inference table stream** is for a host turn whose persistence was just cleared, **in-place full-table reschedule** -- cancel all tier jobs on that stream and enqueue every scoreboard row (no cache replay). Turn writes for other host turns only clear persistence; they do not disturb an unrelated open stream. **Fleet ledger persist** at `fleet@(host_turn - 1)` for one **Player** also invalidates that player's `scores@host_turn` row: drop persistence, bump **scores** orchestrator invalidation generation (aligned with per-player fleet epoch), discard stale in-flight `tier_solve` work, and **in-place row reschedule** on the open stream. Mask overrides remain game-global. The SPA does not call full-table `refreshInference()` on mask save. User-initiated **scores inference recompute** is the supported full-table refresh path.
_Avoid_: full-table refresh on mask save, host-turn-only invalidation when the score turn is replaced, invalidating all perspectives when one turn reloads, aborting the table stream on hull mask edit, leaving in-flight stream rows stale after turn replace on the same host turn

**Inference host turn**:
The host turn whose activity is being explained. Scoreboard deltas are read from the **later** stored **TurnInfo** document (turn *N+1*); the **earlier** document (turn *N*) supplies inventory ground truth for complexity grading and Tier 2 checks.
_Avoid_: inference turn (ambiguous with shell **turn**)

**Inference corpus case**:
One scored test targeting one **Player** on one **inference host turn**, discovered when `games/{gameId}/{perspective}/turns/{N}` and `.../{N+1}` both exist. Default scope: the **Player** at that **perspective** slot (what that slot built on the host turn). Sparse and complete stores are both valid.
_Avoid_: scoreboard row test (too vague)

**Inference case complexity**:
An ordinal label (`minimal` through `adjunct`) for how hard a corpus case is to explain, derived from ground-truth inventory change between the paired turns for the case **Player** (ship builds, ammo and defenses, then adjunct effects such as trades and losses). **Adjunct** classification may require **multi-perspective ground truth** when an effect spans players (e.g. ship trades need every involved **perspective** stored). With sparse storage, classify from what the case **perspective** can see and treat missing cross-player views as unknown adjunct, not proven absence. Runners skip cases above `--max-complexity` with a recorded reason.
_Avoid_: turn band (unless explicitly mapped to complexity)

**Multi-perspective ground truth**:
Inventory truth for a corpus case assembled from one or more stored **TurnInfo** documents at the same host turn (and the following turn), merging visibility across **perspective** slots when adjunct or Tier 2 checks need events that no single slot sees alone.
_Avoid_: omniscient turn (informal)

**Inference corpus runner**:
Test-harness code (not shipped in the Core REST API package) that performs discovery, complexity grading, **catalog coverage**, case execution, and reporting. Two modes: **fixed corpus** (committed fixtures and manifest for CI) and **local corpus** (script `game_id` against a completed game in the **file backend** store). Invokes production inference via the **batch JSON** path (not the SPA NDJSON stream). **Orchestration-level** wall-clock caps (e.g. `--probe-time-limit-seconds`) stop the run between cases; per-case solver time limits remain on the batch path so CI and probes stay bounded after the SPA drops row time budgets. Probe options should surface `time_limited` outcomes and support deeper diagnosis of slow sub-steps (per-case time override, timeout-case filters, extended single-case reruns).
_Avoid_: inference integration test (implementation name)

**Ground truth explanation**:
The feasible action multiset inferred from inventory change between the paired turns for the case **Player** (exact by construction when adjunct effects are absent or fully visible). Used for **Tier 2 compatibility check** and for **top-K ranking** checks against solver output.
_Avoid_: true build (implies uniqueness)

**Structure build counter** (`builtdefense`):
Per-turn defense-post build count on a planet or starbase turn snapshot (`builtdefense` field). Resets across turn boundaries. For planetary defense **ground truth explanation**, sum on prior-turn owned planets is the authoritative build signal for that host turn -- not positive `Δdefense` on continuously owned planets (any scored build appears there).
_Avoid_: builtdefense drain (pairwise delta -- not the primary signal)

**Planet capture defense transfer**:
Defense posts credited or debited when planet ownership changes between the prior and score snapshots of a host-turn pair. Gained planets contribute standing `defense` on the score turn; lost planets debit prior `defense`. Distinct from **structure build counter** builds on continuously owned planets.
_Avoid_: Δdefense on owner totals (masks capture)

**Defense post ground truth (net)**:
Planet or starbase defense-post contribution for one host-turn pair: sum of **structure build counter** totals on prior-owned bodies, plus capture gains, minus capture losses (same three-component rule on starbase fields). May be **negative** when losses exceed builds. **Ground truth explanation** records the net faithfully (no clamping). When any defense-post aggregate count is negative, the **inference corpus runner** skips catalog coverage, **inference top-K ranking check**, and Tier 1 with skip reason `negative_defense_gt_pending_solver` while `groundTruthAvailable` stays true. Solver support for negative defense-post counts is a follow-on.
_Avoid_: clamping net defense to zero in extraction; `out_of_search_space` for known-good negative GT

**Tier 2 compatibility check**:
Independent ship-level re-verification that the **ground truth explanation** is consistent with **multi-perspective ground truth** inventory (when enabled). Enabled by manifest `tier: 2` or CLI `--tier 2`. Runs after catalog coverage, before the solver. Contradiction yields outcome `failed` (not `ranking_miss`). Skipped when **ground truth explanation** is unavailable.
_Avoid_: solver compatibility (Tier 2 does not compare to top solution)

**Inference top-K ranking check**:
Whether the **ground truth explanation** appears among the solver's top *K* ranked solutions (default *K* = 3). A miss yields outcome `ranking_miss` -- constraints satisfied but ordering may be wrong. Distinct from Tier 1 `failed` and from **out of search space**. On miss, per-case JSON may include `groundTruthRank` (1-based index in the full held list, or null when the GT multiset appears in no returned solution) and `topK`.
_Avoid_: best solution match (implies rank 1 only)

**Hard ranking policy**:
Manifest `requireTopK: true` or CLI `--fail-on-ranking-miss`. A **ranking_miss** under hard policy fails the run (exit code 1) while keeping outcome `ranking_miss` -- not reclassified as `failed`. Complexity-based auto-harden (`heavy` and above) is deferred; only explicit manifest or CLI flags harden in v1.
_Avoid_: hard fail (ambiguous with Tier 1 failure)

**Inference corpus case skip (pending solver)**:
Corpus outcome `skipped_pending_solver` when **ground truth explanation** is available but must not be compared to the solver yet (e.g. negative **defense post ground truth (net)** before the catalog admits negative defense-post counts). Sets `skip_reason` (e.g. `negative_defense_gt_pending_solver`); does not run Tier 1; not `failed` or **out of search space**.
_Avoid_: `passed` with only a skip_reason (hides the bucket), clamping GT to force coverage

**Catalog coverage** (inference):
Whether the **ground truth explanation** can be expressed using the solver's candidate **action catalog** for that turn (aggregate actions and ship-build combos, within bounds). If not, the case is **out of search space** -- a distinct outcome from solver failure; the runner should not treat `no_exact_solution` as a solver regression on that row.
_Avoid_: infeasible (ambiguous with CP-SAT status)

**Out of search space**:
Corpus case outcome when **catalog coverage** fails: the inferencer's modeled action inventory is incomplete for this host turn (deferred effect families, missing hull combo tier, bucket cap too low, etc.). Report separately from `skipped` (complexity cap) and from Tier 1 `exact` / `no_exact_solution`.
_Avoid_: unsupported (too vague)

### Observability

**Request diagnostics**:
Optional per-request timing and value trees collected server-side when BFF routes are called with `includeDiagnostics=true`. Core and BFF code attach sections via a shared **Diagnostics** protocol; the response may include a serialized tree. Disabled by default on normal SPA traffic.
_Avoid_: logging, tracing, metrics (generic observability)

**Diagnostics buffer**:
BFF in-memory ring of recent **request diagnostics** from instrumented calls. Served to the **Diagnostics modal** via `GET /bff/diagnostics/recent`; cleared on process restart.
_Avoid_: log buffer, audit trail

### Game concepts

**Game concept**:
Host-aligned rules, geometry, or static catalogs the console computes or holds -- warp wells, flare points, planet-connection reachability, race-specific numeric traits. Lives in Core `concepts/`; may be exposed as concept HTTP routes and reused inside **turn analytics**. Do not embed race-specific `raceid` constants or per-race mechanics inside analytic modules (e.g. accelerated-start scoreboard helpers); use **`api.concepts.races`** instead.
_Avoid_: domain service, utility module

**Turn-scoped concept**:
A **game concept** evaluated against a specific **TurnInfo** (e.g. whether a map cell lies in a planet's warp well). Routes include game id, **perspective**, and turn.
_Avoid_: per-turn helper

**Global concept**:
A **game concept** that does not depend on loaded game state (e.g. flare-point offset tables keyed by warp speed). Exposed under Core `/v1/concepts/...` without a turn path.
_Avoid_: static lookup, catalog endpoint

**Race-specific game concept**:
Planets.nu mechanics that depend on **`raceid`** (Evil Empire free starbase fighters, Fascist-only hull rules, and similar). Consolidated in **`packages/api/api/concepts/races.py`** -- constants, helpers, and settings-aware formulas. **Turn analytics** and inference catalogs import from there; they do not define new race ids or race-only numbers locally. Game-wide defaults (homeworld starting inventory, accelerated-start scoreboard baselines) stay in the module that owns that cross-race behavior (e.g. `accelerated_start.py`), not in `races.py`.
_Avoid_: scattering `raceid == 8` in `analytics/`, duplicating race tables per feature

**Connections engine**:
The public entry for planet-pair reachability in one turn (`connection_engine.py` under `planet_connections/`). The **Connections** turn analytic calls `connection_routes_with_options`; spatial index, annuli, and flare BFS stay private to the package.
_Avoid_: planet_connections module (when meaning the engine entry only)

### Storage

**Logical store path**:
A slash-separated key into the single logical JSON tree (e.g. `games/628580/1/turns/111`). All services read and write via these paths through **StorageBackend**.
_Avoid_: key, URL path (when meaning the storage address)

**StorageBackend**:
The abstract protocol (`get`, `put`, `delete`, `list`) that hides whether data lives in memory or on disk. Services never reference concrete implementations.
_Avoid_: database, file store (when meaning the protocol itself)

**Breakpoint**:
A declared point in the path hierarchy where persistence writes a separate JSON document. Logical paths at or below a breakpoint share that document until a deeper breakpoint splits again.
_Avoid_: shard key, partition (without "breakpoint" context)

**Document** (storage):
One JSON file on disk corresponding to a breakpoint path. Nested logical paths without an intervening breakpoint are stored inside the document, not as separate files.
_Avoid_: node, blob (when persistence boundary is meant)

**Ephemeral backend**:
The in-memory backend used for tests and dev; mutations do not survive process restart.
_Avoid_: temporary storage (ambiguous with session state)

**File backend**:
The durable **StorageBackend** that persists **documents** at **breakpoint** paths under a configured storage root. Local dev uses this; tests and CI default to **ephemeral backend**.
_Avoid_: persistent mode, disk backend (use backend id `file`)

**Breakpoint registry**:
The code-defined list of path patterns that declares where JSON documents begin. Kept in sync with service key conventions; not loaded from external config.
_Avoid_: storage schema file, boundaries YAML

**Registered path**:
A logical store path that matches at least one breakpoint pattern (longest matching prefix wins). Only registered paths may be read or written by the file backend; unregistered paths fail fast.
_Avoid_: valid key (too generic)

**V1 breakpoint patterns**:
- `games/*/info` -- **GameInfo** document
- `games/*/*/turns/*` -- **TurnInfo** document per **perspective** and turn
- `games/*/analytics/*` -- game-global **analytic persistence** document per analytic id
- `games/*/*/analytics/*` -- per-**perspective** **analytic persistence** document per analytic id (nested keys such as `evidence` live inside the document)
- `games/*/*/turns/*/analytics/*` -- per-turn **analytic persistence** document per analytic id (separate from the **TurnInfo** snapshot at the same turn path)
- `credentials/accounts/*` -- account record (e.g. api_key and future fields)

**Analytic persistence**:
Server-side cached output for a **turn analytic** that must not recompute on every request. Three tiers under the `analytics/` namespace (see [ADR 0002](docs/adr/0002-analytic-persistence.md)): **game-global** `games/{gameId}/analytics/{analytic_id}` (e.g. **Scores** hull catalog mask overrides); **perspective supplement** `games/{gameId}/{perspective}/analytics/{analytic_id}/...` (e.g. **homeworld locator evidence**); **turn-scoped supplement** `games/{gameId}/{perspective}/turns/{turn}/analytics/{analytic_id}` (one JSON document per shell turn and **perspective**, distinct from the **TurnInfo** file at `.../turns/{turn}`). **Homeworld locator** is the reference two-tier consumer; **Scores inference row persistence** is the first **turn-scoped** consumer.
_Avoid_: analytic cache at game root, `{gameId}/homeworld-locator`, nesting computed cache inside **TurnInfo** documents

**Scores inference row persistence**:
Server-side terminal **military score build inference** result for one scoreboard row, keyed by game, shell **perspective**, **inference host turn**, and target **Player** (`playerId`). Stored at logical path `games/{gameId}/{perspective}/turns/{turn}/analytics/scores/inference_rows/{playerId}` inside document `games/{gameId}/{perspective}/turns/{turn}/analytics/scores.json`. Durable payload is the functional row only: status, summary, solutions, and **host turn functional targets** -- enough to render the **Scores** table row and **inference solution detail modal** without reopening the scheduler. Solver **diagnostics** (including full action catalogs / ship-build combo lists) are wire and in-memory only and are not written to storage. Written only when a row completes with status **`exact`** or **`no_exact_solution`**; not written for `stopped`, `fetch_error`, immediate path terminals (`no_prior_turn`, `player_not_found`), or in-progress / `paused` rows. After orchestrator migration (**#200**), terminal `tier_solve` writes go through **`ScoresPersistencePolicy.persist`** (same pattern as fleet ledger persist); the inference stream adapter node-complete listener emits wire events only. Dropped or marked stale on **scores inference row invalidation**. Distinct from game-global hull catalog mask overrides at `games/{gameId}/analytics/scores/inference_hull_catalog_masks/{playerId}`.
_Avoid_: SPA-only inference cache, duplicating turn in the in-document key when the breakpoint already scopes by turn, persisting cancellation or transient error outcomes, adapter-owned terminal persist callbacks (legacy pre-#200), persisting full action catalogs or other solver diagnostics on disk

**Shallow store read**:
A read that returns only the **immediate child segment names** at a logical store path (e.g. game ids under `games`), not nested values. Used to enumerate stored games without loading full documents.
_Avoid_: directory listing, prefix scan

**Store root path** (`""`):
`list("")` returns top-level logical segments. `get`, `put`, and `delete` on the root path are rejected. All **StorageBackend** implementations must behave the same way.
_Avoid_: whole-store read (no aggregate root document)

**Backend conformance**:
Shared parametrized tests exercise the same **StorageBackend** contract against every implementation. Backend-specific tests cover only implementation details (deep copy, atomic write, prune, layout).
_Avoid_: duplicate test modules per backend (for shared semantics)

**Startup seed** (`include_dummy_data`):
When true, seed sample paths only if each target path is missing. Never overwrite existing documents. Same behavior for ephemeral and file backends.
_Avoid_: force seed, reset on boot

## Flagged ambiguities

**Officer Homeworld vs homeworld planet**:
- **Officer Homeworld** -- planets.nu account / campaign metagame; not a turn-map object.
- **Homeworld planet** -- the in-game starting planet for a **Player** slot; what the **homeworld locator** finds.

Use **homeworld planet** in Console prose and UI for map inference. Do not say "homeworld" alone when Officer Homeworld could be misread.

**Player vs perspective vs viewpoint**:
- **Player** -- the domain entity (name, race, scores) inside **GameInfo** / **TurnInfo**.
- **Perspective** -- the 1-based **slot number** used in paths and Core routes (`…/3/turns/111`).
- **Viewpoint** -- which **Player** the shell is showing, resolved to a perspective.

Use **perspective** in storage paths and API path segments; use **viewpoint** in UI copy; use **Player** when referring to model fields or upstream payload entities. Do not say "player 3" when you mean perspective slot 3 unless the prose explicitly ties slot to the `Player` record.

## Example dialogue

**Dev:** I'm wiring a new map analytic. What scope does it need?  
**Expert:** A **turn analytic** -- game id, turn, and **perspective** from **shell context**. The SPA must wait for **turn ensure** so **TurnInfo** is in storage before any analytic GET runs.

**Dev:** The header says viewpoint "Alice" but storage path uses `3`. Which is which?  
**Expert:** **Viewpoint** is the player name shown in the UI. **Perspective** is her 1-based slot (`3`). Core routes and storage paths always use the slot; the shell resolves name ↔ slot from **GameInfo** after refresh.

**Dev:** Where does turn 111 for game 628580 live on disk?  
**Expert:** Logical path `games/628580/1/turns/111` -- a **breakpoint** match -- so one JSON **document** with the whole **TurnInfo**. Settings under `games/628580/info/settings` share the same file as `games/628580/info` because there is no deeper breakpoint.

**Dev:** Should warp-well math live in the BFF or a new analytic module?  
**Expert:** In Core as a **game concept** (`api.concepts.warp_well`). **Normal** well cells ship on **base-map** nodes as `normalWellCells`; **hyperjump** stays on turn-scoped concept routes. The SPA renders server cells only -- no duplicate geometry in TypeScript. **Connections** uses the same module's reachability helpers.

**Dev:** Military score inference needs Evil Empire free fighter counts. Where do those live?  
**Expert:** In **`api.concepts.races`** as a **race-specific game concept** -- `raceid`, base free-fighter count, and `freestarbasefighters5adjustment` from settings. The inference action catalog imports the helper; it does not define Evil Empire constants beside accelerated-start or scoring code.

**Dev:** Can the frontend call `GET /api/v1/games/.../analytics/connections` directly?  
**Expert:** No. The SPA talks only to the **BFF**. Core owns **turn analytics**; the shell never bypasses that layer.

**Dev:** Game info lists a Player with `id: 42`. Is that perspective 42?  
**Expert:** No. **Player** ids come from the planets.nu payload. **Perspective** is the slot index (`1`..`11`) in path segments like `games/628580/3/turns/111`. Match name to slot via **GameInfo** player order, not via `Player.id`.

**Dev:** Turn ensure failed -- where should the message go?  
**Expert:** The **shell error bar**, not inline on the header control. Include which BFF endpoint failed so it is actionable.

**Dev:** Why does the map stay on the old turn for a moment when I step turns?  
**Expert:** **Map display retention** -- the SPA keeps the last displayable **combined map** mounted during reload so React Flow preserves zoom and pan. It clears on game or **perspective** change, not on turn step within the same viewpoint.

**Dev:** Connections feels slow -- how do I see where time went?  
**Expert:** Open the **Diagnostics modal**, enable session diagnostics, repeat the request. **Request diagnostics** on the BFF response populate the **diagnostics buffer** with section timings from Core **turn analytics** and concept code.
