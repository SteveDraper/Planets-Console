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
A registered analysis feature the user can enable -- tabular output, a map overlay, or both. Each has an `analytic_id`, Core computation, and BFF shaping for the SPA.
_Avoid_: widget, report, metric

**Turn analytic**:
An **analytic** computed from **TurnInfo** for a specific game, turn, and **perspective**. Invoked through the shared Core route `.../turns/{turn}/analytics/{analytic_id}` and corresponding BFF routes.
_Avoid_: query, dashboard tile

**Base map**:
The always-on map layer (`type: base`, id `base-map`) that renders planet nodes from **TurnInfo**. Fetched automatically in **map mode** and omitted from the analytics sidebar; other map analytics overlay it.
_Avoid_: background layer, planet layer (without "base map")

**View mode**:
Shell display mode for the main area: **tabular** (stacked analytic tables) or **map** (React Flow graph). Analytics grey out in the selector when they do not support the active mode.
_Avoid_: layout mode, display type

**Map layer**:
One analytic's contribution to the combined map graph -- nodes and/or edges merged with **base map** and other enabled map analytics via id-prefixing.
_Avoid_: overlay (acceptable informally; prefer map layer in docs)

### Observability

**Request diagnostics**:
Optional per-request timing and value trees collected server-side when BFF routes are called with `includeDiagnostics=true`. Core and BFF code attach sections via a shared **Diagnostics** protocol; the response may include a serialized tree. Disabled by default on normal SPA traffic.
_Avoid_: logging, tracing, metrics (generic observability)

**Diagnostics buffer**:
BFF in-memory ring of recent **request diagnostics** from instrumented calls. Served to the **Diagnostics modal** via `GET /bff/diagnostics/recent`; cleared on process restart.
_Avoid_: log buffer, audit trail

### Game concepts

**Game concept**:
Host-aligned rules, geometry, or static catalogs the console computes or holds -- warp wells, flare points, planet-connection reachability. Lives in Core `concepts/`; may be exposed as concept HTTP routes and reused inside **turn analytics**.
_Avoid_: domain service, utility module

**Turn-scoped concept**:
A **game concept** evaluated against a specific **TurnInfo** (e.g. whether a map cell lies in a planet's warp well). Routes include game id, **perspective**, and turn.
_Avoid_: per-turn helper

**Global concept**:
A **game concept** that does not depend on loaded game state (e.g. flare-point offset tables keyed by warp speed). Exposed under Core `/v1/concepts/...` without a turn path.
_Avoid_: static lookup, catalog endpoint

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
- `credentials/accounts/*` -- account record (e.g. api_key and future fields)

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

**Dev:** Can the frontend call `GET /api/v1/games/.../analytics/connections` directly?  
**Expert:** No. The SPA talks only to the **BFF**. Core owns **turn analytics**; the shell never bypasses that layer.

**Dev:** Game info lists a Player with `id: 42`. Is that perspective 42?  
**Expert:** No. **Player** ids come from the planets.nu payload. **Perspective** is the slot index (`1`..`11`) in path segments like `games/628580/3/turns/111`. Match name to slot via **GameInfo** player order, not via `Player.id`.

**Dev:** Turn ensure failed -- where should the message go?  
**Expert:** The **shell error bar**, not inline on the header control. Include which BFF endpoint failed so it is actionable.

**Dev:** Connections feels slow -- how do I see where time went?  
**Expert:** Open the **Diagnostics modal**, enable session diagnostics, repeat the request. **Request diagnostics** on the BFF response populate the **diagnostics buffer** with section timings from Core **turn analytics** and concept code.
