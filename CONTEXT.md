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
CI verifies committed `schema-<slice>.ts` files match the filtered OpenAPI dumps (`make check_frontend_api_slices`). A guard against reintroducing monolithic `src/api/schema.ts` is tracked separately (issue #60).
_Avoid_: relying on reviewers to notice stale or monolithic generated types

**Generated schema import rule**:
Application code imports the smallest matching `schema-<slice>.ts` module for types; `bff.ts` remains the facade for HTTP calls. Do not add a barrel `schema.ts` that re-exports every slice (that recreates a single monolith in git and in review).
_Avoid_: `import from './schema'` as the default in feature folders

**Analytic descriptor**:
The single BFF registration object for one **turn analytic** -- catalog fields plus optional table/map handlers and diagnostic hooks. Aggregated in `REGISTERED_ANALYTICS`; the SPA catalog comes from this list via `GET /bff/analytics`.
_Avoid_: METADATA dict, handler registry (when meaning the consolidated descriptor)

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
- `credentials/accounts/*` -- account record (e.g. api_key and future fields)

**Analytic persistence**:
Server-side cached output for a **turn analytic** that must not recompute on every request. Lives under `games/{gameId}/analytics/{analytic_id}` for game-global state and `games/{gameId}/{perspective}/analytics/{analytic_id}/...` for **perspective**-scoped supplements. **Homeworld locator** is the first analytic to use this pattern; user-asserted records share the same **homeworld candidate record** shape as inferred rows, distinguished only by **homeworld attribution**. See [ADR 0002](docs/adr/0002-analytic-persistence.md).
_Avoid_: analytic cache at game root, `{gameId}/homeworld-locator`

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
