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
CI verifies committed `schema-<slice>.ts` files match the filtered OpenAPI dumps (`make check_frontend_api_slices`) and fails if monolithic `src/api/schema.ts` reappears (`make check_frontend_api_no_monolithic_schema`; both run in `make ci`).
_Avoid_: relying on reviewers to notice stale or monolithic generated types

**Generated schema import rule**:
Application code imports the smallest matching `schema-<slice>.ts` module for types; `bff.ts` remains the facade for HTTP calls. Do not add a barrel `schema.ts` that re-exports every slice (that recreates a single monolith in git and in review).
_Avoid_: `import from './schema'` as the default in feature folders

**Turn analytic catalog**:
Shared declarative list (`TURN_ANALYTIC_CATALOG` in `api/analytics/catalog.py`) of turn analytic ids and SPA-facing metadata (`name`, `supports_table`, `supports_map`, `type`). Core and BFF both import it; handler and descriptor registries are validated against it at import. Adding an analytic still requires three registrations: one **catalog** entry (identity + metadata), one Core `_HANDLERS_BY_ID` entry (computation), and one BFF `_BFF_DESCRIPTORS_BY_ID` entry (table/map shaping). The catalog does not replace handler or descriptor registration -- it prevents metadata and id drift between layers.
_Avoid_: single registration list (handlers and shapers are still per-layer dicts)

**Analytic descriptor**:
The BFF registration object for one **turn analytic** -- optional table/map handlers and diagnostic hooks, with catalog metadata from `TURN_ANALYTIC_CATALOG` via `from_catalog_entry`. Aggregated in `REGISTERED_ANALYTICS`; the SPA catalog comes from this list via `GET /bff/analytics`.
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

**Military score build inference**:
Core **turn analytic** behavior (optional on the **Scores** analytic) that explains one player's scoreboard deltas on a turn as a ranked set of feasible build and load actions, not a single proved history. Requests run **per scoreboard row** with top-K **20**. No fixed row time budget once **#71** ships -- SPA runs continue until the ladder finishes, **inference global pause** freezes them, or the stream is cancelled (scope change, disable build inference, disconnect). See [design-military-score-build-inference.md](docs/design-military-score-build-inference.md).
_Avoid_: build solver, score guesser

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
The declarative record for one **inference search tier** on the unified ladder -- constraints on the full action catalog (ship-build component filters such as permitted tech levels, **tier aggregate allowlist** and caps, military-score band tolerance `alpha` in 2x units, seed budget). Later tiers loosen constraints; the final tier uses `alpha = 0`. Policies are loaded from a static asset (YAML); runtime parameter injection (e.g. fleet-known launcher/torp types) is a follow-on overlay on that base.
_Avoid_: tier config, search phase

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
The solver likelihood objective attached to one explanation. Orders the merged top-K and each streamed `solution` event; the consumer may maintain final ranked order incrementally from this weight without waiting for the full ladder to finish.
_Avoid_: probability score, objective value (implementation field name)

**Inference tier policy overlay** (follow-on):
Solver-side merge of injected parameters into the static **inference tier policy asset** at solve time (e.g. extra launcher torpedo tech levels, earlier beam tech bands). Defines how overlays combine with the base YAML -- not which upstream features produce overlay values (fleet histogram, prior builds, user settings, etc.). Separate ticket from the static-policy refactor.
_Avoid_: fleet prior, runtime tier config, injection source

**Inference tier policy asset**:
Static YAML ladder under `assets/analytics/military_score_build_inference/` (repo root). Defines ordered **inference tier policy** steps: per-axis tech-level allowlists, aggregate allowlists and caps, `alpha`, beam/launcher slot-count widening at named steps, and flags such as use-player-active-lists. Loaded at solve time via a resolver that accepts an optional **inference tier policy overlay** (no-op when absent). Not mixed with storage seed fixtures.
_Avoid_: tier_policy.yaml (filename in prose only when citing path)

**Inference solution streaming**:
NDJSON wire protocol (**#71**, Phase 1H). The SPA opens **one multiplexed table stream** (`GET .../inference/table-stream`) for all scoreboard rows on the current shell scope; events carry an optional `playerId` tag (except `globalPause`). Emits whenever a **new** **inference explanation signature** is admitted to **inference merged top-K** -- within-tier enumeration and cross-tier ladder progress -- so the hourglass clears before top-K is full. Admission is incremental-only: the solver `on_solution` callback merges into held top-K; there is no post-solve re-merge. Each `solution` event carries the **full held top-K** for that row (ranked by **inference solution rank weight**); the consumer replaces local held state from the event (no client-side merge). Follows the load-all progress stream pattern (Zod-owned events). Batch JSON remains for the inference corpus harness. **Stream disconnect** (refresh, network loss, disable build inference, tab close) cancels all in-flight work and clears **inference global pause** on the server; reopening the table stream on the same scope **recalculates from scratch**.
_Avoid_: websocket inference

**Inference table stream**:
Single NDJSON connection for all scoreboard rows on one game / turn / **perspective** scope. The backend multiplexes per-row scheduler event queues onto one wire; the frontend demuxes on `playerId`. Chosen over parallel per-row HTTP connections so **inference global pause** can freeze all rows on one scope without juggling N client abort controllers. The build-inference column header hosts the global pause control.
_Avoid_: turn-level inference job queue in the SPA

**Inference global pause**:
User-initiated freeze of all in-flight build inference for the current shell scope (game, turn, **perspective**) **while the inference table stream is connected**. **Pause** drains the scheduler worker queue into a held buffer and broadcasts `globalPause` on the open stream; rows already held in top-K stay visible with `paused` chrome. **Resume** (column header or `DELETE .../global-pause`) requeues held tier jobs and continuations on the same connection. Open streams drive the pause-control chrome via `globalPause` events (single source of truth with REST pause/resume). **Stream disconnect** clears server-side global pause and cancels all row runs; reconnect recalculates from scratch. Implicit scope change also cancels everything.
_Avoid_: confusing global pause with implicit stream cancellation

**Inference row scheduler**:
Process-wide backend facility (**#71** companion) that fair-schedules **inference search tier** work for rows on the active inference table stream. One schedulable **inference tier job** = one full **inference search tier** step for one scoreboard row (catalog build, exact/band passes, within-tier top-K, merge admit, seed output). Each row's ladder is sequential (tier *n+1* needs tier *n* job outputs). Cross-row fairness: enqueue tier-1 when a row is scheduled, append tier *n+1* after tier *n* completes, shared FIFO queue drained by a worker pool (default **4** workers, configurable). Distinct from **inference corpus runner** `--workers` (batch case parallelism). `solution` events emit from inside the tier job via merge-admit hooks. Integrates **inference global pause** (held jobs while the table stream stays open). Table stream teardown cancels all row runs and clears global pause.
_Avoid_: frontend job queue, per-solve queue jobs

**Inference solve interrupt boundary**:
Where stream cancellation (scope change, disable build inference, client disconnect) and **inference global pause** can take effect without losing tier progress. v1 (**#71**): cooperative checks at sub-step boundaries inside a tier job -- top-K no-good iterations, seed attempts, exact vs band passes -- plus `StopSearch()` in a CP-SAT callback when cancel fires mid-`Solve()`. OR-Tools CP-SAT cannot resume internal search state across `Solve()` calls; only complete solutions can warm-start the next pass via hints. **Known gap:** a single long first-feasible `Solve()` on a huge catalog may block cancel until that call returns. **Follow-on (if needed):** retry `UNKNOWN` sub-steps until feasible or cancelled (logical continuation; CP-SAT restarts internally each retry).
_Avoid_: routine short-solve slice loops (wastes search), assuming CP-SAT pause/resume

**Inference solution count indicator**:
Per scoreboard row chrome replacing the binary green tick: a green outlined badge showing **N** = the number of rows currently held in **inference merged top-K** (not cumulative discoveries above K). **N > 0** as soon as the first exact explanation is held; rises toward K then plateaus while eviction swaps membership. Hourglass while **N = 0** and search is in flight; red cross when the row completes with no exact explanation. Global pause/resume is controlled from the column header only. Click on the badge (or row chrome when **N > 0**) opens the ranked modal.
_Avoid_: green tick, checkmark column

**Accelerated-start inference row** (SPA):
A scoreboard row whose host turn falls in an accelerated-start window may run multiple internal segments (accel window + reported host turn). v1 **#71** uses the same table-stream scheduler path as other rows; segments stay inside the row's inference path with no per-segment SPA time split (natural completion or implicit stream cancellation ends the row).
_Avoid_: per-segment stream, segment-level halt (v1)

**Inference stream cancellation**:
End of in-flight build inference when the shell scope changes (game, turn, **perspective**), build inference is disabled, or the **inference table stream** disconnects (`AbortSignal`, refresh, network loss). There is no per-row halt control in the SPA; use **inference global pause** to freeze all rows while the stream stays open, or change scope / disconnect to cancel. On disconnect the scheduler cancels every row run, clears server-side **inference global pause**, and drops held tier jobs; reopening the table stream on the same scope **recalculates from scratch**. A terminal wire `complete` with `status: stopped` may still carry the last held top-K for that row on the way out; that is not server state preserved across reconnect. Distinct from failure (`no_exact_solution`, solver error), from natural completion (`exact` when final-catalog equalities pass), and from **inference global pause** (all rows frozen on an open stream, resumable via the column header).
_Avoid_: per-row halt (removed from SPA), time_limited (as the primary SPA stop mechanism)

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
The feasible action multiset inferred from inventory change between the paired turns for the case **Player** (exact by construction when adjunct effects are absent or fully visible). Used for Tier 2 compatibility checks and for **top-K ranking** checks against solver output.
_Avoid_: true build (implies uniqueness)

**Inference top-K ranking check**:
Whether the **ground truth explanation** appears among the solver's top *K* ranked solutions (default *K* = 3). A miss means constraints are satisfied but likelihood ordering may be wrong -- reported as an investigation signal, not necessarily a hard failure unless promoted in the fixed corpus.
_Avoid_: best solution match (implies rank 1 only)

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
