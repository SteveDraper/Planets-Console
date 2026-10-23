# Territory map analytic

Map-only **turn analytic** (`analytic_id` `team-information`) that paints **Territory**: the map colored by who owns the nearest planet. **By team** off (the default) paints **player territory**. **By team** on paints **team territory**. Phase 1: [issue 546](https://github.com/SteveDraper/Planets-Console/issues/546). Phase 2: [issue 547](https://github.com/SteveDraper/Planets-Console/issues/547). Both partitions: [issue 586](https://github.com/SteveDraper/Planets-Console/issues/586). Glossary: **Territory**, **Player territory**, **Team territory**, **Team territory site set**, **League team**, **Sphere map** in [CONTEXT.md](../CONTEXT.md).

Related: [Adding a turn analytic](design-adding-a-turn-analytic.md), [Analytics structure](design-analytics-structure.md), [ADR 0008](adr/0008-shared-map-region-overlays.md) (shared `regionOverlays`).

## Product

| Requirement | Decision |
|-------------|----------|
| Registration | Selectable, `supports_table=false`, `supports_map=true`, display name `Territory`. `analytic_id` stays `team-information` |
| Sites | Shell-turn planets. Unowned means `ownerid == 0`. **League team** is `Player.leagueteamid` on that owner (`0` means no league team). In-game `Player.teamid` is ignored |
| Distance | Euclidean light-years. On a **sphere map** (`GameSettings.sphere`), toroidal distance on the rectangle of size `mapwidth` by `mapheight` centered on `(2000, 2000)`, both axes. `mapshape` does not change the period. `Game.maptype` is a hosting category and is ignored |
| Site sets | Both **team territory site set**s are computed on every map response. Checkbox **Owned planets only** (default off, global localStorage) chooses which set is painted. Toggling does not refetch |
| Partitions | Each site set is unioned twice on that same response. Checkbox **By team** (default off, localStorage per game id) chooses the union. Toggling does not refetch. With no open game the checkbox shows off and does not write storage |
| Holes | Cells whose winning site is unowned are omitted from the all-planets set. Owned-planets-only assigns that area to the nearest owned planet. **Team territory** also omits an owner with `leagueteamid == 0`. **Player territory** keeps every owned player, including `leagueteamid == 0` |
| Paint | Shared **map region overlay** boundary polygons (line edges only). One overlay per disjoint component. Exactly one of the four kinds is painted. Semi-transparent fill so planet dots stay readable |
| Color | **Team territory**: each league team on the turn gets a distinct hue. Teams that share a border are placed as far apart on the wheel as the team count allows. A shared border whose hues are still within 60 degrees uses a different hatch (`solid`, `forward`, `back`, `horizontal`, `vertical`, `dots`). Both team site sets share that style. **Player territory**: the shared per-player palette (preset plus per-player overrides), solid pattern, opacity `0.35`. Ignores global diplomacy color mode, the same rule as minefield owner paint. The SPA applies that color at paint and in the legend, so a settings change updates the map without a refetch. The wire still carries a `fillColor`; the SPA replaces it |
| Legend | **By team** on: each league team that owns a planet, with a checkbox, swatch, and league team name ([#549](https://github.com/SteveDraper/Planets-Console/issues/549), [#550](https://github.com/SteveDraper/Planets-Console/issues/550), [#557](https://github.com/SteveDraper/Planets-Console/issues/557)). The numeric id shows only when the name is unresolved. Member usernames are hover text on the name and color chip, not drawn in the row. Each checkbox starts checked. Unchecked league team ids are stored in the same global localStorage entry as **Owned planets only**; a team that is not in that list stays visible, including teams that appear later. The same league team id is the same team in every game. An unchecked row omits that team's fill. Hovering the name or the color chip outlines that team's regions on the active site set, whether or not the row is checked. The checkbox and the empty space after the name do not. Scrolling the analytics bar clears the outline, and it stays clear until the pointer moves onto a name or color chip again. **By team** off: one row per player who owns at least one planet ([#604](https://github.com/SteveDraper/Planets-Console/issues/604)), with a checkbox, palette swatch, and roster username (numeric id when the name is missing). There is no row for a player who owns nothing. Each checkbox starts checked. The accessible name is `Show ${legendText} territory`, the same pattern as a league team. Unchecked values are that row's `Player.id` (the id on the legend row and the overlay `playerId`), stored per open game id in the same localStorage entry as **Owned planets only**. A missing game, or an id not in that game's list, stays visible. Hiding a player in one game does not hide them in another. `Player.accountid` and the perspective slot are not stored. With no open game the checkbox does not write storage. An unchecked row omits that player's fill on both player site sets and does not change the fill color. It does not omit team-territory overlays. A hidden league team does not omit player-territory overlays. Hovering the name or the color chip outlines that player's regions on the active site set, whether or not the row is checked. The checkbox and the empty space after the name do not. Scrolling the analytics bar clears the outline, and it stays clear until the pointer moves onto a name or color chip again. Cell hover names the team or the player under the pointer from the active site set, including when that fill is hidden. Legend hover, the outline, and the cell hover run only while the analytic is enabled. Toggling a row or **By team** does not refetch |
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
5. Union the same cells two ways. **Team territory** paints a cell only when its winning site has an owner with `leagueteamid > 0`, and unions by that league team id. **Player territory** paints a cell only when its winning site has `ownerid > 0`, and unions by that owner id. Disjoint components stay separate overlays.
6. Clip every ring to the map rectangle: `[2000 - mapwidth / 2, 2000 + mapwidth / 2] x [2000 - mapheight / 2, 2000 + mapheight / 2]`.

## Wire

Core `compute` returns a JSON object:

- `analyticId`: `team-information`
- `sphere`: bool from settings
- `teams`: `{ leagueTeamId, fillColor, fillPattern, playerIds }[]` for every league team that owns at least one planet on the turn (even if a site set paints nothing for them)
- `players`: `{ playerId }[]` for every player who owns at least one planet on the turn, including `leagueteamid == 0`
- `regionOverlays`: both site sets, each unioned both ways

| By team | Owned planets only | `kind` | `id` |
|---------|--------------------|--------|------|
| on | off | `team-territory` | `team-territory:{leagueTeamId}:{component}` |
| on | on | `team-territory-owned-only` | `team-territory-owned-only:{leagueTeamId}:{component}` |
| off | off | `player-territory` | `player-territory:{playerId}:{component}` |
| off | on | `player-territory-owned-only` | `player-territory-owned-only:{playerId}:{component}` |

Each overlay is a shared boundary **map region overlay**. Team overlays carry `leagueTeamId`, `fillColor`, and `fillPattern` (`solid`, `forward`, `back`, `horizontal`, `vertical`, or `dots`), opacity `0.35`. Player overlays carry `playerId` and `fillPattern: solid`. They do not carry a league team id. `fillColor` is present so the shared overlay shape stays intact; the SPA replaces it. `geometry` is `{ type: "boundary", vertices: [{x, y}, ...], edges: [{type: "line"}, ...] }`, closed, no arcs. No English strings.

`fillPattern` on a team row matches every team overlay for that team. The SPA draws the hatch in screen pixels so it stays readable when zoomed out. Hatch strokes are white at 0.35 opacity so the team color stays dominant, and the legend swatch uses the same marks.

BFF map handler passes the Core object through. The table route stays a validation error.

## Frontend

- Register the map merger so `regionOverlays` from this analytic join the combined map.
- Persist **Owned planets only** and hidden league-team ids in localStorage (global). Default off and all teams visible.
- Persist **By team** as a map of game id to boolean in that same entry. Missing id reads as off. Bump the persist version; a blob without the field rehydrates as off for every game. Other games are unchanged.
- Persist hidden player ids in that same entry, keyed by game id. Each list is `Player.id` from the legend row. A missing game or a missing id stays visible. Bump the persist version; a blob with no player-hide field rehydrates as no hidden players. `ownedPlanetsOnly`, `hiddenLeagueTeamIds`, and `byTeamByGameId` stay as they are. No game id does not write. The storage key stays `planets-console-team-information-preferences`.
- Paint exactly one kind from the checkbox pair. Filter in a territory-owned function. Do not run these kinds through Visibility kind preferences. Hidden league-team ids do not filter player overlays. Hidden player ids do not filter team overlays. Legend visibility runs after kind selection and player-palette colors. Highlight and cell hover read the list from before that visibility filter.
- Sidebar: the shared `AnalyticSidebarTile` enable row, display name **Territory**. **By team** sits above **Owned planets only** in the chevron pane (closed until expanded, and only while the analytic is enabled). Accessible name: `By team`. **By team** on: legend rows from `teams` (visibility checkbox, swatch, directory name or the numeric id when that name is null). Usernames are hover text on the name and color chip and are not drawn in the row. **By team** off: legend rows from `players` (visibility checkbox, palette swatch, roster username or the numeric id). Names load from `GET /bff/games/{game_id}/league-teams` with TanStack Query for the open game, separate from the map query, and only the team legend uses them. Grey the tile in tabular **view mode** via `supports_table=false`.
- Cell hover: a **map interaction contributor** (role `team-territory`) hit-tests the active site set. **By team** on includes league teams whose fill is hidden and contributes the team label. **By team** off includes players whose fill is hidden and contributes the player label. Title is `Territory`. It `yieldsTo` planet hover and `mergesWith` fleet, region, and cartography (off a planet, the fleet card anchored at the ship hosts the territory section). It is registered only while the analytic is enabled.
- No edge-mirror strip. Opposite edges of one region share a color, which is the wrap cue.

## Layers

- **Core** (`api/analytics/team_information.py`): paint, styles, overlays, and wire. The Voronoi and the four-section partition live in `team_territory.py`. One site-set table orders the live partitions and the movie file sections: team kind then player kind, all-planets then owned-planets. `territory_sections` returns those sections and does not compute border neighbors. The live map calls `territory_sections_with_neighbors`, which takes border neighbors from the same Voronoi that built each site set. The Territory movie packer calls `territory_sections` in `team_territory.py`. It does not import `team_information.py`.
- **BFF** (`bff/analytics/team_information.py`): passthrough `get_map`. Empty export catalog on the Core registration.
- **SPA** (`src/analytics/team-information/`): merge, preference store, sidebar legend and checkboxes, kind filter, player-palette paint.

Reuse the turn-analytic catalog, `empty_export_catalog_for`, shared boundary `regionOverlays`, and the map fetch/merge registry. Do not add a query parameter to the shared map route. Do not import another analytic for the partition.

## League team directory

Legend names for **team territory** come from the **league team directory**, not from this analytic ([#549](https://github.com/SteveDraper/Planets-Console/issues/549)). Drawing them is [#550](https://github.com/SteveDraper/Planets-Console/issues/550).

Stored GameInfo players already carry `username` and `leagueteamid`. `leagueteamid == 0` is omitted from the directory. Each distinct id is resolved once: one public `GET /account/loadprofile` for any member of that id, then the `playergroups` row whose `groupid` equals the id, and `_group.name`. The `{id, name}` pair is cached by league team id, across games. A cached id is not fetched again. An unknown id, a profile with no matching row, or an upstream failure for that id returns `name: null` and leaves the other ids intact. Failures are not cached.

- Core `GET /api/v1/games/{game_id}/league-teams`
- BFF `GET /bff/games/{game_id}/league-teams` forwards to Core and returns the same body: `{ "teams": [{ "id", "name" }] }`

`api/analytics/team_information.py` does not import the directory service. The SPA does not fold this fetch into the Territory map compute. **Player territory** labels come from the turn roster, not this directory.

## Territory movie payload

Core packs one movie for a game at one perspective. The span is stored host turns 1 through `GameInfo.game.turn`, not the shell's selected turn. A missing stored turn fails the request. The route does not fetch turns from Planets.nu and does not skip a turn after elimination.

`GET /api/v1/games/{game_id}/{perspective}/territory-movie`

The BFF route is the same path under `/bff/games` and returns that body unchanged. OpenAPI for the route lives in the games slice.

The body is `turn` (`GameInfo.game.turn`), `rectangle` (`left`, `bottom`, `width`, `height`), base64 gzip blobs `rings` and `planets`, and a span-wide legend `players` and `teams` (`id`, `name`). `name` is null when the roster username or the league team directory name is missing. No colors, selection, or HTML.

`rings` is little-endian `uint16`, four sections in order: `team-territory`, `player-territory`, `team-territory-owned-only`, `player-territory-owned-only`. Inside a section, turns `1..turn`. A turn is a component count, then that many components of `group_id`, vertex count, and `dx`, `dy` pairs. `x = rectangle.left + dx / 10`, `y = rectangle.bottom + dy / 10`. Quantization is Python 3 `round` (ties to even). Group id `0` is omitted. An empty turn is a zero count. Owned-planets-only is the second diagram from `territory_unions`, not a filter of the all-planets rings.

`planets` is a `uint16` count, then rows sorted by planet id: `id`, host `x`, host `y`, `first_turn`. `first_turn` is the first stored turn that contains that id. The coordinates are that turn's host coordinates.

Turns in the span share one map rectangle (`mapwidth`, `mapheight`, `sphere`). Measurements: [issue 601](https://github.com/SteveDraper/Planets-Console/issues/601). Planet-dot layout: [issue 606](https://github.com/SteveDraper/Planets-Console/issues/606).

## Territory movie page

The Territory tile's details pane includes a **Generate movie** button with **By team** and **Owned planets only**. While the file is built the button is disabled. There is no progress strip.

The click opens a blank window immediately, then ensures the current viewpoint's host turns 1 through `GameInfo.game.turn` with the existing turn-ensure route, including turns after elimination. It then fetches the Territory movie payload, wraps it in one HTML document, and navigates that window to the document. A failed ensure or payload closes the blank window and sets the shell error bar. The button does not read or write the live analytic's player-hide preference.

The document is `text/html` served by the console at `/bff/territory-movie-pages/{id}` until the window closes, so Save Page As, HTML only, writes one file that runs from `file://`. The address is an ordinary console URL. The page is HTML, CSS, and one script. It inflates the two gzip blobs with `DecompressionStream`. No React and no graph library.

Each frame is one SVG of the map rectangle on a `#000` background. The viewBox flips y so host +y is up. Rings for the section selected by **By team** and **Owned planets only** are filled at opacity 1 with no stroke, even-odd, one path per visible group id and a closed subpath per ring. Planet dots are 4px `#9ca3af`, painted on top of the rings, for every id whose `first_turn` is at or before the frame. A planet blob whose count disagrees with its length, or that repeats an id, paints no dots. The turn scale under the map is the frame indicator.

Playback starts on turn 1. Under the map, a turn scale has a tick per turn and a number on turn 1 and every 10th turn. A draggable cursor on that scale selects the frame. To its right, **Speed** has slower and faster buttons. Faster shortens the frame period by 10 percent and slower lengthens it, bounded by 0.1 seconds and 5 seconds. The playback controls sit under that scale and are skip to turn 1, one frame back, play, pause, and one frame forward. The scale and those controls share the sidebar's dark grey. The media buttons are lighter so they read against it: play and pause in green, the frame and restart controls in cyan. **By team**, **Owned planets only**, and the legend sit in a sidebar to the left of the map. The legend is indented under those two switches. The sidebar width fits the longer of the player and team names, so the map stays put when the legend changes. The map scales to the space left in the window. Play starts at one frame every second. Both legends start empty. Checking an owner assigns the next Territory movie color index that selection has not given out. Unchecking keeps the index. Changing frame or either section switch does not reassign indexes. A selected owner with no ring on the frame keeps the legend row. Fill is the movie palette at full opacity.

The file embeds palette indexes 0 through 59. A legend longer than 60 appends further colors with the same maximin rule before the file is written, and does not recompute indexes 0 through 59. The page only indexes that list.

## Tests

**Geometry (Core)**:

- Sphere: a site at `x = 1` is nearer to `x = mapwidth - 1` than a site at the middle of the same row. The painted component crosses the seam as two rings inside the rectangle (or one ring per side) with the edge site's league team.
- Non-sphere: the same pair uses planar distance, so the far side of the seam is not claimed by the edge site.
- All-planets set: an unowned planet's cell is absent from both unions. Owned-planets-only assigns that area to the nearest owned player and, when that owner has a league team, to that league team.
- `leagueteamid == 0`: that owner's cells are absent from both team kinds and present in the player kinds.
- Two adjacent planets with different owners on one league team: one team component, two player components.
- Exact tie: lower planet id wins.

**BFF and SPA**:

- Registry metadata: map yes, table no, selectable, display name Territory.
- BFF map returns the Core shape; table route is a validation error.
- Merger keeps every kind. The preference filter emits only the selected kind and leaves non-territory overlays alone.
- **By team** on: legend lists the league team name when the directory has one, otherwise the id. Member usernames stay on the name and color chip and are not drawn.
- **By team** off: legend and hover use the player. Preferences default off, a stored true sticks for that game id only, and a pre-change blob stays off. Each owning player has a show checkbox, default checked. Uncheck removes that player's fill on both site sets, does not change the fill color, and survives reload for this game only. Another game's hidden players are unchanged. A blob with no player-hide field still shows every player. With the fill hidden, legend hover still outlines that player and cell hover still names them.
- **By team** on still hides only league teams. A hidden player does not drop team-territory overlays.
- Browser: the row reads Territory; with the analytic enabled, player colors show; checking **By team** switches to league-team colors with no refetch; reload keeps that choice for this game and not for another. The tile is grey in tabular mode.
- Territory movie: the button opens a window during the click, then ensures turns 1 through `GameInfo.game.turn` for the current viewpoint and navigates that window to the document. A failed ensure or payload closes the window and sets the shell error bar. The document contains both blobs and the playback controls. Index assignment, an empty-frame legend row, full-opacity fills under 4px dots, a 1 second play step, the turn scale, and a 10 percent speed step are covered in the page runtime.

## Out of scope

Context menu for member usernames, edge-mirror margin, in-game `teamid` coloring, tabular tile, export queries, per-team color pickers, client-side distance, renaming `analytic_id` or the preferences storage key. League team names are [#549](https://github.com/SteveDraper/Planets-Console/issues/549) and [#550](https://github.com/SteveDraper/Planets-Console/issues/550).
