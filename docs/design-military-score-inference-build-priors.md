# Design: Military score inference build priors

Authoritative contract for **inference build prior** assets, loaders, and (future) mining. Tracker: **#86** (asset + loader). Mining pipeline: follow-on ticket (see [section 12](#12-related-tickets)).

**Related:** [design-military-score-build-inference-implementation.md](design-military-score-build-inference-implementation.md), [design-military-score-build-inference.md](design-military-score-build-inference.md), [design-inference-corpus.md](design-inference-corpus.md), repo root `CONTEXT.md` (glossary).

---

## 1. Purpose

Replace placeholder `probability_weight` and bucket `marginal_weight` constants with population-level priors that improve **inference solution rank weight** ordering in degenerate feasible cases (many exact explanations, poor default ordering).

Exact feasibility remains the contract; priors only affect ranking within the feasible set.

**Phase 1J-A (#86):** static YAML assets, Core loaders, catalog integration, hand-seeded v1 values, diagnostics.

**Follow-on:** offline miner that fills assets from finished games (separate ticket).

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

1. `resolve_inference_game_category(game_info) -> category_id` (Core; same function as miner).
2. Load `prior_weights_{category_id}.yaml`.
3. If missing, fall back to `prior_weights_standard.yaml` and record fallback in diagnostics.

**Game category** is not a runtime partition dimension inside one file -- conditioning on game type is **file selection**, not a cross-product key at solve time.

### 3.1 Category resolution (v1)

Ordered predicate rules in Core (first match wins). Minimum category ids: `standard`, `blitz`, `epic`. Rules are immutable once published; extend by adding new ids, not redefining existing ones.

Example shape (exact predicates TBD against Planets.nu settings):

```python
# Illustrative only -- implement in Core alongside hull category resolver
def resolve_inference_game_category(info: GameInfo) -> str:
    settings = info.settings
    if settings.endturn <= 30:  # example blitz rule
        return "blitz"
    if settings.shiplimit >= 500:  # example epic rule
        return "epic"
    return "standard"
```

Glossary: `CONTEXT.md` -- **Inference game category**.

---

## 4. Partitions within each asset

All tables below live **inside** one category file. Every family splits on **inference ship-limit band**: `before_ship_limit` | `after_ship_limit` (from `InferenceObservation.is_after_ship_limit` / `is_after_ship_limit()` in `inference_target.py`).

| Prior family | Partition key | Notes |
|--------------|---------------|-------|
| **Hull marginal** | `ship_limit_band` + optional per-race slice | v1: global table + sparse per-race rows for race-exclusive hulls |
| **Component conditional** | `(hull_category, ship_limit_band)` | Race-agnostic (pooled) |
| **Aggregate histogram** | `(action_id, ship_limit_band)` | Rolled into solver buckets at load (see section 7) |

Race does **not** cross into component conditionals in v1. Fleet-informed per-player skew is **#87**, not static priors.

Glossary: `CONTEXT.md` -- **Inference hull marginal prior**, **Inference conditional component prior**, **Inference aggregate prior**, **Inference ship-limit band**.

---

## 5. Ship-build prior structure

### 5.1 Hull marginal

Un-normalized counts over hull ids. Optional per-race slices in schema; v1 hand-seeds global counts plus sparse overrides for race-characteristic hulls (`concepts/races.py` alignment).

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

YAML (or code) may supply explicit log-offset or count overrides for specific combo ids or hull ids where decomposition is wrong.

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

Ship combo final weight: `round(SCALE * sum of log weights from hull + component tables)` (plus overrides).

Hand-seeded v1 YAML uses round pseudo-counts; miner output uses the same schema.

---

## 7. Aggregate priors

### 7.1 Histogram schema (asset)

Store **raw magnitude histograms** -- counts on discrete totals or histogram edges -- not pre-binned solver weights:

```yaml
# Illustrative fragment
aggregates:
  before_ship_limit:
    planet_defense_posts_added_total:
      histogram:
        5: 120
        15: 80
        40: 20
        90: 5
```

### 7.2 Runtime bucketing

Loader aggregates histogram counts into the solver's fixed **probability bucket** ranges defined in `actions.py` (`PLANET_DEFENSE_POST_BUCKETS`, etc.), then applies the same Laplace log conversion per `(action_id, ship_limit_band)` across bins.

v1 hand-seed: choose histogram pseudo-counts so bucketing reproduces intended modest / heavy / extreme ratios (mapping is not unique).

Non-bucketed aggregates (`fighters_starbase_to_ship`, etc.) use simple count tables per `(action_id, ship_limit_band)`.

Torpedo loads by type remain separate action ids (`ship_torps_loaded_{id}`) with per-type histograms.

---

## 8. YAML schema sketch

```yaml
version: 1
category: standard   # must match filename stem
gameCategoryRulesVersion: 1  # bump when resolve_inference_game_category rules change

hulls:
  before_ship_limit:
    global:
      12: 450   # hull id -> pseudo-count
      45: 120
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
      histogram: { 5: 120, 15: 80, 40: 20 }
  after_ship_limit: { ... }

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
  inference_game_category.py # resolve_inference_game_category (or colocate with prior_weights)
  hull_category.py             # resolve_inference_hull_category(hull, *, beam_count, launcher_count)
  actions.py                 # consume prior weights instead of hardcoded constants
  ship_build_combos.py       # combo probability_weight from prior_weights
```

Diagnostics payload (`priorWeights` block): resolved category id, asset path/version, fallback flag, `ship_limit_band`, optional race slice used.

---

## 10. Mining specification (follow-on)

Distinct from the **inference regression corpus** ([design-inference-corpus.md](design-inference-corpus.md)). Glossary: **Inference prior mining corpus**.

### 10.1 Corpus manifest

Explicit allowlist of **finished** game ids grouped by category (all perspectives must be available):

```yaml
# assets/analytics/scores/mining_corpus.yaml (spec)
version: 1
categories:
  standard: [628580, ...]
  blitz: []
  epic: []
```

Miner assigns each game to a category via `resolve_inference_game_category` and must agree with manifest grouping.

### 10.2 Ship-build observations

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

Record: hull, components, `hull_category`, `ship_limit_band` (from score turn), race, game category.

### 10.3 Aggregate observations

Per host-turn-player multiset from inventory deltas on **existing** ships/planets/starbases (corpus section 9.2 rules). Assign each positive delta to histogram keys; exclude loads on newly built ships per corpus ammo rules.

### 10.4 Eligibility filter

Within manifest games, include turn pairs with build activity (validated ship build and/or non-zero aggregate deltas for that player). Skip eliminated players (no owned starbases / no score row).

### 10.5 Miner output

Write `prior_weights_{category}.yaml` count tables; no log conversion in miner. Optional report: observation counts, dropped validations, ambiguous matches.

---

## 11. #86 acceptance criteria

- [ ] `prior_weights_standard.yaml` with hand-seeded pseudo-counts (hulls, at least two hull categories of component tables, aggregate histograms)
- [ ] `resolve_inference_game_category()` and `resolve_inference_hull_category()` in Core with unit tests
- [ ] Loader applies priors at catalog build; hardcoded placeholder weights removed or demoted to emergency fallback only
- [ ] Per-table Laplace log conversion; combo weights compose additively
- [ ] Missing category asset falls back to `standard` with diagnostics flag
- [ ] Tests: two combos differing only in unlikely vs likely components get different `probability_weight`
- [ ] Tests: synthetic fixture top-K orders higher-prior explanation above lower-prior feasible alternative
- [ ] Diagnostics include `priorWeights` metadata block
- [ ] `make lint` and relevant tests pass

## 12. Out of scope (#86)

- Offline mining pipeline (follow-on ticket)
- Per-player fleet-informed overlay (#87)
- Corpus top-K hardening (#65)
- Changing CP-SAT constraint model

## 13. Related tickets

| Ticket | Role |
|--------|------|
| **#86** | Asset schema, loaders, hand-seed `standard`, catalog integration |
| **Mining follow-on** | Typer/CLI miner, `mining_corpus.yaml`, fill assets from finished games |
| **#87** | Fleet-informed runtime overlay on static priors |
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
