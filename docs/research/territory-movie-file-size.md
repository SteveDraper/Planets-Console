# Territory movie file size and geometry encoding

Research for [Territory movie file size and geometry encoding](https://github.com/SteveDraper/Planets-Console/issues/601). Map: [Territory movie](https://github.com/SteveDraper/Planets-Console/issues/597).

**Verified:** 2026-10-20 against [`team_territory.py`](../../packages/api/api/analytics/team_territory.py), [`team_information.py`](../../packages/api/api/analytics/team_information.py), [`map_region_overlay_to_wire`](../../packages/api/api/concepts/map_region_coverage.py), and stored RST turns in this workspace's gitignored `.data/games`.

This note sizes the four Territory partitions and picks an encoding for one self-contained HTML file. It does not choose zoom, planet names, or the drawing API, and it does not change the live Territory analytic.

## Summary for implementers

Keep all four partitions. They stay small together.

The largest complete movie measured is **Adobee Sector** (game 673864, viewpoint 1, host turns 1 through 60, sphere, 759 planets, 57 players, no league teams): **877,408 bytes** packed, **91,330 bytes** gzipped. Base64 of that gzip is **121,776** characters in the HTML. The only measured game whose league-team rings are a different shape from its player rings is **Bundy Sector** (game 686674, viewpoint 21, turns 1 through 22, sphere, 705 planets, real league teams): **461,340 bytes** packed, **82,840 bytes** gzipped, base64 **110,456** characters.

Store the rings `territory_unions` already returns. Four sections, one per kind (`team-territory`, `player-territory`, `team-territory-owned-only`, `player-territory-owned-only`). Each vertex is a little-endian `uint16` offset from the map rectangle's lower-left corner on a **0.1 LY** grid. Gzip the four sections and embed the base64. The page inflates with the browser's `DecompressionStream` (no network, so `file://` works) and filters with two choices it already has to make: which section, and which `group_id`s are shown. No React and no graph library.

The analytic's `regionOverlays` wire is the wrong body for this file: about **15.0 MB** of compact JSON for Adobee and **7.9 MB** for Bundy, because every vertex is an `{x, y}` object plus a `{type: "line"}` edge.

## 1. The four partitions

[`compute_team_information`](../../packages/api/api/analytics/team_information.py) paints both **team territory site set**s and both groupings from one turn:

| Kind | Site set | Group id |
|------|----------|----------|
| `team-territory` | All planets | `league_team_id` |
| `player-territory` | All planets | `owner_id` |
| `team-territory-owned-only` | Owned planets only | `league_team_id` |
| `player-territory-owned-only` | Owned planets only | `owner_id` |

`_SITE_SETS` runs [`territory_unions`](../../packages/api/api/analytics/team_territory.py) twice. One call builds one Voronoi and returns team components, player components, and team adjacency. Group id `0` is omitted (no league team, or an unowned planet). A hole in a union is cut into that component's ring (`_single_ring`): the stored ring is open (the repeated closing vertex is dropped by `_open_ring`), the last vertex connects back to the first, and the interior is the even-odd fill of that ring.

Owned planets only is a second diagram. `_sites` drops `ownerid == 0` before the Voronoi, so those cells are absorbed by the nearest owned planet. Filtering the all-planets rings does not produce it. Player vs team is also a second diagram when several players share a league team: the union follows a different id. Both site sets and both groupings have to be in the file. The measurements below are that file.

## 2. What was measured

A movie frame list is host turns 1 through `GameInfo.game.turn` at one viewpoint. For each complete span on disk, measurement loaded `games/{id}/{perspective}/turns/{n}.json`, built `TerritorySite`s the way `_sites` does (`ownerid == 0` forces league team `0`; otherwise `players[].leagueteamid`), and called `territory_unions` with that turn's `mapwidth`, `mapheight`, and `sphere`.

Packed bytes are little-endian, concatenated in the kind order in the table above, turns `1..game.turn` inside each kind. Each turn is:

```
uint16 component_count
repeated component_count times:
  uint16 group_id
  uint16 vertex_count
  repeated vertex_count times:
    uint16 dx    # x = rectangle.left + dx / 10
    uint16 dy    # y = rectangle.bottom + dy / 10
```

`rectangle` is [`nu_map_rectangle`](../../packages/api/api/analytics/team_territory.py): `mapwidth` by `mapheight` centered on `(2000, 2000)`. Quantization is Python 3 `round` (ties to even): `int(round((coord - origin) * 10))`. Gzip sizes use `gzip.compress(..., compresslevel=9, mtime=0)`. Vertex counts are the `territory_unions` rings before that grid.

Games on disk whose viewpoint did not have every turn from 1 through `game.turn` were not measured (604777, 606461, 609783, 665502, 677987, 680224, 683364).

| Game | Viewpoint | Turns | Sphere | Planets | League teams | Team shape vs player |
|------|-----------|------:|--------|--------:|--------------|----------------------|
| 686674 Bundy Sector | 21 | 22 | yes | 705 | 16 nonzero ids; roster fixed all 22 turns | Different on every turn |
| 628580 Serada 9 Sector | 1 | 111 | no | 509 | none (`leagueteamid` 0) | Team sections empty |
| 673864 Adobee Sector | 1 | 60 | yes | 759 | none | Team sections empty |
| 663307 The Vaporum War | 2 | 85 | no | 489 on turn 1, 514 from turn 37 | 11 ids, one player each | Same rings on every turn, different ids |
| 686688 Bimbo Sector | 2 | 15 | no | 24 | 2 ids, two players each | Different on every turn |

Coordinates of a planet id never changed. Bundy, Serada, Adobee, and Bimbo also kept the same id set on every turn, and the all-planets clipped cells from turn 1 matched turn `game.turn`. Vaporum added ids on turns 12, 17, 18, 26, 28, 32, 33, and 37 (25 planets, `debrisdisk == 0` on each) and never moved an existing id. The all-planets diagram is stable only while the id set is stable. Owned-only changes whenever the owned set changes: Serada repeated the previous turn's owner tuple on 63 of 111 turns; Bundy did that on 0 of 22; Adobee on 1 of 60.

Largest `uint16` written was 23400 (Adobee's 2340 LY side times 10). Largest ring was 170 vertices (Vaporum). Largest group id was 427. All of those fit the field widths above. A side longer than 6553.5 LY would not fit this grid in `uint16`; none of the stored maps are that wide.

## 3. Sizes

Totals over turns 1 through `game.turn`, all four kinds. "Wire" is compact JSON in the shape [`map_region_overlay_to_wire`](../../packages/api/api/concepts/map_region_coverage.py) builds for these rings: `fillColor`, `fillOpacity`, `fillPattern`, `geometry.vertices[]` as `{x, y}`, `geometry.edges[]` as `{"type":"line"}`, and `playerId` or `leagueTeamId`. "JSON rings" is `[[group_id, [[x, y], ...]], ...]` with coordinates rounded to 0.1 LY. Packed and gzip are the layout in section 2.

| Game | Vertices (team all / player all / team owned / player owned) | Wire bytes | JSON-ring bytes | Packed bytes | Gzip bytes | Base64 of gzip |
|------|---------------------------------------------------------------:|-----------:|----------------:|-------------:|-----------:|---------------:|
| Bundy 686674 | 25946 / 30259 / 23549 / 28734 | 7,895,011 | 1,766,659 | 461,340 | 82,840 | 110,456 |
| Serada 628580 | 0 / 9737 / 0 / 5486 | 1,036,586 | 247,010 | 64,300 | 3,657 | 4,876 |
| Adobee 673864 | 0 / 104966 / 0 / 101352 | 14,962,647 | 3,351,053 | 877,408 | 91,330 | 121,776 |
| Vaporum 663307 | 32005 / 32005 / 23320 / 23320 | 7,854,404 | 1,805,960 | 465,760 | 37,410 | 49,880 |
| Bimbo 686688 | 404 / 571 / 320 / 520 | 116,121 | 30,556 | 8,248 | 1,266 | 1,688 |

Empty team sections are in those totals: one `uint16` zero per turn (222 bytes across Serada's 111 turns, 120 bytes across Adobee's 60). They have to stay, so the By team control still has a section when the game has no league teams.

Late frames, in vertices per kind (team all, player all, team owned, player owned):

| Game | Turn | Vertices |
|------|-----:|----------|
| Bundy | 22 | 1443, 1859, 1355, 1785 |
| Serada | 111 | 0, 108, 0, 57 |
| Adobee | 60 | 0, 2202, 0, 2156 |
| Vaporum | 85 | 673, 673, 536, 536 |
| Bimbo | 15 | 36, 55, 34, 53 |

Serada's gzip is tiny because the painted outline is a few hundred vertices and 63 turns repeat the previous owner tuple. The packed form still stores those turns; gzip collapses them. A repeat opcode is not required.

Unpacked, Adobee's geometry is 877,408 bytes (base64 1,169,880 characters). That file is already small. Gzip is what keeps the HTML near 120 KB of geometry. `DecompressionStream('gzip')` runs locally. The rectangle origin and the scale of 10 sit beside the blob (the page needs the rectangle for the shared planet-dot background anyway). Those few numbers are not in the byte counts above.

The page parses `game.turn` turns, then the next kind, four times. At load it keeps four arrays of rings. By team selects the team kind or the player kind. Owned planets only selects the owned kind or the all-planets kind. Which owners are shown drops rings whose `group_id` is not selected. Player ids and league team ids are different selections; the file carries both. Colors stay out of the blob. The movie palette is applied when a ring is drawn.

## 4. The 0.1 LY grid

Every stored planet `x` and `y` in the sampled turns was an integer. Voronoi vertices are not. The grid moves each vertex by at most half of 0.1 LY on each axis, so at most `sqrt(0.05**2 + 0.05**2) = 0.0707` LY.

Across every ring of every measured turn:

| Game | Rings checked | Already self-touching before the grid | Valid rings the grid made invalid | Largest absolute even-odd area change |
|------|-------------:|---------------------------------------:|----------------------------------:|--------------------------------------:|
| Bundy | 6803 | 179 | 2 | 39.6 LY^2 |
| Serada | 630 | 69 | 0 | 59.1 LY^2 |
| Adobee | 12914 | 414 | 4 | 39.3 LY^2 |
| Vaporum | 5620 | 446 | 0 | 66.6 LY^2 |
| Bimbo | 217 | 0 | 0 | 8.0 LY^2 |

"Already self-touching" is `_single_ring`'s zero-width hole cut. Those rings are invalid as simple polygons before any rounding. The fill contract is even-odd, which is what the cut was built for. A nonzero-winding fill will paint the holes.

The grid itself broke six component records, which are three rings:

- Bundy turn 11, owned site set, one triangle of area 0.0018 LY^2. The same ring is stored under team id 71 and player id 5. At 0.1 LY it collapses to area 0 (one edge length goes to zero).
- Adobee turn 42, player 54, a 15-vertex ring of area 16,534 LY^2 in both site sets. After the grid, shapely reports a self-intersection at `(3170, 3150)`, which is on the rectangle's right edge (`2000 + 2340/2`). Even-odd area changes by 5.9 LY^2.
- Adobee turn 55, player 54, a 27-vertex ring of area 52,241 LY^2, again in both site sets, same edge point. Area changes by 4.5 LY^2.

The largest area change on any ring is 66.6 LY^2 (Vaporum turn 33) on a 2150 by 2150 LY map (4,622,500 LY^2). A scale of 20 per LY still fits in `uint16` for these maps (Adobee's side would be 46,800) and cleared the Adobee edge intersections when rechecked. It did not save the Bundy sliver, which is thinner than either grid. Packed size does not change with the scale, because each coordinate is still two bytes. Gzip was measured at scale 10. Scale 10 is the encoding these byte counts belong to.

## 5. Why not one shared cell atlas

Planet positions are fixed per id, and team vs player is a label on the same sites, so it is tempting to store each planet's clipped Voronoi cell once and recolor it. That atlas is the wrong body for this file.

Owned planets only rebuilds the diagram when an unowned planet is dropped. Those cells, packed the same way, were 304,788 bytes on Bundy (gzip 52,792) and 1,070,768 bytes on Adobee (gzip 73,458), before the all-planets cells and the per-turn labels. Union rings are smaller because shared cell edges cancel. A cell atlas also has to be redone when a planet id appears: Vaporum's turn-1 atlas does not match turn 85. On a sphere a planet is not one ring. Bundy's all-planets clip is 773 pieces for 705 planets.

Putting both site sets in as cells, plus a `uint16` owner and `uint16` league team per planet per turn, gzipped to 71,537 bytes on Bundy and 96,101 on Adobee. That is the same order as the union-ring gzip (82,840 and 91,330). The union rings are the rings the analytic already checks against the painted polygon, they filter by the same `group_id` the legend uses, and they do not need a second geometry for "By team". Use them.

## 6. Left open

Zoom, pan, planet name labels, and the drawing call stay open. The ring contract that any of those must honor is the one `_single_ring` already states: open vertex list, close last to first, even-odd fill, line edges only (Territory does not emit arcs).

By team, Owned planets only, and which owners are shown all stay. The four sections together are the whole geometry cost measured here, and the largest of those files is 91 KB gzipped.
