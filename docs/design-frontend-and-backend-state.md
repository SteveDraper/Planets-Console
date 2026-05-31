# Design: Frontend and backend state

This document is the reference for **where state lives** in Planets Console: the SPA split between **Zustand** (client state), **TanStack Query** (server-derived state cached from the BFF), and **local React state**; and how the **Python stack** remains stateless per request while **persisting** through storage.

For layering and packages, see [.cursor/rules/architecture.mdc](../.cursor/rules/architecture.mdc).

---

## 1. Frontend: Zustand (client state)

Zustand stores hold **session and shell context** that should not live in the TanStack Query cache: values that are **not** the direct JSON body of a single GET, or that must be **shared** across the tree without prop drilling.

Stores are **in-memory** unless a store explicitly adds persistence middleware. Session passwords follow project rules: **never persisted** to localStorage, sessionStorage, cookies, or URLs.

| Store | Path | Responsibility |
|--------|------|----------------|
| **Session** | `packages/frontend/src/stores/session.ts` | Login **name** and **password** for planets.nu-backed operations. Used by game refresh and related flows. |
| **Shell** | `packages/frontend/src/stores/shell.ts` | **Selected game id**, snapshot from the last successful game-info refresh (**max turn**, **perspectives** / player order, **Stellar Cartography settings gates**), **selected turn**, **viewpoint override**, and **`applyGameInfoRefresh`** (turn and override rules when game info updates). |
| **Enabled analytics** | `packages/frontend/src/stores/enabledAnalytics.ts` | Persisted sidebar master enable toggles (`planets-console-enabled-analytics`; default none enabled). |
| **Stellar Cartography layers** | `packages/frontend/src/stores/stellarCartographyLayers.ts` | Persisted per-layer map visibility toggles for the Stellar Cartography analytic (`planets-console-stellar-cartography-layers`; default all on). |
| **Display preferences** | `packages/frontend/src/stores/displayPreferences.ts` | Player/sector list label modes (persisted). |

**When to use Zustand:** identity or shell context needed in **multiple** places (header, main area, mutations), or **`getState()`** from outside React (e.g. inside a mutation callback).

**Do not** mirror BFF GET responses in Zustand; that belongs in TanStack Query (section 2).

---

## 2. Frontend: TanStack Query (server state)

TanStack Query owns **data fetched from the BFF** (the SPA never calls the Core REST API directly). It provides **caching**, **loading and error states**, **deduplication**, and **automatic refetch** when **query keys** change.

### Query key conventions

| Pattern | Purpose | Examples |
|---------|---------|----------|
| `['bff', '<resource>']` | BFF lists or singleton metadata | `['bff', 'analytics']`, `['bff', 'games']` |
| `['analytic', <id>, 'table', <scope>]` | Tabular analytic for a **game + turn + perspective** | Scope is `AnalyticShellScope` (or equivalent fields) so changing shell context **refetches** without manual `invalidateQueries`. |
| `['analytic', <id>, 'map', <scope>, 'planet-v2']` | Generic map fetch in `MainArea.tsx` (**base-map** and other map analytics except **connections**). `<scope>` is `AnalyticShellScope \| null`. The `'planet-v2'` suffix invalidates cache when base-map node shape changes (e.g. `normalWellCells`). |
| `['analytic', 'connections', 'map', gameId, turn, perspective, warpSpeed, gravitonicMovement, flareMode, flareDepth]` | **Connections** map overlay (`MainArea.tsx`). Primitive scope + sidebar params so changing warp/flare settings refetches. When scope is not ready, the key uses `'idle', 0, 0` in place of `gameId, turn, perspective`. |
| `['bff', 'turnData', gameId, turn, perspective, loginName, credentialsRevision]` | **Turn presence in storage** (see below) | One logical ensure per distinct shell + identity; `credentialsRevision` bumps on login/clear (not the password). |

**Mutations** (`useMutation`) are for operations that **change server-side** data (e.g. `POST /bff/games/{id}/info`). They may call `queryClient.invalidateQueries` for related lists (e.g. games) when needed.

**Retries (query default):** The root `QueryClient` in `packages/frontend/src/App.tsx` sets **`retry: shouldRetryTanStackQuery`** from `packages/frontend/src/lib/queryRetry.ts`. TanStack’s built-in default (retry most failures several times) is **not** used.

Rationale: **planets.nu** sometimes returns **502** for **non-transient** failures (for example, requesting another player’s data in an incomplete game). Retrying those only adds latency before the UI can show an error. The policy is **conservative**: only errors that are **commonly transient** are retried.

| Outcome | Retried? | Notes |
|---------|----------|--------|
| Likely **network** failure (`TypeError`, or message contains e.g. `Failed to fetch`, `NetworkError`, `Load failed`) | Yes | Retries until TanStack’s `failureCount` reaches **`MAX_FAILURE_COUNT_BEFORE_STOP` (3)** in `queryRetry.ts` (same cap as the previous default). |
| **408** Request Timeout, **503** Service Unavailable, **504** Gateway Timeout | Yes | Parsed from the start of the `Error.message` (e.g. `503 (GET /bff/…)`) or from phrases such as `Gateway Timeout` / `Service Unavailable`. |
| **4xx** other than the row above (404, 422, etc.) | No | Client or domain errors; fail fast. |
| **502** Bad Gateway, **500** Internal Server Error, other **5xx** | No | Treated as non-transient for this app; 502 in particular is used for forbidden-style upstream behavior. |
| **Unknown** error message (no recognizable status or phrase) | No | Avoid blind retries. |

**Mutations** (e.g. game info refresh) use **`retry: false`** on the mutation itself; this policy applies to **queries** via the shared `QueryClient` defaults.

**Refetch rule:** For turn-scoped analytics, **include game id, turn, and perspective** in the query key (via a scope object). Then a new turn or viewpoint selection updates the key and **refetches enabled analytics** (including hidden **base** map layers) without extra invalidation logic.

### Turn data ensure: one request per scope, analytics only after storage is ready

Turn blobs live in **Core storage** (`games/{gameId}/{perspective}/turns/{turn}`). The SPA must not fire turn-scoped **analytics** BFF GETs until that path is populated (either already present or loaded from Planets.nu **loadturn** via the ensure endpoint).

**Ensure query (`useShellContext`):**

- **Endpoint:** `POST /bff/games/{gameId}/turns/ensure` with `{ turn, perspective, username, password? }` (same credential pattern as game info refresh). Username may be empty **only** when the turn is **already** in storage (no Planets.nu loadturn); the shell enables this path when the selected game matches **`bff.show_initial_game`** from bootstrap config (dev/demo).
- **Query key:** `['bff', 'turnData', gameId, turn, perspective, loginName, credentialsRevision]` (primitives only; **do not** put the session password in the key). `credentialsRevision` increments in the session store on `setCredentials` / `clearSession` so a corrected password refetches ensure even when the username is unchanged.
- **Enabled** when shell scope is complete **and** either a non-empty login name is set **or** the “initial game without login” path applies (see `useShellContext` `turnEnsureEnabled`). If ensure is disabled because login is missing and the path above does not apply, the main area explains that turn data cannot be loaded.
- **Caching:** `staleTime: Infinity` and `refetchOnWindowFocus: false` so a stable scope does not trigger duplicate ensure POSTs; changing game, turn, perspective, login name, or credentials revision changes the key and runs **at most one** new ensure for that key.

**Why this yields a single ensure when turn and perspective change together (e.g. new game selection):**

1. **One derived scope per render:** `analyticScope` is a `useMemo` over `selectedGameId`, `selectedTurn`, `gameInfoContext.perspectives`, and the resolved viewpoint name. After `applyGameInfoRefresh` updates the shell store, React sees **one** committed render with the final game id, turn, and viewpoint -- not separate ensures for intermediate combinations.
2. **TanStack Query deduplication:** Identical query keys share one in-flight request (e.g. Strict Mode double mount, or rapid re-renders).

**Analytics gating (`MainArea.tsx`):**

- **`turnDataReady`** is `turnEnsureEnabled && ensureQuery.isSuccess` so it is never true when the query is disabled or has not finished successfully.
- Tabular and map **analytic** queries use `enabled: analyticScope != null && turnDataReady` (via `analyticFetchEnabled`). They **do not** run while the ensure query is pending or before it succeeds, so the BFF/Core never serves analytics for a turn that is still missing from storage.

**Backend idempotency:** `GameService.ensure_turn_loaded` returns immediately if the turn path already exists; otherwise it calls Planets.nu and writes **`rst`**. Repeating ensure for the same turn is safe.

### Map display retention

While map analytic queries reload, the SPA keeps **MapGraph** mounted and may show the last displayable **combined map** so React Flow preserves zoom and pan. See **Map display retention** in [CONTEXT.md](../CONTEXT.md).

**Owner:** `useRetainedMapDisplay` in `packages/frontend/src/lib/useRetainedMapDisplay.ts`. Map queries in `MainArea.tsx` do **not** use `placeholderData: keepPreviousData`; TanStack Query cannot retain across turn or ensure gaps (new query keys plus `enabled: false` while **turn ensure** runs).

**Retention key:** `{ gameId, perspective }`. Clears **synchronously** when either changes so another viewpoint's planets never flash on screen. **Turn** is not part of the key -- stepping turns within the same game and viewpoint keeps the prior frame until fresh data arrives.

**Display rule:** When live `combined` has nodes, show it; otherwise show the retained snapshot if the retention key still matches. **`mapShellView`** (`MapShellView`) is derived in `useRetainedMapDisplay` via `deriveMapShellView` in `mapDisplayRetention.ts` from retention state plus turn-ensure and map-query loading inputs. Phases: **`full-loading`** with a loading message (turn or map fetch); **`showing-map`** keeps **MapGraph** mounted with `displayMapData` and sets **`showDeferredPending`** when the deferred "Loading additional map data…" overlay should appear (live data with secondary queries still pending -- false while showing a retained prior frame); **`error`** drives the full-pane error placeholder in `MainArea.tsx`. Tabular and map turn-ensure loading both use **`deriveTurnEnsureLoadingView`** in `mapDisplayRetention.ts` with **`ShellCenterPane`** in `components/shell/ShellPlaceholders.tsx`.

**Predicates:** `hasDisplayableMapData`, `shouldRetainMapDuringLoad`, `deriveTurnEnsureLoadingView`, and `deriveMapShellView` in `mapDisplayRetention.ts` (unit-tested separately).

**Turn ensure vs retention:** While a prior frame is retained, `deriveMapShellView` returns **`showing-map`** with **`showDeferredPending: false`** even when `turnEnsurePending && !turnDataReady`, so the map shell does not enter **`full-loading`** during turn reload. If **turn ensure** then fails (`turnEnsureIsError && !turnDataReady`), `MainArea.tsx` still renders the full-pane turn-error placeholder **before** the map shell body -- the retained frame is not shown alongside that error. The hook keeps reporting **`showing-map`** until scope or live data changes; only the shell layout decides whether the user sees the stale map or the error pane.

---

## 3. Frontend: Local React state (`useState` / `useRef`)

Some state stays in **component state** when it is **local to the shell** or **ephemeral UI** rather than global client or server cache:

- **View mode** (tabular vs map), **map zoom** and slider wiring, **shell error bar** rows (`ShellErrorItem[]`), and similar.

**Enabled analytic ids** and **Stellar Cartography layer toggles** live in persisted Zustand stores (see section 1), not in `App.tsx` local state.

If a piece of UI state later needs to be shared widely, promote it to Zustand or derive it from query data rather than duplicating.

---

## 4. Backend: Stateless HTTP and persistent storage

The **Core REST API**, **BFF**, and **root server** process handle requests **without per-client in-memory session state**. There is no server-side map of "current user" or "selected game" for the SPA; each request is handled with injected dependencies (storage, config, clients).

**Durable** game info, turn blobs, credentials keys, and other stored data live **only** behind the **`StorageBackend`** abstraction (`packages/api/api/storage/`, import `api.storage`). With `storage_backend: file` (repo default), data is persisted as JSON documents at registry **breakpoints** under `storage_root` (default `./.data/`). Services use that protocol; routers do not touch concrete backends. See [design-storage-abstraction-and-crud-api.md](design-storage-abstraction-and-crud-api.md) §15 and [ADR 0001](adr/0001-breakpoint-file-storage.md).

The **BFF** does not introduce its own persistence; it shapes responses for the SPA and may call Core services according to the allowed import surface in architecture rules.

---

## 5. Related documents

| Topic | Document |
|--------|----------|
| Layering and tech stack | [.cursor/rules/architecture.mdc](../.cursor/rules/architecture.mdc) |
| Storage protocol, CRUD, file backend | [design-storage-abstraction-and-crud-api.md](design-storage-abstraction-and-crud-api.md) §15 |
| Persistence ADR | [adr/0001-breakpoint-file-storage.md](adr/0001-breakpoint-file-storage.md) |
| Glossary | [CONTEXT.md](../CONTEXT.md) |
| Shell error bar and query/mutation failures | [design-shell-error-handling.md](design-shell-error-handling.md) |
| Game selection UX | [design-issue-13-game-selection.md](design-issue-13-game-selection.md) |
| Connections map analytic (reachability, flares, BFF) | [design-connections-analytic.md](design-connections-analytic.md) |
