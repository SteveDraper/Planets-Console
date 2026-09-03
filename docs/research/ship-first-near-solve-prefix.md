# Ship-first near-solve prefix on the current ladder

Research for [Ship-first near-solve prefix on the current ladder](https://github.com/SteveDraper/Planets-Console/issues/395). Map: [Ship-first near-solutions in the mine-contaminated regime](https://github.com/SteveDraper/Planets-Console/issues/394).

**Verified:** 2026-09-03 against `main` (`a806361f`) -- YAML [`assets/analytics/scores/tier_policy.yaml`](../../assets/analytics/scores/tier_policy.yaml), Core solver/orchestrator under `packages/api/api/analytics/military_score_inference/`, [design-military-score-build-inference.md](../design-military-score-build-inference.md) §3.5 / §3.7, [design-military-score-build-inference-implementation.md](../design-military-score-build-inference-implementation.md) §8.5.3 / §8.5.4 / §8.8, and [`CONTEXT.md`](../../CONTEXT.md).

This note records **which current inference search tier steps** are the ship-first near-solve prefix (ship-build combos, ship loss / gift / trade / acquired ship, belief-set ship torps; **no** planet or starbase defense posts; without the expensive tail). It does **not** pick a remainder bound, ranking, or destination product.

---

## Summary for implementers

The prefix that matches the ticket's catalog (ships + decrease / pairing families + belief-set torps, no planet or starbase defense posts, no expensive tail) is the **contiguous production ladder through `admit_ship_torpedoes`**:

`early_game_bands` → `widen_launchers` → `collision_hull_widen` → `widen_hulls` → `admit_ship_torpedoes`

That cut is **not** the shipped cheap-versus-expensive cut. Cheap exact always runs **through `full_components`**, which already retains modest planet posts. Expensive abort then refuses `admit_starbase_defense_posts` / `torp_escape_tier` / `full_catalog_exact`.

Belief torps first enter the **tier aggregate allowlist** at `admit_ship_torpedoes`. Planet posts first enter at the **next** step, `modest_planet_defense`. A prefix can therefore include torps and exclude posts **without** violating the YAML strict-superset rule: posts are added later, not dropped. A prefix that continues through `modest_planet_defense` or `full_components` **cannot** exclude posts.

Decrease / pairing families are **not** allowlist keys. Catalog construction appends them on every ship-bearing step, including `early_game_bands` with `aggregateAllowlist: {}`. Lattice-gated idle-dock PP binds on the same catalog path, not delayed to `full_components`.

Today each step tries **exact** military equality first; on infeasible exact, `alpha > 0` retries a **one-sided under-explain floor** (`explained_2x >= observed_2x - alpha`) whose hits are **seeds only**. There is no policy-step field for overshoot, and no existing runtime overlay that changes military constraint direction. Running this prefix as a user-facing overshoot near-solve would need a new abort/cut (the cheap abort hook is hardcoded to `full_components`) **and** a new military-constraint encoding -- either a new YAML field on the step or a new runtime overlay analogous to fleet torp admission, not an allowlist-only edit.

---

## 1. Ordered production ladder

[`assets/analytics/scores/tier_policy.yaml`](../../assets/analytics/scores/tier_policy.yaml) `steps:` (validated by [`tier_policy.py`](../../packages/api/api/analytics/military_score_inference/tier_policy.py) `parse_tier_policy_steps` / `validate_tier_policy_steps`; production load also requires penultimate `torp_escape_tier` with `alpha > 0` via `_validate_production_escape_tier`):

| Index | Step id | Ship-build filters (static YAML) | `aggregateAllowlist` | `alpha` | Notes |
|-------|---------|----------------------------------|----------------------|---------|-------|
| 0 | `early_game_bands` | Hulls tech 1-6; engines all; beams/launchers tech 1-5 | `{}` | 50 | First ship-bearing step. `allowShipOnlyExactEarlyStop: false`. |
| 1 | `widen_launchers` | Launchers widen to tech 1-8 | `{}` | 50 | |
| 2 | `collision_hull_widen` | Same bands as step 1; `hullCollisionTwinWiden: true` | `{}` | 50 | Runtime `includeComponentIds` for twin high-tech hulls. May **skip** when the admitted twin set is empty ([implementation §8.5.7](../design-military-score-build-inference-implementation.md)). |
| 3 | `widen_hulls` | Hulls `all: true` | `{}` | 50 | |
| 4 | `admit_ship_torpedoes` | All axes `all: true`; `beamSlotCounts` / `launcherSlotCounts`: `partial` | `ship_torps_per_type: 40` | 30 | First torp allowlist key. `runDegradeAggregateProbe: true` (only this step). |
| 5 | `modest_planet_defense` | Same component filters / partial slots | torps 40 **+** `planet_defense_posts_added_total: 16` | 50 | First planet posts. |
| 6 | `full_components` | Same | torps 40 + planet posts 16 | 50 | Last cheap step. First `allowShipOnlyExactEarlyStop: true`. |
| 7 | `admit_starbase_defense_posts` | Same | + SB posts 5, SB fighters 50, ship fighters 20, fighter transfers 50 | 30 | First starbase posts and fighter channel. |
| 8 | `torp_escape_tier` | Same | Same keys/caps as step 7 | 30 | Penultimate; all eligible torp types. |
| 9 | `full_catalog_exact` | Same | Raised caps (planet posts 100, SB posts 100, torps 200, ...) | 0 | Final step; `alpha` must be 0. |

YAML comment on order: "ship bands first, then high-prior aggregates (belief torps, modest planet defense), then full-catalog ship polish (capped), then heavier aggregates / escape." Same table is in [implementation §8.5.3](../design-military-score-build-inference-implementation.md).

Loader tests pin this id order and that `allowShipOnlyExactEarlyStop` is false through `modest_planet_defense` and true from `full_components` onward ([`test_military_score_inference_tier_policy.py`](../../packages/api/tests/test_military_score_inference_tier_policy.py) `test_policy_loader_validates_final_alpha_zero`).

---

## 2. Cheap versus expensive cut as shipped

Design [§3.5](../design-military-score-build-inference.md): cheap exact **inference search tiers** always run through `full_components` (ships + belief torps + modest planet posts + last modest-cap ship polish). **Inference expensive-tier abort** refuses `admit_starbase_defense_posts`, `torp_escape_tier`, and `full_catalog_exact`. It does not skip the row and does not add unconstrained negative slack.

Code constants match that cut ([`hopeless_classifier.py`](../../packages/api/api/analytics/military_score_inference/hopeless_classifier.py)):

- `CHEAP_LADDER_LAST_STEP_ID = "full_components"`
- `EXPENSIVE_TIER_STEP_IDS = {"admit_starbase_defense_posts", "torp_escape_tier", "full_catalog_exact"}`

[`maybe_expensive_tier_abort_after_step`](../../packages/api/api/analytics/military_score_inference/policy_ladder_admission.py) returns immediately unless `policy_step.id == CHEAP_LADDER_LAST_STEP_ID`. It then skips abort if a held solution still satisfies exact hard equalities. Otherwise it classifies leftover after the ship/freighter construction envelope and, on abort, sets `ladder_complete` with reason `expensive_tier_abort`. [`finish_tier_step`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_finish.py) runs that hook only on `TierStepFinishMode.COMPLETE` (not on skip or budget-stop of `full_components`).

Tests: abort after cheap-unsat does not enter the three expensive ids; positive leftover with no classifier hit still attempts them ([`test_hopeless_classifier.py`](../../packages/api/tests/test_hopeless_classifier.py) `test_expensive_tiers_are_not_entered_on_mine_residual_abort`, `test_positive_leftover_still_climbs_expensive_tiers`). Skip or budget-stop of `full_components` does not abort ([`test_skip_of_full_components_does_not_abort`](../../packages/api/tests/test_hopeless_classifier.py)).

[`CONTEXT.md`](../../CONTEXT.md) **Inference expensive-tier abort**: stopping after cheap exact tiers through the last modest-cap ship-polish step (production `full_components`) so fighter / starbase-post / raised-cap steps do not run.

Consequence for this ticket: the shipped cheap prefix **includes planet posts** (`modest_planet_defense` and `full_components`). The ship-first catalog (torps, no posts) is a **strictly earlier** cut than cheap-versus-expensive.

---

## 3. First belief torps, first planet posts, strict-superset

### 3.1 First belief torps

YAML first puts `ship_torps_per_type: 40` on `admit_ship_torpedoes`. Earlier steps have `aggregateAllowlist: {}`.

Runtime materialization is not "every eligible torp id at that cap." [`admitted_torp_ids_for_policy_step`](../../packages/api/api/analytics/military_score_inference/fleet_torp_overlay.py):

- If `ship_torps_per_type` is **absent** from the step allowlist: admit **no** torp ids.
- Overlay disabled: all `eligible_torp_ids`.
- `alpha == 0` (`full_catalog_exact`): all `eligible_torp_ids`.
- Before `torp_escape_tier`: **belief-set ∩ eligible**, or **empty** when the belief set is empty.
- At/after `torp_escape_tier`: all `eligible_torp_ids`.

[`CONTEXT.md`](../../CONTEXT.md) **Inference aggregate admission**: on steps that admit template torpedo-load actions, restrict `ship_torps_loaded_{id}` to the **inference fleet launcher belief set**; empty belief set materializes **none** on early torp-admitting tiers; **inference torp escape tier** admits all eligible. Implementation §8.8.2 names the early window as `admit_ship_torpedoes` through `admit_starbase_defense_posts`.

Catalog tests: `admit_ship_torpedoes` emits `ship_torps_loaded_*` (cap 40) and does **not** emit `planet_defense_posts_added_total` ([`test_ship_torpedoes_admitted_after_full_components_with_caps`](../../packages/api/tests/test_military_score_inference_tier_policy.py) -- name is historical; assertion is the torp step). `compute_aggregate_admission_caps` through that step is `{ship_torps_per_type: 40}` only ([`test_compute_aggregate_admission_caps_records_first_step_appearance`](../../packages/api/tests/test_military_score_inference_tier_policy.py)).

`runDegradeAggregateProbe: true` is YAML-gated on `admit_ship_torpedoes` only; the probe rewrites held ship-only exacts toward belief-eligible `ship_torps_loaded_*` ([implementation §8.5.3a](../design-military-score-build-inference-implementation.md)). Planet-defense degrade probe is out of scope for v1.

### 3.2 First planet posts; first starbase posts

Planet posts: YAML `planet_defense_posts_added_total: 16` first appears on `modest_planet_defense` and is retained on every later step (raised to 100 on `full_catalog_exact`). [`_append_aggregate_action`](../../packages/api/api/analytics/military_score_inference/aggregate_catalog_build.py) no-ops when the allowlist key is missing (`resolved_aggregate_cap` is `None`). Catalog test: `modest_planet_defense` has planet posts cap 16 **and** torp actions ([`test_slack_admitted_on_later_steps_with_caps`](../../packages/api/tests/test_military_score_inference_tier_policy.py)).

Starbase defense posts: YAML `starbase_defense_posts_added_total` first appears on `admit_starbase_defense_posts` (expensive). `full_components` allowlist is torps + planet posts only.

### 3.3 Strict-superset vs a torps-without-posts prefix

[`CONTEXT.md`](../../CONTEXT.md) **Inference search tier**: later tiers are strict supersets of earlier ones on every dimension they control (permitted actions, per-action caps, ship-build component eligibility, constraint strictness). **Tier aggregate allowlist**: each tier's allowlist is a strict superset of the previous (new action ids and/or relaxed caps).

Load-time enforcement is [`validate_tier_policy_steps`](../../packages/api/api/analytics/military_score_inference/tier_policy.py):

- Component `techLevels` must be a set-superset, or the axis may switch one-way to `all: true`.
- Slot modes cannot narrow `partial` → `none`.
- Every prior allowlist **key** must be retained; caps may only stay or rise.

`alpha` is **not** checked as a widening dimension. Production `alpha` sequence is 50, 50, 50, 50, **30**, 50, 50, 30, 30, 0 -- the torp step **tightens** the band floor relative to `widen_hulls`.

**Can a prefix include torps and exclude posts without violating that rule?** Yes, and the production YAML already does: `admit_ship_torpedoes` has torps and no planet/SB posts; `modest_planet_defense` **adds** planet posts. Stopping after `admit_ship_torpedoes` does not remove a key from a later step; it simply does not climb.

**What would violate the rule:** a later YAML step that **drops** `planet_defense_posts_added_total` after `modest_planet_defense`, or that drops `ship_torps_per_type` after `admit_ship_torpedoes`. A prefix through `full_components` cannot exclude planet posts because that key is already required to be retained.

Fleet torp overlay already makes the **runtime** torp-id set a subset of the YAML allowlist key (belief-set filter, or none when empty). That is a documented overlay on template members, not a dropped allowlist key. There is no equivalent overlay that omits planet posts from a step whose YAML lists them.

---

## 4. Decrease families on cheap steps

Design [§3.7](../design-military-score-build-inference.md) **Cheap ladder**: decrease families and lattice-gated idle-dock PP enter at the first ship-bearing cheap step (`early_game_bands` / ship-only); every later step is a superset. They are **not** delayed to `full_components` or the expensive tail. Implementation §8.5.4 item 12 matches.

[`build_action_catalog`](../../packages/api/api/analytics/military_score_inference/actions.py) always calls [`build_ship_transfer_catalog_fragment`](../../packages/api/api/analytics/military_score_inference/ship_transfer_families.py) and extends `aggregate_actions` with that fragment. The call is **not** gated on `policy_step.id` or on `aggregateAllowlist`. Prefixes: `ship_loss:`, `gift:`, `trade:`, acquired-ship ids (`ACQUIRED_SHIP_ACTION_PREFIX`).

[`test_decrease_families_enter_at_early_game_bands`](../../packages/api/tests/test_ship_transfer_families.py): production step 0 has `aggregate_allowlist == {}` and still materializes `ship_loss:` when prior-fleet records exist.

Caps that bind on those actions (same catalog, every step that builds it):

- Prior-fleet class and per-group departure caps ([`constraints.py`](../../packages/api/api/analytics/military_score_inference/constraints.py) `_add_prior_fleet_departure_caps` / `_add_prior_fleet_group_departure_caps`). Loss count cannot exceed prior active rows of that class (design §3.7).
- Acquired incoming budget ([`_add_acquired_incoming_caps`](../../packages/api/api/analytics/military_score_inference/constraints.py)): several counterparties are alternative signatures for the same arrival, not a sum of peer `excess_out`.
- Combo upper bounds use extra warship/freighter capacity from the same fragment (loss+replace when `shipchange = 0`).

Idle-dock PP: [`should_enforce_idle_dock_pp`](../../packages/api/api/analytics/military_score_inference/idle_dock_pp.py) is observation + settings (pre-limit PQ/PPQ, no planet/SB count drop, PP on the even lattice). The flag is stored on the catalog (`enforce_idle_dock_pp_equality`) and applied in `InferenceHardConstraints` whenever true -- not delayed by step id. Off-lattice or planet/SB drop: skip PP enforcement; still admit decrease families (design §3.7).

These families are ranked `solutions[]` actions, not post-unsat placeholders (design §3.7; [`CONTEXT.md`](../../CONTEXT.md) **Ship loss** / **Gift** / **Trade** / **Acquired ship**).

---

## 5. Exact then band under-explain (not overshoot product)

[`CONTEXT.md`](../../CONTEXT.md) **Inference score band**: `explained_2x >= observed_2x - alpha`; warship and freighter stay exact; final step `alpha = 0`; each tier tries exact first; band applies only on retry after infeasible exact; band-feasible results **seed the next tier only** and are never user-facing. Implementation §8.5.4 items 3-7 match.

CP-SAT ([`constraints.py`](../../packages/api/api/analytics/military_score_inference/constraints.py) `_SumEqualityConstraint.add_to_model` for `score_delta_2x`):

- Exact: `lhs == rhs`.
- `military_score_alpha > 0`: `lhs >= rhs - alpha` only (no `lhs <= rhs` upper bound). Diagnostics string is the same one-sided floor.
- Distinct path: `military_partition_slack_2x > 0` is **two-sided** (`rhs ± slack`).

Ladder ([`policy_ladder_tier_step.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_step.py)): after a no-exact catalog solve, if `policy_step.alpha > 0`, `_solve_catalog(..., military_score_alpha=policy_step.alpha)` stores up to `maxSeeds` into `state.band_seeds`. Residual recorded is `observed_2x - explained_2x` (positive means under-explained). The **next** step consumes those seeds via `_solve_seed_progression`, which calls `_solve_catalog` **without** `military_score_alpha` (exact), fixing ship-build counts then widening neighborhood then free search -- "admit newly unlocked aggregate actions to close residual" (implementation §8.5.4 item 6). After `admit_ship_torpedoes`, that newly unlocked aggregate on the production ladder is **planet posts**.

User-facing merge is exact-only (`merge_exact_solutions` / `solution_satisfies_exact_hard_equalities`). Cheap-unsat after `full_components` is abort to `moderate_residual` / `mine_score_residual`, or else climb expensive -- not a published band action list (design §3.5, §3.8).

There is **no** YAML key for overshoot (`explained >= observed`), overshoot cap, or "emit band as `solutions[]`". `alpha` is the under-explain floor width on the retry, and it is smaller on `admit_ship_torpedoes` (30) than on the ship-only steps (50).

---

## 6. What would have to change (policy step vs runtime overlay)

Facts about existing knobs only; not a destination choice.

**Policy step (YAML + load-time validator)**

- The prefix catalog **already exists** as steps 0-4. No new allowlist key is required to get ships + torps without posts.
- You **cannot** express "torps without posts" on any step **after** `modest_planet_defense` without failing `validate_tier_policy_steps` (must retain `planet_defense_posts_added_total`).
- `alpha` cannot encode overshoot direction or an overshoot cap; it only feeds `lhs >= rhs - alpha` on the infeasible-exact retry.
- Cheap abort is **not** a YAML flag. Last cheap id is the code constant `CHEAP_LADDER_LAST_STEP_ID`. Moving it to `admit_ship_torpedoes` would also skip `modest_planet_defense` and `full_components` (including last modest-cap ship polish and the current classifier evaluation point). No production step has an `abortAfterThisStep` / `lastCheap` field.
- Global resolve-time **inference tier policy overlay** was cancelled ([implementation §8.5.6](../design-military-score-build-inference-implementation.md); [`CONTEXT.md`](../../CONTEXT.md) **Inference tier policy asset**). Step-local YAML flags that exist today: `hullCollisionTwinWiden`, `raiseMaxTechFromPriorFleet`, `runDegradeAggregateProbe`, `allowShipOnlyExactEarlyStop`. None change military equality vs band vs overshoot, and none omit planet posts.

**Runtime overlay (existing pattern)**

- Fleet torp overlay ([`fleet_torp_overlay.py`](../../packages/api/api/analytics/military_score_inference/fleet_torp_overlay.py)) subsets **which** `ship_torps_loaded_{id}` rows exist when the allowlist key is present. It does not add a posts-free step, does not stop the ladder, and does not change `lhs == rhs` vs band.
- Hull-collision twin `includeComponentIds` and prior-fleet tech-raise widen **ship-build eligibility** on named steps. Same: no military-constraint overlay, no posts omission.
- Expensive-tier abort is a **runtime ladder hook** keyed to a step id, not an overlay on the catalog. The analogous hook for "stop after `admit_ship_torpedoes`" does not exist.
- Seed progression is exact-close-with-new-aggregates. Treating a posts-free overshoot as the product would not use that path as shipped: after the torp step, the next unlock is planet posts, and band hits are not `solutions[]`.

**Constraint code (neither YAML allowlist nor existing overlay)**

- User-facing overshoot (`explained_2x >= observed_2x`, under-explain not this path -- map standing preference, not shipped) would be a new encoding in [`constraints.py`](../../packages/api/api/analytics/military_score_inference/constraints.py) / the exact-first retry in [`policy_ladder_tier_step.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_step.py). Gating that encoding could be a **new policy-step field** or a **new runtime overlay** (regime-scoped, like fleet torp), but neither exists today.
- This note does not pick the worthwhile remainder bound or ranking.

---

## 7. Prefix versus cheap versus expensive (compact)

| Cut | Steps included | Belief torps | Planet posts | SB posts / fighters / raised caps | Decrease families |
|-----|----------------|--------------|--------------|-----------------------------------|-------------------|
| Ship-first near-solve prefix (this ticket) | 0-4 through `admit_ship_torpedoes` | Yes (belief-set, or none if belief empty) | No | No | Yes, from step 0 |
| Shipped cheap exact | 0-6 through `full_components` | Yes | Yes (from step 5) | No | Yes, from step 0 |
| Shipped expensive tail (aborted on classifier) | 7-9 | Escape / full-catalog all eligible | Yes (retained; caps rise on step 9) | Yes | Yes (superset) |

Empty belief set: steps 0-4 still run ship combos and decrease families; `admit_ship_torpedoes` materializes **no** torp-load actions; non-belief types wait for `torp_escape_tier` (expensive).
