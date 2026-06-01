# Analytic persistence in the logical store

Status: accepted

Some **turn analytics** are expensive to recompute and accumulate state across turns or user edits. The **homeworld locator** is the first consumer: it caches inferred **homeworld candidates**, merges **homeworld inference evidence** from later turns, and stores **user-asserted** **homeworld candidate records** that must survive inference refreshes. Re-running full inference on every map/table request or holding results only in browser storage would waste work and lose cross-session annotations.

We persist analytic output **server-side** under a dedicated path convention, not at the game root (which would collide with future keys like `info` or ad-hoc feature blobs):

- **Game-global:** `games/{gameId}/analytics/{analytic_id}`
- **Perspective supplement:** `games/{gameId}/{perspective}/analytics/{analytic_id}/...` (nested keys such as `evidence` live inside the document at the analytic-id breakpoint)

These paths are registered as new breakpoints in `boundaries.py`:

- `games/*/analytics/*`
- `games/*/*/analytics/*`

Longest-prefix rules match ADR 0001: one JSON **document** per breakpoint; trailing segments are in-document keys. **Core** owns read, merge, invalidation, and write (including `POST .../analytics/{analytic_id}/assertions` upserts). The **BFF** shapes responses for the SPA and proxies mutations; it does not touch **StorageBackend** directly.

**Record shape:** cached rows use the same schema whether **inferred** or **user-asserted**; only **homeworld attribution** (or the analytic's equivalent field) differs. Recompute merges fresh inference back in and must not drop user-asserted rows unless the user revokes them.

**Split scope:** game-global state holds facts shared across viewers (slot assignments, user assertions). Perspective supplements hold sensor-picture-dependent accumulation (e.g. homeworld evidence from turns stored for that **perspective** only). Serving an analytic merges both layers.

## Considered options

- **Recompute on every request** — simple but too slow for multi-turn evidence accumulation and repeated map loads.
- **Browser localStorage keyed by game id** — no server writes, but annotations do not travel with stored games, cannot participate in Core definite-tier logic for tabular output, and bypass the storage model.
- **`games/{gameId}/{analytic_id}` at game root** — rejected; top-level segments under `games/{id}/` should stay reserved for stable domain documents (`info`, turns, `analytics/` namespace).
- **Single monolithic analytic cache per game** — rejected; perspective-scoped evidence would force either redundant copies or lossy merging.

## Consequences

- Every new persisted analytic needs a registered breakpoint pattern (if not already covered by the wildcards), Core merge/invalidation logic, and optional BFF routes.
- `boundaries.py`, conformance tests, and **CONTEXT.md** (**Analytic persistence**) must stay aligned when adding analytics that persist.
- Homeworld locator invalidation (new stored turns, **GameInfo** settings change, manual refresh) is analytic-specific; the path convention is shared.
- File-backend multi-worker caution from ADR 0001 applies to concurrent assertion writes; single-process dev assumption until locking is addressed.

See also: [CONTEXT.md](../../CONTEXT.md) (**Analytic persistence**, **Homeworld locator state**), [ADR 0001](0001-breakpoint-file-storage.md).
