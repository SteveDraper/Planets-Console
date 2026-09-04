# Mine-stock prior mining surface

Research for [Mine-stock prior mining surface](https://github.com/SteveDraper/Planets-Console/issues/396). Map: [Ship-first near-solutions in the mine-contaminated regime](https://github.com/SteveDraper/Planets-Console/issues/394). Miner: [Military score inference: mine build prior assets from finished games](https://github.com/SteveDraper/Planets-Console/issues/92).

**Verified:** 2026-09-03 against `docs/design-military-score-inference-build-priors.md` section 10, Core `prior_mining/` plus `TurnInfo` / `Minefield` / `GameCategory`, committed `prior_weights_*.yaml` provenance, and this workspace's gitignored `.data/games` loadall trees.

This note specs a **mine-stock observation family** so a later task can collect histograms. It does **not** pick a percentile, convert units to military points, or implement destination assets.

## Summary for implementers

Mine-stock is a **single-turn snapshot** of one owner's fields, not a T-to-T+1 inventory delta. Reuse the existing miner's pattern discovery, `loadall` import, owning-player perspective, Horwasp skip, and elimination gates. Do **not** reuse the pair-shaped **inference prior player-host-turn**, adjunct skip, or **inference ship-limit band** as the partition.

Each retained sample is `(game_id, player_id, host_turn T)` read from that player's stored RST: `sum(units)` and `count` over `TurnInfo.minefields` with `ownerid == player_id` and `units > 0` (include the `(0, 0)` empty-stock outcome). Partition **game category** (one file, same `GameCategory.from_game_settings` as today) **x race x host turn**. Store raw integer histograms (same shape as section 7 aggregates). Per-field `units` histograms are cheap (the field already carries `units`). Split web vs normal with `Minefield.isweb` if the collector wants it; do **not** join `(x, y)` to nebulas; do **not** apply 5% + 1-per-field (or any other) decay at mine time.

Per-turn cells are viable as the **stored grain** given the committed contributing-game lists (O(100) games per standard/epic category). Do not pre-band at mine time. Local `.data` is not a substitute: this workspace has no stored standard/epic contributing games. A first mine-stock pass must **replay** games already listed in `contributingGameIds`, because that list is a skip-set for the current miner.

---

## 1. Sampling unit vs today's ship-build / aggregate units

### 1.1 What the miner traverses today

Design section 10.3 defines the atomic unit as `(game_id, player_id, host_turn N)` where turns `N` and `N+1` exist at the owning player's perspective, the player is not eliminated on or before `N+1`, and **inference ship-limit band** is taken from score turn `N+1`. [`CONTEXT.md`](../CONTEXT.md) (**Inference prior player-host-turn**) repeats that pair grain.

Code matches the design:

- [`enumerate_extraction_work_units`](../../packages/api/api/analytics/military_score_inference/prior_mining/extraction_pool.py) walks `game_info.players`, skips Horwasp (`api.concepts.races.is_horwasp`), resolves `GameService.perspective_for_player_id`, iterates `host_turn` in `range(1, last_meaningful_turn)`, requires stored `N` and `N+1`, and skips `is_eliminated_at_turn(player, N+1)`.
- [`extract_extraction_work_unit`](../../packages/api/api/analytics/military_score_inference/prior_mining/extraction_worker.py) loads those two `TurnInfo` documents from the **same** perspective.

From each retained pair the miner emits two **different** observation kinds ([design section 10.4--10.5](../design-military-score-inference-build-priors.md)):

| Family | Grain | What is counted |
|--------|-------|-----------------|
| **Ship-build** | One observation per validated build | Starbase order on `N`, new ship on `N+1` at the base with exact spec. Zero or more per pair. |
| **Aggregate** | One increment per action id per pair | Inventory **delta** on `(N, N+1)`, including `0:` when the delta is 0. |

[`PlayerHostTurnExtraction`](../../packages/api/api/analytics/military_score_inference/prior_mining/observations.py) therefore always carries a `ship_limit_band` and `aggregate_deltas`; it has no minefield fields.

### 1.2 Mine-stock grain (spec)

Mine-stock is a **level**, not a delta. `TurnInfo.minefields` is a list on a single snapshot ([`packages/api/api/models/game.py`](../../packages/api/api/models/game.py) `TurnInfo.minefields`; [`Minefield`](../../packages/api/api/models/space.py) with `units`, `ownerid`, `isweb`, `ishidden`, `infoturn`, `x`, `y`, `radius`). There is no T+1 validation analogous to a starbase build order.

**Specified unit:** `(game_id, player_id, host_turn T)` on **one** stored owner-perspective `TurnInfo` for `T`.

| Gate | Ship-build / aggregate (today) | Mine-stock (this family) |
|------|--------------------------------|--------------------------|
| Discovery / `loadall` / category file | Pattern YAML + `GameCategory.from_game_settings` + complete finished-game turns ([section 10.1--10.2](../design-military-score-inference-build-priors.md)) | Same |
| Perspective | Owning player slot, not spectator 0, not omniscient merge ([section 10.3](../design-military-score-inference-build-priors.md); `enumerate_extraction_work_units` iterates `game_info.players` only) | Same |
| Horwasp | Skipped at enumerate and again in the worker | Same |
| Elimination | Skip if eliminated on or before score turn `N+1` | Skip if eliminated on or before snapshot turn `T` (`is_eliminated_at_turn(player, T)` / `last_meaningful_turn` in [`player_elimination.py`](../../packages/api/api/services/player_elimination.py)) |
| Pair `N` and `N+1` | Required (`work_unit_has_turn_pair`) | **Not required.** Sample every stored owner turn `T` in `1 .. last_meaningful_turn` |
| Adjunct | Skip (section 10.3) | **Do not skip** (section 1.3) |
| Ship-limit band | Partition key for all current tables ([section 4](../design-military-score-inference-build-priors.md)) | **Not a partition key** (section 4) |
| `settings.nominefields` | Not consulted | Skip the **game** when `GameSettings.nominefields` is true ([`game.py`](../../packages/api/api/models/game.py)); stock is identically empty and would dilute every cell |

Do not emit one row per extra perspective slot and do not merge every slot's `minefields` into one omniscient list. That prohibition is already in section 10.3 / the glossary for the miner; mine-stock keeps it.

### 1.3 Adjunct skips

Today, after the pair is loaded, [`classify_complexity`](../../packages/api/api/analytics/military_score_inference/inference_corpus_complexity.py) returns `adjunct` on net ship-count decrease, planet/starbase count decrease, trade/capture hints, or unexplained military swing. [`extract_extraction_work_unit`](../../packages/api/api/analytics/military_score_inference/prior_mining/extraction_worker.py) then returns `ExtractionSkipReason.ADJUNCT` and [`_apply_extraction_row_result`](../../packages/api/api/analytics/military_score_inference/prior_mining/extraction_pool.py) increments `adjunct_skips` without calling `accumulation.add_player_host_turn`. Design section 10.3 applies that skip to **both** ship-build and aggregate sampling so those priors describe clean military-score transitions.

Mine-stock is a population prior of **how many mines an owner holds at T**, used later as a worthwhile cap ([map standing preference](https://github.com/SteveDraper/Planets-Console/issues/394): percentile of mine-stock, convert at solve time). Adjunct turns are exactly the combat / loss / unexplained-swing turns where mine stock is still a real holding. Skipping them would bias the histograms toward quiet pairs.

**Spec:** classify complexity if the collector wants a report tally, but **do not drop** mine-stock samples on `adjunct`. Continue to skip Horwasp and eliminated players.

### 1.4 Owning perspective: full own-field truth, not fogged RST

Solve-time code treats `TurnInfo.minefields` as **viewpoint RST**. [`max_owner_minefield_units`](../../packages/api/api/analytics/military_score_inference/hopeless_classifier.py) documents "Largest RST `units` among this owner's fields" and filters `field.ownerid == owner_id`. [`CONTEXT.md`](../CONTEXT.md) **Recent minefield observation** is "Viewpoint-RST evidence". That is the fogged document the console has for **other** scoreboard rows.

Finished-game mining already stores **each player's own RST** via `loadall` into `games/{id}/{perspective}/turns/{turn}` ([`loadall_import.py`](../../packages/api/api/analytics/military_score_inference/prior_mining/loadall_import.py); [`TurnLoadService.turn_store_key`](../../packages/api/api/services/turn_load_service.py)). Spectator slot 0 is imported when present (`SPECTATOR_PLAYER_SLOT = 0`) but is **not** in `enumerate_extraction_work_units`.

Measured 2026-09-03 on this workspace's `.data/games` (gitignored; stored RST JSON `minefields` arrays):

| Game | Category-relevant settings | Own fields vs others on owner RST | Own `infoturn` vs host turn |
|------|----------------------------|-----------------------------------|-----------------------------|
| 628580 | `campaignmode=False`, `endturn=100`, `shiplimit=500`, 11 players, `minefieldsvisible=False`, `nebulas=0` | Perspective 1 turn 50: **0 own, 9 other**; others' `infoturn` all stale (`42..48`). Across 1221 owner-turns, other-owner fields on the RST averaged 44.7 (max 222). | **0** mismatches on 15792 owned `units > 0` fields |
| 604777 | `campaignmode=True` (campaign contributing id), `minefieldsvisible=False`, `nebulas=3` | Perspective 1 turn 50: 1 own (`infoturn=50`) + 1 other (`infoturn=41`) | **0** mismatches on 7879 owned fields |
| 673864 | campaign, 57 players, `minefieldsvisible=True`, `nebulas=5` | Perspective 1 turn 50: 61 own + 401 other; almost all other fields have current `infoturn` | **0** mismatches on 21491 owned fields |

**Spec:**

1. Read `minefields` only from the **owning player's** stored turn (perspective from `perspective_for_player_id`).
2. Keep a field iff `ownerid == player_id` and `units > 0`. Map entry (i) on [issue 394](https://github.com/SteveDraper/Planets-Console/issues/394) already uses `units > 0`; mining must match.
3. Do **not** sum other owners' fields on that RST. When `minefieldsvisible` is false they are typically stale intel; when it is true they are still **someone else's** stock.
4. Do **not** mine spectator (slot 0) even if `minefieldsvisible` is true.
5. Do not use `infoturn` as an extra own-field filter: in these trees own `infoturn` already equals `T`. Other-owner `infoturn` is not a substitute for switching perspective.
6. Ignore `radius`; stock is `units` (wire keys on stored RST: `friendlycode`, `id`, `infoturn`, `ishidden`, `isweb`, `ownerid`, `radius`, `units`, `x`, `y`). `ishidden` was 0 on all owned fields in the three games; still include hidden owned fields if `units > 0`.

---

## 2. Proposed asset shape

### 2.1 Where it lives relative to today's YAML

Current assets are one file per **game category** under `assets/analytics/scores/prior_weights_{category}.yaml` ([design section 3](../design-military-score-inference-build-priors.md)). Category is **file selection**, not an in-file cross-product key. `GameCategory` ids are `campaign`, `blitz`, `epic`, `standard`, plus `unknown` ([`game_category.py`](../../packages/api/api/concepts/game_category.py) `GAME_CATEGORY_RULES_VERSION = 4`). Miner patterns exist for standard, epic, and campaign only ([`prior_mining_patterns_*.yaml`](../../assets/analytics/scores/)); there is no `prior_weights_blitz.yaml`.

[`merge_accumulation_into_asset`](../../packages/api/api/analytics/military_score_inference/prior_mining/merge.py) only folds hull, component, and aggregate tables plus `contributingGameIds`. [`PriorWeightsAsset`](../../packages/api/api/analytics/military_score_inference/prior_weights_asset.py) has no mine-stock field. `contributingGameIds` is provenance only: parsed onto the asset and **ignored** by [`resolve_prior_weights_catalog`](../../packages/api/api/analytics/military_score_inference/prior_weights_resolve.py) ([design 10.6](../design-military-score-inference-build-priors.md), glossary **Inference prior contributing games**).

**Spec:** add a **sibling** YAML per category, e.g. `mine_stock_{category}.yaml`, written by the same miner process (shared discovery, `loadall`, turn cache, report). Do not stuff mine-stock into `aggregates.{before,after}_ship_limit` -- that partition is ship-limit queue rules ([`is_after_ship_limit`](../../packages/api/api/analytics/military_score_inference/inference_target.py)), not calendar turn, and is the wrong axis for stock that grows with `T` (section 3).

Give the sibling its **own** `contributingGameIds` (monotonic append, same semantics as 10.6). A first collection **must replay** ids already listed on `prior_weights_{category}.yaml` (and any locally complete finished games in `.data`) because the live miner skips any id already on that list ([design 10.1 step 4 and 6](../design-military-score-inference-build-priors.md); [`iter_accepted_games_for_pattern`](../../packages/api/api/analytics/military_score_inference/prior_mining/discovery.py)). Replaying mine-stock through the existing skip-set would otherwise collect **zero** rows from the games already mined for hull/aggregate priors.

Rejected ids are also appended to `contributingGameIds` ([`runner.py`](../../packages/api/api/analytics/military_score_inference/prior_mining/runner.py) `_process_prepared_game` false branch and `_provenance_updates_for_state`). The skip-list is not "successfully extracted games only". Mine-stock replay should still attempt extraction when the turn set is complete; keep a separate rejected tally in the miner report.

### 2.2 Observation record (one sample)

For each retained `(game, player, T)`:

```text
owned = [f in turn.minefields if f.ownerid == player_id and f.units > 0]
total_units = sum(f.units for f in owned)   # 0 if empty
field_count = len(owned)                    # 0 if empty
race_id = player.raceid                     # same source as ShipBuildObservation.race_id
category = GameCategory.from_game_settings(settings, player_count=len(info.players))
```

Use `from_game_info` / `from_game_settings(..., player_count=...)` so standard/epic still require exactly 11 players (`STANDARD_EPIC_PLAYER_COUNT`); mismatch is `unknown` and must not be merged into `standard` / `epic` files ([`GameCategory.from_game_settings`](../../packages/api/api/concepts/game_category.py)).

Increment **raw integer histograms** (design section 7.1 / 10.5: miner does not pre-bin; `0:` is a real outcome):

| Histogram | Key | When |
|-----------|-----|------|
| `totalUnits` | `total_units` (0 if none) | Once per sample |
| `fieldCount` | `field_count` (0 if none) | Once per sample |
| `perFieldUnits` | each `f.units` | Once per owned field; **no** `0:` from empty stock (empty is already on the two totals) |

Optional cheap splits (same traversal, `Minefield.isweb`):

| Histogram | Filter |
|-----------|--------|
| `webTotalUnits` / `webFieldCount` / `webPerFieldUnits` | `isweb is True` |
| `normalTotalUnits` / `normalFieldCount` / `normalPerFieldUnits` | `isweb is False` |

Pooled `totalUnits` / `fieldCount` is the map's required pair. Web vs normal is **not** required to pick a percentile later; emit it because the flag is already on the record (measured: 628580 had 2123 web + 13669 normal owned fields; 604777 1625 web + 6254 normal; 673864 Crystal perspective-1 turn 50 had 61 own web fields). A later consumer may pool or not.

### 2.3 Partition keys

Minimum required by the ticket / map: **game category x race x turn**.

```yaml
# Illustrative; not a shipped schema
version: 1
category: standard
gameCategoryRulesVersion: 4
mineStock:
  byRace:
    1:                    # raceid
      byTurn:
        40:
          totalUnits:
            histogram:
              0: 12
              40645: 1
          fieldCount:
            histogram:
              0: 12
              9: 1
          perFieldUnits:
            histogram:
              437: 4
              1826: 1
contributingGameIds: [ ... ]
```

- **Game category:** filename + `category:` field, resolved with the same function as the miner ([design 10.1](../design-military-score-inference-build-priors.md): do not infer from list `gametype` alone).
- **Race:** integer `raceid` as in hull `byRace` ([design section 5.1](../design-military-score-inference-build-priors.md); `ShipBuildObservation.race_id`).
- **Turn:** host turn `T` of the snapshot (the stored turn number). Not ship-limit band. Not a 10-turn band at write time (section 3).

Do not add a global (race-pooled) table as the primary product: the worthwhile cap is race-conditioned on the map. A pooled diagnostic in the miner report is fine.

### 2.4 Per-field sizes are cheap

Each `Minefield` already has `units` ([`space.py`](../../packages/api/api/models/space.py)). Owner filtering plus two integer reductions (`sum`, `len`) is one pass over `turn.minefields`. A third histogram that increments once per owned field is the same pass. Map [issue 394](https://github.com/SteveDraper/Planets-Console/issues/394) **Not yet specified** asked whether the miner can cheaply emit sizes: **yes**. Collect `perFieldUnits` in v1 so a later task can choose `(total units, field count)` vs size-aware bounds without a second loadall.

Measured unique `units` values (owned, `units > 0`): 2646 in game 628580 (15792 fields), 3600 in 604777 (7879 fields), 3665 in 673864 (21491 fields). Wide support, still a raw integer histogram like aggregates.

### 2.5 What the miner must not do

From the ticket and map standing preferences / out of scope:

- **Do not convert to decay military points at mine time.** Store `units` and field counts. The map converts leftover points **at solve time** with default 5% + 1 per field and says "Do not store decay points."
- **Do not split by nebula.** `Minefield.x` / `y` and `TurnInfo.nebulas` would make a join possible; v1 must not. Map out of scope: nebula 15% decay / homeworld-segment-conditioned bounds. `GameSettings.nebulas` on the three local trees was 0, 3, and 5 -- category files will mix nebula and non-nebula games unless someone later adds a follow-on family.
- **Do not pre-bin** into solver probability buckets (`magnitude_bin_index` is a catalog-build concern for aggregates, [section 7.2](../design-military-score-inference-build-priors.md)). Mine-stock is not a solver action weight.
- **Do not pick a percentile** in this family or in the collector.

---

## 3. Sparsity: per-turn cells vs turn bands

### 3.1 Committed contributing games

`contributingGameIds` in the category assets (parsed 2026-09-03):

| Asset | `contributingGameIds` count | Pattern `max_games` |
|-------|-----------------------------|---------------------|
| `prior_weights_standard.yaml` | 117 | 100 (`standard-v1-seed`) |
| `prior_weights_epic.yaml` | 111 | 100 (`epic-v1-seed`) |
| `prior_weights_campaign.yaml` | 58 | 50 (`campaign-v1-seed`) |

Counts can exceed `max_games` because rejected games are also appended (section 2.1).

Proxy for **successfully extracted pair-units** (non-adjunct): sum of all histogram bin counts on `aggregates.*.planet_defense_posts_added_total`, which [`add_aggregate_sample`](../../packages/api/api/analytics/military_score_inference/prior_mining/accumulation.py) increments once per retained player-host-turn:

| Category | `before_ship_limit` | `after_ship_limit` | Total pair-units |
|----------|---------------------|--------------------|------------------|
| standard | 20435 | 19642 | 40077 |
| epic | 32013 | 22903 | 54916 |
| campaign | 14040 | 12710 | 26750 |

Mine-stock snapshots (no pair, no adjunct skip, include last turn) will be **strictly more** numerous than these pair-units on the same games.

Standard and epic 11-player games typically have distinct `raceid` 1--11 ([`STANDARD_EPIC_PLAYER_COUNT`](../../packages/api/api/concepts/game_category.py); local 628580 races `[1..11]`). Then each `(category, race, turn)` cell receives **about one sample per contributing game that still has that race alive at T**. With O(100) listed games that is O(100) samples early, fewer late as `last_meaningful_turn` / `is_eliminated_at_turn` drop players.

### 3.2 Local stored finished turns (this workspace)

`.data/games/` is gitignored. On 2026-09-03 it held 10 game ids. Overlap with committed `contributingGameIds`: **campaign only** -- `604777`, `606461`, `609783`, `673864`. Standard and epic contributing lists overlap **none** of the local trees. `606461` has `info.json` and no perspective turn dirs.

Full-tree owner-perspective scans:

| Game | Owner-turn samples | Zero-stock samples | `(race, turn)` samples/cell | `(race, 10-turn band)` samples/cell |
|------|--------------------|--------------------|-----------------------------|-------------------------------------|
| 628580 (epic-shaped settings) | 1221 | 575 (47%) | min=max=median **1** | median **10** |
| 604777 (campaign, in YAML) | 912 | 392 | **1** | median **10** |
| 673864 (campaign, 57 slots, duplicate races) | 3006 | 1020 | min 1 max 6 median **5** | median **48** |

Stock is strongly turn-dependent on these trees (628580: turn 1 mean units 0; turn 40 mean 9541; turn 105 mean 18524). Collapsing only on ship-limit band would mix those regimes. Late cells thin (604777 turn 97: 5 remaining players vs 11 at turn 1).

**One local game cannot populate a per-turn cell.** The collection task must `loadall` the committed contributing ids (and/or discover up to pattern caps). Local `.data` is useful for pipeline tests, not for the histogram corpus of standard/epic.

### 3.3 Verdict

**Mine and store per host turn. Do not pre-band.**

Per-turn cells are viable as an empirical histogram grain once the existing contributing lists are replayed: O(games) samples per `(race, turn)`, on the order of 50--100 for standard/epic before late elimination, not 1. Field-count keys are dense (local means rose from 0 to ~20 fields). Total-unit keys are sparse (often unique per sample in a single game; across ~100 games a cell is a bag of ~100 integers -- the same raw-histogram convention as section 7). A later percentile consumer may pool adjacent turns when a late cell is thin; that is a **read-time** choice and must not destroy per-turn counts at mine time.

Campaign is thinner (`max_games` 50, 58 listed ids, variable slot counts). Same grain; consumers should expect emptier late `(race, turn)` cells.

---

## 4. Observation family contract (for the collector)

**Name:** mine-stock (total mine units and field count per owner-perspective player-host-turn).

**Pipeline:** same inference prior miner ([issue 92](https://github.com/SteveDraper/Planets-Console/issues/92)): patterns YAML, `games/list` discovery, `loadinfo` category check, `loadall` completeness skip, `TurnLoadService` extraction. New extract/accumulate/merge path; new sibling asset.

**Sample if and only if:**

1. Game passes the pattern filters and `GameCategory.from_game_settings` matches the target file.
2. `settings.nominefields` is false.
3. Player is not Horwasp.
4. Player is not eliminated at `T`.
5. Owner-perspective turn `T` is stored.

**Emit:** increment `totalUnits` and `fieldCount` (and `perFieldUnits` plus optional web/normal twins) under `mineStock.byRace.{raceid}.byTurn.{T}`. Always increment totals, including `0:`.

**Report:** games replayed vs newly discovered, owner-turns sampled, zero-stock count, Horwasp skips, elimination skips, `nominefields` skips, own-field infoturn mismatches (expect ~0), optional adjunct **tally without drop**.

**Tests (collector, not this note):** fixture `TurnInfo.minefields` with mixed `ownerid`, stale other-owner `infoturn`, `units == 0`, `isweb`, empty list; assert filters and histogram keys. No live API in CI (same as 10.8).

---

## Sources

- [Mine-stock prior mining surface](https://github.com/SteveDraper/Planets-Console/issues/396); map [Ship-first near-solutions in the mine-contaminated regime](https://github.com/SteveDraper/Planets-Console/issues/394); miner [Military score inference: mine build prior assets from finished games](https://github.com/SteveDraper/Planets-Console/issues/92)
- [`docs/design-military-score-inference-build-priors.md`](../design-military-score-inference-build-priors.md) sections 3--4, 7, 10
- [`packages/api/api/analytics/military_score_inference/prior_mining/`](../../packages/api/api/analytics/military_score_inference/prior_mining/) (`extraction_pool.py`, `extraction_worker.py`, `observations.py`, `accumulation.py`, `runner.py`, `merge.py`, `loadall_import.py`, `discovery.py`)
- [`packages/api/api/models/game.py`](../../packages/api/api/models/game.py) (`TurnInfo`, `GameSettings.minefieldsvisible`, `GameSettings.nominefields`, `GameSettings.nebulas`); [`packages/api/api/models/space.py`](../../packages/api/api/models/space.py) (`Minefield`)
- [`packages/api/api/concepts/game_category.py`](../../packages/api/api/concepts/game_category.py); [`packages/api/api/concepts/races.py`](../../packages/api/api/concepts/races.py) (`is_horwasp`); [`packages/api/api/services/player_elimination.py`](../../packages/api/api/services/player_elimination.py); [`packages/api/api/services/game_service.py`](../../packages/api/api/services/game_service.py) (`perspective_for_player_id`)
- [`packages/api/api/analytics/military_score_inference/inference_corpus_complexity.py`](../../packages/api/api/analytics/military_score_inference/inference_corpus_complexity.py); [`hopeless_classifier.py`](../../packages/api/api/analytics/military_score_inference/hopeless_classifier.py) (`max_owner_minefield_units`); [`inference_target.py`](../../packages/api/api/analytics/military_score_inference/inference_target.py) (`is_after_ship_limit`)
- [`assets/analytics/scores/prior_weights_{standard,epic,campaign}.yaml`](../../assets/analytics/scores/) `contributingGameIds` and `planet_defense_posts_added_total` histograms; [`prior_mining_patterns_*.yaml`](../../assets/analytics/scores/)
- [`CONTEXT.md`](../CONTEXT.md) glossary: Inference prior miner, player-host-turn, contributing games, aggregate prior, ship-limit band, recent minefield observation
- Workspace `.data/games/{628580,604777,673864}` stored RST `minefields` (gitignored; 2026-09-03)
