# Budgeted, replaceable homeworld layout-prior solver

Homeworld layout prior selection must stay interactive on dense circular maps while still allowing richer (near-optimal) discrete choice and sample-grid stand-in placement. We extract a pure `LayoutPriorSolver` boundary (cost, sector build, persist, and annotate stay outside), keep the #36 capped enumerator as a selectable implementation, and deliver in two phases: encapsulate first (no `LAYOUT_PRIOR_ALGORITHM_VERSION` bump), then default to greedy frontier init plus seeded, size-aware simulated annealing under a pluggable stop-gate (wall-clock in production, step-count in tests), followed by alternating sample-grid stand-in refine outside the gate. Exact global optimality is a goal when budget allows, not a requirement on every request. See #270 and design §4.3.3.

## Considered Options

- Nested per-combo continuous stand-in search — rejected (hung map GETs on dense games).
- Hard-capped full product as the permanent production solver — rejected (blocks richer discrete choice).
- Beam search as the primary discrete strategy — deferred; SA preferred for anytime behavior and simpler partial-bound story.
- Exposing SA cooling knobs in YAML — rejected; budget ms + solver selector only; temperature follows a budget-progress schedule in code (`T0` may be problem-size adaptive).

## Modules

Under `packages/api/api/analytics/homeworld_locator/`:

| Module | Role |
|--------|------|
| `layout_prior.py` | Facade: eligibility → build → `solver.solve` → annotate |
| `layout_prior_problem.py` | `LayoutPriorProblem` / `SectorLayoutState` + sector build + seed materials |
| `layout_prior_cost.py` | Shared cost + position assembly (outside solvers): neighbor + center Normal ``-log`` families plus soft origin-distance evidence ``E(S)`` |
| `layout_prior_solver.py` | `LayoutPriorSolver` protocol, `LayoutPriorSolution`, factory |
| `layout_prior_stop_gate.py` | `StopGate` / `NeverStopGate` / `DeadlineStopGate` / `MaxStepsStopGate` |
| `layout_prior_enumerate.py` | `EnumeratingLayoutPriorSolver` (≤4 nearest-mid product) |
| `layout_prior_anneal.py` | `AnnealingLayoutPriorSolver` (greedy frontier + seeded SA) |
| `layout_prior_refine.py` | Sample-grid stand-in refine + #273 scored-sample hook |

Production default: `layout_prior_solver: anneal` with `layout_prior_budget_ms: 1000` (`DeadlineStopGate`). Enumerate remains selectable.
