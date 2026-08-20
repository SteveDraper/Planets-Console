# Generic freighter placeholder (hull id 0)

Research for [issue #354](https://github.com/SteveDraper/Planets-Console/issues/354). Map: [issue #352](https://github.com/SteveDraper/Planets-Console/issues/352). Consumer: [issue #358](https://github.com/SteveDraper/Planets-Console/issues/358) (Unknown military ship placeholder contract).

**Verified:** 2026-08-20 against Core, fleet ingest, scores export schema, and SPA sources in this repo.

This note records the **existing generic freighter combo** pattern and the **warship gap**. It does **not** design **unknown military ship**.

## Summary for implementers

True-freighter (and other zero-military-score) builds collapse to one solver-only **ship build combo**: `combo_freighter` with **hull id 0** (`GENERIC_FREIGHTER_SENTINEL_HULL_ID`), not a host catalog id. Count, starbase-slot, warship, and military-score equalities stay hard. The combo itself contributes `freighter_delta = 1`, `score_delta_2x = 0`, `build_slot_usage = 1`. **Priority-point equality is not enforced** in production, and `ShipBuildCombo` has no `priority_point_delta` field -- PP is observed/displayed only.

On the wire the generic row is the same `shipBuilds[]` object as a named hull, with sentinel zeros instead of host ids. Fleet **fleet build option set**s keep `hullId: 0` and **omit** non-positive engine/beam/torp ids. The **inference solution detail modal** and fleet table both label it **Freighter** and paint the LDSF glyph (hull 17) as a stand-in.

There is **no parallel warship placeholder**. When `shipchange` is non-zero and no named hull combo closes the row, inference returns `no_exact_solution` with empty `shipBuilds`. Fleet still seeds count-only inferred rows from the scoreboard; those stay unknown-spec until a named solution exists. Military slack (partition slack / `alpha` / aggregate padding) does not substitute for unidentified hulls.

---

## 1. Catalog construction: collapse to hull id 0

### 1.1 When a named combo is skipped

[`packages/api/api/analytics/military_score_inference/ship_build_combos.py`](../../packages/api/api/analytics/military_score_inference/ship_build_combos.py) enumerates buildable hull × engine × beam/launcher fills. For each candidate it computes `ship_build_military_score_delta_2x`. If that value is **0**, it does **not** emit a named `combo_{hull}_{engine}_…` row. It only raises `freighter_upper_bound` and `continue`s.

Zero military score is defined in [`packages/api/api/concepts/ship_build_military.py`](../../packages/api/api/concepts/ship_build_military.py) (`ship_build_has_zero_military_score`):

- Hull has **no weapon slots** (**true freighter**), or
- Hull has beam/launcher slots but is built **empty** and has **no fighter bays** (scoreboard **weaponless hull** / unarmed escort).

Carriers (`fighterbays > 0`) score hull construction even unarmed and stay named warship combos.

After the loop, if `freighter_upper_bound > 0`, Core appends **one** `_generic_freighter_combo`:

| Field | Value |
|-------|--------|
| `combo_id` | `"combo_freighter"` (`GENERIC_FREIGHTER_COMBO_ID`) |
| `hull_id` | `0` (`GENERIC_FREIGHTER_SENTINEL_HULL_ID` in [`packages/api/api/concepts/hulls.py`](../../packages/api/api/concepts/hulls.py)) |
| `engine_id` | `0` |
| `beam_id` / `torp_id` | `None` |
| `beam_count` / `launcher_count` | `0` |
| `labels` | `("Freighter",)` |
| `score_delta_2x` | `0` |
| `freighter_delta` | `1` |
| `warship_delta` | `0` (dataclass default) |
| `build_slot_usage` | `1` (dataclass default) |
| `upper_bound` | `min(max(0, freighter_delta), starbases_owned)` via `ship_build_upper_bound` |
| `probability_weight` | `prior_catalog.freighter_probability_weight(combo_id="combo_freighter")` |

Named warship combos keep real host hull/engine ids and `combo_{hullId}_{engineId}_{beam}_{torp}_{beamCount}_{launcherCount}`.

### 1.2 True-freighter hull set for priors (narrower than combo skip)

[`_generic_solver_freighter_hull_ids`](../../packages/api/api/analytics/military_score_inference/actions.py) is **slot-based**, not score-based: buildable hulls with `fighterbays == 0` and `launchers == 0` and `beams == 0`. That set is passed into prior resolution.

[`prior_weights_resolve.py`](../../packages/api/api/analytics/military_score_inference/prior_weights_resolve.py) sums those real hull counts in the **true freighter** table into a solver cell keyed `"generic_freighter"`, Laplace-converts, and stores the log weight on the catalog. Asset YAML keeps real hull ids; the synthetic id never appears in the prior asset ([`docs/design-military-score-inference-build-priors.md`](../design-military-score-inference-build-priors.md)).

[`PriorWeightsCatalog.freighter_probability_weight`](../../packages/api/api/analytics/military_score_inference/prior_weights_catalog.py) then composes **true-freighter category marginal + collapsed hull marginal** (plus optional combo-id override). Weaponless-hull counts are **not** folded into that weight; they only affect combo generation via the zero-score skip.

### 1.3 Ground-truth mapping

Corpus / miner mapping in [`ship_inventory.py`](../../packages/api/api/analytics/military_score_inference/ship_inventory.py) `ship_to_build_combo_id` returns `combo_freighter` whenever `ship_build_has_zero_military_score` is true -- same collapse as catalog generation, including unarmed escorts.

---

## 2. Solver constraints that stay exact

Hard equalities live in [`packages/api/api/analytics/military_score_inference/constraints.py`](../../packages/api/api/analytics/military_score_inference/constraints.py). Always enforced:

| Constraint | Form | Generic combo coefficient |
|------------|------|---------------------------|
| **Military score** | `sum(score_delta_2x * count) == military_delta_2x`, or a band when `military_partition_slack_2x > 0` or tier `alpha > 0` | `0` -- combo does not explain military; other actions must |
| **Warship count** (`shipchange`) | `sum(warship_delta * count) == warship_delta` | `0` |
| **Freighter count** (`freighterchange`) | `sum(freighter_delta * count) == freighter_delta` | `1` per unit |
| **Starbase slots** | `sum(build_slot_usage * count) <= starbases_owned` | `1` per unit; `upper_bound` already clipped to `starbases_owned` |

There is **no slack** on warship or freighter count. Military slack is score-only.

**Priority points:** `_PRIORITY_POINT_EQUALITY` exists but is added only when `InferenceProblem.enforce_priority_point_constraint` is true. Production `build_inference_problem` never sets that flag (default `False`). Diagnostics always record `requestedPriorityPointDelta` and, when unenforced, `priorityPointConstraintNote` ("Priority-point equality is not a hard solver constraint until production-queue semantics assign per-build `priority_point_delta` values."). `ShipBuildCombo` has **no** `priority_point_delta` attribute; only `CandidateAction` does.

### 2.1 Generic combo is not merged/expanded

[`solver.py`](../../packages/api/api/analytics/military_score_inference/solver.py) `_merge_score_equivalent_combos` **excludes** `combo_freighter` from score-equivalent groups. Extraction emits a single `InferenceSolutionShipBuild` with the sentinel tuple; it does not expand into named freighter hulls.

Freighter-only rows (`military_delta_2x == 0`, `warship_delta == 0`, `freighter_delta > 0`) take a CP-SAT skip (`FREIGHTER_ONLY_FAST_PATH`) that assigns `count = freighter_delta` on `combo_freighter` when `upper_bound` allows. That fast path is refused only if PP equality is **enforced** and `priority_point_delta != 0` -- which production does not do.

---

## 3. Wire / export: generic vs named hull

Both kinds serialize through the same `shipBuilds[]` object in [`inference_api_payload.py`](../../packages/api/api/analytics/military_score_inference/inference_api_payload.py) `_serialize_solution_ship_builds`. Scores export schema is [`packages/api/api/analytics/scores/export_schema.py`](../../packages/api/api/analytics/scores/export_schema.py) (`$.solutions[].shipBuilds[]`). Schema text still says hull/engine are "Host … id"; the sentinel is a documented exception in Core/fleet code, not in that schema blurb.

**Named hull example** (Missouri-style):

```json
{
  "comboId": "combo_13_9_3_6_8_6",
  "label": "Build Missouri: 2x Transwarp Drive, 8x Heavy Phaser, 6x Mark 8 Photon launcher",
  "count": 1,
  "hullId": 13,
  "engineId": 9,
  "beamId": 3,
  "torpId": 6,
  "beamCount": 8,
  "launcherCount": 6
}
```

**Generic freighter** (from solver extraction / tests):

```json
{
  "comboId": "combo_freighter",
  "label": "Freighter",
  "count": 1,
  "hullId": 0,
  "engineId": 0,
  "beamId": null,
  "torpId": null,
  "beamCount": 0,
  "launcherCount": 0
}
```

`militaryScoreArithmetic.lineItems` for the combo uses `comboId` (not `actionId`), `count`, and **zero** military subtotals. Row summary text is `Best: Freighter` or `Best: Nx Freighter`.

Cross-analytic consumers (fleet) must read top-level `$.solutions` only ([`docs/design-analytic-exports.md`](../design-analytic-exports.md)); they must not parse diagnostics for this contract.

---

## 4. Fleet option sets (hull id 0)

[`fleet_build_option_set_from_inference_ship_build`](../../packages/api/api/analytics/fleet/serialization.py):

- **Preserves** `hullId == 0` (`_resolved_fleet_hull_id`).
- Maps other non-positive component ids to **omitted / unknown** (`engineId` 0 is dropped on the fleet wire).
- Copies `comboId`, `label`, counts, `solutionRankWeight`.

Test: [`test_generic_freighter_option_set_omits_zero_component_ids_on_wire`](../../packages/api/tests/test_fleet_inference_ingest.py) -- domain `hull_id == 0`, `engine_id is None`; compute wire has `hullId: 0` and no `engineId`.

Refine ([`inferred_acquisition_refine.py`](../../packages/api/api/analytics/fleet/inferred_acquisition_refine.py)) classifies `combo_freighter` as **freighter** (`_inference_ship_build_class`); every other combo id is **warship**. Scoreboard placeholders are created **before** refine from `freighterchange` / `shipchange` counts ([`scoreboard_placeholder_targets.py`](../../packages/api/api/analytics/fleet/scoreboard_placeholder_targets.py)); option sets attach only when held solutions contain matching `shipBuilds`.

Observation match ([`observation_ingest.py`](../../packages/api/api/analytics/fleet/observation_ingest.py), [`docs/design-fleet-analytic.md`](../design-fleet-analytic.md) §4.3) treats sentinel hull 0 as typed "some freighter":

| Kind | Rule |
|------|------|
| `standard` | Ordinary lock match (real hull id) |
| `generic_freighter` | Sentinel hull 0; other axes lock-compatible; observed hull is a true freighter (no weapon slots) |
| `fed_refit` | Federation only; sentinel may match any observed hull (Super Refit) |

Military estimate for sentinel hull 0 is **0** ([`military_estimate.py`](../../packages/api/api/analytics/fleet/military_estimate.py)).

Homeworld starting freighters are **not** this sentinel: they seed known MDSF + Transwarp host ids.

---

## 5. SPA labels

### 5.1 Inference solution detail modal

Spec: [`docs/design-military-score-inference-solution-modal.md`](../design-military-score-inference-solution-modal.md) §8.1. Implementation: [`InferenceDetailModal.tsx`](../../packages/frontend/src/analytics/scores/InferenceDetailModal.tsx), [`inferenceSolutionLineIcon.tsx`](../../packages/frontend/src/analytics/scores/inferenceSolutionLineIcon.tsx), [`solutionLineItemDisplayOrder.ts`](../../packages/frontend/src/analytics/scores/solutionLineItemDisplayOrder.ts).

- Line id is `comboId` when `actionId` is absent ([`inferenceConstraints.ts`](../../packages/frontend/src/analytics/scores/inferenceConstraints.ts)).
- `combo_freighter` is a combo family (`isComboActionId` -- prefix `combo_`).
- Label: `Freighter` or `Nx Freighter` (count 1 stays bare).
- Icon: `hullId > 0` from the ship-build row, else parse `combo_*`; `combo_freighter` maps to **`GENERIC_FREIGHTER_HULL_ID = 17`** (LDSF stand-in, [`hullImageUrl.ts`](../../packages/frontend/src/concepts/hullImageUrl.ts)). Wire `hullId: 0` is **not** used as a picture id.
- Observed constraints include freighter change and **priority point change** when present. The PP *constraint note* stays in the Scores diagnostics panel, not the modal.

### 5.2 Fleet inferred-acquisition display

[`fleetRecordComponentDisplay.ts`](../../packages/frontend/src/analytics/fleet/fleetRecordComponentDisplay.ts) / [`fleetRecordDisplay.ts`](../../packages/frontend/src/analytics/fleet/fleetRecordDisplay.ts):

- `comboId === "combo_freighter"` → hull **label** is the option-set label (`Freighter`), not catalog name for id 0 or 17.
- Glyph still uses hull 17.
- `hullId <= 0` is not treated as a known host hull (`resolvedOptionSetComponentId`); engine `0` displays as `?`; beam/launcher counts `0` display as empty.

---

## 6. Warship gap (not a second pattern)

There is **no** generic warship combo, no sentinel hull id for unidentified military ships, and no score-band placeholder in `shipBuilds`.

When `shipchange` (`warship_delta`) is non-zero:

1. Catalog emits **named** warship combos only (`score_delta_2x > 0`). Unarmed non-carrier military hulls have already collapsed into `combo_freighter` (freighter class), not warships.
2. Solver **must** hit exact `warship_delta`. Fine-grained slack actions (defense posts, torp loads) have `warship_delta = 0`; they cannot stand in for a missing hull.
3. If some named combo (plus aggregates) closes military + counts + slots → `exact` with real `hullId`s.
4. If not → `no_exact_solution` ("No feasible build explanation found"), **empty** `solutions` / `shipBuilds`. That is a failed exact search, not `invalid_problem` (malformed catalog) and not a slack-only explanation of unidentified ships.
5. Fleet **still** creates N **fleet inferred acquisition** rows from scoreboard `shipchange` with empty option sets and unknown component fields. Refine no-ops when there are no warship `shipBuilds`. UI shows `?` until a named solution or a sighting arrives.

Military partition slack / tier `alpha` can widen the **score** band while counts stay exact; they do not emit an unidentified-hull row.

**Copyable pieces for #358** (pattern only -- not a design): typed sentinel distinct from host ids; `combo_id` + label as identity; count and slot coefficients that remain exact when identity is collapsed; preserve sentinel on fleet option sets (do not coerce 0 to unknown); SPA must not treat the sentinel as a host picture id. **Missing on the warship side today:** any catalog row, any score bounds, any solution-line emission when hull is unknown.

---

## 7. Priority points when ship identity is generic

| Layer | Behavior |
|-------|----------|
| Observation | `priority_point_delta` copied from scoreboard `prioritypointchange` (or prior-row diff). |
| Combo | No PP coefficient on `ShipBuildCombo` / `combo_freighter`. |
| Solver | PP equality **off** in production. Generic-freighter fast path still runs when `priority_point_delta != 0`. Idle rows that are zero except PP are treated as idle (`_observation_is_solver_idle`). |
| Diagnostics / modal | Requested PP delta is visible; enforcement note is diagnostics-only. |
| Fleet option set | No PP field. |

PP does **not** currently survive as an exact per-build constraint when hull identity is generic. Count (`freighterchange`) and starbase slots do.

---

## Sources

- [`packages/api/api/concepts/hulls.py`](../../packages/api/api/concepts/hulls.py)
- [`packages/api/api/concepts/ship_build_military.py`](../../packages/api/api/concepts/ship_build_military.py)
- [`packages/api/api/analytics/military_score_inference/ship_build_combos.py`](../../packages/api/api/analytics/military_score_inference/ship_build_combos.py)
- [`packages/api/api/analytics/military_score_inference/actions.py`](../../packages/api/api/analytics/military_score_inference/actions.py)
- [`packages/api/api/analytics/military_score_inference/prior_weights_resolve.py`](../../packages/api/api/analytics/military_score_inference/prior_weights_resolve.py)
- [`packages/api/api/analytics/military_score_inference/prior_weights_catalog.py`](../../packages/api/api/analytics/military_score_inference/prior_weights_catalog.py)
- [`packages/api/api/analytics/military_score_inference/constraints.py`](../../packages/api/api/analytics/military_score_inference/constraints.py)
- [`packages/api/api/analytics/military_score_inference/solver.py`](../../packages/api/api/analytics/military_score_inference/solver.py)
- [`packages/api/api/analytics/military_score_inference/models.py`](../../packages/api/api/analytics/military_score_inference/models.py)
- [`packages/api/api/analytics/military_score_inference/inference_api_payload.py`](../../packages/api/api/analytics/military_score_inference/inference_api_payload.py)
- [`packages/api/api/analytics/military_score_inference/score_arithmetic.py`](../../packages/api/api/analytics/military_score_inference/score_arithmetic.py)
- [`packages/api/api/analytics/scores/export_schema.py`](../../packages/api/api/analytics/scores/export_schema.py)
- [`packages/api/api/analytics/fleet/serialization.py`](../../packages/api/api/analytics/fleet/serialization.py)
- [`packages/api/api/analytics/fleet/inferred_acquisition_refine.py`](../../packages/api/api/analytics/fleet/inferred_acquisition_refine.py)
- [`packages/api/api/analytics/fleet/observation_ingest.py`](../../packages/api/api/analytics/fleet/observation_ingest.py)
- [`packages/frontend/src/analytics/scores/InferenceDetailModal.tsx`](../../packages/frontend/src/analytics/scores/InferenceDetailModal.tsx)
- [`packages/frontend/src/analytics/fleet/fleetRecordComponentDisplay.ts`](../../packages/frontend/src/analytics/fleet/fleetRecordComponentDisplay.ts)
- [`docs/design-fleet-analytic.md`](../design-fleet-analytic.md)
- [`docs/design-military-score-inference-solution-modal.md`](../design-military-score-inference-solution-modal.md)
- [`docs/design-military-score-inference-build-priors.md`](../design-military-score-inference-build-priors.md)
- Glossary: **generic freighter combo**, **fleet build option set**, **inference solution detail modal** in [`CONTEXT.md`](../../CONTEXT.md)
