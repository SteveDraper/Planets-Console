# Team information map analytic

Map-only **turn analytic** (`analytic_id` `team-information`) that paints **team territory**: the map colored by the **league team** of the owner of the nearest planet. Phase 1: [issue 546](https://github.com/SteveDraper/Planets-Console/issues/546). Phase 2: [issue 547](https://github.com/SteveDraper/Planets-Console/issues/547). Glossary: **Team information analytic**, **League team**, **Team territory**, **Team territory site set**, **Sphere map** in [CONTEXT.md](../CONTEXT.md).

Related: [Adding a turn analytic](design-adding-a-turn-analytic.md), [Analytics structure](design-analytics-structure.md), [ADR 0008](adr/0008-shared-map-region-overlays.md) (shared `regionOverlays`).

## Product

| Requirement | Decision |
|-------------|----------|
| Registration | Selectable, `supports_table=false`, `supports_map=true`, display name `Team information` |
| Sites | Shell-turn planets. Unowned means `ownerid == 0`. **League team** is `Player.leagueteamid` on that owner (`0` means no league team) |
| Distance | Euclidean light-years. On a **sphere map** (`GameSettings.sphere`), toroidal distance on the rectangle of size `mapwidth` by `mapheight` centered on `(2000, 2000)`, both axes. `mapshape` does not change the period. `Game.maptype` is a hosting category and is ignored |
| Site sets | Both **team territory site set**s are computed on every map response. Checkbox **Owned planets only** (default off, global localStorage) chooses which set is painted. Toggling does not refetch |
| Holes | Cells whose winning site is unowned are omitted from the all-planets set. Cells whose winning owner has `leagueteamid == 0` are omitted from both sets. Owned-planets-only fills the rectangle when every owner has a league team |
| Paint | Shared **map region overlay** boundary polygons (line edges only). One overlay per disjoint component of a league team's union. Semi-transparent fill so planet dots stay readable |
| Color | Each league team on the turn gets a distinct hue. Teams that share a border are placed as far apart on the wheel as the team count allows. A shared border whose hues are still within 60 degrees uses a different hatch (`solid`, `forward`, `back`, `horizontal`, `vertical`, `dots`). Both site sets share that style. Independent of **player color** |
| Legend | Sidebar lists each league team that appears: swatch and league team name ([#549](https://github.com/SteveDraper/Planets-Console/issues/549), [#550](https://github.com/SteveDraper/Planets-Console/issues/550)). The numeric id shows only when the name is unresolved. Member usernames are hover text on the row, not drawn in the row. Hovering a row outlines that team's painted regions with a solid high-opacity stroke. Cell hover names the team territory under the pointer, as its own descriptive section beside stellar cartography. Legend hover, the outline, and the cell hover run only while the analytic is enabled |
| Exports | Empty catalog. No orchestrator profile. No map query params |

Example sphere game: [686674](https://planets.nu) Bundy Sector (`sphere: true`, `mapshape` rectangular, 2278 by 2278). Help: planets.nu Sphere is a flattened torus; leaving one edge re-enters the opposite edge, and the wrap rectangle is used even when the planet disk is round.

## Geometry

Core owns the partition. The SPA blits.

1. Sites are `turn.planets` with coordinates. Drop `ownerid == 0` only for the owned-planets set.
2. Distance from point `P` to site `S`:
   - `sphere` false: `hypot(Sx - Px, Sy - Py)`.
   - `sphere` true: `dx = min(d, W - d)` where `d = abs(Sx - Px) mod W` and `W = mapwidth`; same for `y` with `mapheight`; then `hypot(dx, dy)`.
3. Build the Voronoi partition of the site set on the map rectangle. On a sphere map, replicate each site across the eight neighboring periods (3 by 3 tiling) and clip the diagram back to the fundamental rectangle. Split any polygon that crosses a seam so every emitted ring lies inside the rectangle.
4. The winning site at a point is the nearest site. An exact distance tie uses the lower planet id.
5. A cell is painted only when its winning site has an owner with `leagueteamid > 0`. Union painted cells that share a league team id. Disjoint components stay separate overlays with the same color and team id.
6. Clip every ring to the map rectangle: `[2000 - mapwidth / 2, 2000 + mapwidth / 2] x [2000 - mapheight / 2, 2000 + mapheight / 2]`.

## Wire

Core `compute` returns a JSON object:

- `analyticId`: `team-information`
- `sphere`: bool from settings
- `teams`: `{ leagueTeamId, fillColor, fillPattern, playerIds }[]` for every league team that owns at least one planet on the turn (even if a site set paints nothing for them)
- `regionOverlays`: both partitions

Each overlay is a shared boundary **map region overlay**:

| Field | Value |
|-------|--------|
| `kind` | `team-territory` (all planets) or `team-territory-owned-only` |
| `id` | `team-territory:{leagueTeamId}:{component}` or `team-territory-owned-only:{leagueTeamId}:{component}` |
| `fillColor` | distinct hue for that team on this turn |
| `fillPattern` | `solid`, `forward`, `back`, `horizontal`, `vertical`, or `dots` |
| `fillOpacity` | `0.35` |
| `geometry` | `{ type: "boundary", vertices: [{x, y}, ...], edges: [{type: "line"}, ...] }` closed, clockwise or counterclockwise, no arcs |
| `leagueTeamId` | int domain fact. No English strings |

`fillPattern` is the same on the team row and on every overlay for that team. The SPA draws the hatch in screen pixels so it stays readable when zoomed out. Hatch strokes are white at 0.35 opacity so the team color stays dominant, and the legend swatch uses the same marks.

BFF map handler passes the Core object through. The table route stays a validation error.

## Frontend

- Register the map merger so `regionOverlays` from this analytic join the combined map.
- Persist **Owned planets only** in localStorage (global, same sticky scope as other analytic display toggles). Default off.
- Paint exactly one kind: `team-territory` when the checkbox is off, `team-territory-owned-only` when it is on. Filter in a team-information-owned function. Do not run these kinds through Visibility kind preferences.
- Sidebar: generic enable control plus the checkbox and the legend. Legend rows come from `teams` on the map payload (swatch, directory name or the numeric id when that name is null). Usernames are resolved from the turn roster onto the row, shown as hover text, and are not drawn in the row. Hovering a row sets the outlined league team. Names load from `GET /bff/games/{game_id}/league-teams` with TanStack Query for the open game, separate from the map query. Grey the tile in tabular **view mode** via `supports_table=false`.
- Cell hover: a **map interaction contributor** (role `team-territory`) hit-tests the painted site set and contributes the team label. It `yieldsTo` planet hover and `mergesWith` fleet, region, and cartography (off a planet, the fleet card anchored at the ship hosts the team section). It is registered only while the analytic is enabled.
- No edge-mirror strip. Opposite edges of one team share a color, which is the wrap cue.

## Layers

- **Core** (`api/analytics/team_information.py`): partition and wire. Toroidal distance and Voronoi live next to the analytic unless a second caller needs them; then extract to `api/concepts/`.
- **BFF** (`bff/analytics/team_information.py`): passthrough `get_map`. Empty export catalog on the Core registration.
- **SPA** (`src/analytics/team-information/`): merge, preference store, sidebar legend and checkbox, kind filter.

Reuse the turn-analytic catalog, `empty_export_catalog_for`, shared boundary `regionOverlays`, and the map fetch/merge registry. Do not add a query parameter to the shared map route. Do not import another analytic for the partition.

## League team directory

Legend names come from the **league team directory**, not from this analytic ([#549](https://github.com/SteveDraper/Planets-Console/issues/549)). Drawing them is [#550](https://github.com/SteveDraper/Planets-Console/issues/550).

Stored GameInfo players already carry `username` and `leagueteamid`. `leagueteamid == 0` is omitted. Each distinct id is resolved once: one public `GET /account/loadprofile` for any member of that id, then the `playergroups` row whose `groupid` equals the id, and `_group.name`. The `{id, name}` pair is cached by league team id, across games. A cached id is not fetched again. An unknown id, a profile with no matching row, or an upstream failure for that id returns `name: null` and leaves the other ids intact. Failures are not cached.

- Core `GET /api/v1/games/{game_id}/league-teams`
- BFF `GET /bff/games/{game_id}/league-teams` forwards to Core and returns the same body: `{ "teams": [{ "id", "name" }] }`

`api/analytics/team_information.py` does not import the directory service. The SPA does not fold this fetch into the team-information map compute.

## Tests

**Phase 1 (Core)** -- write the failing geometry tests first:

- Sphere: a site at `x = 1` is nearer to `x = mapwidth - 1` than a site at the middle of the same row. The painted component crosses the seam as two rings inside the rectangle (or one ring per side) with the edge site's league team.
- Non-sphere: the same pair uses planar distance, so the far side of the seam is not claimed by the edge site.
- All-planets set: an unowned planet's cell is absent. Owned-planets-only assigns that area to the nearest owned league team.
- `leagueteamid == 0`: that owner's cells are absent from both kinds.
- Two adjacent planets on one league team union into one component when they share a border.
- Exact tie: lower planet id wins.

**Phase 2 (BFF and SPA)** -- do not repeat the geometry cases:

- Registry metadata: map yes, table no, selectable, catalog order.
- BFF map returns the Core shape; table route is a validation error.
- Merger keeps both kinds. The preference filter emits only the selected kind.
- Legend lists the league team name when the directory has one, otherwise the id. Member usernames stay on the row and are not drawn.
- Browser: enable the analytic, confirm the tint, toggle **Owned planets only** and confirm holes close without a refetch, and confirm the tile is grey in tabular mode. On a sphere game, confirm color continues across an edge.

## Phases

1. **Core geometry** ([#546](https://github.com/SteveDraper/Planets-Console/issues/546)). Module, catalog entry, registration, empty exports, geometry tests above. No SPA.
2. **Map and sidebar** ([#547](https://github.com/SteveDraper/Planets-Console/issues/547)). BFF descriptor, frontend merge, checkbox, legend, kind filter, registry tests, quick-reference row in [design-analytics-structure.md](design-analytics-structure.md), browser check. Starts after phase 1 has merged.

## Out of scope

Context menu for member usernames, edge-mirror margin, in-game `teamid` coloring, tabular tile, export queries, per-team color pickers, client-side distance. League team names are [#549](https://github.com/SteveDraper/Planets-Console/issues/549) and [#550](https://github.com/SteveDraper/Planets-Console/issues/550).
