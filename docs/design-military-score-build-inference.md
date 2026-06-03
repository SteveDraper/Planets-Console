# Design: Military score build inference

This document describes an approach for inferring likely per-turn builds from scoreboard military-score deltas and related scoreboard constraints.

The goal is not to prove what happened. Military score is deliberately lossy: several combinations of ships, ammunition, and defenses can produce the same delta. The analytic should therefore return feasible explanations, rank them by plausibility, and make ambiguity visible.

**Related:** [design-military-score-build-inference-implementation.md](design-military-score-build-inference-implementation.md), [vga-planets-domain-context.md](vga-planets-domain-context.md), [design-analytics-structure.md](design-analytics-structure.md), [design-planets-api-data-model.md](design-planets-api-data-model.md).

---

## 1. Purpose

Given two adjacent scoreboard turns, infer possible actions for each player that explain:

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
- ship trades, captures, or losses,
- planet losses, including planets with defense posts,
- starbase losses, including bases with fighters or defense,
- ship destruction or combat ammo use,
- hard prior constraints from known inventory, minerals, cash, or ship locations.

The design should still make those extensions natural. Deferred effects should be added as new action families and constraints, not as special-case patches to the solver.

---

## 4. Problem formulation

For one player and one turn transition, define candidate actions in **two layers**:

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
sum(action.score_delta_2x * count) == 2 * militarychange
sum(action.warship_delta * count) == shipchange
sum(action.freighter_delta * count) == freighterchange
sum(action.priority_delta * count) == prioritypointchange
sum(action.build_slot_usage * count) <= starbases_owned
```

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

- **Mine laying:** add minefield-score actions with negative torpedo inventory and positive minefield score.
- **Ship trades and captures:** add ownership-transfer actions with paired loss/gain effects across players.
- **Ship losses:** add negative ship and score actions, constrained by prior known or inferred fleet state.
- **Planet losses:** add negative planet defense-post score and planet-count changes.
- **Starbase losses:** add negative base fighter and defense score, plus starbase-count changes.
- **Prior inventory:** add upper bounds from known ships, starbases, torpedoes, fighters, planets, and resources.
- **Resource feasibility:** add mineral, cash, supply, and tech-level constraints when enough data is known.

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
- status: exact, exact-with-deferred-risk, no-exact-solution, or skipped,
- ranked explanations,
- explanation probability or score,
- action breakdown,
- residuals if any constraint was relaxed,
- warnings about ignored deferred effects,
- a compact summary suitable for a scoreboard cell.

The user-facing feature should be an optional capability of the existing Scores analytic rather than a separate analytic. When enabled, the scoreboard adds an inference column with row-level status: green tick for at least one solution, hourglass while a row is still solving, and red cross for no solution or solver failure. Hover text should summarize the result. Clicking a green tick should open a modal with the detailed ranked explanations, including action vectors and score arithmetic.

---

## 9. Validation strategy

Validation should start before any UI work:

- Unit-test the scaled score contribution for each component type.
- Use synthetic turn transitions with known builds and ammo changes.
- Test unsatisfiable cases, especially score deltas that require deferred minefield or loss effects.
- Test ambiguous cases where multiple hulls or ammo mixes fit the same score.
- Compare inferred explanations against real turn histories where the player's own builds are known.
- Track solver runtime per player and cap top-K enumeration for UI responsiveness.

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
| Catalog widening | Tiered search with jump when `active*` lists are empty |
| Score-equivalent combos | Solver-side merge for feasibility; distinct top-K when probability differs |
| Priority points | Diagnostic-only until production-queue model assigns per-build PP deltas |
| Fleet priors | Deferred; will inform tier order and weights, not hard exclusion |

### Still open

- Engine/hull tech-legality rules beyond active component lists.
- How much of the probability model should be user-configurable.
- Whether BFF returns full solutions inline or lazily per row at scale.
- Column generation if tier-4 combo search exceeds time budget on large games.

These decisions affect implementation, not the overall approach. The core design remains: exact integer feasibility first, probabilistic ranking second.
