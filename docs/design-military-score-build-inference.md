# Design: Military score build inference

This document describes an approach for inferring likely per-turn builds from scoreboard military-score deltas and related scoreboard constraints.

The goal is not to prove what happened. Military score is deliberately lossy: several combinations of ships, ammunition, and defenses can produce the same delta. The analytic should therefore return feasible explanations, rank them by plausibility, and make ambiguity visible.

**Related:** [design-military-score-build-inference-implementation.md](design-military-score-build-inference-implementation.md), [vga-planets-domain-context.md](vga-planets-domain-context.md), [design-analytics-structure.md](design-analytics-structure.md), [design-planets-api-data-model.md](design-planets-api-data-model.md).

---

## 1. Purpose

Given scoreboard data for a player on turn **T**, infer possible actions that explain the observation deltas for that row (normally the transition from turn **T-1** to **T**; see [section 3.3](#33-accelerated-start-scoreboard) when **Accelerated Start** applies). The inputs are:

- change in military score,
- change in number of military ships,
- change in number of freighters,
- change in priority points,
- hulls buildable by that player,
- number of starbases owned by that player,
- whether the turn is before or after the ship limit.

The output should be a small ranked set of explanations per player, not one forced answer. A typical explanation might be "built one Rush and loaded 18 fighters" or "built one medium warship, added starbase fighters, and transferred fighters from a starbase to ships."

---

## 2. Military score model

The Planets.nu military score is based on AutoScore-style construction value. The score counts warships, loaded ship torpedoes and fighters, starbase defense posts and fighters, planetary defense posts, and minefields. Mobile military assets count at full value. Fixed-position assets count at half value.

The score has half-point components, so the inference model should multiply all score contributions by 2 and solve with integers:

| Component | Military score | Scaled contribution |
|-----------|----------------|---------------------|
| Warship hull, engines, beams, tubes | construction value | `2 * value` |
| Loaded ship fighter | `125` | `250` |
| Loaded ship torpedo | torpedo MC cost | `2 * torpedo_mc_cost` |
| Starbase fighter | `62.5` | `125` |
| Starbase defense post | `7.5` | `15` |
| Planet defense post | `5.5` | `11` |
| Minefields | derived from mine units | deferred initially |

Construction value is `megacredits + 5 * minerals`. For ships, the value includes hull, engines, beams, and torpedo tubes, but not cargo and not cloning surcharge. A ship counts as a military ship for score purposes if it has at least one beam, torpedo tube, or fighter bay. Freighters can still affect constraints through freighter count and priority points, but usually do not add military score except through edge cases that should be handled by the ship catalog rules.

---

## 3. Initial scope

### 3.1 In scope

The first version should model these action families:

- **Ship builds:** one built hull at a starbase, with a concrete engine type, optional beam type and count, and optional torp tube type and count. Construction score includes hull, engines (`hull.engines` copies of one type), fitted beams, and tube hardware (`launchercost`). Beams and tubes may be omitted independently. **Do not** include fighters or torpedo ammo loaded at build time; those are separate aggregate actions.
- **Freighter builds:** constrained by `freighterchange`, buildable hull list, starbase count, and priority-point behavior (diagnostic until queue model lands).
- **Warship builds:** constrained by `shipchange`, buildable hull list, starbase count, and priority-point behavior (diagnostic until queue model lands).
- **Loaded torpedoes:** score increase from torpedoes loaded onto ships.
- **Ship fighters:** score increase from fighters loaded onto ships.
- **Starbase fighters:** score contribution at half value.
- **Starbase defense posts:** score contribution at half value.
- **Planet defense posts:** score contribution at half value.
- **Fighter transfers:** movement of fighters between ships and starbases, changing score by `+62.5` when a fighter moves from starbase to ship and `-62.5` in the reverse direction.

### 3.2 Deferred

The first version should not try to explain:

- mine laying or mine scooping,
- planet losses, including planets with defense posts,
- starbase losses, including bases with fighters or defense,
- ship destruction or combat ammo use (as distinct families -- unmatched **ship loss** in §3.7 does not split combat vs recycle vs glory),
- hard prior constraints from minerals, cash, or ship locations (departing **ships** are **prior-fleet decrease candidate**s in §3.7).

Ship trades, captures, and losses for this quality bar are §3.7 (shipped, #370) -- not deferred into [extended action families](https://github.com/SteveDraper/Planets-Console/issues/49).

The design should still make remaining extensions natural. Deferred effects should be added as new action families and constraints, not as special-case patches to the solver.

### 3.3 Accelerated start scoreboard

Planets.nu **Accelerated Start** (`settings.acceleratedturns = N`, `N > 0`) lets players run their first **N** host turns without waiting for the full game. During that window the persisted **scoreboard rows on turns 1..N-1 are unreliable** (zeroed or incomplete totals and deltas). The **first reliable scoreboard row** is on host turn **N**.

Inference implications:

| Turn | Prior row available? | Observation source |
|------|----------------------|--------------------|
| `T < N` (accelerated window) | No -- treat as `no_prior_turn` | Do not run build inference |
| `T = N` (first reliable row) | Synthetic -- homeworld baseline, not turn `N-1` | See below |
| `T > N` | Yes -- normal prior row | `militarychange`, `shipchange`, `freighterchange` on row **T** |

**First reliable row (`T = N`):** The score row shows **current totals** plus **deltas for host turn N-1 only** (not cumulative over the whole accelerated window). Military inference must still explain **all military score gained since game start**, because builds on host turns 1..N-1 are folded into the totals even when their per-turn deltas were not reported correctly.

Observation mapping on turn **N** (implementation: `observation_deltas_from_score` in `accelerated_start.py`):

- **Military (2x):** `2 * (militaryscore - homeworld_baseline.militaryscore)` -- cumulative since turn-1 baseline under normal Starmap homeworld rules (`homeworldhasstarbase`, starting starbase fighters and defense posts, one starting freighter when applicable).
- **Warships:** `capitalships - homeworld_baseline.capitalships` -- cumulative warship builds since baseline (not only `shipchange`).
- **Freighters:** `freighterchange` on the row -- **host N-1 only**; freighters built earlier in the accelerated window appear in totals (`freighters` count) but not in `freighterchange`. Diagnostics may use `infer_accelerated_window_ship_builds` to split window vs reported-host-turn ship counts; the solver observation still uses `freighterchange` as the hard freighter constraint.
- **Priority points:** `prioritypointchange` as on a normal row.

**After turn N:** Use the same hard constraints as section 4, with observation fields taken from the score row delta columns (`militarychange`, `shipchange`, `freighterchange`, `prioritypointchange`) scaled for military score as elsewhere in this document.

Corpus and regression fixtures for accelerated games (e.g. game `628580`) should document that a case with `scoreTurn = N` is explaining activity through the first reliable scoreboard snapshot, not a single host turn in isolation. See [design-inference-corpus.md](design-inference-corpus.md) case notes when authoring manifests.

**Race-specific candidate actions** (e.g. Evil Empire free starbase fighters) use Planets.nu race ids and settings from **`api.concepts.races`**. **`accelerated_start.py`** holds only cross-race accelerated-start and homeworld baseline logic. See [design-analytics-structure.md](design-analytics-structure.md) (race-specific rules).

### 3.4 Inference admission skip

Rows in the **inference admission skip** set never submit `tier_solve`. This is identity or visibility **before** the scoreboard delta, distinct from the **hopeless classifier** (post-admission, cheap tiers still run). Locked in [Inference admission skip set](https://github.com/SteveDraper/Planets-Console/issues/356):

| Skip | Detector | Why certain before the delta |
|------|----------|------------------------------|
| Viewpoint owner | `player_id ==` shell **perspective** for slots `1..N` | That **TurnInfo** is the empire's RST. Spectator `0` has no owner row. |
| Dead | `is_eliminated_at_turn` inclusive of the elimination turn | Host Dead/vacant-ineligible flag, not 0 planets. Death-turn ship strip is administrative, not a build. |
| Live inbound Full Alliance | Mutual `relationfrom` and `relationto` at Full Alliance, or team-locked FA | Hull and mounts are already on the turn; scoreboard inference adds little. One-way FA does not skip. Share Intel does not skip. |
| Stealth Mode | `settings.stealthmode` | Military column unpublished for every row (including the viewpoint). **Scores** stays available; **Include build inference** greys out. |
| Horwasp | Race identity | Catalog does not model the race; never search. |
| `no_prior_turn` | Turn 1, or accelerated window with no backfill | No comparable prior scoreboard. Backfill/split when turn `N` is stored still solve. |
| `player_not_found` | No scoreboard row for that `player_id` | No observation. |

Not in the set: inbound Share Intel (hull locks constrain a later follow-on), 0-planet living players, idle/missed turns, fog-of-war, mine/moderate residual, hopeless.

Cheap skip terminals persist as fallback-complete so fleet evidence can close. Mixed-table chrome: keep the build-inference column; muted skip cell and tooltip; no red X; no modal. Wire statuses are per-reason (`viewpoint_owner`, `dead`, `full_alliance`, `horwasp`, `no_prior_turn`, `player_not_found`). Stealth uses **build inference availability** instead of per-row skip hover. Persist, stream, and chrome: [§3.8](#38-product-status-persist-and-stream).

### 3.5 Hopeless classifier and expensive-tier abort

Locked in [Mine-score residual likelihood and expensive-tier abort](https://github.com/SteveDraper/Planets-Console/issues/357). **Hopeless classifier / expensive-tier abort shipped** ([Implement hopeless classifier and expensive-tier abort](https://github.com/SteveDraper/Planets-Console/issues/368)). Cheap exact **inference search tiers** always run through `full_components` (ships + belief torps + modest planet posts + last modest-cap ship polish). **Inference expensive-tier abort** refuses `admit_starbase_defense_posts`, `torp_escape_tier`, and `full_catalog_exact`. It does not skip the row and does not add unconstrained negative slack.

The **hopeless classifier** is evaluated only after that cheap run. A hard-equality exact from cheap tiers is kept; the classifier does not fire, and **mine-residual sticky prior** plus N-window carry-forward both clear. T+1 may open a new observation window from its own RST. The in-regime ship-first path ([§3.10](#310-ship-first-overshoot-constraint), [#401](https://github.com/SteveDraper/Planets-Console/issues/401)) revises leftover-0: current-turn owner fields with `units > 0` skip exact. Implementation later on [#394](https://github.com/SteveDraper/Planets-Console/issues/394).

On cheap-unsat, any one of the following is sufficient for expensive-tier abort (planet/SB **count** drops and race vetoes still block the scoreboard mine-shaped path; a warship-count drop is not mine-shaped -- see [Ship loss, gift, and trade as exact families](https://github.com/SteveDraper/Planets-Console/issues/359)):

1. Decrease-shaped unexplained military beyond the **inference moderate residual** floor (1-11 after the ship/freighter construction envelope).
2. **Mine-residual sticky prior** (previous turn for that player was **mine-score residual** / expensive-tier abort -- not raw `no_exact_solution`, not **inference admission skip**).
3. **Large minefield observation** (historical #368): max `units` among that owner's fields in the **recent minefield observation** window (default 3 host turns, default minimum 1000 units). Folded by [#411](https://github.com/SteveDraper/Planets-Console/issues/411) -- see overlay below. Classifier-only RST existence; not a decay model and not an observed vs unobserved solver split. Remainder sign does not matter.

Window length is overridable on the **inference tier policy asset** (`solverThresholds`): `recentMinefieldObservationTurns` (default 3). `largeMinefieldObservationMinUnits` is dropped.

| This turn after cheap | Expensive tail | Status this contract names | Sticky prior |
|----------------------|----------------|----------------------------|--------------|
| Hard-equality exact | Already exact | `exact` | Clear; drop N-window carry-forward |
| Unsat, leftover 1-11, no sticky, no large observation | Expensive-tier abort | **inference moderate residual** | Do not start |
| Unsat, decrease-shaped >11 | Expensive-tier abort | **mine-score residual** | Start / keep |
| Unsat, sticky prior, remainder either sign | Expensive-tier abort | **mine-score residual** | Keep |
| Unsat, large observation in N-window, remainder either sign | Expensive-tier abort | **mine-score residual** | Start / keep |
| Unsat, positive leftover, no sticky, no large observation | Climb expensive | Then `exact`, junk-exact, or `no_exact_solution` | Unchanged |

Abort is the anti-junk mechanism. Classifier misses that still get slack-padded expensive exacts remain a named **junk-exact** failure; no second slack-ratio detector here. Persist, stream, and SPA chrome for `moderate_residual` / `mine_score_residual` / `no_exact_solution`: [§3.8](#38-product-status-persist-and-stream). This abort is not [Scores inference: unify ladder early-stop into optional per-tier entry gates](https://github.com/SteveDraper/Planets-Console/issues/244) (that issue's per-step entry gates stay a leftover for hygiene).

**#394 overlay -- entry gate shipped** ([Implement mine-contaminated regime entry overlay](https://github.com/SteveDraper/Planets-Console/issues/411); tracker rewrite [Hygiene: this map vs the previous quality bar and implementation epic](https://github.com/SteveDraper/Planets-Console/issues/403)). The shipped table above is the #352 / #357 / #368 contract. **Shipped #411:** fold the 1000-unit **large minefield observation** entry gate -- that term is not current glossary. **Mine-contaminated regime** entry is (i) any owner field `units > 0` in the **recent minefield observation** window, (ii) cheap-unsat decrease-shaped leftover beyond the moderate floor with mine-plausible counts, or (iii) **mine-residual sticky prior**. **Hopeless classifier** still aborts the expensive tail, and is wider than the regime: **inference moderate residual** (1-11, no (i)/(iii)) aborts without sticky or near-solve. `largeMinefieldObservationMinUnits` is dropped from the inference tier policy asset. **Not this overlay phase:** do not treat pad-inclusive hard-equality as success; run the ship-first prefix ([§3.10](#310-ship-first-overshoot-constraint)); leftover-0 `exact` only with no current-turn owner fields.

### 3.6 Unknown military ship placeholder

Locked in [Unknown military ship placeholder contract](https://github.com/SteveDraper/Planets-Console/issues/358). **Shipped** ([Implement unknown military ship and residual freighter placeholders](https://github.com/SteveDraper/Planets-Console/issues/369)).

When the row has no ranked action list (**inference moderate residual**, empty-list **mine-score residual**, `no_exact_solution`), inference emits count-constrained **post-unsat** placeholders so ship and priority-point constraints still surface. These are not CP-SAT catalog combos and not ranked `solutions[]` entries. A **mine-score residual** row with **ship-first near-solution**s does not emit placeholders ([§3.8](#38-product-status-persist-and-stream)).

**Unknown military ship**

- One row, `count = N` unexplained **positive** `shipchange` remainder after any exact families on that row.
- No emit when `N <= 0`, or when the player's legal-warship construction envelope is empty (catalog hole / decrease-family miss, not a fake range).
- Per-unit military bounds: race construction envelope in `score_delta_2x` (min cheapest legal warship fill, max most expensive legal fill; engines fill every slot; weapons may be below max; carriers count at 0 beams). Residual size stays on the row; leftover (including mine leftover) is not assigned to the ships.
- Starbase slots: `build_slot_usage = 1` per unit, matching the **generic freighter combo**. Priority-point equality is not a hard constraint; observed `prioritypointchange` surfaces on the row. Optional per-unit PP envelope (`1 + ceil(mass/50)`, mass cap 1000 KT) is display-only metadata.
- Residual / no-exact rows do not emit cheap-tier aggregates, band seeds, or junk-exact padding.

**Generic freighter on the same row**

- Observation-derived post-unsat **generic freighter combo** (hull id 0) for unexplained positive `freighterchange`. Same sentinel as the solver combo; not a ranked solution. Exact 0-military solves still emit `combo_freighter` in `solutions[]` as today. Negative freighter count is unmatched **ship loss** / outgoing **gift** / **trade** in §3.7 (not a negative placeholder).

**Wire**

- Dedicated row-level collection (not `solutions[].shipBuilds`).
- Typed id `unknown_military_ship`; hull sentinel `-1` (not generic-freighter `0`).
- Fields: `count`, per-unit `militaryScoreDelta2xMin` / `Max`, `buildSlotUsage: 1`, optional PP envelope. No `probability_weight` / rank.
- Label "Unknown military ship" / `Nx …`. Not a proved hull, not a mine explanation.

**Fleet cardinality interface**

Fleet explodes `count = N` to N unit **fleet inferred acquisition** rows and copies the per-unit envelope onto each hull-sentinel build option set (`hullId` `-1` for unknown military, `0` for generic freighter; no engine/beam/torp fills). Do not introduce multi-ship fleet rows.

Persist, stream `complete`, and export carry the collection as `placeholders` ([§3.8](#38-product-status-persist-and-stream)).

### 3.7 Ship loss, gift, and trade

Locked in [Ship loss, gift, and trade as exact families](https://github.com/SteveDraper/Planets-Console/issues/359). **Shipped** ([Implement ship loss, gift, trade, and acquired ship](https://github.com/SteveDraper/Planets-Console/issues/370)).

**Distinguishability** uses **public scoreboard pairing** (other players' public `shipchange` / `freighterchange` / `militarychange` as observations, plus idle-dock PP / dock-cap **transfer budgets**). The CP-SAT stays per scoreboard row -- not a joint multi-player solve, not RST ship-id identity, not a new **fleet analytic** feature.

| Fingerprint | Family | Notes |
|-------------|--------|-------|
| Net count drop, no compatible counter-delta | **Ship loss** | Combat, recycle, glory, mines, black hole are not split. Recycle `+1` PP is off the idle-dock lattice, so PP is skipped that row. |
| Net count drop + compatible +count / +military elsewhere | **Gift** | Includes capture (tow, combat prize, Force Surrender). Host **trade** is two gifts. Military sign gate applies on this raw-drop path. |
| Idle-dock `k = starbases − PP/2` vs net, or dock-cap `net > starbases`, with a peer `excess_out` / `excess_in` | **Gift** / **Acquired ship** | Mixed build+transfer. Same families as raw complementary-drop. Do not require opposite signs on the same class column. Relax the military sign gate on this path only (both rows may go up). Pin class from the **receiver** residual when unique (acquired: this row; gift: the peer). If class is unknown, still pair as one transfer `{counterparty, count, pinned_class | None}` -- warship and freighter are exclusive alternatives, not two additive class columns. Several peers with `excess_out` are **alternative** ranked signatures for the same arrival budget -- a solution pairs with one matching donor; it does not consume every peer. `excess_out` with no raw count drop is PP-only. If `excess_in > 0` and no peer has `excess_out`, stay `no_exact_solution` -- no unpaired / unknown-source acquired. |
| Counts flat, military swapped and/or warship↔freighter columns flip | **Trade** | Pairing fingerprint, not a host mechanic. |
| Matched incoming hull on this row | **Acquired ship** | Score-increasing. Not a **ship build combo**. |

Catalog military envelopes on interval actions (PP-gap acquired `[0, this row's military]`, unknown-hull loss, etc.) stay wide for search. Each ranked `solutions[]` row's `militaryScoreArithmetic` intersects those envelopes with leftover after the other elements of **that** solution so line-item military is self-consistent and maximally tight. Floor slack stays as a residual band on the line item when it still has width.

**Reserved incoming.** The build bound reserves this row's idle-dock or dock-cap `excess_in` (class split only when the receiver residual pins warship or freighter; unknown class reserves the total only). Several PP-gap counterparties are alternative signatures for that same budget -- not `max(raw, pp)` and not the sum of peer `transfer_count`s. Raw-drop acquired matches name counterparties; they do not size the reserve.

Several compatible counterparties are distinct ranked **inference explanation signature**s. Counterparty player id is on the explanation when pairing pins one row.

**Catalog.** Departures are **prior-fleet decrease candidate**s: **active** **fleet ship record**s on that player's prior-turn **fleet acquisition ledger**. Hull-known or option-set-bounded records contribute that military; unknown-hull inferred records contribute only that record's envelope. Cannot lose more warships or freighters than prior active rows of that class. Do **not** invert the ship-build combo catalog as `warship_delta = -1` fills (junk-exact). Missing or non-final prior ledger uses the same wait / **scores inference row invalidation** path as today's prior-turn fleet overlay.

These families are ranked `solutions[]` actions (counts + pairing when it exists), not post-unsat placeholders. **Unknown military ship** still only for unexplained **positive** remainder after them (`N <= 0` does not emit). Same-row negative freighter count is a departure family, not a negative generic-freighter placeholder.

**Idle-dock PP equality** binds on the same steps: pre-limit PQ/PPQ, planet/SB counts did not drop, observed PP on `2 × (starbases − ships built)`. Off-lattice or planet/SB count drop: skip PP enforcement; still admit decrease families. Classic PBP and PLS: no idle-dock constraint. After ship-limit: [Post-limit PP accounting for military score build inference](https://github.com/SteveDraper/Planets-Console/issues/364).

**Cheap ladder.** Decrease families and lattice-gated idle-dock PP enter at the first ship-bearing cheap step (`early_game_bands` / ship-only); every later step is a superset. They are not delayed to `full_components` or the expensive tail -- otherwise ship-only exact can empty-exact a loss+replace (`shipchange = 0`) and fighters/SB posts can junk-pad. Loss count is bounded by prior active rows, not an unbounded slack action. A warship-count drop is still not mine-shaped ([§3.5](#35-hopeless-classifier-and-expensive-tier-abort)).

**#49.** This bar takes **ship loss**, **gift**, **trade**, and **acquired ship** (shipped #370). Mines, ammo spend, negative defense, and planet/SB loss stay out of this map and out of [#394](https://github.com/SteveDraper/Planets-Console/issues/394). Laying/scooping stay on [extended action families](https://github.com/SteveDraper/Planets-Console/issues/49); **ship-first near-solution**s on a **mine-score residual** are not those families ([Hygiene: this map vs the previous quality bar and implementation epic](https://github.com/SteveDraper/Planets-Console/issues/403)). Prior inventory on #49 shrinks to minerals/cash/locations. Per-location defense/fighters and fleet-histogram priors stay on #49. Post-limit PP is #364, not #49.

### 3.8 Product status persist and stream

Locked in [Inference product-status persist and stream contract](https://github.com/SteveDraper/Planets-Console/issues/360). **Persist / first-class `status` shipped** ([Implement inference admission skip and product-status persist](https://github.com/SteveDraper/Planets-Console/issues/366)). **Table-stream `complete` payload, BFF `displayStatus`, and SPA cell chrome shipped** ([Implement inference status stream and SPA cell chrome](https://github.com/SteveDraper/Planets-Console/issues/367)). **Export product `status` / leftover / `placeholders` shipped** ([Scores analytic exports](https://github.com/SteveDraper/Planets-Console/issues/97)). **Non-empty `placeholders[]` shipped** ([Implement unknown military ship and residual freighter placeholders](https://github.com/SteveDraper/Planets-Console/issues/369)). **Ship-first near-solutions on residual rows** locked in [Residual rows with ranked near-solutions: persist, stream, and SPA](https://github.com/SteveDraper/Planets-Console/issues/402) (map: [Ship-first near-solutions in the mine-contaminated regime](https://github.com/SteveDraper/Planets-Console/issues/394)) -- revises the empty-`solutions[]` residual payload and chrome below; write-gate statuses do not grow. Implementation is a later effort on that map.

**Wire `status`** is first-class (same field as today). The player-facing contracts:

| Product | `status` |
|---------|----------|
| Exact (including **ship loss** / **gift** / **trade** / **acquired ship**) | `exact` |
| **Inference moderate residual** | `moderate_residual` |
| **Mine-score residual** | `mine_score_residual` |
| No-solution after a search we meant to finish | `no_exact_solution` |
| **Inference admission skip** | Per-reason: `viewpoint_owner`, `dead`, `full_alliance`, `horwasp`, `no_prior_turn`, `player_not_found` |

"Intractable residual" is informal for `no_exact_solution`, not a distinct status. **Stealth Mode** is **build inference availability**, not a row status. `invalid_problem`, `solver_error`, `time_limited`, `stopped`, `paused`, `pending`, `fetch_error` stay as today. Junk-exact, long unsat, and catalog hole stay named diagnostics; junk-exact remains `exact` chrome.

**Persist.** `exact` / `no_exact_solution` / `moderate_residual` / `mine_score_residual` join functional persist. Skip statuses join fallback-complete with `no_prior_turn` / `player_not_found` (and existing `invalid_problem` / `solver_error`). All of those close fleet turn evidence. Do not persist `fetch_error`, in-progress, or `paused`. **Mine-residual sticky prior** is derived from the prior host-turn persisted row (`status === mine_score_residual`), including when that row holds **ship-first near-solution**s; no parallel sticky flag. Cleared when the persisted row is `exact` (leftover within partition slack). Current-turn owner fields with `units > 0` skip leftover-0, so sticky cannot clear that turn ([§3.10](#310-ship-first-overshoot-constraint)). ADR 0002 write gate statuses are unchanged.

**Functional payload.** Three residual shapes:

- Leftover within partition slack is `exact` (existing exact payload; leftover field omitted) -- only when this turn's viewpoint-RST has no owner field with `units > 0`.
- **Mine-score residual** with a non-empty **ship-first near-solution** list: same `solutions[]` wire as exact (rank weight, actions, ship-builds, `militaryScoreArithmetic`) plus Core **ship-first family tag** per solution; `solutionCount = N`; `placeholders []`; `unexplainedMilitaryDelta2x` = rank-1 overshoot `explained - observed` (2x units). No per-solution leftover field -- arithmetic already has explained vs observed.
- Empty-list **mine-score residual**, **inference moderate residual**, and `no_exact_solution`: `solutions[]` empty; `placeholders[]` is the §3.6 collection (**unknown military ship** hull `-1` with per-unit military bounds; observation-derived **generic freighter combo** hull `0`); `unexplainedMilitaryDelta2x` on the row is today's observation delta (not explained-minus-observed).

Skip: status + summary only. Band residual and named compute failures stay diagnostics (wire/live-only). **Inference moderate residual** and `no_exact_solution` do not carry user-facing near-solutions.

**Stream.** Incremental `solution` events remain leftover-0 / `exact` only (full held top-K, as today). Overshooting **ship-first near-solution** lists do not emit `solution` events; they ride on terminal `complete` with `status` `mine_score_residual` (and persist replay of that `complete`). Empty-list residual / skip / `no_exact_solution` terminals still emit one `complete` with that functional payload and `solutionCount` 0. No `solution` event for placeholders. Fleet and MCP read persist/export, not this NDJSON stream. Option-set / id-constraint mapping for **unknown military ship** stays unspecified.

**Export.** `$.meta.searchStatus` stays lifecycle-only (`complete` for these terminals). Product `status`, leftover (`unexplainedMilitaryDelta2x`), and `placeholders` are siblings of `$.solutions`. `$.solutions` may be non-empty on `mine_score_residual`. Shipped by [Scores analytic exports](https://github.com/SteveDraper/Planets-Console/issues/97); export precedence is unchanged.

**SPA chrome** (not modal layout). BFF `displayStatus` stays `mine_score_residual` when `status` is that value (does not flip to `success` because `solutionCount > 0`). Skip: muted cell, tooltip, no modal. Exact: green solid N. Complete **mine-score residual** with **N > 0**: the same **inference solution count indicator** in blue (probable build first; leftover secondary -- tooltip / accessible name, not a second numeral). When the list mixes **mine-overshoot** and **ammo-top-up**, tooltip/aria names the mix and still quotes rank-1 leftover. Empty-list **mine-score residual** and **inference moderate residual**: distinct residual markers + leftover size. `no_exact_solution` keeps the red X. Click opens the existing **inference solution detail modal**: one weight-ordered list + explained-vs-observed mismatch when **N > 0**; **ship-first family tag** chip on each header; mixed-list subtitle when both families are present; summary when the list is empty. Do not design a new modal, split N, family sections, or leftover-on-cell beside N. Family tag / **ship-first stratified hold**: [§3.11](#311-ship-first-family-tag-and-stratified-hold).

### 3.9 Worthwhile remainder bound

Locked in [Remainder bound percentile and turn partitioning](https://github.com/SteveDraper/Planets-Console/issues/399). Arithmetic: [Mine-stock to leftover military arithmetic](https://github.com/SteveDraper/Planets-Console/issues/397). Asset grain: [Mine-stock prior mining surface](https://github.com/SteveDraper/Planets-Console/issues/396) / [Collect mine-stock histograms from finished games](https://github.com/SteveDraper/Planets-Console/issues/398). Map: [#394](https://github.com/SteveDraper/Planets-Console/issues/394). Implementation is a later effort on that map.

In the **mine-contaminated regime**, a **ship-first near-solution** is feasible only when overshoot leftover satisfies `slack < leftover_2x <= floor(worthwhile remainder bound)` in solver 2x (`leftover_2x = explained - observed`). Leftover within partition slack is `exact` only with no current-turn owner field (`units > 0`); with those fields leftover 0 is not produced ([§3.10](#310-ship-first-overshoot-constraint)). Rank by **inference solution rank weight**; leftover is a post-collection tie-break and this hard cap, not the CP-SAT objective. In-regime K-membership is **ship-first stratified hold** ([§3.11](#311-ship-first-family-tag-and-stratified-hold)). The cap is not **inference score band** and not a ranking-only penalty. Integerize the real bound once at the constraint: `cap_2x = floor(bound)`. If `cap_2x <= slack`, the overshoot window is empty.

**Empirical cell (exact host turn, no 10-turn lookup band).** Category file × race × host turn on the **mine-stock prior**. Drop empty-stock `0:` from the percentile. Take p90 of `totalUnits` and p90 of `fieldCount` independently, convert that pair with equal-split default decay (`round(0.95x) - 1` per implied field, `54L/100` 2x). Do not re-mine a leftover histogram. Do not race-pool. Do not use **inference ship-limit band**.

**Remainder-bound turn mixture.** Let `n_total` be owner-turns in the cell (including empty stock) and `n0 = 20`. Empirical leftover is the cell p90 above, or **0** when there are no positive-stock samples. Mixed leftover is `w * empirical + (1-w) * interp(T)` with `w = n_total / (n_total + n0)`. `interp(T)` is a same-race isotonic (non-decreasing) series of leftover 2x vs host turn, weighted by `n_total`; beyond the last knot, hold that value (do not extrapolate the superlinear tail). A cell with `n_total = 0` is 100% interpolant. This is the sparse-cell policy: no refuse-a-bound, no race pooling, no mine-time turn-banding.

**Observed-stock floor.** `bound = max(mixed, observed)`. `observed` is exact per-field default decay of this scoreboard turn's viewpoint-RST owner fields with `units > 0` (sizes are on the RST; do not equal-split observed totals). No visible owner fields → floor 0 (prior stands). This **floors** the cap when early laying beats a p90 of 0. It does **not** tighten (`min` with visible units): fogged other-player RSTs would collapse the cap. Not window-max over the entry-(i) N-turn window. The same current-turn fields skip leftover-0 exact ([§3.10](#310-ship-first-overshoot-constraint)).

Sweep, scoop, and mutual-elim leftover above decay of stock stays unmodeled: overshoot past the bound yields an empty near-solve list, not a larger percentile. Two-threshold worthwhile policy remains not-yet-specified on #394.

### 3.10 Ship-first overshoot constraint

Locked in [Near-solve overshoot constraint vs inference score band](https://github.com/SteveDraper/Planets-Console/issues/401). Prefix: [Ship-first near-solve prefix on the current ladder](https://github.com/SteveDraper/Planets-Console/issues/395). Cap: [§3.9](#39-worthwhile-remainder-bound) / [#399](https://github.com/SteveDraper/Planets-Console/issues/399). Persist leftover: [§3.8](#38-product-status-persist-and-stream) / [#402](https://github.com/SteveDraper/Planets-Console/issues/402). Map: [#394](https://github.com/SteveDraper/Planets-Console/issues/394). Implementation is a later effort on that map.

In-regime military score on the ship-first prefix is a new constraint identity, not **inference score band** and not widened `military_partition_slack_2x`. Production observations always carry slack `1` (half-point rounding); the shipped CP-SAT adder applies two-sided `±slack` before `alpha`, so band retry is shadowed in production. Do not reuse that slot.

**Window.** Warship and freighter stay equalities. Military:

```text
observed + slack < explained <= observed + cap_2x
```

with `leftover_2x = explained - observed` and `cap_2x = floor(worthwhile remainder bound)`. Exact iff `matchesObserved` (`|explained - observed| <= slack`). Near-solutions require leftover strictly above slack. Do not add slack on top of the cap. Empty-list residual leftover stays today's observation delta; a non-empty ship-first list stores rank-1 raw overshoot.

**Current-turn owner fields** (`units > 0` on this scoreboard turn's viewpoint-RST -- same evidence as **observed-stock floor**, not the N-turn window, not sticky-only, not the 1000-unit gate): skip the exact pass. Leftover 0 is not a legal outcome; sticky cannot clear. Fogged absence does not undermine leftover-0.

**No current-turn owner fields:** leftover-0 on the prefix preempts. Exact (`±slack`) first; if any leftover-0 is held, status is `exact` and overshoots are discarded. Overshoot only if that exact pass is unsat.

**Overlay.** Runtime overlay on each prefix step through `admit_ship_torpedoes`, replacing band retry -- not a YAML `alpha` and not a new policy step. No current-turn fields: exact then overshoot-if-unsat. Current-turn fields: overshoot only. In-regime prefix never runs under-explain `alpha` retry and never emits band seeds. Out-of-regime cheap exact keeps exact-then-band as shipped.

**Search.** Same maximize **inference solution rank weight** + near-best band as exact. Leftover is post-sort only, not a CP-SAT objective term. In-regime K-eviction is **ship-first stratified hold** ([§3.11](#311-ship-first-family-tag-and-stratified-hold)), then leftover asc among equal weight. Overshoot hits merge into the user-facing list; they are not **inference near-solution seed**s. If `cap_2x <= slack`, the overshoot window is empty (empty-list residual unless leftover-0 exact ran).

### 3.11 Ship-first family tag and stratified hold

Locked in [Belief-torp remainder cap against the worthwhile bound](https://github.com/SteveDraper/Planets-Console/issues/400). Window: [§3.10](#310-ship-first-overshoot-constraint). Persist/chrome: [§3.8](#38-product-status-persist-and-stream) / [#402](https://github.com/SteveDraper/Planets-Console/issues/402). Map: [#394](https://github.com/SteveDraper/Planets-Console/issues/394). Implementation is a later effort on that map.

Belief-set torps stay on the prefix catalog (YAML `ship_torps_per_type: 40` and diversity cap 2 unchanged). There is **no** extra hard torp-military fraction of the **worthwhile remainder bound**: an **ammo-top-up near-solution** *is* torps closing that solution's gap. The standing preference is coexistence in **inference merged top-K**, not deleting that family.

**Family tag (structural, Core-owned).** On each feasible **ship-first near-solution**, non-torp military is everything except `ship_torps_loaded_*` (ship builds, decrease / pairing / **acquired ship**, other prefix aggregates). Compare in solver 2x:

- `non_torp > observed + slack` → **mine-overshoot near-solution** (`mine_overshoot`). Leftover is unmodeled mine decrease; modest torps may still appear and only inflate leftover.
- `non_torp <= observed + slack` and belief torps lift the total into the overshoot window → **ammo-top-up near-solution** (`ammo_top_up`). Still `explained > observed + slack`, not under-explain vs observed.

No ternary mixed family. No leftover-fraction classifier. Tag omitted on leftover-0 exact. Wire field on each in-regime solution: `shipFirstFamily`. SPA chips and tooltip read that field; they do not re-derive it.

**Stratified hold.** Default K = 20. When both families have at least one hit: floor **3** per family (or every hit if that family has fewer than 3); remaining slots by rank weight then leftover; never evict below the floor while the other family is over it. When only one family is feasible, that family may fill all K (no empty-family padding). Exact leftover-0 top-K stays weight-only eviction.

**Chrome.** Cell stays one blue **N** ([#402](https://github.com/SteveDraper/Planets-Console/issues/402)). Mixed-list tooltip/aria names both families and still quotes rank-1 leftover. Modal stays one weight-ordered list (not sections or tabs). Each ship-first header includes a family chip (`Mine leftover` / `Ammo top-up`). Mixed-list subtitle when both families are present; omit the subtitle when the held list is one family. Rank-1 row leftover is unchanged.

---

## 4. Problem formulation

For one player and one scoreboard observation (see section 3.3 when accelerated start applies), define candidate actions in **two layers**:

1. **Aggregate actions** -- flat integer variables for defense posts, starbase fighters, ship ammo loading, fighter transfers, and similar location-agnostic effects.
2. **Ship build combos** -- sparse integer variables for `(hull, engine, beam?, torp?, beam_count, launcher_count)` configurations. See [design-military-score-build-inference-implementation.md](design-military-score-build-inference-implementation.md) section 8.

Each aggregate action or ship build combo has:

- a scaled military-score delta,
- a warship-count delta,
- a freighter-count delta,
- a priority-point delta,
- a starbase build-slot usage,
- optional resource or inventory effects for later phases,
- a heuristic log-probability contribution.

The solver chooses non-negative integer counts subject to hard constraints summed over **both** layers:

```text
sum(action.score_delta_2x * count) == observation.military_delta_2x
sum(action.warship_delta * count) == observation.warship_delta
sum(action.freighter_delta * count) == observation.freighter_delta
sum(action.priority_delta * count) == observation.priority_point_delta
sum(action.build_slot_usage * count) <= starbases_owned
```

(`observation.*` is built from adjacent score rows in the normal case, or from accelerated-start rules on the first reliable row; see section 3.3.)

Additional constraints depend on the queue and ship-limit state. Before the ship limit, the build-slot constraint dominates. **Priority-point equality is diagnostic-only in the initial model** until production-queue semantics (standard vs priority build) are encoded per ship-build combo.

The objective is not simply "minimize score error"; score equality is a hard constraint for the initial model. Among feasible solutions, rank by heuristic probability:

```text
maximize sum(action.log_probability * count) + explanation_adjustments
```

Probability heuristics should be isolated from legality. If a low-probability explanation is the only feasible solution, it should still appear.

---

## 5. Candidate algorithms

### 5.1 Integer programming / CP-SAT

Model each candidate action as an integer variable and solve the linear constraints exactly. Use the objective for probability ranking, and ask for top-K feasible solutions.

**Pros**

- Directly matches the integer-constrained formulation.
- Cleanly separates hard constraints from ranking heuristics.
- Easy to add new action families, upper bounds, and prior-knowledge constraints.
- Mature solvers can prune large search spaces far better than brute force.
- Unsatisfiable cases produce useful diagnostics: which constraints conflict or how much residual score remains if relaxed.

**Cons**

- Adds a solver dependency and a modeling layer.
- Top-K enumeration needs care because many solutions can differ only by small ammo or defense changes.
- Solver behavior can feel opaque unless explanations and diagnostics are designed well.

**Fit:** Best default approach. CP-SAT is especially attractive because all variables are integer and constraints are linear after score scaling.

### 5.2 Domain-specific branch-and-bound

Search over action families in a fixed order, pruning branches by remaining score, count deltas, priority points, starbase slots, and probability bound.

**Pros**

- No solver dependency.
- Easy to encode domain-specific pruning and explanation ordering.
- Can stream partial results and stop after enough high-quality solutions.
- Transparent when debugging a single player's inference.

**Cons**

- More bespoke algorithm code to maintain.
- Extension pressure can make pruning logic complicated.
- Harder to guarantee good performance across all game states.
- Top-K correctness depends on careful bound design.

**Fit:** Good fallback or solver-independent implementation, but more fragile as constraints grow.

### 5.3 Multiple-choice knapsack / dynamic programming

Treat each build slot or action group as a knapsack choice, with dimensions for scaled score, ship deltas, freighter deltas, and priority points.

**Pros**

- Deterministic and exact within bounded dimensions.
- Can be fast when score deltas and build slots are small.
- Naturally returns counts or ways to reach a target delta.

**Cons**

- Multi-dimensional state can explode quickly.
- Less natural for unbounded ammo, defense posts, and transfer actions.
- Hard to express later constraints such as prior inventory or per-planet ownership changes.

**Fit:** Useful as a subroutine for bounded ship-build combinations, not as the whole architecture.

### 5.4 Meet-in-the-middle enumeration

Split candidate actions into groups, enumerate partial sums for each group, and join compatible partials.

**Pros**

- Exact for bounded action sets.
- Often much faster than naive enumeration.
- Good for combining ship-build possibilities with non-ship score adjustments.

**Cons**

- Requires tight bounds before enumeration.
- Memory can grow quickly with several constraint dimensions.
- Awkward for top-K ranking unless partial states keep probability summaries and backpointers.

**Fit:** Useful optimization inside a branch-and-bound or custom exact solver.

### 5.5 Best-first / A* top-K search

Explore partial explanations by descending optimistic probability, using admissible bounds to avoid lower-quality branches.

**Pros**

- Produces the most plausible explanations early.
- Can stop once the UI has enough explanations.
- Works well when good heuristics exist.

**Cons**

- Requires an admissible or at least conservative upper bound to avoid missing better solutions.
- Still needs strong feasibility pruning to avoid large open sets.
- More complex than CP-SAT for the same hard constraints.

**Fit:** Attractive for a later ranking layer or custom solver, but not the simplest first implementation.

### 5.6 Bayesian or factor-graph inference

Represent builds, ammo, defenses, transfers, and observed deltas as random variables, then infer posterior probabilities.

**Pros**

- Conceptually matches "several explanations with probabilities."
- Can incorporate soft evidence from previous turns, race tendencies, visible economy, and known fleet composition.
- Handles uncertainty explicitly.

**Cons**

- Exact inference is still hard; practical methods become approximate or solver-backed.
- Requires calibrated priors to avoid false confidence.
- More difficult to explain to users than a constrained solution list.

**Fit:** Good long-term framing for probability calibration, but too heavy as the initial solving mechanism.

### 5.7 Genetic algorithms

Evolve candidate explanations and score them by constraint fit and probability.

**Pros**

- Simple to prototype for very large spaces.
- Can find plausible approximate explanations when exact modeling is incomplete.

**Cons**

- No guarantee of feasibility or completeness.
- Poor fit for equality constraints where exact score and count deltas matter.
- Reproducibility and user trust are weak unless heavily constrained.

**Fit:** Not recommended for the first version.

### 5.8 Simulated annealing

Randomly walk the explanation space, sometimes accepting worse moves to escape local optima.

**Pros**

- Can explore rough probability landscapes with little solver infrastructure.
- Useful for stress-testing heuristic objectives.

**Cons**

- Approximate, stochastic, and hard to explain.
- May miss exact feasible solutions.
- Requires tuning schedules and move operators.

**Fit:** Not recommended for the first version.

### 5.9 SAT / SMT

Encode action counts and constraints into a satisfiability or SMT solver, optionally optimizing with repeated calls.

**Pros**

- Precise hard-constraint reasoning.
- Unsat cores can help diagnose impossible observations.
- SMT handles richer constraints than linear integer programming if needed.

**Cons**

- Linear integer optimization is the natural shape here; SMT adds complexity without much initial benefit.
- Optimization and top-K enumeration can be less straightforward than CP-SAT.

**Fit:** Consider if later constraints become non-linear or highly logical.

### 5.10 Column generation

Generate only promising composite actions, solve a restricted master problem, then add columns that can improve the explanation set.

**Pros**

- Scales when the full action catalog is huge.
- Separates "generate possible builds" from "fit observed deltas."

**Cons**

- More architecture than the initial problem needs.
- Harder to debug and test.

**Fit:** A later scaling technique if tiered combo generation is still too slow after Phase 1G.

---

## 6. Recommended approach

Use a hybrid exact-plus-ranking architecture:

1. **Build a two-layer catalog** for the player and turn: aggregate actions (defense, ammo load, transfers) plus **ship build combos** from eligible hulls and components. Use **tiered widening** when a narrow combo set is INFEASIBLE; jump tiers when `activeengines` / `activebeams` / `activetorps` are empty. Early tiers use beam/launcher counts of `0` or full slot fill; partial slot counts are a later tier (niche builds).
2. **Apply cheap bounds before solving.** Drop actions whose score contribution cannot fit the residual, whose ship class cannot match count deltas, or whose priority-point behavior is impossible for the ship-limit state.
3. **Solve hard constraints with CP-SAT or an integer-programming adapter.** Treat exact score, ship-count, and freighter-count as mandatory; treat priority-point fit as diagnostic until the queue model is added. Enforce starbase build-slot limits.
4. **Enumerate top-K feasible solutions.** Use no-good cuts over both aggregate and combo variables. Score-equivalent combos may share solver variables for feasibility, but distinct labels/weights should still yield distinct ranked explanations when probabilities differ.
5. **Rank by heuristic log-probability.** Prefer common builds, race-appropriate hulls, and plausible ammo loads. Keep the heuristic model separate from hard constraints.
6. **Return ambiguity deliberately.** Show several explanations when they are close in probability, and report when no exact explanation exists under the current scope and tier.

The solver interface should hide the concrete backend:

```text
InferenceProblem -> [AggregateActions + ShipBuildCombos] -> ConstraintSolver -> FeasibleExplanation[] -> Ranker
```

This keeps the first implementation independent of whether the backend is CP-SAT, another integer-programming solver, or a domain-specific branch-and-bound fallback.

---

## 7. Extensibility

The design should grow by adding action families and constraints:

- **Mine laying:** add minefield-score actions with negative torpedo inventory and positive minefield score (out of this quality bar; **mine-score residual**).
- **Ship trades, captures, and losses:** §3.7 (shipped, #370). Per-row **public scoreboard pairing** plus **prior-fleet decrease candidate**s; not a joint multi-player CP-SAT.
- **Planet losses:** add negative planet defense-post score and planet-count changes (out of this quality bar).
- **Starbase losses:** add negative base fighter and defense score, plus starbase-count changes (out of this quality bar).
- **Prior inventory:** minerals, cash, and locations remain deferred; departing ships are **prior-fleet decrease candidate**s (§3.7).
- **Resource feasibility:** add mineral, cash, supply, and tech-level constraints when enough data is known.
- **Post-limit PP:** [Post-limit PP accounting for military score build inference](https://github.com/SteveDraper/Planets-Console/issues/364). Pre-limit PQ/PPQ is **idle-dock PP equality** (§3.7).

The important rule is that every new phenomenon becomes either:

- a new candidate action with a contribution vector,
- a new hard constraint,
- a new prior probability term,
- or a diagnostic residual category.

It should not be embedded directly in the military-score equation.

---

## 8. Output shape

The inference engine should return a per-player list of explanations that can enrich the existing scoreboard analytic:

- observed deltas,
- constraints used,
- status: exact, no-exact-solution, stopped (implicit scope cancel on SPA stream, #71), or skipped (`exact-with-deferred-risk` reserved for deferred-effect modeling in #49); `time_limited` remains on the batch / corpus path,
- ranked explanations (leftover-0 exact in user-facing top-K; **ship-first near-solution**s on **mine-score residual** also user-facing -- [§3.8](#38-product-status-persist-and-stream); band-feasible **inference near-solution seed**s from tier search stay internal -- section 8.5.5 of implementation doc),
- explanation probability or score,
- action breakdown,
- residuals in diagnostics when the full policy ladder yields zero exact solutions (band retry best miss),
- warnings about ignored deferred effects,
- a compact summary suitable for a scoreboard cell.

The user-facing feature should be an optional capability of the existing Scores analytic rather than a separate analytic. When enabled, the scoreboard adds an inference column with row-level status: an **inference solution count indicator** -- an outlined badge with **N** = held top-K size (green for exact; blue for complete **mine-score residual** with **ship-first near-solution**s). While search is in flight and **N = 0**, the badge shows a dashed-border **0** with an in-progress animation (same count-badge chrome, not a separate hourglass icon); when **N > 0** on the exact path, the border is solid and the count rises toward K. Overshooting ship-first lists do not appear mid-search (no in-flight `solution` events). Paused chrome when **inference global pause** is active; red cross when the row completes naturally with no exact explanation or on solver failure; empty-list residual keeps marker + leftover. The column header hosts the global pause control. Hover text should summarize the result (for blue N: count first, leftover second). Clicking the badge opens the **inference solution detail modal** with ranked held explanations: per-solution icon tables, plausibility headers, and military-score reconciliation. See [design-military-score-inference-solution-modal.md](design-military-score-inference-solution-modal.md).

**Streaming (#71):** the SPA opens one multiplexed **inference table stream** for all scoreboard rows on the current scope; each leftover-0 `solution` event carries the full held top-K for one row (dashed-zero badge transitions to solid count when **N** becomes 1; the badge and modal grow while search continues). Overshooting **ship-first near-solution** lists do not use `solution` events -- they arrive on terminal `complete` ([§3.8](#38-product-status-persist-and-stream)). **Inference global pause** freezes all rows without losing partial held top-K **while the stream stays open**; resume via the column header. **Stream disconnect** is detach-only: clears server-side pause, retains row shells as `DETACHED` for late persist, and leaves in-flight solve tokens alone; reconnect replays durable **scores inference row persistence** and only recalculates rows that lack a valid persisted terminal. A thin **inference row scheduler** (orchestrator stream adapter) submits `tier_solve` work through the process-wide **compute orchestrator** so quick-to-solve players are not blocked behind another row's deep ladder climb. SPA searches are open-ended (no row time budget). Implicit **inference stream cancellation** (scope change, disable build inference, explicit cancel/recompute -- **not** disconnect) drops shells, records `CANCEL_DENY`, and aborts orchestrator scopes. Ownership: [ADR 0006](adr/0006-table-stream-lifecycle-invariants.md). See [design-military-score-build-inference-implementation.md](design-military-score-build-inference-implementation.md) sections 7.4--7.5, Phase 1H, and section 8.5.4.

---

## 9. Validation strategy

Validation should start before any UI work:

- Unit-test the scaled score contribution for each component type.
- Use synthetic turn transitions with known builds and ammo changes.
- Test unsatisfiable cases, especially score deltas that require deferred minefield or loss effects.
- Test ambiguous cases where multiple hulls or ammo mixes fit the same score.
- Compare inferred explanations against real turn histories where the player's own builds are known.
- Track solver runtime per player; corpus and batch JSON retain per-case time limits after the SPA drops row budgets (#71).

The first implementation should prefer correct "unknown or ambiguous" output over overconfident guesses.

---

## 10. Design decisions

### Resolved

| Topic | Decision |
|-------|----------|
| Solver backend | OR-Tools CP-SAT in Core API (`design-military-score-build-inference-implementation.md`) |
| Buildable hulls | `activehulls` intersect race and turn catalogs; ignore `Hull.isbase` as a build filter |
| Build-time ammo | Not on ship combos; use aggregate `ship_fighters_added_total` and `ship_torps_loaded_*` |
| Beams vs tubes | May be omitted independently; same-type rule within each fitted component |
| Partial slot fills | Allowed; `{0, max}` counts in early tiers; intermediate counts in later tier (niche) |
| Ship build catalog shape | Factored combos (Phase 1G), not flat cross-product preset IDs |
| Catalog widening | Variable-length **inference search tier** ladder from YAML policy (#77); jump when `active*` lists are empty |
| Fine-grained slack | Deferred to higher policy steps via **tier aggregate allowlist** (planet/SB defense posts, ship torps); not always-on |
| Score band + seeding | Out-of-regime: exact-first per step; band retry when infeasible and `alpha > 0`; near-solutions seed next step only (max 5); final step `alpha = 0`. In-regime prefix: [§3.10](#310-ship-first-overshoot-constraint) overlay, no `alpha` retry, no seeds. |
| User-facing exact | Any policy step may contribute exact solutions to top-K; band results never shown directly |
| Policy overlay | **#78** cancelled; step-local widens (`includeComponentIds` for collision twins, #226) |
| Score-equivalent combos | Solver-side merge for feasibility; distinct top-K when probability differs |
| Priority points | Diagnostic-only except **idle-dock PP equality** (§3.7 / #359) on pre-limit PQ/PPQ lattice-gated rows. Post-limit: [#364](https://github.com/SteveDraper/Planets-Console/issues/364). |
| Fleet-informed ranking | **#87** torp admission + misalignment prior; **#156** component tech-gap prior; tunables in `fleetInferenceTuning` (tier policy YAML). Catalog filter widens are step-local (#226), not a parallel #78 overlay. Absent fleet overlay == empty belief set. |
| SPA streaming (#71) | One multiplexed **inference table stream** per shell scope |
| Cross-row scheduling (#71) | **Inference row scheduler**: thin orchestrator adapter; `tier_solve` via process-wide compute pool ([design-compute-orchestrator.md](design-compute-orchestrator.md)) |
| Global pause (#71) | Freeze/resume all rows on current scope while stream connected; cleared on disconnect (detach, not cancel) |
| SPA time budget (#71) | None; global pause while connected; disconnect detaches (late persist allowed); cancel ends scopes |
| Stream cancel terminal (#71) | `stopped` on implicit **cancel** (not disconnect); last held top-K on wire when applicable; durable row persistence may survive reconnect |
| Batch / corpus time limits | Retained on batch JSON path; probe orchestration cap (`--probe-time-limit-seconds`) |
| Solve interrupt (v1) | Sub-step boundaries + `StopSearch()`; UNKNOWN sub-step retry follow-on if needed |
| Accelerated-start rows (#71) | Same stream and scheduler as normal rows; segments internal to row path |
| Inference admission skip (#356) | Never `tier_solve` for owner, Dead (inclusive), live inbound Full Alliance, Stealth (grey inference, keep Scores), Horwasp, `no_prior_turn`, `player_not_found`. Persist fallback-complete. Share Intel is not a skip. |
| Hopeless classifier / expensive-tier abort (#357 / shipped #368; entry-gate overlay shipped #411) | **Shipped:** cheap always through `full_components`. Abort `admit_starbase_defense_posts`+ on cheap-unsat if decrease-shaped >11, sticky prior, or any owner field `units > 0` in the N-window (`recentMinefieldObservationTurns`, default 3). Moderate 1-11 with no (i)/(iii) aborts expensive without starting sticky. Not #244. **#411:** folded the 1000-unit gate; YAML `largeMinefieldObservationMinUnits` dropped. Remaining overlay (leftover-0 skip, ship-first prefix) later on #413. |
| Unknown military ship placeholder (#358 / shipped #369) | Post-unsat artifact, not a catalog combo or ranked solution. One row `count = N` unexplained +warships; per-unit race construction envelope in `score_delta_2x`; residual stays on the row. Dedicated collection, hull sentinel `-1`. Same-row post-unsat **generic freighter combo** for +freighters. Fleet explodes to N unit inferred rows. |
| Ship loss, gift, and trade (#359 / shipped #370; mixed gift+build #387) | Per-row **public scoreboard pairing**; departures from **prior-fleet decrease candidate**s (not inverted build catalog). **Gift** includes capture. Incoming matched hull is **acquired ship**, not a **ship build combo**. **Idle-dock PP equality** pre-limit PQ/PPQ lattice-gated. PP-gap / dock-cap transfer budgets pair mixed build+transfer when net columns cancel. Families from first ship-bearing cheap step. **Unknown military ship** still `N > 0` only. Post-limit PP: #364. #49 no longer owns these families. |
| Product status persist and stream (#360; ship-first residual list #402) | First-class `status` (`exact`, `moderate_residual`, `mine_score_residual`, `no_exact_solution`, per-reason skip). Write-gate statuses unchanged. Empty-list residuals functional-persist with `placeholders` + leftover; **mine-score residual** with **ship-first near-solution**s persists ranked `solutions[]` + rank-1 leftover and `placeholders []`. Skips fallback-complete. Sticky derived from T-1 `mine_score_residual` (including non-empty list); leftover within slack is `exact` and clears sticky except when current-turn owner fields skip leftover-0 (§3.10). Stream: incremental `solution` events leftover-0 / exact only; overshooting lists on `complete` only. BFF `displayStatus` stays `mine_score_residual` when that is `status`. Exact: green N. Residual with N>0: same badge in blue (leftover in tooltip/aria). Empty-list mine / moderate: marker + leftover. No new modal. Export: product `status` / leftover / `placeholders` siblings of `$.solutions` (solutions may be non-empty on mine residual); `searchStatus` stays lifecycle-only. |
| Worthwhile remainder bound (#399) | Hard overshoot cap for in-regime **ship-first near-solution**s. Exact host turn; p90 of positive-stock units and field count, equal-split decay convert; **remainder-bound turn mixture** `n_total/(n_total+20)` with same-race isotonic leftover vs T (hold last knot); **observed-stock floor** from current-turn visible owner fields (exact per-field decay). CP-SAT `cap_2x = floor(bound)`. Not score band, not RST tighten, not a 10-turn lookup band. §3.9. |
| Ship-first overshoot constraint (#401) | New military window on the in-regime prefix, not `alpha` and not widened partition slack. `observed + slack < explained <= observed + cap_2x`. Current-turn owner fields (`units > 0`) skip leftover-0 exact. No those fields: exact-preempt, then overshoot. Overlay per prefix step, replacing band retry; no in-regime `alpha` retry; overshoots are not seeds. Rank weight + near-best as exact; leftover post-sort only. §3.10. |
| Ship-first family tag / stratified hold (#400) | Belief torps stay in the prefix; no extra torp-military fraction of the bound. Structural Core tag: non-torp `> observed + slack` is **mine-overshoot**, else **ammo-top-up** (torps lift into the window). Stratified hold: floor 3 per family when both have hits; rest of K by weight then leftover. One list; chips + mixed subtitle; blue N; rank-1 leftover. §3.11. |

### Still open

- Engine/hull tech-legality rules beyond active component lists.
- How much of the probability model should be user-configurable.
- Whether BFF returns full solutions inline or lazily per row at scale.
- Column generation if full-catalog combo search remains too slow after streaming + scheduler + global pause (#71).
- Corpus probe options for timeout-case deep diagnosis (per-case time override, `time_limited` filters).

These decisions affect implementation, not the overall approach. The core design remains: exact integer feasibility first, probabilistic ranking second.
