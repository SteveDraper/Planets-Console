# Design: Military score inference build priors

Authoritative contract for **inference build prior** assets, loaders, and (future) mining. Tracker: **#86** (asset + loader). Mining pipeline: follow-on ticket (see [section 12](#12-related-tickets)).

**Related:** [design-military-score-build-inference-implementation.md](design-military-score-build-inference-implementation.md), [design-military-score-build-inference.md](design-military-score-build-inference.md), [design-inference-corpus.md](design-inference-corpus.md), repo root `CONTEXT.md` (glossary).

---

## 1. Purpose

Replace placeholder `probability_weight` and bucket `marginal_weight` constants with population-level priors that improve **inference solution rank weight** ordering in degenerate feasible cases (many exact explanations, poor default ordering).

Exact feasibility remains the contract; priors only affect ranking within the feasible set.

**Phase 1J-A (#86):** static YAML assets, Core loaders, catalog integration, hand-seeded v1 values, diagnostics.

**Follow-on (#92):** pattern-driven offline miner that discovers finished games, `loadall`s turns, and incrementally fills assets.

---

## 2. Prior model (log space)

Ship-build combo rank weight composes **additively in log-probability space** at catalog-build time:

```text
log P(combo) ≈ log P(hull | ship_limit_band, race?)
             + log P(engine, beam, torp, slot_fill | hull_category, ship_limit_band)
             + log override_sparse   (optional)

combo_probability_weight = scaled_integer(log P(combo))
```

Aggregate actions use histogram-derived magnitude-bin weights (see [section 7](#7-aggregate-priors)).

The **inference build prior asset** stores **un-normalized count distributions** (human-readable). Conversion to integer solver weights happens at catalog build (see [section 6](#6-count-to-weight-conversion)).

Glossary: `CONTEXT.md` -- **Inference build prior**, **Inference solution rank weight**.

---

## 3. Asset layout and game category

One YAML file per **inference game category** under:

```text
assets/analytics/scores/
  prior_weights_standard.yaml    # v1 hand-seed
  prior_weights_blitz.yaml       # when mined
  prior_weights_epic.yaml        # when mined
  tier_policy.yaml               # existing; unrelated
```

At solve time:

1. `GameCategory.from_game_settings(settings)` (Core `api.concepts.game_category`; same function as miner).
2. Load `prior_weights_{category_id}.yaml`.
3. If missing, fall back to `prior_weights_standard.yaml` and record fallback in diagnostics.

**Game category** is not a runtime partition dimension inside one file -- conditioning on game type is **file selection**, not a cross-product key at solve time.

### 3.1 Category resolution (v1)

Ordered predicate rules in Core (first match wins). Category ids: `campaign`, `blitz`, `epic`, `standard`. Rules are immutable once published; extend by adding new ids, not redefining existing ones.

Implemented in `api/concepts/game_category.py` as `GameCategory.from_game_settings(settings)` (`campaignmode` first, then blitz/epic/standard predicates).

Glossary: `CONTEXT.md` -- **Game category**.

---

## 4. Partitions within each asset

All tables below live **inside** one category file. Every family splits on **inference ship-limit band**: `before_ship_limit` | `after_ship_limit` (from `InferenceObservation.is_after_ship_limit` / `is_after_ship_limit()` in `inference_target.py`).

| Prior family | Partition key | Notes |
|--------------|---------------|-------|
| **Hull marginal** | `ship_limit_band` + optional per-race slice | v1: global table + sparse per-race rows for race-exclusive hulls |
| **Component conditional** | `(hull_category, ship_limit_band)` | Race-agnostic (pooled) |
| **Aggregate histogram** | `(action_id, ship_limit_band)` | Rolled into solver buckets at load (see section 7) |

Race does **not** cross into component conditionals in v1. Fleet-informed per-player skew is **#87** / **#156** (runtime overlay on static priors), not static prior assets.

Glossary: `CONTEXT.md` -- **Inference hull marginal prior**, **Inference conditional component prior**, **Inference aggregate prior**, **Inference ship-limit band**.

---

## 5. Ship-build prior structure

### 5.1 Hull marginal

Un-normalized counts over real hull ids, including actual freighter hulls. Optional per-race slices in schema; v1 hand-seeds global counts plus sparse overrides for race-characteristic hulls (`concepts/races.py` alignment).

The solver still exposes one generic `combo_freighter` row for true freighter builds whose construction contributes no military score. That generic row is a solver compression artifact, not an asset concept: at catalog build, Core collapses the eligible **true freighter** hull counts (`fighterbays == 0`, `launchers == 0`, `beams == 0`) into one generic freighter marginal before Laplace conversion. Miner output therefore samples freighter builds exactly like any other hull build and writes the observed real hull ids to the asset.

### 5.2 Component conditional

Given **inference hull category**, counts over:

- `engine_id`
- `beam_id` (when beams fitted)
- `torp_id` (when launchers fitted)
- `slot_fill` pattern (e.g. full vs partial beams/launchers)

Composed additively in log space into each generated **ship build combo**'s `probability_weight`.

### 5.3 Hull category assignment

Deterministic priority predicates + sparse hull-id overrides. Shared Core resolver (not YAML). Build-aware where noted.

| Order | Category | Predicate (summary) |
|-------|----------|---------------------|
| 1 | **true freighter** | No fighter bays, beams, or launcher slots |
| 2 | **alchemy ship** | Override / `Hull.special` rules |
| 3 | **carrier** | `fighterbays > 0` |
| 4 | **battleship** | `beams > 0`, `launchers > 0`, and `mass >` fixed hand-tuned constant |
| 5 | **torpedo ship** | `launchers > 0` (beams allowed) |
| 6 | **beam-ship** | `beams > 0`, `launchers == 0` |
| 7 | **weaponless hull** | Has weapon slots, built empty (`beam_count == 0`, `launcher_count == 0`), not carrier |
| 8 | **utility** | Explicit overrides only |

- **true freighter** vs **weaponless hull:** former has no military slots; latter has slots but empty build (Fed refit relevance; scoreboard freighter count).
- **Battleship mass threshold:** single integer constant in Core, tuned against anchor hulls in the standard roster.
- Category assignment for mining and catalog build uses fitted spec from the validated build order where **weaponless hull** applies.

Glossary: `CONTEXT.md` -- **Inference hull category**.

### 5.4 Sparse overrides

YAML (or code) may supply explicit log-offset or count overrides for specific combo ids or hull ids where decomposition is wrong. Do not use overrides to introduce synthetic solver-only hull ids; solver compression such as `combo_freighter` is derived from real asset hull counts during catalog resolution.

---

## 6. Count-to-weight conversion

Applied **per table** at catalog build (not stored normalized in YAML):

```text
p_i = (c_i + alpha) / (total + alpha * K)
weight_i = round(SCALE * log(p_i))
```

- `alpha = 1` (Laplace smoothing)
- `K` = number of cells in that table
- `SCALE` = fixed integer (tune once against synthetic fixtures; target range above aggregate slack ~10)

Ship combo final weight: `round(SCALE * sum of log weights from hull + component tables)` (plus overrides). For the solver's generic freighter combo, Core first collapses eligible true-freighter real hull counts into a single solver cell, then applies the same table-level Laplace conversion.

Hand-seeded v1 YAML uses round pseudo-counts; miner output uses the same schema.

After wildcard expansion, each resolved hull/component table must cover every eligible id
used by catalog generation. Missing ids are asset/resolution errors, not neutral zero
weights: real Laplace weights are negative, so an implicit `0` would make omitted ids
artificially most likely. A completely absent component sub-table still resolves to an
implicit uniform distribution for that eligible component universe.

---

## 7. Aggregate priors

### 7.1 Histogram schema (asset)

Every aggregate is a **single histogram shape** (there is no separate `counts` shape). Store **raw magnitude histograms** -- counts on discrete totals or histogram edges -- not pre-binned solver weights. An optional `0:` key carries the **occurrence prior**: the pseudo-count for "this action did not happen" (`count == 0`), routed into a leading `none` bin:

```yaml
# Illustrative fragment
aggregates:
  before_ship_limit:
    planet_defense_posts_added_total:
      histogram:
        0: 198   # occurrence (none) bin: count == 0
        5: 120
        15: 80
        40: 20
        90: 5
```

### 7.2 Runtime bucketing and the occurrence (none) bin

Every aggregate histogram has a leading `none` bin `[0, 0]` ahead of the positive magnitude bins. The loader aggregates histogram counts into the solver's fixed **probability bucket** ranges defined in `aggregate_action_registry.py` (`PLANET_DEFENSE_POST_BIN_BOUNDS`, etc.), then applies the same Laplace log conversion per `(action_id, ship_limit_band)` across bins. The solver requires **exactly one** bin to be active, including the `none` bin, so each action contributes a self-normalised `log P(observed bin)` term that includes the "did not happen" outcome.

This subsumes the old standalone parsimony penalty: the `0:` seeds are computed via `none_bin_pseudo_count` so the gap from the `none` bin (the max-weight bin, cost `0`) down to the most likely active bin reproduces the legacy penalty `LEGACY_PARSIMONY_OCCURRENCE_PENALTY` (`SCALE // 2 = 50`). Because adding the `none` cell changes the denominator for all bins equally, the spacing among the positive bins is unchanged, so behaviour is preserved within +/-1 (integer log rounding).

v1 hand-seed: choose positive histogram pseudo-counts so bucketing reproduces intended modest / heavy / extreme ratios (mapping is not unique), then add the `0:` seed for occurrence.

Fighter transfers (`fighters_starbase_to_ship`, `fighters_ship_to_starbase`) are occurrence-only **2-bin histograms** (`none` plus a single active band), e.g. `{0: 108, 1: 65}`; they have no magnitude prior.

Torpedo loads by type remain separate action ids (`ship_torps_loaded_{id}`) with per-type histograms. When a torpedo table is absent from the asset (implicit-uniform policy), the loader still seeds the `none` bin via `none_bin_pseudo_count` so the occurrence cost is retained rather than the action becoming free.

Template aggregate action ids are schema-validated as `ship_torps_loaded_<positive integer>`.
Malformed suffixes are rejected instead of being accepted by prefix match alone.

---

## 8. YAML schema sketch

```yaml
version: 1
category: standard   # must match filename stem
gameCategoryRulesVersion: 2  # bump when GameCategory.from_game_settings() rules change

hulls:
  before_ship_limit:
    global:
      12: 450   # hull id -> pseudo-count
      45: 120
      15: 220   # true freighter hull; Core collapses eligible freighters into combo_freighter
    byRace:
      9:          # race id
        12: 800
  after_ship_limit:
    global: { ... }

components:
  before_ship_limit:
    torpedo_ship:
      engines: { 3: 200, 5: 80 }
      torpedoes: { 5: 150, 8: 40 }
      slotFill: { full: 180, partial: 20 }
    carrier: { ... }
  after_ship_limit: { ... }

aggregates:
  before_ship_limit:
    planet_defense_posts_added_total:
      histogram: { 0: 198, 5: 120, 15: 80, 40: 20 }   # 0: = occurrence (none) bin
    fighters_starbase_to_ship:
      histogram: { 0: 108, 1: 65 }                     # occurrence-only 2-bin
  after_ship_limit: { ... }

contributingGameIds: [628580]   # optional; miner provenance -- ignored by catalog loader

overrides:
  combos: {}
  hulls: {}
```

Exact key names validated by loader; schema evolution bumps `version`.

---

## 9. Core modules (#86)

```text
packages/api/api/analytics/military_score_inference/
  prior_weights.py           # load YAML, convert counts, resolve tables for observation
  concepts/game_category.py  # GameCategory.from_game_settings()
  hull_category.py             # resolve_inference_hull_category(hull, *, beam_count, launcher_count)
  actions.py                 # consume prior weights instead of hardcoded constants
  ship_build_combos.py       # combo probability_weight from prior_weights
```

Diagnostics payload (`priorWeights` block): resolved category id, asset path/version, fallback flag, `ship_limit_band`, optional race slice used.

---

## 10. Mining specification (#92)

Distinct from the **inference regression corpus** ([design-inference-corpus.md](design-inference-corpus.md)). Glossary: `CONTEXT.md` -- **Inference prior miner**, **Inference prior mining pattern**, **Inference prior player-host-turn**, **Inference prior contributing games**, **Inference prior ship-build observation**, **Inference aggregate prior**.

### 10.1 Pattern config and game discovery

The miner is driven by **patterns YAML files** under `assets/analytics/scores/` (e.g. `prior_mining_patterns_standard.yaml` for standard-only runs -- not a hand-maintained game-id manifest). Each row is an **inference prior mining pattern**:

| Field | Type | Meaning |
|-------|------|---------|
| `id` | string | Stable unique id (miner report provenance) |
| `game_category` | string | Target bucket: `standard` \| `blitz` \| `epic` \| `campaign` (must match `GameCategory` / `from_game_settings`) |
| `max_games` | int | **Lifetime** cap on games this pattern may contribute across incremental runs (not a per-run batch) |
| `min_difficulty` | float | Floor on `Game.difficulty` from upstream |
| `earliest_date` | string | ISO calendar date `YYYY-MM-DD`; floor on `datecreated` |

```yaml
# assets/analytics/scores/prior_mining_patterns_standard.yaml
version: 1
patterns:
  - id: standard-recent
    game_category: standard
    max_games: 30
    min_difficulty: 1.0
    earliest_date: "2024-01-01"
```

**Discovery pipeline** (public finished games; no api key required):

1. `GET https://api.planets.nu/games/list?status=3&scope=0` ([API games list](https://help.planets.nu/API-games-list)).
2. Client-side filter: `datecreated >= earliest_date`, `difficulty >= min_difficulty` (parse host date strings).
3. Sort candidates: **`dateended` descending**, tie-break **`game.id` ascending**.
4. For each candidate not already in the target asset's `contributingGameIds`: `loadinfo`, then `GameCategory.from_game_settings(settings)` must equal `game_category`. Skip on mismatch (do not mine into the wrong category file).
5. Stop when this pattern has contributed `max_games` ids (track per-pattern counts in the miner report; patterns targeting the same category file have **independent** caps).
6. **Global dedup:** one `contributingGameIds` list per category asset; any id already listed is skipped by every pattern.

Do **not** infer blitz/epic/standard from list `gametype` alone; category resolution requires `loadinfo` settings (`campaignmode`, `endturn`, `shiplimit`).

### 10.2 Turn data (`loadall` import)

For each newly selected game id:

1. If `--storage-root` already holds a **complete** finished-game turn set for that id, skip download. Completeness: for every player slot `1..game.slots`, all turns in `required_turn_numbers(player, game.turn)` are stored (same semantics as `LoadAllTurnsService._is_load_all_complete`, without username-scoped perspective filtering).
2. Otherwise: `PlanetsNuClient.load_all`, parse via `load_all_archive`, import into storage.
3. Extract observations via `TurnLoadService` / `StorageBackend` (not by re-parsing the ZIP during extraction).

CLI: `--patterns` (required path to patterns YAML), `--storage-root` (default `./.data`), `--dry-run` (discovery + report only, no asset write).

### 10.3 Sampling unit (`inference prior player-host-turn`)

Atomic traversal unit: `(game_id, player_id, host_turn N)` where:

- Turn documents `N` and `N+1` exist at the owning player's **perspective** (`GameService.perspective_for_player_id`).
- Player is **not eliminated** on or before turn `N+1` (`is_eliminated_at_turn` / `last_meaningful_turn` from `api.services.player_elimination`).
- **Inference ship-limit band** derived from turn `N+1` (score turn), matching `InferenceObservation.is_after_ship_limit` at solve time.

Iterate every active player and every `host_turn` from `1` through `last_meaningful_turn - 1` where the pair exists. Not one row per perspective slot; not omniscient multi-perspective merge.

**Adjunct exclusion:** skip units classified `adjunct` by inference corpus complexity signals (`tests.inference_corpus.complexity`); report skip counts. Remaining units use unconditional aggregate marginals (below).

### 10.4 Ship-build observations

One **inference prior ship-build observation** per validated build:

**Turn T (order snapshot):**

- Player-owned starbase with `isbuilding == true`
- Read `buildhullid`, `buildengineid`, `buildbeamid`, `buildtorpedoid`, `buildbeamcount`, `buildtorpcount`

**Turn T+1 (validation):**

- New ship: `ship.id` not present among active owned ships on turn T
- Ship at starbase planet coordinates (`planet.x/y` from `starbase.planetid`)
- Fitted spec **exactly matches** order fields

Rejects:

- Inventory-diff-only detection (trades, destruction)
- Unvalidated queued orders (optimistic post-limit queues)
- Pre-existing ships that moved to the same location with identical spec

Do **not** use the corpus harness inventory-diff ship extraction ([design-inference-corpus.md](design-inference-corpus.md) section 9) for priors.

Record: hull, components, `hull_category`, `ship_limit_band` (from score turn), race. Fold into hull marginal and component conditional count tables for the game's resolved category.

### 10.5 Aggregate observations

Per **inference prior player-host-turn**, single traversal over aggregate action ids (corpus section 9.2 inventory rules on **existing** ships/planets/starbases; exclude ammo loads on newly built ships):

1. Compute inventory delta per action (0 when none).
2. Increment `histogram[delta]` for `(action_id, ship_limit_band)` -- including **`0:`** for zero-delta samples.

**Unconditional marginal (v1):** do **not** condition on asset ownership or per-action feasibility at mining time. Sample every aggregate action on every non-adjunct unit. The solver applies the same static prior whenever an action enters the catalog (tier allowlist + residual bounds -- not ownership). Runtime fleet conditioning is **#87** / **#156**, not mining.

**Histogram keys:** raw observed positive integer deltas (loader buckets via `magnitude_bin_index` at catalog build; miner does not pre-bin). Fighter transfers (`fighters_starbase_to_ship`, `fighters_ship_to_starbase`): occurrence-only 2-bin histograms (`0:` and `1:` for any positive transfer); use `_fighter_transfer_counts` logic from corpus ground truth. Emit `histogram:` only; no `counts:` shape.

**Torpedo loads:** one `ship_torps_loaded_{id}` histogram per torpedo id present in the turn catalog; delta 0 still increments `0:`.

Do **not** gate on scoreboard `militarychange`; inventory-only (same rationale as corpus ground truth).

### 10.6 Incremental merge and asset output

**In-place merge** into `assets/analytics/scores/prior_weights_{category}.yaml`:

- Read existing asset if present; **add** mined counts into hull/component/aggregate tables.
- Append new game ids to **`contributingGameIds`** (monotonic; never remove). Parsed as metadata on `PriorWeightsAsset`; **ignored** by `resolve_prior_weights_catalog`.
- Set `category` and `gameCategoryRulesVersion` to current Core values.
- `--dry-run`: run discovery and extraction tallies; do not write YAML.

No log conversion in miner (loader owns Laplace conversion).

**Miner JSON report** (stdout or `--report` path): per-pattern discovery stats (`patternId`, candidates examined, games added, slots remaining), global skips (already contributed, category mismatch, incomplete loadall), adjunct skips, ship-build validation drops, per-action sample counts (`zero` / `positive`).

### 10.7 Implementation layout

| Piece | Location |
|-------|----------|
| Pattern load, discovery, observation extraction, accumulation, YAML merge | `packages/api/api/analytics/military_score_inference/prior_mining/` |
| Shared inventory deltas | Hoist from `tests/inference_corpus/ship_inventory.py` into Core (used by corpus harness and miner) |
| `PlanetsNuClient.games_list` | `packages/api/api/planets_nu.py` (new) |
| `contributingGameIds` on asset | `prior_weights_asset.py` (optional metadata field) |
| CLI | `scripts/run_inference_prior_miner.py` (thin Typer; pattern `run_inference_corpus.py`) |
| Unit tests | `packages/api/tests/test_inference_prior_mining*.py` (fixture turns; no live API in CI) |

### 10.8 #92 acceptance criteria

- [ ] Patterns YAML committed with documented schema (e.g. `prior_mining_patterns_standard.yaml`; may use small `max_games` for v1)
- [ ] `games/list` client; discovery + category filter + ordering per 10.1
- [ ] `loadall` import path; completeness skip per 10.2
- [ ] In-place merge produces/updates `prior_weights_standard.yaml` with `contributingGameIds` and merged counts from at least one finished standard game
- [ ] Ship observations: starbase order + T+1 validation (not inventory-diff ships)
- [ ] Aggregate histograms: raw delta keys including `0:`; fighter transfer 2-bin shape; no `counts:` blocks
- [ ] Adjunct player-host-turns excluded; unconditional marginals on retained units
- [ ] Unit tests on extraction (fixtures); `make lint` and relevant tests pass

---

## 11. #86 acceptance criteria

- [ ] `prior_weights_standard.yaml` with hand-seeded pseudo-counts (hulls, at least two hull categories of component tables, aggregate histograms)
- [x] `GameCategory.from_game_settings()` and `resolve_inference_hull_category()` in Core with unit tests
- [ ] Loader applies priors at catalog build; hardcoded placeholder weights removed or demoted to emergency fallback only
- [ ] Per-table Laplace log conversion; combo weights compose additively
- [ ] Missing category asset falls back to `standard` with diagnostics flag
- [ ] Tests: two combos differing only in unlikely vs likely components get different `probability_weight`
- [ ] Tests: synthetic fixture top-K orders higher-prior explanation above lower-prior feasible alternative
- [ ] Diagnostics include `priorWeights` metadata block
- [ ] `make lint` and relevant tests pass

## 12. Out of scope (#86)

- Offline mining pipeline (follow-on ticket)
- Per-player fleet-informed overlay (**#87** torp slice, **#156** tech-gap follow-on)
- Corpus top-K hardening (#65)
- Changing CP-SAT constraint model

## 13. Related tickets

| Ticket | Role |
|--------|------|
| **#86** | Asset schema, loaders, hand-seed `standard`, catalog integration |
| **#92** | Pattern-driven miner, per-category patterns YAML (e.g. `prior_mining_patterns_standard.yaml`), `loadall`, incremental `prior_weights_{category}.yaml` |
| **#87** | Fleet-informed **torp load** overlay (admission + misalignment prior) |
| **#156** | Fleet-informed **component tech-gap prior** on ship builds |
| **#65** | Top-K regression after priors stabilize |
| **#64** | Regression ground truth (inventory diff) -- not prior mining |

---

## 14. Issue map

| Topic | This doc section |
|-------|------------------|
| Log-space composition | 2 |
| Per-category assets | 3 |
| Partitions | 4 |
| Hull categories | 5.3 |
| Conversion | 6 |
| Aggregates | 7 |
| #86 implementation | 8, 9, 11 |
| Mining | 10 |
