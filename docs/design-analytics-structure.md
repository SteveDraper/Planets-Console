# Design: Analytics module structure

Analytics use generic HTTP routes but keep per-analytic implementation in layer-local modules.

## Core API

- Shared route: `GET /api/v1/games/{game_id}/{perspective}/turns/{turn_number}/analytics/{analytic_id}`.
- Storage and turn loading stay in `packages/api/api/services/game_service.py`.
- Per-analytic response construction lives under `packages/api/api/analytics/`:
  - `base_map.py`
  - `scores.py`
  - `connections.py`
  - `registry.py`

`GameService.get_turn_analytics(...)` loads `TurnInfo`, builds `TurnAnalyticsOptions`, and delegates to the registry.

## BFF

- Shared routes stay in `packages/bff/bff/routers/analytics.py`.
- Per-analytic metadata, table shaping, map shaping, and query forwarding live under `packages/bff/bff/analytics/`.
- The router should stay thin: parse HTTP query params, build diagnostics, then call the BFF analytics registry.
- BFF modules should not import Core concept modules directly. If a query enum is needed for HTTP parsing, define it in the BFF layer and pass wire values down through the Core service boundary.

## Frontend

- Generic shell components remain in `src/components/`.
- Analytic-specific UI, query helpers, and map-layer behavior live under `src/analytics/`.
- `AnalyticsBar` renders generic tiles and delegates specialized controls, such as Connections controls, to analytic modules.
- `MainArea` owns high-level tabular/map orchestration; map layer combination is in `src/analytics/mapLayers.ts`.

## Adding an analytic

1. Add a Core analytic module and register it in `api.analytics.registry`.
2. Add a BFF analytic module for metadata and response shaping, then register it in `bff.analytics.registry`.
3. Add frontend analytic modules only for behavior that is not covered by the generic table or map shells.
4. Add focused tests at the layer where behavior lives.
