# Design: Player elimination detection

This document records how Planets.nu represents eliminated players, how we verified it against live API data, and the helper API to use before implementing turn clamping, load-all completeness, and viewpoint auto-adjust.

Related: [design-planets-api-data-model.md](design-planets-api-data-model.md), load-all progress in `TurnLoadService`.

---

## 1. Goals

- Detect **elimination death** per perspective (player slot), not merely missing turn files.
- Know **which turn** a player was eliminated on (`statusturn`).
- Support future shell behaviour:
  - Clamp turn selection to the last meaningful turn for an eliminated viewpoint.
  - On viewpoint switch, if the selected turn is past that player's elimination, auto-adjust to their last turn.
  - Treat load-all as complete for an eliminated perspective through `statusturn`, not through `game.turn`.
- Distinguish elimination from **slot replacement** and other uses of `statusturn`.

---

## 2. Wire fields (Planets.nu)

Each `Player` row in `loadinfo` and in every `TurnInfo.players[]` snapshot includes:

| Field | Role |
|-------|------|
| `status` | Player life-cycle state (integer). **`3` = eliminated** in verified samples. **`1` = active** in verified samples. |
| `statusturn` | Turn when `status` last changed. For eliminated players, this is the **elimination turn**. |

The `Game` object also has `turnstatus` (string, one char per slot). Planets.nu documents **`x` = dead** for that slot. Useful as a cross-check on the **current** game snapshot; prefer `players[].status` + `statusturn` for historical logic.

**Do not confuse** `Game.status == 3` (`GameStatus.FINISHED`) with `Player.status == 3` (eliminated). They share the numeric value on different objects.

**Do not infer death from:**

- Missing turn files in storage or loadall alone.
- `username == "dead"` or `accountid == 0` (common after elimination, not reliable alone).
- `statusturn` without checking `status` (see §4).

---

## 3. Verified behaviour (game 628580, live API, 2026)

Calls: `loadinfo`, `loadturn` (playerid = perspective), `loadall` ZIP inspection.

### 3.1 Eliminated player (perspective 1, originally `dougp314`)

| Turn | `status` | `statusturn` | `username` | Notes |
|------|----------|--------------|------------|-------|
| 47 | 1 | 1 | `dougp314` | Alive |
| 48 | 1 | 1 | `dougp314` | Alive |
| 49 | 3 | 49 | `dead` | Eliminated on this turn |
| 50+ | 3 | 49 | `dead` | Remains eliminated |

Same pattern inside loadall `player1-turn48.trn` / `turn49.trn` / later files.

`game.turnstatus` slot char for perspective 1 becomes `'x'` from turn **50** onward (one turn after the `players[]` flip at 49).

### 3.2 Loadall vs final turn

For this finished game, loadall ZIP contains turns **0--110** for **every** perspective, including eliminated ones (turns after death are still present). The only turn missing from loadall for all slots is **111** (`game.turn`). A separate **`final_turn`** load-all phase (`loadturn` for turn 111 per perspective) is therefore still required after ZIP import.

Post-death turns in the ZIP are mostly redundant for analysis; skipping them in load-all policy is a **Console choice**, not an upstream ZIP limitation for this game.

### 3.3 Counterexample: `statusturn` without elimination (perspective 11, `nocere`)

Latest `loadinfo`: `status = 1`, `statusturn = 90` (still active).

| Turn | `username` | `status` | `statusturn` |
|------|------------|----------|--------------|
| 88--89 | `root` | 1 | 1 |
| 90+ | `nocere` | 1 | 90 |

Here `statusturn = 90` marks **slot takeover / join**, not death. Rule: **require `status == ELIMINATED` before treating `statusturn` as an elimination turn.**

---

## 4. Helper API (Core)

**Module:** `packages/api/api/services/player_elimination.py`

**Enum:** `PlayerStatus` in `packages/api/api/models/enums.py` (separate from `GameStatus`).

| Function | Purpose |
|----------|---------|
| `player_status(player)` | Map wire `status` to `PlayerStatus`, `UNKNOWN` if unrecognised. |
| `elimination_turn(player)` | `statusturn` when `status == ELIMINATED`, else `None`. |
| `is_eliminated_at_turn(player, turn)` | `True` when eliminated and `turn >= elimination_turn`. |
| `last_meaningful_turn(player, game_latest_turn)` | `elimination_turn` if eliminated, else `game_latest_turn`. |

**Planned consumers (not implemented in this doc):**

- Shell turn max per viewpoint (BFF field derived from stored `game_info`).
- Viewpoint switch clamp in `useShellContext` / `shellContext.ts`.
- `TurnLoadService.load_all_turns_status` and ZIP import completeness (expected turns `1 .. last_meaningful_turn` per perspective).
- Optional: skip `final_turn` `loadturn` for perspectives already stored through `game.turn - 1` when eliminated before latest turn (optimisation only).

---

## 5. Tests

**Unit:** `packages/api/tests/test_player_elimination.py` -- enum mapping and rules using documented 628580 values.

**Manual / regression:** Re-run live API script against game 628580 if upstream semantics change.

---

## 6. Open gaps

- Full `Player.status` enum beyond `1` (active) and `3` (eliminated) is not vault-documented (resign, computer slots, etc.).
- Whether every elimination type sets `status = 3` is assumed from samples, not exhaustively proven.
- Slot replacement (`nocere` / `root`) may need a separate `join_turn` concept later; out of scope for elimination clamping.
