# Design: Military score inference implementation with OR-Tools

This document turns [design-military-score-build-inference.md](design-military-score-build-inference.md) into a phased implementation plan using OR-Tools CP-SAT.

The implementation should make exact feasibility the first-class contract: observed score and scoreboard deltas are hard constraints when enabled, while probability heuristics are encoded as an integer objective so the solver finds plausible explanations before low-probability noise.

**Related:** [design-military-score-build-inference.md](design-military-score-build-inference.md), [design-analytics-structure.md](design-analytics-structure.md), [design-planets-api-data-model.md](design-planets-api-data-model.md), [vga-planets-domain-context.md](vga-planets-domain-context.md).

---

## 1. Dependency choice

Use the Python package `ortools` for CP-SAT.

| Property | Decision |
|----------|----------|
| Package | `ortools` |
| Solver API | `ortools.sat.python.cp_model` |
| License | Apache-2.0 |
| Package location | `packages/api/pyproject.toml` |
| Lockfile update | via `uv` |

The dependency belongs in the Core API package because the inference model is domain logic. The BFF should only reshape Core results for the SPA, and the frontend should only render the analytic.

When adding the dependency, respect the dependency cooldown rule. At design time, the current OR-Tools release observed was older than seven days and supports the repo's Python 3.14 baseline.

---

## 2. Data flow

```mermaid
flowchart LR
    Scores["Adjacent scoreboard rows"] --> Observations["InferenceObservation"]
    Observations --> Agg["Aggregate actions"]
    Observations --> Combos["Ship build combos"]
    Agg --> Model["CP-SAT model"]
    Combos --> Model
    Model --> Solutions["Top-K feasible explanations"]
    Solutions --> CoreScores["Core scores payload"]
    CoreScores --> BffScores["BFF scores table"]
    BffScores --> Frontend["Scoreboard table with inference column"]
```

The first implementation solves each player independently. Cross-player coupling is deferred until ship trading, ship capture, and ownership transfers are modeled.

---

## 3. Module layout

Start with a small Core API subpackage so the solver and scoring model do not crowd the existing `scores` analytic:

```text
packages/api/api/analytics/military_score_inference/
|-- __init__.py
|-- actions.py            # aggregate noisy actions (defense, ammo load, transfers)
|-- ship_build_combos.py  # eligible hull/engine/beam/torp combos and tier policy (Phase 1G+)
|-- models.py             # dataclasses for observations, actions, problems, solutions
|-- scoring.py            # scaled military-score contribution formulas
|-- solver.py             # OR-Tools CP-SAT adapter
`-- analytic.py           # turn-level analytic assembly
```

Phase 1F shipped an interim flat `build_{hull}_{preset}` catalog in `actions.py`. Phase 1G moves ship builds into `ship_build_combos.py` and leaves aggregate actions in `actions.py`.

Do not register `military_score_inference` as a separate user-facing analytic. The solver package should be called by the existing `scores` analytic when inference is requested.

BFF and frontend files should follow existing analytics structure:

```text
packages/bff/bff/analytics/scores.py
packages/bff/bff/analytics/registry.py
packages/frontend/src/analytics/scores/
```

The implementation should not put solver logic in the BFF or frontend.

---

## 4. Core dataclasses

Use plain dataclasses in the Core package.

```python
@dataclass(frozen=True)
class InferenceObservation:
    player_id: int
    turn: int
    military_delta_2x: int
    warship_delta: int
    freighter_delta: int
    priority_point_delta: int
    starbases_owned: int
    is_after_ship_limit: bool


@dataclass(frozen=True)
class CandidateAction:
    id: str
    label: str
    score_delta_2x: int
    warship_delta: int = 0
    freighter_delta: int = 0
    priority_point_delta: int = 0
    build_slot_usage: int = 0
    lower_bound: int = 0
    upper_bound: int = 0
    probability_weight: int = 0
```

The important modeling rule is that action variables are non-negative integers, but action contribution vectors may contain positive or negative values. `probability_weight` is enough for simple actions, but repeated actions also need count-dependent probability terms.

```python
@dataclass(frozen=True)
class ProbabilityBucket:
    label: str
    lower_count: int
    upper_count: int
    marginal_weight: int
```

Use buckets when the probability of `n` repeated actions is not `n` independent repetitions of the same event. For example, building 10 defense posts is plausible, building 100 is much less plausible, but 100 defense posts should not be penalized as 100 independent rare choices.

```python
@dataclass(frozen=True)
class InferenceProblem:
    observation: InferenceObservation
    actions: tuple[CandidateAction, ...]
    probability_buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]]
    max_solutions: int = 20
    time_limit_seconds: float = 1.0
```

**Target extension (Phase 1G+):** ship builds become structured combos; aggregate noisy actions stay flat.

```python
@dataclass(frozen=True)
class ShipBuildCombo:
    combo_id: str
    hull_id: int
    engine_id: int
    beam_id: int | None       # None = no beams fitted
    torp_id: int | None       # None = no torp tubes fitted
    beam_count: int           # 0 .. hull.beams
    launcher_count: int       # 0 .. hull.launchers
    labels: tuple[str, ...]   # display labels; multiple when score-equivalent
    score_delta_2x: int
    warship_delta: int
    freighter_delta: int
    probability_weight: int


@dataclass(frozen=True)
class InferenceProblem:
    observation: InferenceObservation
    aggregate_actions: tuple[CandidateAction, ...]
    ship_build_combos: tuple[ShipBuildCombo, ...]
    ship_build_tier: int
    probability_buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]]
    max_solutions: int = 20
    time_limit_seconds: float = 1.0
```

The solver sums contributions from **both** aggregate action counts and ship-build combo counts into the same hard constraints.


@dataclass(frozen=True)
class InferenceSolutionAction:
    action_id: str
    label: str
    count: int


@dataclass(frozen=True)
class InferenceSolution:
    objective_value: int
    actions: tuple[InferenceSolutionAction, ...]


@dataclass(frozen=True)
class InferenceResult:
    status: str
    solutions: tuple[InferenceSolution, ...]
    diagnostics: dict[str, object]
```

These contracts can be refined during implementation, but the boundary should stay explicit: observations and candidate actions go into the solver; ranked feasible explanations come out.

---

## 5. CP-SAT formulation

For each `CandidateAction`, create one integer variable:

```text
count[action] in [lower_bound, upper_bound]
```

Add hard constraints:

```text
sum(score_delta_2x[action] * count[action]) == observation.military_delta_2x
sum(warship_delta[action] * count[action]) == observation.warship_delta
sum(freighter_delta[action] * count[action]) == observation.freighter_delta
sum(priority_point_delta[action] * count[action]) == observation.priority_point_delta
sum(build_slot_usage[action] * count[action]) <= observation.starbases_owned
```

Priority points should be configurable at first. If queue behavior is not yet confirmed for a scenario, run the solve with priority points as a diagnostic or optional constraint rather than silently accepting a wrong queue model.

Add an integer objective:

```text
maximize action_weights + bucketed_count_weights + interaction_weights
```

Weights should be scaled integer log-probabilities or penalties. For example, a common race-appropriate hull receives a better weight than an unusual one, and generic defense-post explanations receive a penalty so they do not crowd out more informative ship-build explanations.

### 5.1 Count-dependent probability terms

Some actions need probability as a function of count, not as a constant per unit. Use bucket variables for these cases.

Example for planetary defense posts:

| Bucket | Count range | Marginal meaning |
|--------|-------------|------------------|
| modest build-up | 0-10 | plausible local development |
| heavy build-up | 11-50 | less likely but common in border areas |
| extreme build-up | 51-100 | possible but strongly penalized |

The model can represent this with separate integer variables per bucket:

```text
defense_posts_total == defense_posts_bucket_1 + defense_posts_bucket_2 + defense_posts_bucket_3
0 <= defense_posts_bucket_1 <= 10
0 <= defense_posts_bucket_2 <= 40
0 <= defense_posts_bucket_3 <= 50
```

Then the objective uses different marginal weights for each bucket. This keeps the CP-SAT objective linear while avoiding the wrong assumption that 100 defense posts are as unlikely as 100 fully independent one-post actions.

This bucket pattern also applies to:

- starbase defense posts,
- starbase fighter increases,
- loaded fighter increases,
- loaded torpedoes by type,
- future mine-laying quantities.

---

## 6. Top-K solving

Do not enumerate all feasible solutions. Low-value actions can produce many exact but unhelpful combinations.

Use repeated optimization:

1. Build the model and solve for the best objective value.
2. Extract the non-zero action counts.
3. Add a no-good cut excluding that exact action vector.
4. Re-solve for the next best solution.
5. Stop when `max_solutions`, solver status, or time budget is reached.

A no-good cut can be encoded with indicator variables that detect whether each action count differs from its previous value, then require at least one difference. Keep this inside `solver.py` so the rest of the analytic only sees top-K results.

The solver should return:

- `exact` when at least one feasible solution is found,
- `no_exact_solution` when the model is infeasible under enabled constraints,
- `time_limited` when the solver reaches the time budget before proving optimality,
- `invalid_problem` when generated action bounds or observations are inconsistent before solving.

---

## 7. Scoreboard integration

The user-facing feature belongs to the existing **Scores** analytic. It should not appear as a separate analytic in the analytics list.

### 7.1 Analytics pane

Add an option inside the existing Scores tile:

- label: `Include build inference`,
- control: checkbox,
- default: off,
- disabled state: disabled only when Scores itself is unavailable,
- behavior: when checked, the scoreboard table requests or computes inference details in addition to normal score rows.

The checkbox should preserve the normal Scores analytic behavior. Turning it off should return the current scoreboard table shape with no inference column.

### 7.2 Scoreboard table

When inference is enabled, add one extra column to the existing scoreboard table.

| Icon | Meaning | Hover text | Click behavior |
|------|---------|------------|----------------|
| Green tick | At least one feasible solution found | summarize top solution and alternative count | open modal with detailed ranked solutions |
| Hourglass | solving is in progress for this player row | show that inference is still running | no modal until a result is available |
| Red cross | no solution, timeout, invalid problem, or solver failure | summarize failure status and key diagnostics | optionally open diagnostic modal if details exist |

The row-level hourglass means the frontend should track inference status per player, not block the whole scoreboard table until all rows are solved. The table should remain useful while slower rows are still pending.

### 7.3 Modal details

The modal for a green tick should show:

- player and turn transition,
- observed deltas used as constraints,
- solver status and runtime,
- ranked solutions in descending objective/probability order,
- action breakdown for each solution,
- score arithmetic for the selected solution,
- warnings when priority points were diagnostic-only or when deferred effects may explain missing solutions.

### 7.4 API shape

Keep the Core solver as an internal component. The Core `scores` analytic should accept an option such as `include_military_score_inference`. When false, it returns the current score rows. When true, each row may include an `inference` object:

```json
{
  "status": "exact",
  "summary": "Best: built one Rush with 18 fighters; 3 alternatives",
  "solutionCount": 4,
  "isComplete": true,
  "solutions": []
}
```

The BFF can decide whether to include detailed solutions in the initial table response or fetch them lazily when the modal opens. The initial implementation should prefer a simple table response unless row-level solve time requires lazy per-player requests.

---

## 8. Action catalog

The catalog has **two layers** that feed the same CP-SAT hard constraints:

1. **Aggregate actions** -- flat `CandidateAction` rows for repeated or location-agnostic effects.
2. **Ship build combos** -- sparse `(hull, engine, beam?, torp?, counts)` tuples with integer count variables (Phase 1G+).

Do **not** fold build-time fighter or torpedo **ammo** into ship combos. Loaded fighters and loaded torpedoes are separate aggregate actions that can take non-zero counts alongside ship builds.

### 8.1 Ship build combos (target model)

Each combo describes **one ship construction configuration** built at a starbase:

- one hull type;
- `hull.engines` copies of **one** engine type;
- `beam_count` copies of **one** beam type, or zero beams fitted;
- `launcher_count` copies of **one** torp tube type (via a torp's `launchercost`), or zero tubes fitted.

**Independence of beams and tubes:** omitting beams, omitting launchers, or omitting both is always allowed when the hull has the corresponding slots. Beams and tubes are not required to be fitted together.

**Same-type rule:** when `beam_count > 0`, all fitted beams share one beam type. When `launcher_count > 0`, all fitted tubes share one torp type (`launchercost`).

**Construction score** (scaled `score_delta_2x`):

```text
hull.cost
+ hull.engines * engine.cost
+ beam_count * beam.cost            (if beam_count > 0)
+ launcher_count * torp.launchercost (if launcher_count > 0)
plus minerals via megacredits + 5 * minerals
times 2 for military score scaling
```

Ammo (fighters loaded on ships, torpedoes loaded into tubes) is **not** part of this formula.

**Warship vs freighter:** a hull is a warship when it has `beams > 0`, `launchers > 0`, or `fighterbays > 0`; otherwise it counts as a freighter for `shipchange` / `freighterchange` constraints.

**Buildable hulls:** intersection of `player.activehulls`, race hull lists, `turn.racehulls`, and hulls present in `turn.hulls`. Do not filter hull catalog rows on `Hull.isbase`; Planets.nu marks normal starships with `isbase: true`.

**Eligible components** (widened by search tier -- see 8.5):

- engines from `player.activeengines` intersect `turn.engines`;
- beams from `player.activebeams` intersect `turn.beams`;
- torps from `player.activetorps` intersect `turn.torpedos` (tube cost only).

**Combo families by tier:**

| Tier focus | Beam / launcher counts | Typical use |
|------------|------------------------|-------------|
| Early tiers | `0` or maximum slot count only (`beam_count in {0, hull.beams}`, `launcher_count in {0, hull.launchers}`) | Default search; covers almost all practical builds |
| Later tiers | Intermediate counts `1 .. hull.beams - 1` and `1 .. hull.launchers - 1` | Niche partial-fit builds; lower priority |

Early tiers still include **minimal** builds `(beam_count=0, launcher_count=0)` for hulls with slots, including unarmed warships and torp hulls with empty tubes and/or empty beams.

**Global linking** (same hard constraints as today, summed over both layers):

```text
sum_agg(score_delta_2x * count)
  + sum_combo(score_delta_2x * build) == military_delta_2x

sum_agg(warship_delta * count)
  + sum_combo(warship_delta * build) == warship_delta

sum_agg(freighter_delta * count)
  + sum_combo(freighter_delta * build) == freighter_delta

sum(build_slot_usage) <= starbases_owned
```

Ship combos use `build_slot_usage = 1` per ship. Priority-point deltas on ship builds remain **zero** until production-queue semantics are modeled; treat `prioritypointchange` as diagnostic-only until then.

**Solution shape:** emit structured rows `{ hull, engine, beam?, torp?, beam_count, launcher_count, count }` rather than opaque `build_*` preset IDs.

### 8.2 Interim flat ship builds (Phase 1F -- to be replaced)

Phase 1F shipped a reduced flat catalog (`build_{hull}_{preset}`) with known gaps:

- single default engine (lowest ID in `turn.engines`);
- single default beam and torp type for armed presets;
- no beam-type or engine-type enumeration;
- preset names `empty` / `torpedoes` only.

This was enough to prove the pipeline but produces frequent INFEASIBLE results when the true build used other components. Phase 1G replaces this block with section 8.1.

### 8.3 Aggregate noisy actions

Aggregate actions where location detail is not yet known:

- `planet_defense_posts_added_total`,
- `starbase_defense_posts_added_total`,
- `starbase_fighters_added_total`,
- `ship_fighters_added_total`,
- `ship_torps_loaded_{torpedo_id}` for each torp type in `turn.torpedos`.

These variables still have exact score contributions, but they avoid one variable per planet or starbase in the initial version.

### 8.4 Negative actions

Support signed contribution vectors from the start:

- fighter transfer from ship to starbase: negative score delta,
- fighter transfer from starbase to ship: positive score delta,
- future ship loss or transfer actions: negative or cross-player deltas.

Negative actions need explicit upper bounds. Without bounds, positive and negative actions can create cancellation loops and a huge number of equivalent solutions.

### 8.5 Tiered catalog expansion

A full cross product of buildable hulls times eligible engines, beams, and torps can reach **low thousands to ~10k** combo variables in worst cases (many torp hulls, full turn catalogs, empty `active*` lists). Prefer **staged widening** over a single hand-tuned subset.

Search tiers (increase component eligibility and, in later tiers, partial beam/launcher counts):

| Tier | Engines | Beams | Torps (tube cost) | Partial beam/launcher counts |
|------|---------|-------|-------------------|----------------------------|
| 0 | single default (min id) | default | default | no |
| 1 | `activeengines` or jump if empty | default | default | no |
| 2 | active or full turn catalog if active empty | `activebeams` or jump | default | no |
| 3 | active or full | active or full | `activetorps` or full | no |
| 4 | full `turn.*` catalog | full | full | yes (niche counts) |

**Empty `active*` lists:** do not linger on narrow tiers. **Jump** to the next tier that uses a usable component set (typically full turn-catalog intersection for that axis) rather than solving repeatedly with a single default component.

Per player:

1. Build combo list for tier *n* plus aggregate actions.
2. Solve.
3. Stop on FEASIBLE (or TIME_LIMITED with at least one solution).
4. Else advance tier and retry until max tier or time budget.

Record `ship_build_tier`, `tiers_attempted`, and `combo_count` in diagnostics.

**Future refinement:** order tiers and intra-tier weights from fleet priors (histogram of engines, beams, and torps on existing ships). Likelihood informs search order and objective weights; it should not hard-exclude legal combos unless the product explicitly chooses a "most likely only" mode.

### 8.6 Score-equivalent combos (solver-side merge)

Multiple combos may share the same `(score_delta_2x, warship_delta, freighter_delta)` but differ in labels or probability weights (different hull names with identical construction cost, or different components that collide after scaling).

For **feasibility**, the solver may merge such combos into one integer variable carrying multiple `labels`.

For **top-K enumeration**, equal score does **not** imply equal probability. Distinct labels with the same score should still produce **distinct ranked solutions** when their probability weights differ. Implementation options:

- keep separate objective terms until after solve, or
- expand merged variables back into label-specific solution rows during extraction.

Do not treat score-equivalent combos as interchangeable in the UI ranking solely because the military score constraint cannot distinguish them.

---

## 9. Bounds and performance

The solver should receive a bounded catalog. Ship builds use **tiered combo generation** (section 8.5) rather than materializing the full cross product on the first attempt.

Use these bounds before building the CP-SAT model:

- **Residual score bound:** `abs(action.score_delta_2x) * count` cannot exceed a conservative residual cap unless the action is explicitly allowed to offset another signed action.
- **Build slot bound:** total ship builds cannot exceed starbases owned in the initial no-loss model.
- **Count-delta bound:** warship and freighter build actions are bounded by the observed count deltas when losses and trades are out of scope.
- **Capacity bound:** ship fighters and torpedoes should be capped by plausible loadout capacity where known.
- **Noisy-action cap:** defense posts, starbase fighters, and generic ammo adjustments should have conservative caps and lower probability weights.
- **Combo tier cap:** stop widening ship-build tiers when feasible or when the per-player time budget is exhausted.
- **Top-K cap:** default to a small solution count, such as 10 or 20 per player.
- **Time cap:** use a per-player solver budget so a pathological player does not block the whole analytic.

Expect **hundreds to low thousands** of variables per player at mid tiers; worst-case full catalogs may approach **~10k** combo variables before partial-count expansion. Staged solving is the primary mitigation. Column generation remains a later option if tier search is still too slow.

---

## 10. Implementation phases

These phases are intentionally small enough to hand to junior engineers. Each phase should be a reviewable PR unless the team explicitly batches adjacent phases.

### Phase 1A: Add the solver dependency

Goal: make OR-Tools available to Core API tests without changing product behavior.

Files:

- `packages/api/pyproject.toml`,
- `uv.lock`.

Steps:

1. Add `ortools` to the API package dependencies with `uv`.
2. Confirm the selected release satisfies the dependency cooldown rule.
3. Add a tiny import smoke test in `packages/api/tests/test_military_score_inference_solver.py`.
4. Do not create inference model code yet.

Done when:

- `PYTHONPATH=packages/api uv run python -m pytest packages/api/tests/test_military_score_inference_solver.py` passes,
- `make lint` passes.

### Phase 1B: Add Core contracts and score helpers

Goal: define the data shapes and deterministic score arithmetic before using CP-SAT.

Files:

- `packages/api/api/analytics/military_score_inference/models.py`,
- `packages/api/api/analytics/military_score_inference/scoring.py`,
- `packages/api/api/analytics/military_score_inference/__init__.py`,
- `packages/api/tests/test_military_score_inference_scoring.py`.

Steps:

1. Add dataclasses for observations, candidate actions, probability buckets, problems, solutions, and diagnostics.
2. Add scaled score helpers for fighters, torpedoes, starbase fighters, starbase defense posts, and planet defense posts.
3. Keep ship construction score as a helper that accepts already-known hull/component costs if full catalog data is not ready.
4. Add tests for exact scaled values, including half-point components multiplied by two.

Done when:

- score helper tests pass,
- dataclasses are frozen or otherwise safe to share between catalog and solver code,
- no OR-Tools model code exists outside the solver adapter planned for Phase 1C.

### Phase 1C: Add minimal CP-SAT exact solver

Goal: solve small synthetic inference problems exactly.

Files:

- `packages/api/api/analytics/military_score_inference/solver.py`,
- `packages/api/tests/test_military_score_inference_solver.py`.

Steps:

1. Convert each `CandidateAction` into a bounded integer variable.
2. Add hard equality constraints for scaled military score, warship count, freighter count, and priority points.
3. Add the build-slot upper-bound constraint.
4. Add support for signed action contribution vectors.
5. Return structured statuses instead of raising for infeasible models.

Tests:

- one exact positive-action solution,
- one solution using a negative action contribution,
- one infeasible problem,
- one invalid problem with bad action bounds.

Done when:

- solver tests pass with small synthetic catalogs,
- all solver-specific OR-Tools imports are isolated to `solver.py`.

### Phase 1D: Add ranked top-K solving

Goal: return the best few feasible solutions without enumerating the whole feasible space.

Files:

- `packages/api/api/analytics/military_score_inference/solver.py`,
- `packages/api/tests/test_military_score_inference_solver.py`.

Steps:

1. Add the integer objective for constant action weights.
2. Solve for the best feasible solution.
3. Add no-good cuts to exclude each returned action vector.
4. Re-solve until `max_solutions`, infeasibility, or time budget stops the loop.
5. Include objective value and non-zero action counts in each solution.

Tests:

- higher-weight solution sorts first,
- no-good cuts prevent duplicate solutions,
- top-K stops at the configured limit,
- time-limited or non-optimal status is surfaced in diagnostics.

Done when:

- top-K tests demonstrate descending objective order,
- the solver never enumerates all feasible solutions by default.

### Phase 1E: Add bucketed probability terms

Goal: support count-dependent probability for repeated low-value actions.

Files:

- `packages/api/api/analytics/military_score_inference/models.py`,
- `packages/api/api/analytics/military_score_inference/solver.py`,
- `packages/api/tests/test_military_score_inference_solver.py`.

Steps:

1. Add `ProbabilityBucket` support to `InferenceProblem`.
2. For each bucketed action, add bucket variables whose sum equals the action count.
3. Apply bucket marginal weights in the objective.
4. Prefer bucketed penalties for defense posts, starbase fighters, loaded fighters, and loaded torpedoes.

Tests:

- 10 defense posts has a different marginal penalty from 100 defense posts,
- a bucketed action still satisfies the exact score constraint,
- bucket variables cannot exceed their configured count ranges.

Done when:

- count-dependent priors are covered by tests,
- constant-weight actions still work unchanged.

### Phase 1F: Add initial action catalog

Goal: generate a bounded catalog for the first useful scoreboard-inference cases.

Status: **delivered** with interim flat ship-build presets (section 8.2). Replace in Phase 1G.

Files:

- `packages/api/api/analytics/military_score_inference/actions.py`,
- `packages/api/tests/test_military_score_inference_actions.py`.

Steps:

1. Add aggregate variables for low-value repeated actions.
2. Add interim flat ship-build actions from a small preset catalog.
3. Bound ship-build actions by observed warship/freighter deltas and starbase count.
4. Bound noisy actions by residual score and configured caps.
5. Add negative fighter-transfer actions with explicit caps.

Done when:

- action catalog tests pass,
- generated catalog size is logged or exposed in diagnostics for performance checks.

### Phase 1G: Factored ship build combos and tiered search

Goal: replace flat ship-build presets with structured combos (section 8.1) and staged tier widening (section 8.5).

Files:

- `packages/api/api/analytics/military_score_inference/ship_build_combos.py` (new),
- `packages/api/api/analytics/military_score_inference/actions.py` (aggregate actions only),
- `packages/api/api/analytics/military_score_inference/models.py`,
- `packages/api/api/analytics/military_score_inference/solver.py`,
- `packages/api/api/analytics/military_score_inference/analytic.py`,
- `packages/api/tests/test_military_score_inference_ship_build_combos.py` (new),
- updates to existing inference tests.

Steps:

1. Add `ShipBuildCombo` generation with validity rules (independent beam/tube omission, same-type rule, `hull.engines` engine count in score).
2. Early tiers: combo counts limited to `{0, max slots}` per axis; later tier adds partial beam/launcher counts.
3. Implement tier policy with **jump** when `activeengines` / `activebeams` / `activetorps` are empty.
4. Extend `InferenceProblem` and CP-SAT model to sum aggregate actions and combo counts into shared constraints.
5. Extend no-good cuts and solution extraction for combo variables; emit structured build rows.
6. Optional solver-side merge of score-equivalent combos; preserve distinct top-K rows when probability weights differ (section 8.6).
7. Expose `ship_build_tier`, `tiers_attempted`, and combo counts in diagnostics.
8. Remove interim flat `build_{hull}_{preset}` actions once parity tests pass.

Tests:

- combo validity and construction score for minimal, beam-only, tube-only, and fully armed builds;
- multi-engine hulls multiply engine cost by `hull.engines`;
- tier widening finds a feasible solution when tier 0 is too narrow;
- empty `active*` lists jump tiers without false INFEASIBLE from single-default components;
- score-equivalent merge does not collapse distinct probability-ranked solutions.

Done when:

- real-turn cases that failed under Phase 1F (wrong engine/torp/beam type) become feasible at an documented tier,
- diagnostics report tier and combo cardinality,
- `make lint` and inference package tests pass.

### Phase 2: Integrate with the existing Core scores analytic

Goal: enrich `scores` rows with optional inference data while preserving current behavior when disabled.

Files:

- `packages/api/api/analytics/scores.py`,
- `packages/api/api/analytics/options.py`,
- `packages/api/api/analytics/military_score_inference/analytic.py`,
- `packages/api/tests/test_analytics_registry.py`,
- `packages/api/tests/test_military_score_inference_analytic.py`.

Steps:

1. Add a scores option such as `include_military_score_inference`.
2. Keep `get_scores_table(turn)` behavior unchanged when the option is false.
3. When enabled, build one `InferenceObservation` per score row with enough adjacent-turn data available.
4. Call the internal solver package per player.
5. Attach an `inference` object to each Core scores row.
6. Do not add a new Core analytic ID for the user-facing feature.

Tests:

- current scores output remains unchanged when disabled,
- enabled output includes per-row inference status,
- missing prior score data produces a row-level diagnostic status,
- one player's solver failure does not remove other players' score rows.

Done when:

- Core scores tests cover both disabled and enabled behavior,
- the analytics registry still exposes `scores` as the user-facing analytic.

### Phase 3: Add BFF request and table shaping

Goal: expose the optional inference column through the existing BFF scores table.

Files:

- `packages/bff/bff/analytics/scores.py`,
- `packages/bff/bff/analytics/models.py` if query options need to expand,
- `packages/bff/bff/routers/analytics.py` if table query parsing needs a new option,
- `packages/bff/tests/test_analytics.py`.

Steps:

1. Add a BFF query option for `includeBuildInference`.
2. Forward the option to the Core scores analytic.
3. Keep existing scores table columns unchanged when the option is false.
4. Add an inference column when the option is true.
5. Shape each inference cell with status, summary text, and detail payload or detail lookup key.

Tests:

- disabled BFF response exactly matches the current table contract,
- enabled response adds the inference column,
- exact, in-progress, and failure statuses format predictably,
- diagnostics from Core are preserved enough for hover text.

Done when:

- BFF tests prove backward-compatible default behavior,
- no solver logic exists in BFF code.

### Phase 4: Add frontend scoreboard controls and status cells

Goal: let users enable inference from the Scores tile and see row-level status in the scoreboard.

Files:

- `packages/frontend/src/analytics/scores/` or the existing scores-related frontend module,
- `packages/frontend/src/AnalyticsBar.tsx` or the generic tile component that owns per-analytic controls,
- `packages/frontend/src/MainArea.tsx` if query keys or table rendering need option wiring,
- frontend tests near the touched components.

Steps:

1. Add a checkbox labeled `Include build inference` to the Scores analytic controls.
2. Include the checkbox state in the scores query key.
3. Render the inference column only when enabled.
4. Render green tick, hourglass, or red cross based on row status.
5. Add hover text with the row summary.
6. Keep the normal scoreboard table fast and unchanged when the checkbox is off.

Tests:

- checkbox toggles the query option,
- disabled state shows the current scoreboard columns,
- enabled state renders the inference column,
- each status renders the expected icon and accessible label.

Done when:

- frontend tests pass,
- the scoreboard remains usable while inference is disabled.

### Phase 5: Add solution-detail modal

Goal: let users inspect ranked solutions for rows with feasible explanations.

Files:

- `packages/frontend/src/analytics/scores/` modal component,
- any shared dialog component if one already exists,
- frontend tests for modal behavior.

Steps:

1. Open the modal when the user clicks a green tick.
2. Show solutions in descending objective/probability order.
3. Show observed deltas, action breakdown, score arithmetic, and warnings.
4. Do not open a solution modal for hourglass rows.
5. For red cross rows, either show hover-only diagnostics or a separate diagnostic modal if details are already available.

Tests:

- clicking a green tick opens the modal,
- solutions are displayed in order,
- hourglass rows are non-clickable or explain that solving is pending,
- modal closes cleanly and does not reset the Scores checkbox.

Done when:

- modal behavior is covered by frontend tests,
- detailed solution rendering does not require BFF or frontend to understand OR-Tools internals.

### Phase 6: richer constraints and deferred effects

Add action families and constraints only after Phase 1G ship-build combos are measurable.

Candidates:

- mine laying and scooping,
- ship trades and captures,
- planet and starbase losses,
- prior inventory and resource bounds,
- per-location defense post and fighter attribution,
- production-queue priority-point effects on ship builds,
- fleet-histogram priors for tier ordering and combo weights.

Each addition should include tests showing both new feasible explanations and cases where the new action removes a previous false unsat.

---

## 11. Testing strategy

Keep most tests below HTTP boundaries until the model stabilizes.

| Layer | Tests |
|-------|-------|
| Scoring helpers | exact scaled contribution values for ships, fighters, torpedoes, defenses |
| Aggregate action catalog | bounds, signed actions, noisy-action aggregation, bucket assignments |
| Ship build combos | validity rules, tier widening, construction score, partial counts (later tier) |
| Solver | exact fit, top-K, no-good cuts over aggregate + combo vars, tier diagnostics, infeasible status |
| Core scores analytic | disabled behavior, enabled row enrichment, per-player results, diagnostics |
| BFF scores table | default table contract, optional inference column, hover summaries |
| Frontend scores UI | checkbox control, row status icons, modal behavior |

Prefer synthetic fixtures with small combo catalogs. Large real-turn fixtures should include tier and combo-count regression checks.

---

## 12. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Too many low-probability exact solutions | optimize by probability first, top-K only, aggregate noisy actions |
| Ship-build catalog too narrow (INFEASIBLE) | factored combos with tiered widening; jump tiers when `active*` empty |
| Ship-build catalog too wide (slow solve) | tier caps, per-player time limits, combo-count diagnostics |
| Score-equivalent combos hide UI diversity | merge for feasibility only; split labels for top-K when weights differ |
| Incorrect priority-point model | priority-point equality soft/diagnostic until queue semantics are modeled |
| False confidence | return multiple explanations and expose ambiguity |
| Scoreboard regression | keep inference disabled by default and test the existing table contract |
| Row-level solving blocks the table | track per-row status and consider lazy or asynchronous detail loading |
| Dependency/platform issue | keep solver isolated behind an adapter so a fallback can be added |
| Hard-to-debug CP-SAT models | emit diagnostics with tier, combo counts, bounds, constraint targets, solver status |

---

## 13. Acceptance criteria

Phase 1 should be considered complete when:

- OR-Tools is isolated to the Core API solver adapter,
- synthetic CP-SAT tests pass for positive and negative action vectors,
- bucketed probability terms pass count-dependent objective tests,
- top-K ranked solving returns distinct feasible explanations,
- infeasible cases return diagnostics rather than exceptions,
- `make lint` and the relevant package tests pass.

The user-facing scoreboard integration should be considered complete when:

- inference remains disabled by default,
- the existing Scores table contract is unchanged when inference is disabled,
- the Scores tile includes an `Include build inference` checkbox,
- enabling inference adds an inference column with row-level status,
- green tick rows open a modal with ranked solution details,
- BFF and frontend code never import OR-Tools or encode solver rules directly,
- `make lint` and the relevant API, BFF, and frontend tests pass.
