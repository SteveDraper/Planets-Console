# Mine-stock to leftover military arithmetic

Research for [Mine-stock to leftover military arithmetic](https://github.com/SteveDraper/Planets-Console/issues/397). Map: [Ship-first near-solutions in the mine-contaminated regime](https://github.com/SteveDraper/Planets-Console/issues/394).

**Verified:** 2026-09-03 against design military-score table, Core score arithmetic / partition-slack / band constraints in this repo, and a `planets-nu-wiki` Background brief (game-domain sources listed in [§8](#8-game-domain-sources)). This note does **not** pick a percentile cap and does **not** design the destination.

## Summary for implementers

Default decay is **per field**: remaining `round(0.95 x) - 1`, lost `x - round(0.95 x) + 1`. Sum lost units `L` across fields. Working conversion (ticket formula, help simplified line): mine military drop `27 L / 100` host 1x points. Solver 2x is twice host 1x, so the **nominal** leftover is `54 L / 100` (not inherently integer).

The scoreboard **floors the military column total**, not the mine term alone. Displayed 1x drop is `floor(27 L / 100)` or `ceil(27 L / 100)` according to the fractional part of the rest of the total; leftover in solver units is then `2` times that displayed drop, plus the existing half-point partition channel of `±1` 2x. That `±1` is **not** a mine leftover budget.

A `(total units, field count)` sample cannot recover exact `L`. Equal split is the natural point estimate; a single blob under-counts the per-field `-1` (about `n - 1` units when rounding is exact). Pathological all-size-1 fields are a bound, not a prior.

Today's **inference score band** is one-sided **under-explain** (`explained_2x >= observed_2x - alpha`) and is internal seed-only. The near-solve path needs **overshoot** (`explained_2x >= observed_2x`, leftover `= explained_2x - observed_2x`). Production observations always carry `military_partition_slack_2x = 1`, and the CP-SAT adder applies that **bidirectional** `±1` **instead of** `alpha`. Neither channel is the mine leftover.

---

## 1. 2x units the solver already uses

Design military-score table ([`docs/design-military-score-build-inference.md`](../design-military-score-build-inference.md) §2): Planets.nu military score has half-point components, so inference **multiplies all score contributions by 2** and solves in integers.

| Component | Military score (1x) | Scaled contribution (2x) | Code constant |
|-----------|---------------------|--------------------------|---------------|
| Warship hull, engines, beams, tubes | construction value `MC + 5 * minerals` | `2 * value` | [`ship_construction_score_delta_2x`](../../packages/api/api/concepts/ship_build_military.py) |
| Loaded ship fighter | `125` | `250` | `LOADED_SHIP_FIGHTER_SCORE_DELTA_2X` |
| Loaded ship torpedo | torpedo MC cost (+ ammo minerals) | `2 * construction_value(...)` | [`loaded_ship_torpedo_score_delta_2x`](../../packages/api/api/analytics/military_score_inference/scoring.py) |
| Starbase fighter | `62.5` | `125` | `STARBASE_FIGHTER_SCORE_DELTA_2X` |
| Starbase defense post | `7.5` | `15` | `STARBASE_DEFENSE_POST_SCORE_DELTA_2X` |
| Planet defense post | `5.5` | `11` | `PLANET_DEFENSE_POST_SCORE_DELTA_2X` |
| Minefields | derived from mine units | **deferred initially** | none in Core |

Construction value and the 2x scale are in [`packages/api/api/concepts/ship_build_military.py`](../../packages/api/api/concepts/ship_build_military.py). The half-point table is duplicated as integer 2x constants in [`packages/api/api/analytics/military_score_inference/scoring.py`](../../packages/api/api/analytics/military_score_inference/scoring.py). There is **no** minefield row in `scoring.py`.

Observation mapping ([`reported_host_military_delta_2x`](../../packages/api/api/analytics/military_score_inference/accelerated_start.py)): scoreboard `militarychange` is stored in **1x integer** units; solver observation is `2 * score.militarychange`. Display conversion back is `military_delta_2x // 2` ([`military_change_from_delta_2x`](../../packages/api/api/analytics/military_score_inference/hull_collision_twins_asset.py); same `// 2` on arithmetic payloads in [`score_arithmetic.py`](../../packages/api/api/analytics/military_score_inference/score_arithmetic.py)).

Wiki brief: vault does **not** name "2x units". Half-points (5.5, 7.5, 62.5) exist in help; doubled integers are a Console encoding.

---

## 2. Per-field decay, lost units, `27 L / 100`

Game-domain (wiki brief; [§8](#8-game-domain-sources)):

- Default (non-nebula) decay is per **field**, not per owner's total stock: `new units = round(old units * 0.95) - 1`. Help: "just over 5% of the mines in **each** minefield." Export wiki: `m_1 = round(m_2 * (1 - d)) - 1` with default `d = 0.05`. Donovan / host config: "5% plus one extra unit from each field" (same `-1`; no `round` there).
- Lost units on one field: `L_i = old - (round(0.95 * old) - 1) = old - round(0.95 * old) + 1`.
- Radius after decay: `floor(sqrt(units))`. A **~50 ly** field is `units` in `[2500, 2601)` (`floor(sqrt(2500)) = 50`, `floor(sqrt(2601)) = 51`).
- **Midpoint `.5` tie-break for `round` is unspecified.** `0.95 x` is half-integer at `x = 10, 30, 50, ...`. Python/`round` (banker's) and half-up **disagree at `x = 30`** (`28.5` -> 28 vs 29) and agree at `x = 10, 50, 250`. Examples below use sizes where `0.95 x` is not `.5`.
- Clamp if `round(0.95 x) - 1 < 0` is unspecified. Literal formula at `x = 0` yields remaining `-1`. Size-1 fields: remaining `0`, lost `1`.

**Do not** apply `round(0.95 U) - 1` to the player's **total** units `U`.

Lost units convert through the mine **military term**, not a separate host score step. Help simplified line (wiki-adopted): total mine units `x` score `27x / 100` (fixed-position half of Mk8 scoop MC `54 / 2 = 27`). Change from decay:

```text
delta_1x = 27 * (x_new - x_old) / 100 = -27 L / 100
```

with `L = sum_i L_i`. Nominal leftover in solver units (positive overshoot if ships explain the rest and mines are omitted):

```text
leftover_2x_nominal = 54 L / 100
```

**Help-page contradiction (unresolved in Authoritative):** the same help paragraph also says total units **divided by 100, fractions truncated**, then `× 27`, i.e. `27 * floor(x / 100)`. That is **not** `27 L / 100`. Crossing a 100-unit bucket moves leftover in **27-point** steps (e.g. `400 -> 379` lost 21: simplified drop `5.67` vs truncated drop `27`). This note follows the ticket's `27 * lost / 100`. If host truth is the truncated form, leftover scale is wrong by a large factor near 100-unit boundaries. No `raw/Authoritative/` resolution (wiki brief).

---

## 3. Scoreboard floor of the military total

Authoritative vault note `raw/Authoritative/planets-nu-military-score-scoreboard-rounding.md` (wiki brief): the **military column** is an **integer floored** (one planet defense post true `5.5` displays `+5`; two display `+11`). Help states fractional components; it does **not** state display rounding. Wiki: **no** vault rule for Raw Score / overall; the floor is of the **whole military total**, not of the mine term alone.

Console encoding of that floor for **half-point** components ([`accelerated_start.py`](../../packages/api/api/analytics/military_score_inference/accelerated_start.py) comment on `SCOREBOARD_MILITARY_PARTITION_SLACK_2X`):

```text
SCOREBOARD_MILITARY_PARTITION_SLACK_2X = 1
```

"`militarychange` is stored in 1x integer units. Half-point military components ... can lose up to one 2x unit when a host-turn delta is rounded." Production observations set this slack ([`observation_from_deltas`](../../packages/api/api/analytics/military_score_inference/inference_target.py) default). Test: 5 starbase fighters contribute `5 * 125 = 625` 2x against observed `624`, admitted by `±1` ([`test_scoreboard_partition_slack_allows_half_point_military_rounding`](../../packages/api/tests/test_military_score_inference_constraints.py)).

Mine `27 L / 100` is **not** restricted to `.5` fractions. Let `d = 27 L / 100` be the true 1x mine drop and `S` the 1x change from modeled actions. True military delta is `S - d` (plus other unmodeled terms). Displayed `militarychange` is a difference of **floors of the grand military total**. For any real `a` and drop `d`:

```text
floor(a - d) - floor(a)  in  {-ceil(d), -floor(d)}   (and `-d` when `d` is integer)
```

so the **displayed 1x mine-shaped drop** is `floor(d)` or `ceil(d)`. In 2x, that is `2 floor(d)` or `2 ceil(d)` -- always even -- **before** mixing other half-point components in the same floor.

If near-solve leftover is `explained_2x - observed_2x` with `observed_2x = 2 * militarychange` and `explained_2x` the 2x sum of modeled actions, then leftover 1x equals `d + ε` where `ε = (S - d) - militarychange` is the floor error on the **sum**. That `ε` lies in `(-1, 1)` in 1x (`(-2, 2)` in 2x). The existing slack of **one** 2x unit covers `|ε| <= 0.5` (half a display point), which matches `.5` posts, **not** the full floor-error range of an arbitrary fractional mine term.

**Do not** treat leftover as `floor(27 L / 100)` applied to the mine term in isolation, and **do not** expect `SCOREBOARD_MILITARY_PARTITION_SLACK_2X` to absorb `d`.

Integer leftover the solver can constrain is `explained_2x - observed_2x` (always int). `54 L / 100` is only a **nominal** real. A stock sample converts to an **interval** of plausible leftover_2x, not a single 2x integer:

```text
leftover_2x in { 2 floor(27 L / 100),  2 ceil(27 L / 100) }
             plus the half-point channel ±1 when other .5 components share the same floor
```

This note does not pick which endpoint a worthwhile cap should use.

---

## 4. Blob vs equal split when sizes are unknown

Given only `(U, n)` = (total units, field count), `L = U - sum_i round(0.95 x_i) + n`. Exact `L` requires the per-field sizes.

| Approximation | Rule | Bias vs exact |
|---------------|------|----------------|
| **Blob** | one field of `U` | Misses `n - 1` extra `-1`s; rounding is pooled. **Under-states** lost units when `n > 1` and `0.95 U` is exact. |
| **Equal split** | `n` parts as equal as possible (`q, q+1`) | Natural point estimate for a miner that emits count but not a size histogram. Still not exact (rounding is per field). |
| **Max-split bound** | `n` fields of size 1 when `U = n` (each lost 1) | Degenerate; not a ~50 ly stock. |

Map standing preference: convert to leftover military points **at solve time** with default **5% + 1 per field**; do not store decay points ([Ship-first near-solutions in the mine-contaminated regime](https://github.com/SteveDraper/Planets-Console/issues/394)). Equal split implements "5% + 1 **per field**"; blob implements "5% + 1" on the **stock**.

Worked numbers use Python `round` (banker's). Host midpoint is unspecified ([§2](#2-per-field-decay-lost-units-27-l--100)).

### 4.1 Modest stock -- 400 units (~20 ly if one field)

`0.95 * 400 = 380` exact.

| Split | Sizes | `L` | `27 L / 100` | `54 L / 100` | displayed 1x drop `{floor, ceil}` | leftover_2x `{2 floor, 2 ceil}` |
|-------|-------|-----|--------------|--------------|-----------------------------------|----------------------------------|
| Blob | `[400]` | 21 | 5.67 | 11.34 | `{5, 6}` | `{10, 12}` |
| Equal `n = 4` | `4 × 100` | 24 | 6.48 | 12.96 | `{6, 7}` | `{12, 14}` |
| Equal `n = 8` | `8 × 50` | 24 | 6.48 | 12.96 | `{6, 7}` | `{12, 14}` |

Per-field 100: remaining `round(95) - 1 = 94`, lost 6; four fields lose 24 vs blob 21 (`+3` from three extra `-1`s). `n = 8` of 50: remaining `round(47.5) - 1 = 48 - 1 = 47`, lost 3; eight fields lose 24 (same `L` as four 100s here). Modest leftover is **a few host points** / **~10-14** 2x -- already larger than partition slack `1`.

One field of 100 (~10 ly): `L = 6`, `27 L / 100 = 1.62`, leftover_2x in `{2, 4}`. Four fields of 25: remaining `round(23.75) - 1 = 24 - 1 = 23`, lost 2; `L = 8`, leftover_2x in `{4, 6}`.

### 4.2 ~50 ly stock -- 2500 units

`floor(sqrt(2500)) = 50`. `0.95 * 2500 = 2375` exact. Blob remaining `2374`, `L = 126`.

| Split | Sizes | `L` | `27 L / 100` | `54 L / 100` | displayed 1x `{floor, ceil}` | leftover_2x `{2 floor, 2 ceil}` |
|-------|-------|-----|--------------|--------------|------------------------------|----------------------------------|
| Blob | `[2500]` | 126 | 34.02 | 68.04 | `{34, 35}` | `{68, 70}` |
| Equal `n = 4` | `4 × 625` | 128 | 34.56 | 69.12 | `{34, 35}` | `{68, 70}` |
| Equal `n = 5` | `5 × 500` | 130 | 35.10 | 70.20 | `{35, 36}` | `{70, 72}` |
| Equal `n = 10` | `10 × 250` | 130 | 35.10 | 70.20 | `{35, 36}` | `{70, 72}` |
| Equal `n = 25` | `25 × 100` | 150 | 40.50 | 81.00 | `{40, 41}` | `{80, 82}` |

Four 625s: remaining `round(593.75) - 1 = 594 - 1 = 593`, lost 32; `L = 128` (blob plus 2, not plus 3, because rounding differs). ~50 ly leftover is **~34-41 host points** / **~68-82** 2x for plausible field counts -- two orders of magnitude above `military_partition_slack_2x = 1`.

---

## 5. Host order (why this leftover is not "mines only")

Wiki brief, host-order help: lay mines / lay webs -> ion storms (including minefield effects) -> sweep/scoop -> **mine decay** -> **mines destroy mines** -> ... first ship build / clone / MKT -> movement -> combat -> structure decay -> second ship build / autobuild -> **Make scoreboard**. Same-turn **lays decay this turn**. Decay is not the only mine or military change before the scoreboard (sweep, MDM, builds, combat, MKT, start-of-host planetary/SB defenses).

A stock-sample leftover is therefore a **decay-path prior**, not an exact catalog term. Map out of scope: modeling decay/sweep/MDM/lay/scoop as exact families.

---

## 6. How this leftover sits next to slack, band, and today's leftover field

Map leftover direction ([Ship-first near-solutions in the mine-contaminated regime](https://github.com/SteveDraper/Planets-Console/issues/394)): one-sided **overshoot** (`explained >= observed`); leftover `= explained - observed`. Under-explain is not this path.

### 6.1 `military_partition_slack_2x`

[`constraints.py`](../../packages/api/api/analytics/military_score_inference/constraints.py) `_SumEqualityConstraint.add_to_model` for `score_delta_2x`:

1. If `military_partition_slack_2x > 0`: **bidirectional** `lhs in [rhs - slack, rhs + slack]`, then **return**.
2. Else if `military_score_alpha > 0`: **one-sided** `lhs >= rhs - alpha` (no upper bound).
3. Else hard `lhs == rhs`.

Production slack is always `1` ([§3](#3-scoreboard-floor-of-the-military-total)). That is a **half-point floor channel**, not a mine budget. Mine leftover of ~11 or ~68 2x is outside `±1`. [`score_arithmetic.py`](../../packages/api/api/analytics/military_score_inference/score_arithmetic.py) uses the same slack to tighten interval-action envelopes so `matchesObserved` is `abs(explained_2x - observed_2x) <= slack`; leftover on an interval line is **assigned so the row still matches observed within slack**, not so ships overshoot by decay.

### 6.2 Today's inference score band (under-explain)

Glossary ([`CONTEXT.md`](../../CONTEXT.md) **inference score band**): `explained_2x >= observed_2x - alpha` with `alpha` from the tier policy; warship/freighter stay exact; final tier `alpha = 0`; band only on retry after infeasible exact; band-feasible results **seed the next tier only**, never user-facing. Implementation doc §8.5.4 step 4 restates the same inequality ([`docs/design-military-score-build-inference-implementation.md`](../design-military-score-build-inference-implementation.md)). Band residual stored as `observed_2x - explained_2x` ([`policy_ladder_tier_step.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_step.py)).

That inequality **allows under-explain up to `alpha`** and, when it actually applies, also allows **unbounded overshoot** (no `lhs <= rhs`). Near-solve needs overshoot **and forbids under-explain** (`explained >= observed`, leftover `= explained - observed`). Reusing the band with `alpha > 0` would still admit under-explain. Reusing it with `alpha = 0` is the overshoot inequality **only if slack does not take the other branch**.

**Composition with slack:** because production `military_partition_slack_2x = 1`, the adder **never reaches** the `alpha` branch ([`constraints.py`](../../packages/api/api/analytics/military_score_inference/constraints.py) `return` after slack). Band-retry tests that demonstrate `alpha` use `slack = 0` ([`test_military_score_inference_constraints.py`](../../packages/api/tests/test_military_score_inference_constraints.py)). Documented band and production `±1` slack are therefore **not the same constraint**, and **neither** is mine-scale leftover.

### 6.3 Hopeless leftover vs functional leftover vs near-solve leftover

| Quantity | Formula | Sign convention | Role today |
|----------|---------|-----------------|------------|
| Hopeless leftover | `observed_2x - min_warship_envelope_2x` ([`leftover_2x_after_construction_envelope`](../../packages/api/api/analytics/military_score_inference/hopeless_classifier.py)) | Negative = decrease-shaped (mine-like) | Classifier only; `leftover_points = abs(leftover_2x) // 2` |
| Functional `unexplainedMilitaryDelta2x` | **entire** `observation.military_delta_2x` on residual / `no_exact_solution` ([`_functional_leftover_2x`](../../packages/api/api/analytics/military_score_inference/inference_api_payload.py)) | Same sign as the scoreboard delta | Empty `solutions[]`; leftover is not `explained - observed` |
| Arithmetic "leftover" on interval actions | observed minus point-combo subtotal, assigned **into** the interval so the row matches ([`test_interval_action_tightens_to_leftover_after_point_combos`](../../packages/api/tests/test_score_arithmetic.py)) | Fills the gap to observed | Hard-equality (plus slack) presentation |
| **Near-solve leftover (this path)** | `explained_2x - observed_2x` with `explained_2x >= observed_2x` | Positive overshoot | Not implemented; map product contract |

A ship-first near-solution that explains more military than the scoreboard shows is **overshoot**. The band residual `observed - explained` is the **negation** of that leftover when explained exceeds observed. Today's functional leftover is the **whole observation**, because residual rows have no explained vector. Design §3.6: mine leftover is **not assigned onto** unknown-military-ship placeholders.

---

## 7. What this is not

- Not a percentile cap (map still open).
- Not nebula 15% / `round(0.85 x) - 1` (map out of scope for v1).
- Not an exact decay/sweep/lay/scoop catalog family.
- Not unconstrained negative CP-SAT slack to make leftover look exact.
- Not today's `±1` partition slack, and not today's under-explain band.

---

## 8. Game-domain sources

Via `planets-nu-wiki` Background brief (this agent did not read vault pages):

- `wiki/concepts/planets-nu/Minefields (Planets.nu).md`
- `wiki/concepts/planets-nu/Military score (Planets.nu).md`
- `wiki/concepts/planets-nu/Host (Planets.nu).md`
- `wiki/concepts/planets-nu/Nebulae (Planets.nu).md`
- `raw/planets-nu-help/minefields/body.html`
- `raw/planets-nu-help/military-score/body.html`
- `raw/planets-nu-help/scoreboard/body.html`
- `raw/planets-nu-help/host-order/body.html`
- `raw/planets/wiki/Minefields__565.mediawiki`
- `raw/planets/wiki/Host Configuration__143.mediawiki`
- `raw/donovansvgap/help/minefields/body.html`
- `raw/Authoritative/planets-nu-military-score-scoreboard-rounding.md`

---

## 9. Console primary sources

- [`docs/design-military-score-build-inference.md`](../design-military-score-build-inference.md) §2 (military table, 2x, minefields deferred), §3.5-3.6 (hopeless leftover, placeholders do not take mine leftover), §4 (hard `sum score_delta_2x == military_delta_2x`)
- [`docs/design-military-score-build-inference-implementation.md`](../design-military-score-build-inference-implementation.md) §8.5.4-8.5.5 (exact then band retry; band not user-facing)
- [`CONTEXT.md`](../../CONTEXT.md) **inference score band**, leftover on export `unexplainedMilitaryDelta2x`
- [`packages/api/api/concepts/ship_build_military.py`](../../packages/api/api/concepts/ship_build_military.py)
- [`packages/api/api/analytics/military_score_inference/scoring.py`](../../packages/api/api/analytics/military_score_inference/scoring.py)
- [`packages/api/api/analytics/military_score_inference/accelerated_start.py`](../../packages/api/api/analytics/military_score_inference/accelerated_start.py) (`SCOREBOARD_MILITARY_PARTITION_SLACK_2X`, `2 * militarychange`)
- [`packages/api/api/analytics/military_score_inference/inference_target.py`](../../packages/api/api/analytics/military_score_inference/inference_target.py)
- [`packages/api/api/analytics/military_score_inference/constraints.py`](../../packages/api/api/analytics/military_score_inference/constraints.py)
- [`packages/api/api/analytics/military_score_inference/score_arithmetic.py`](../../packages/api/api/analytics/military_score_inference/score_arithmetic.py)
- [`packages/api/api/analytics/military_score_inference/policy_ladder_tier_step.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_step.py)
- [`packages/api/api/analytics/military_score_inference/hopeless_classifier.py`](../../packages/api/api/analytics/military_score_inference/hopeless_classifier.py)
- [`packages/api/api/analytics/military_score_inference/inference_api_payload.py`](../../packages/api/api/analytics/military_score_inference/inference_api_payload.py)
- [`packages/api/tests/test_military_score_inference_constraints.py`](../../packages/api/tests/test_military_score_inference_constraints.py)
- [`packages/api/tests/test_score_arithmetic.py`](../../packages/api/tests/test_score_arithmetic.py)
