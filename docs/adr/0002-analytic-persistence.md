# Analytic persistence in the logical store

Status: accepted

Some **turn analytics** are expensive to recompute and accumulate state across turns or user edits. The **homeworld locator** is the first consumer: it caches inferred **homeworld candidates**, merges **homeworld inference evidence** from later turns, and stores **user-asserted** **homeworld candidate records** that must survive inference refreshes. **Scores inference row persistence** (issue #83) is the first **turn-scoped** consumer: terminal **military score build inference** results per scoreboard row. Re-running full inference on every map/table request or holding results only in browser storage would waste work and lose cross-session annotations.

We persist analytic output **server-side** under a dedicated path convention, not at the game root (which would collide with future keys like `info` or ad-hoc feature blobs):

- **Game-global:** `games/{gameId}/analytics/{analytic_id}`
- **Perspective supplement:** `games/{gameId}/{perspective}/analytics/{analytic_id}/...` (nested keys such as `evidence` live inside the document at the analytic-id breakpoint)
- **Turn-scoped supplement:** `games/{gameId}/{perspective}/turns/{turn}/analytics/{analytic_id}/...` (one JSON document per shell turn and **perspective**, **separate** from the **TurnInfo** file at `.../turns/{turn}`)

These paths are registered as breakpoints in `boundaries.py`:

- `games/*/analytics/*`
- `games/*/*/analytics/*`
- `games/*/*/turns/*/analytics/*`

Longest-prefix rules match ADR 0001: one JSON **document** per breakpoint; trailing segments are in-document keys. The turn-scoped pattern is longer than `games/*/*/turns/*`, so `games/{id}/{perspective}/turns/{turn}/analytics/scores` is its own file, not nested inside the **TurnInfo** document. **Core** owns read, merge, invalidation, and write (including `POST .../analytics/{analytic_id}/assertions` upserts). The **BFF** shapes responses for the SPA and proxies mutations; it does not touch **StorageBackend** directly.

**Record shape:** cached rows use the same schema whether **inferred** or **user-asserted**; only **homeworld attribution** (or the analytic's equivalent field) differs. Recompute merges fresh inference back in and must not drop user-asserted rows unless the user revokes them.

**Split scope:** game-global state holds facts shared across viewers (slot assignments, user assertions, **Scores** hull catalog mask overrides). Perspective supplements hold sensor-picture-dependent accumulation (e.g. homeworld evidence from turns stored for that **perspective** only). Turn-scoped supplements hold computed output tied to one **inference host turn** at one **perspective** (e.g. completed build-inference rows). Serving an analytic merges layers where applicable.

## Scores inference row persistence (#83)

Logical path: `games/{gameId}/{perspective}/turns/{hostTurn}/analytics/scores/inference_rows/{playerId}` in document `.../turns/{hostTurn}/analytics/scores.json`.

- **Write gate:** persist only terminal `complete` outcomes with status `exact` or `no_exact_solution`.
- **Stream replay:** on table-stream open, replay valid rows as a single terminal `complete` event (full solutions embedded); do not schedule tier jobs for cache hits.
- **Invalidation:** hull catalog mask save/reset for one **Player** clears that row and **in-place row reschedule** on the open stream; turn document `put` at turn *T* deletes `.../turns/{T}/analytics/scores` and, when *T-1 >= 1*, `.../turns/{T-1}/analytics/scores` (pair-aware); if the open stream matches the cleared host turn, **in-place full-table reschedule**. User **scores inference recompute** (`POST .../inference/recompute`) clears host-turn persistence, clears **inference global pause**, and full-table reschedules in-place.
- **SPA:** no client stream abort on mask save; remove `refreshInference()` token pattern. Product recompute control in the build-inference column header.

Hull catalog mask overrides remain game-global at `games/{gameId}/analytics/scores/inference_hull_catalog_masks/{playerId}`.

## Considered options

- **Recompute on every request** — simple but too slow for multi-turn evidence accumulation and repeated map loads.
- **Browser localStorage keyed by game id** — no server writes, but annotations do not travel with stored games, cannot participate in Core definite-tier logic for tabular output, and bypass the storage model.
- **`games/{gameId}/{analytic_id}` at game root** — rejected; top-level segments under `games/{id}/` should stay reserved for stable domain documents (`info`, turns, `analytics/` namespace).
- **Single monolithic analytic cache per game** — rejected; perspective-scoped evidence would force either redundant copies or lossy merging.
- **Turn key inside perspective `scores` document** (`games/.../{perspective}/analytics/scores/inference_rows/{turn}/{playerId}`) — rejected; one file per perspective would grow unbounded across turns; turn belongs at the breakpoint.
- **Nest inference cache inside the TurnInfo document** (`games/.../turns/{turn}` with `analytics/scores/...` suffix) — rejected; mixes host snapshot with computed cache and couples invalidation to turn import shape.

## Consequences

- Every new persisted analytic needs a registered breakpoint pattern (if not already covered by the wildcards), Core merge/invalidation logic, and optional BFF routes.
- `boundaries.py`, conformance tests, and **CONTEXT.md** (**Analytic persistence**) must stay aligned when adding analytics that persist.
- Homeworld locator invalidation (new stored turns, **GameInfo** settings change, manual refresh) is analytic-specific; the path convention is shared.
- Scores inference invalidation hooks turn `put` (including loadall paths) even though `ensure_turn_loaded` today skips already-stored turns — future force-refresh must behave correctly.
- File-backend multi-worker caution from ADR 0001 applies to concurrent assertion writes; single-process dev assumption until locking is addressed.

See also: [CONTEXT.md](../../CONTEXT.md) (**Analytic persistence**, **Scores inference row persistence**, **Scores inference row invalidation**, **Scores inference recompute**), [ADR 0001](0001-breakpoint-file-storage.md), GitHub issue #83.
