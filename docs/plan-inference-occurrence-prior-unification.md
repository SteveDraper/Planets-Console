# Plan: Unify aggregate occurrence priors into the histogram model

Tracker: follow-up to #86. Related: [design-military-score-inference-build-priors.md](design-military-score-inference-build-priors.md), repo root `CONTEXT.md`.

## 1. Problem and goal

The aggregate prior system has two shapes today: `histogram` (magnitude bins, e.g. modest/heavy/extreme) and `counts` (a single pseudo-count). The `counts` shape is **mathematically inert**: it is resolved through a single-cell Laplace conversion, and a probability distribution over one outcome is always `1.0`, so `round(SCALE * log(1.0)) == 0` for every pseudo-count. The hand-seeded asset distinguishes `fighters_starbase_to_ship: 65` from `fighters_ship_to_starbase: 35`, but both resolve to weight `0`; the distinction is silently discarded. The same single-cell degeneracy affects the Evil Empire action's `probability_weight`.

The intent behind `counts` was an **occurrence prior** ("how likely is this action to be part of the explanation at all?"), which is conceptually distinct from the histogram's **within-action magnitude prior** ("given it fires, how big?"). A histogram cannot express occurrence today because its bins only partition **positive** counts and are normalised within a single action.

The clean resolution -- and the goal of this plan -- is to make occurrence a first-class, within-action quantity by adding an explicit **`none` bin** (`count == 0`) to every aggregate histogram. Each action then contributes its own self-normalised `log P(observed bin)` term that includes the "did not happen" outcome. This:

- deletes the degenerate `counts` construct entirely (one shape: histogram);
- subsumes the separate, hand-tuned **parsimony penalty** (`parsimony_per_active_slack_type`) into the data-derived `none`-bin weight;
- is **behaviour-preserving** when the `none`-bin seeds are computed to reproduce the current parsimony penalty (see Section 3).

Exact feasibility remains the contract; priors only affect ranking within the feasible set.

## 2. Why a `none` bin reproduces the current behaviour exactly

Today, an active aggregate action contributes two objective terms: a magnitude-bin penalty (relative to the most likely positive bin) **plus** a flat parsimony penalty of `P = parsimony_per_active_slack_type = -(SCALE // 2) = -50`. A count of `0` contributes nothing.

Two algebraic facts make a single `none`-bin seed reproduce this for every bin at once:

1. **Magnitude spacing is denominator-invariant.** Laplace weight is `SCALE * log((c_i + 1) / (T + K))`; the gap between two positive bins is `SCALE * log((c_i + 1) / (c_j + 1))`, independent of `T + K`. Adding a `none` cell changes `T + K` for all cells equally, so it cannot disturb the relative ordering/spacing among the positive bins.
2. **Parsimony is a flat constant.** The only thing the `none` cell must inject is a uniform `|P|`-sized gap between "none" and the best positive bin. Because `none` becomes the largest cell, it is the max-weight bin, so choosing it costs `0` (matching count `0` today), and every active bin sits exactly `|P|` below where it would be without the cell.

### Seed formula

For each `(action, ship_limit_band)`:

```
c0 = round( (c_max + 1) * exp(|P| / SCALE) - 1 )
```

where `c_max` is the **largest bucketed positive-bin count** for that action/band (bucket the existing histogram first, then take the max), `|P| = SCALE // 2 = 50`, `SCALE = 100`, so `exp(|P| / SCALE) = exp(0.5) ~= 1.6487`. Because `c0 > c_max`, the `none` bin is the most likely outcome (cost `0`), exactly as count `0` is free today.

This reproduces the existing objective to within +/-1 (integer rounding of the log conversion). That +/-1 is rounding noise, not modelling drift.

## 3. Computed `none`-bin seeds (verified)

These were computed and verified to reproduce the current `active` costs within +/-1. Add a `0:` key with these values to each histogram table.

### `before_ship_limit`

| action | `0:` seed |
|---|---|
| planet_defense_posts_added_total | 198 |
| starbase_defense_posts_added_total | 166 |
| starbase_fighters_added_total | 149 |
| ship_fighters_added_total | 141 |
| ship_torps_loaded_1 | 133 |
| ship_torps_loaded_2 | 124 |
| ship_torps_loaded_3 | 116 |
| ship_torps_loaded_4 | 113 |
| ship_torps_loaded_5 | 109 |
| ship_torps_loaded_6 | 106 |
| ship_torps_loaded_7 | 103 |
| ship_torps_loaded_8 | 100 |
| ship_torps_loaded_9 | 96 |
| ship_torps_loaded_10 | 93 |
| ship_torps_loaded_11 | 90 |

### `after_ship_limit`

| action | `0:` seed |
|---|---|
| planet_defense_posts_added_total | 149 |
| starbase_defense_posts_added_total | 141 |
| starbase_fighters_added_total | 124 |
| ship_fighters_added_total | 116 |
| ship_torps_loaded_1 | 116 |
| ship_torps_loaded_2 | 108 |
| ship_torps_loaded_3 | 100 |
| ship_torps_loaded_4 | 96 |
| ship_torps_loaded_5 | 93 |
| ship_torps_loaded_6 | 90 |
| ship_torps_loaded_7 | 86 |
| ship_torps_loaded_8 | 83 |
| ship_torps_loaded_9 | 80 |
| ship_torps_loaded_10 | 76 |
| ship_torps_loaded_11 | 73 |

### Fighter transfers (former `counts`, now occurrence-only 2-bin histograms)

These have no magnitude prior -- only a `none` bin and a single `active` bin `[1, cap]`. Use an explicit `active` magnitude key of `1` (any key >= 1 lands in the single active bin). The `65/35` and `55/30` values do not differentiate the directions today (both resolve to ~`-50`); keep them only as documentation of the eventual mined asymmetry.

| band | action | histogram |
|---|---|---|
| before_ship_limit | fighters_starbase_to_ship | `{0: 108, 1: 65}` |
| before_ship_limit | fighters_ship_to_starbase | `{0: 58, 1: 35}` |
| after_ship_limit | fighters_starbase_to_ship | `{0: 91, 1: 55}` |
| after_ship_limit | fighters_ship_to_starbase | `{0: 50, 1: 30}` |

(Verification: active costs are -51, -49, -49, -50 respectively -- all ~`-50` within rounding.)

> Reproduction is exact within +/-1. If you prefer the directions to be visibly identical (since they are behaviourally identical until mined), use a single shared `active`/`none` pair per band instead; this is a cosmetic choice and does not change behaviour.

## 4. Phasing

- **Phase 1 (atomic, behaviour-neutral): occurrence-prior unification.** The model change, asset reseed, and all dead-code removal on the `counts` / parsimony / non-bucketed-aggregate-weight paths. This must land as one PR: partial application drifts behaviour (e.g. removing parsimony before the `none` seeds exist makes every action free). The existing solver and ranking tests are the behaviour-preservation guard.

Per `planning.mdc`, confirm Phase 1's plan is approved before implementing, and stop at the decision points in Section 7.

## 5. Phase 1 -- detailed code changes

All paths are under `packages/api/api/analytics/military_score_inference/` unless noted. Work top-down (model first) so each module compiles against the one below it.

### 5.1 `models.py` -- bin geometry handles a dedicated zero bin

- Rewrite `magnitude_bin_index` to drop the `lower_bound = 1 if bound.lower_count == 0 else ...` clamp. With an explicit `none` bin `[0, 0]`, the routing is a plain inclusive range test:

```python
def magnitude_bin_index(magnitude: int, bin_bounds: tuple[MagnitudeCountBounds, ...]) -> int:
    """Return the index of the magnitude bin containing a non-negative count."""
    for index, bound in enumerate(bin_bounds):
        if bound.lower_count <= magnitude <= bound.upper_count:
            return index
    return len(bin_bounds) - 1
```

  - `0` now lands in the leading `none` bin (`[0, 0]`); counts above the top bin still fall through to the last bin.
- `ProbabilityBinBounds`, `ProbabilityBucket`, `probability_buckets_from_bin_bounds` are unchanged structurally.
- **Remove `CandidateAction.probability_weight`** (the aggregate-action weight field). It becomes unused once the non-bucketed objective branch is deleted (5.7). `ShipBuildCombo.probability_weight` is a different field and stays. Grep for `CandidateAction(` and `.probability_weight` on aggregate actions and remove the argument everywhere it is constructed.

### 5.2 `aggregate_action_registry.py` -- one shape, `none`-first bins

- Add a shared leading `none` bin and prepend it to every bin-bounds constant; bump the first positive bin's `lower_count` from `0` to `1`:

```python
NONE_BIN = ProbabilityBinBounds("no build-up", 0, 0)

DEFENSE_POST_BIN_BOUNDS = (
    NONE_BIN,
    ProbabilityBinBounds("modest build-up", 1, 10),
    ProbabilityBinBounds("heavy build-up", 11, 50),
    ProbabilityBinBounds("extreme build-up", 51, 100),
)
# ...same prepend for STARBASE_FIGHTER_BIN_BOUNDS, SHIP_FIGHTER_BIN_BOUNDS, SHIP_TORPEDO_BIN_BOUNDS
```

- Add an occurrence-only bound for fighter transfers (label its single active band; the upper bound is cosmetic because anything `>= 1` routes to the last bin):

```python
FIGHTER_TRANSFER_BIN_BOUNDS = (
    NONE_BIN,
    ProbabilityBinBounds("transferred", 1, AggregateCatalogCaps().max_fighter_transfers),
)
```

- Convert the two `counts` registry entries (`fighters_starbase_to_ship`, `fighters_ship_to_starbase`) to histogram entries with `bin_bounds=FIGHTER_TRANSFER_BIN_BOUNDS`. They keep `missing_aggregate_policy="required"`, `allowlist_key`, and `is_fighter_channel_member=True`.
- **Delete `PriorShape` and the `prior_shape` field** from `AggregatePriorFields` (everything is a histogram now).
- **Delete the `is_fine_grained_slack` field** from `AggregatePriorFields` and remove it from every entry (its only consumer was parsimony eligibility, removed in 5.8).
- Make `bin_bounds` non-optional on `AggregatePriorFields` (type `tuple[ProbabilityBinBounds, ...]`, no `| None`) since every aggregate now has bins. Remove downstream `bin_bounds is None` guards (5.4, 5.6).

### 5.3 `prior_weights_asset.py` -- delete the `counts` shape

- **Delete `CountsAggregate`** and the `AggregatePrior = HistogramAggregate | CountsAggregate` union. Replace remaining `AggregatePrior` references with `HistogramAggregate` (or keep `AggregatePrior` as a thin alias `= HistogramAggregate` if it reduces churn; prefer using `HistogramAggregate` directly).
- In `_parse_band_aggregate_tables`: remove the entire `elif "counts" in action_raw:` branch and the "is not a known counts aggregate action" path. Every aggregate must now parse as `histogram`. Drop the `spec.prior_shape != "histogram"` check (no more shapes) -- keep the "is this a known aggregate action id" validation via `lookup_aggregate_action_spec`.
- Histogram parsing already accepts a `0` key (non-negative int, `allow_wildcard=False`). No change needed for `0`, but update the surrounding comments.
- Simplify `lookup_slot_aggregate_prior` to the histogram-only case: keep the "required vs implicit-uniform when absent" logic; drop the `CountsAggregate` shape check. Its return type becomes `HistogramAggregate | None`.
- `validate_complete_aggregate_priors` is unchanged in intent (iterate required slots, raise on missing); it now only ever validates histograms.
- Update the module docstring and any `ShipLimitBand`/comment references to drop "counts".

### 5.4 `prior_weights_laplace.py` -- name the occurrence constant; occurrence-aware implicit uniform

- Add the named constant capturing the legacy parsimony magnitude (this is the single place the old magic number survives, now as documented intent):

```python
LEGACY_PARSIMONY_OCCURRENCE_PENALTY = INFERENCE_PROBABILITY_WEIGHT_SCALE // 2  # 50

def none_bin_pseudo_count(active_max: float) -> float:
    """Pseudo-count for the count==0 (none) bin that reproduces the legacy
    occurrence/parsimony penalty against the most likely active bin."""
    return (active_max + 1.0) * math.exp(LEGACY_PARSIMONY_OCCURRENCE_PENALTY / INFERENCE_PROBABILITY_WEIGHT_SCALE) - 1.0
```

  - Keep it as a float (do not round) so the small-count implicit-uniform path stays accurate.
- This constant documents how the asset `0:` seeds in Section 3 were derived; reference it in a comment in the asset.

### 5.5 `prior_weights_resolve.py` -- drop counts resolution; occurrence-aware implicit uniform

- **Delete `_resolve_counts_aggregate_weight` and `_resolve_slot_counts_weight`.**
- Rewrite `_resolve_aggregate_priors` to a single histogram path: it returns only `dict[str, tuple[int, ...]]` (per-action bucket weights). Remove the `action_weights` dict and the `prior_shape`/`histogram` vs `counts` dispatch. Every slot resolves via `_resolve_slot_histogram_bucket_weights`.
- `_resolve_slot_histogram_bucket_weights`: drop the `bin_bounds is None` raise (now always set) and the redundant `isinstance(aggregate, HistogramAggregate)` re-check (`lookup_slot_aggregate_prior` already guarantees the type). When the slot is absent and policy is `implicit_uniform`, call the updated `_implicit_uniform_histogram_bucket_weights`.
- `_implicit_uniform_histogram_bucket_weights`: the bins now include the leading `none` bin. Seed active bins with `IMPLICIT_UNIFORM_PSEUDO_COUNT` (1.0) and the `none` bin (index 0) with `none_bin_pseudo_count(IMPLICIT_UNIFORM_PSEUDO_COUNT)` so missing-asset torpedo tables retain the ~`-50` occurrence cost instead of becoming free. Build the count dict explicitly rather than `dict.fromkeys(range(len(bin_bounds)), 1.0)`.
- `resolve_prior_weights_catalog`: stop computing/passing `aggregate_action_weights`; pass only `aggregate_bucket_marginal_weights`.

### 5.6 `prior_weights_catalog.py` -- remove the aggregate action-weight surface

- Drop the `_aggregate_action_weights` field, the aggregate action-weight constructor input, and the `aggregate_probability_weight(action_id)` method.
- `probability_buckets_for_action` is unchanged (still maps bin bounds + marginal weights to buckets), but it now always has buckets for every aggregate action.

### 5.7 `aggregate_catalog_build.py` -- every aggregate is bucketed

- **Delete `_aggregate_action_probability_weight`** (the histogram->0 / counts-lookup helper).
- `_append_aggregate_action`: remove the `probability_weight=` computation and the `CandidateAction(..., probability_weight=...)` argument. Every aggregate action now contributes ranking via its buckets only.
- `_probability_buckets_for_aggregate_action`: drop the `bin_bounds is None -> None` guard; always return buckets. Since fighter transfers now have bins, they too get buckets here.
- Net effect: `build_aggregate_actions` produces a `CandidateAction` (id, label, score delta, bounds) plus a buckets entry for **every** aggregate action, including the former-counts transfers.

### 5.8 `inference_objective.py` -- exactly one bin always active; delete parsimony loop and non-bucketed branch

- In `_add_ranking_bin_indicators`:
  - Remove the `has_positive_count` reification.
  - Reify each bin with its raw bounds (drop the `lower_bound = 1 if bucket.lower_count == 0` clamp); the `none` bin `[0, 0]` reifies `count == 0`.
  - Change the linking constraint to `model.add(sum(bin_indicators) == 1)` so exactly one bin (possibly `none`) is always active.
  - The `none` bin's penalty is `0` (it is the max-weight bin), so it adds no objective term -- count `0` stays free, matching today.
  - Tier-overflow handling (the `overflow_band` block) is unchanged and still keys off `admission_cap`.
- **Delete the entire `else:` branch** for non-bucketed actions (the `add_count_active_indicator` + `ranking_penalty_from_marginal_weight(action.probability_weight, max_aggregate_weight)` term). After 5.7 every registry aggregate is bucketed; the only remaining non-bucketed candidate is the Evil Empire action, which should contribute no ranking term (it stays "free/likely", exactly as its degenerate `0` weight + parsimony-exemption did before). Non-bucketed actions simply get no ranking penalty.
- **Delete the parsimony loop** (the final `for action in problem.aggregate_actions: if not is_parsimony_eligible_slack_action(...)` block) and the `max_aggregate_probability_weight` usage/import.
- **Keep `add_count_active_indicator`** -- it is still used by `constraints.py` (diversity caps, fighter-transfer exclusivity). Only its objective-internal uses go away.

### 5.9 `ranking_heuristics.py` -- delete parsimony; bin index includes zero

- **Delete** `parsimony_per_active_slack_type` (field + `_default_parsimony_per_active_slack_type`), `is_parsimony_eligible_slack_action`, and `compute_parsimony_objective_contribution`.
- Remove `parsimonyPerActiveSlackType` from `ranking_heuristics_diagnostics_payload`.
- `active_ranking_bin_index`: it must now return the `none` bin (index 0) for `count == 0` rather than `None`, so the post-hoc recompute matches the solver (the `none` bin carries penalty `0`). Simplify to `return magnitude_bin_index(count, buckets)` and drop the `if count <= 0: return None` guard. Update the docstring. (`active_ranking_bin_indicators` then lights the `none` bin for count `0` instead of returning all-zeros.)
- `EVIL_EMPIRE_FREE_STARBASE_FIGHTERS_ID` is no longer referenced by parsimony; check whether it is still used elsewhere (it is referenced in `actions.py`); keep the constant where still needed.

### 5.10 `solver.py` -- keep the post-hoc objective recompute in sync

`_objective_value` must mirror `build_inference_objective_terms` exactly:

- Remove `max_aggregate_probability_weight` import/use.
- Remove the non-bucketed `for action in problem.aggregate_actions: ... ranking_penalty_from_marginal_weight(action.probability_weight, ...)` loop.
- Remove the `compute_parsimony_objective_contribution` call (and its import).
- `compute_bin_penalty_objective_contribution` now naturally includes the occurrence cost (because the active positive bins sit below the `none` max), so no separate parsimony term is needed -- this is what preserves the total objective value.
- Leave `compute_overflow_objective_contribution`, combo penalties, and partial-slot penalties unchanged.

### 5.11 `actions.py` -- remove the degenerate Evil Empire single-cell weight

- The Evil Empire action used the same inert single-cell Laplace (`laplace_log_weight(pc, total=pc, cell_count=1)` == `0`). With `CandidateAction.probability_weight` removed (5.1), construct the action without a probability weight; it contributes no ranking term and remains preferentially cheap (free) relative to penalised actions -- behaviour-neutral.
- **Remove `evil_empire_free_starbase_fighter_pseudo_count`** from `ActionCatalogConfig` and the `laplace_log_weight(...)` call/import in `_evil_empire_free_starbase_fighter_actions`.
- `ActionCatalog.diagnostics()`: the `bucketed_action_count` currently counts actions whose spec `prior_shape == "histogram"`. With `prior_shape` removed, count actions that have an entry in `probability_buckets_by_action_id` instead (all aggregate actions now), or drop the field if it no longer carries signal -- decide per Section 7.

### 5.12 `analytic.py` -- diagnostics shape

- Drop `"probabilityWeight": action.probability_weight` from the per-aggregate-action diagnostics payload (line ~107), since the field is removed. Confirm no other consumer reads it.

### 5.13 Asset: `assets/analytics/scores/prior_weights_standard.yaml`

- Bump `version` (currently `2`) to `3` and update the header comment to describe the `none`-bin/occurrence semantics and the removal of the `counts` shape.
- Add the `0:` key with the Section 3 seed to every histogram table in both bands (defense posts, starbase/ship fighters, all `ship_torps_loaded_*`).
- Replace each `counts:` block for `fighters_starbase_to_ship` / `fighters_ship_to_starbase` with a `histogram:` block per the Section 3 fighter-transfer table (e.g. `{0: 108, 1: 65}`).
- Add a one-line comment near the top noting that `0:` seeds were computed via `none_bin_pseudo_count` to reproduce the legacy parsimony penalty (`LEGACY_PARSIMONY_OCCURRENCE_PENALTY`).
- There is no `prior_weights_blitz.yaml` / `prior_weights_epic.yaml` yet; only `standard` needs editing.

## 6. Phase 1 -- tests and docs

### 6.1 Tests to update (red/green guard)

The behaviour-preservation strategy: the solver-integration and ranking objective-value tests should still assert the **same** objective ordering/values (within +/-1) after the change. Update mechanical shape expectations, not semantics.

- `tests/test_military_score_inference_prior_weights_asset.py`: the `_complete_aggregates_band` / `_minimal_prior_weights_document` helpers emit `{"counts": {"default": 1}}` for non-histogram specs (lines ~23-26) -- change to emit histograms with a `0:` key for all actions. **Delete** the three counts-shape tests: `test_aggregates_reject_unknown_counts_action_id`, `test_aggregates_reject_counts_with_multiple_keys`, `test_aggregates_reject_empty_counts`. Add a test that a histogram action accepts and routes a `0:` key into the `none` bin.
- `tests/fixtures/military_score_inference_prior_weights.py`: line ~58 branches on `spec.prior_shape == "histogram"` and builds counts entries otherwise -- rebuild so the fixture emits histograms (with `0:` seeds) for every aggregate action, including transfers.
- `tests/test_military_score_inference_ranking_heuristics.py`:
  - Update `active_ranking_bin_indicators` expectations to 4-tuples with the `none` bin first: `(1, 0)` patterns shift, e.g. count `1`/`10` -> `(0, 1, 0, 0)`, count `100` -> `(0, 0, 0, 1)`, and add a `count 0 -> (1, 0, 0, 0)` case.
  - **Delete** the parsimony tests (`test_parsimony_allows_planet_and_starbase_defense`, `test_objective_value_includes_parsimony`, the `compute_parsimony_objective_contribution` import and assertions, and `parsimonyPerActiveSlackType` payload assertions).
- `tests/test_military_score_inference_solver.py`: remove the `result.diagnostics["rankingHeuristics"]["parsimonyPerActiveSlackType"] == -50` assertion (line ~470). Keep/adjust any objective-value assertions so they still hold within +/-1.
- `tests/test_military_score_inference_analytic.py`: lines ~346/355 set and assert `"rankingHeuristics": {"parsimonyPerActiveSlackType": -5}` -- remove the parsimony config/assertion; if the test relied on parsimony to force an ordering, re-anchor it on the `none`-bin occurrence cost.
- `tests/test_military_score_inference_prior_weights_catalog_resolution.py`: the implicit-uniform expectation (lines ~125-159) must account for the `none` bin now being part of the bin set and seeded via `none_bin_pseudo_count`; update the expected uniform weights.
- `tests/test_military_score_inference_prior_weights_solver_integration.py`: `higher_prior`/`lower_prior` refer to `ShipBuildCombo.probability_weight` (combos, unaffected) -- no change expected, but re-run to confirm top-K ordering is preserved.

### 6.2 New tests

- A focused test asserting the **behaviour-preservation invariant**: for a representative bucketed action, the objective contribution of `count == 0` is `0`, and the contribution of the most likely positive bin is `~ -LEGACY_PARSIMONY_OCCURRENCE_PENALTY` (within +/-1) -- i.e. the `none`-bin seed reproduces parsimony.
- A test that the `counts` YAML shape is rejected (the shape no longer exists), guarding against accidental reintroduction.
- A test that an aggregate histogram missing its `0:` key still parses but yields a low `none` weight (documents that occurrence mass is opt-in), unless Section 7 decides to require `0:`.

### 6.3 Docs

- Update `design-military-score-inference-build-priors.md` Section 7 (aggregate priors): replace the histogram-vs-counts split with the single `none`-bin histogram model; document the occurrence interpretation and that parsimony is now encoded in the `none` bin. Note the seed formula and `LEGACY_PARSIMONY_OCCURRENCE_PENALTY`.
- Update `CONTEXT.md` glossary entries for **Inference aggregate prior** / parsimony if they reference the `counts` shape or the standalone parsimony penalty.
- Update any inline docstrings touched above (`magnitude_bin_index`, `_implicit_uniform_histogram_bucket_weights`, `active_ranking_bin_index`).

## 7. Decision points (stop and confirm with the user)

1. **Diagnostics contract change.** Phase 1 removes `priorWeights`-adjacent fields: `probabilityWeight` (per aggregate action) and `parsimonyPerActiveSlackType` (ranking heuristics). These live in the analytic diagnostics dict (OpenAPI `unknown`, so no codegen break), but a frontend panel may read them. Confirm removal vs. retaining them as constants. Also decide the fate of `ActionCatalog.diagnostics()["bucketed_action_count"]` (now all aggregates are bucketed -- the count becomes "all aggregate actions").
2. **Fighter transfers now flow through the tier-overflow/admission path.** As `counts` actions they had no buckets and skipped the admission-cap/overflow loop in `build_action_catalog`; as 2-bin histograms they now enter it. Verify via the solver-integration tests whether tier overflow ever triggers for transfers (it only does when `current_cap > admission_cap` for the `fighter_transfers_per_direction` allowlist key). If it triggers and changes behaviour, gate overflow on `len(buckets) > 2` (or a spec flag) so occurrence-only actions are exempt. **Recommended:** verify first; add the guard only if behaviour drifts.
3. **Require an explicit `0:` key?** For seeded tables we add it; for the miner it is natural. Decide whether the parser should *require* a `0:` key on required histograms (stronger guarantee, rejects under-specified assets) or treat a missing `0:` as zero occurrence mass (more permissive). **Recommended:** do not require it in the parser; document the convention.
4. **`none` bucket label surfacing.** A `none`/`no build-up` `ProbabilityBucket` now exists for every action. Check `inference_api_payload.py` / row rendering to confirm a zero-count bucket label is not surfaced in a confusing way in tabular output. **Recommended:** verify; relabel if it leaks to the UI.
5. **Keep the `65/35` direction values or unify them?** They are behaviourally identical until mined. Keep-as-documentation vs. collapse-to-one-shared-pair (Section 3 note). Cosmetic.

## 8. Adjacent cleanups

No pending adjacent cleanups remain in this plan.

## 9. Acceptance criteria

- [ ] `counts` shape removed end-to-end (`CountsAggregate`, `prior_shape`, `_resolve_counts_*`, `aggregate_probability_weight`, `CandidateAction.probability_weight`, the non-bucketed objective branch).
- [ ] Standalone parsimony removed (`parsimony_per_active_slack_type`, `is_parsimony_eligible_slack_action`, `compute_parsimony_objective_contribution`, the objective parsimony loop, diagnostics key).
- [ ] Every aggregate is a histogram with a leading `none` bin; `magnitude_bin_index` routes `0` to it; the objective enforces exactly one active bin.
- [ ] Asset reseeded with the Section 3 `0:` values; fighter transfers converted to histograms; `version` bumped.
- [ ] Implicit-uniform torpedo tables retain the occurrence cost via `none_bin_pseudo_count`.
- [ ] Solver-integration and ranking objective values preserved within +/-1 (behaviour-neutral).
- [ ] `make lint` and `make test_api` pass; tests updated per Section 6.
- [ ] Docs and glossary updated.






