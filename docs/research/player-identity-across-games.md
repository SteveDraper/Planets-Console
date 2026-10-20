# What identifies a Player across games

Research for [What identifies a Player across games](https://github.com/SteveDraper/Planets-Console/issues/598). Map: [Territory movie](https://github.com/SteveDraper/Planets-Console/issues/597). Where hides are stored is [issue #599](https://github.com/SteveDraper/Planets-Console/issues/599) and is out of scope here.

**Verified:** 2026-10-20 against `Player` / `GameInfo` / `TurnInfo`, `GameService` perspective mapping, the team-information player partition, the SPA player-color store, committed game 628580 fixtures, and the Planets.nu help mirror under `Personal-wiki/Personal-wiki/raw/planets-nu-help/`.

## Summary

`Player.accountid` is the planets.nu account id: the same account in every game. The **perspective** slot is only a seat in one game. `Player.id` is a third value, the in-game host player id. It is neither the account nor the seat index. The per-player color palette already keys on `Player.id`.

Live player territory is painted by planet `ownerid`, which Core matches to `Player.id`, not to `accountid` and not to the perspective ordinal.

## Account: `Player.accountid`

`Player` and `Score` both carry `accountid: int` beside `id` ([`packages/api/api/models/player.py`](../../packages/api/api/models/player.py) `Player`, `Score`). `game_info_from_json` and `turn_info_from_json` copy the planets.nu JSON field through unchanged ([`game_info_from_json`](../../packages/api/api/serialization/game.py), [`turn_info_from_json`](../../packages/api/api/serialization/turn.py)).

The help mirror's players object lists `accountid` and `id` as different sample values (`29231` and `1`). The score object repeats that split: `ownerid` `1`, `accountid` `29231` (`raw/planets-nu-help/API-game-loadinfo/body.html`, players object and score object).

`/account/officers` takes `accountid` and describes it as "Account (ID) to read the officers from". The call has no game id (`raw/planets-nu-help/API-account-officers/body.html`). Officer creation keys rows by `AccountId` plus race, not by game (`raw/planets-nu-help/API-account-createofficer/body.html`, `AccountId_RaceId`). That account id is therefore not scoped to one game.

On a seat, `accountid` tracks the occupant. After elimination, live game 628580 perspective 1 is `username == "dead"` with `accountid == 0`; that pair is explicitly not a death test by itself ([`docs/design-player-elimination.md`](../design-player-elimination.md) section 2). The committed `GameInfo` for that game shows the same pattern on every dead slot (`packages/api/tests/fixtures/inference_corpus/628580/info.json`).

No cited source shows one human's `accountid` repeated in two live games. The cross-game claim rests on the account API: `accountid` names an account, and the player row stores that field while the account occupies the seat.

## Seat: perspective slot

**Perspective** is the seat: `1` .. `11` for participants, `0` for spectator, stable for the life of the game ([`CONTEXT.md`](../../CONTEXT.md) **Perspective**). It is the index in `GameInfo.players`, not `Player.id`.

[`GameService.perspective_for_username`](../../packages/api/api/services/game_service.py) returns `index + 1` in `info.players`. [`GameService.player_id_for_perspective`](../../packages/api/api/services/game_service.py) returns `0` for spectator and otherwise `players[perspective - 1].id`. [`GameService.perspective_for_player_id`](../../packages/api/api/services/game_service.py) scans for `player.id`, then returns that list index plus one. The glossary states the same split: a payload `id` of 42 is not perspective 42 ([`CONTEXT.md`](../../CONTEXT.md) example dialogue).

The seat can change hands. On 628580, perspective 11 stays the slot while the username changes from `root` to `nocere` at `statusturn` 90 with `status` still active ([`docs/design-player-elimination.md`](../design-player-elimination.md) section 3.3).

Upstream `loadturn` documents its `playerid` parameter as "Player slot number" (`raw/planets-nu-help/API-game-loadturn/body.html`; turn-ready says a slot from 1 to 35, `raw/planets-nu-help/API-turnready/body.html`). The console does not send the ordinal. [`TurnLoadService.ensure_turn_loaded`](../../packages/api/api/services/turn_load_service.py) sends `GameService.player_id_for_perspective`, which is `Player.id` (or `0` for spectator).

## In-game host player id: `Player.id`

`Player.id` is the payload id on that player row. **Perspective** tells readers to avoid the bare phrase "player id" because it collides with these in-game entity ids ([`CONTEXT.md`](../../CONTEXT.md) **Perspective**, **Player**). The SPA calls `players[].id` the host player id and uses it when present, falling back to the 1-based ordinal only when `id` is absent ([`PerspectiveRow`](../../packages/frontend/src/lib/gameInfoShell.ts), `buildPerspectivesFromGameInfo`, `playerIdForPerspectiveOrdinal`). A shell test sets ordinal 1 to host id `42` ([`gameInfoShell.test.ts`](../../packages/frontend/src/lib/gameInfoShell.test.ts)).

`Score.ownerid` is this id, not `accountid`. Opening-reveal matching uses `player.id == score.ownerid` ([`_opening_reveal_baseline`](../../packages/api/api/concepts/accelerated_scoreboard.py)).

In the committed 628580 `GameInfo`, `Player.id` happens to equal the 1-based list index (`1` .. `11`). That equality is not the model. Whether `Player.id` is reused in another game is not established.

Player-territory overlays group planets by `ownerid` ([`territory_unions`](../../packages/api/api/analytics/team_territory.py)) and put that integer on the wire as `playerId` ([`_boundary_overlay`](../../packages/api/api/analytics/team_information.py), [`_player_rows`](../../packages/api/api/analytics/team_information.py)). The SPA player partition reads `overlay.playerId` ([`territoryOwnerId`](../../packages/frontend/src/analytics/team-information/kinds.ts)). League-team hides are a different id (`hiddenLeagueTeamIds`); this note does not choose a store for player hides.

## Palette key

The per-player palette is [`usePlayerColorsStore`](../../packages/frontend/src/stores/playerColors.ts), persisted as `planets-console-player-colors` (`PLAYER_COLORS_STORAGE_KEY`). Color overrides are keyed by [`playerColorOverrideStorageKey`](../../packages/frontend/src/lib/playerColor.ts), which is `String(playerId)`. Defaults also hash that same integer (`defaultColorForPlayerId`).

Shell paint context fills those ids from `perspectives[].playerId` ([`useShellContext`](../../packages/frontend/src/shell/useShellContext.ts)), which is the host player id above. The persisted document has no game id and no perspective ordinal (`partialize` keeps `overrides`, `mode`, and the diplomacy color knobs only). It does not key on `Player.accountid`.
