# Budgeted, replaceable homeworld layout-prior solver

Homeworld layout prior selection must stay interactive on dense circular maps while still allowing richer (near-optimal) discrete choice and sample-grid stand-in placement. We extract a pure `LayoutPriorSolver` boundary (cost, sector build, persist, and annotate stay outside), keep the #36 capped enumerator as a selectable implementation, and deliver in two phases: encapsulate first (no `LAYOUT_PRIOR_ALGORITHM_VERSION` bump), then default to greedy frontier init plus seeded, size-aware simulated annealing under a pluggable stop-gate (wall-clock in production, step-count in tests), followed by alternating sample-grid stand-in refine outside the gate. Exact global optimality is a goal when budget allows, not a requirement on every request. See #270 and design §4.3.3.

## Considered Options

- Nested per-combo continuous stand-in search — rejected (hung map GETs on dense games).
- Hard-capped full product as the permanent production solver — rejected (blocks richer discrete choice).
- Beam search as the primary discrete strategy — deferred; SA preferred for anytime behavior and simpler partial-bound story.
- Exposing SA cooling knobs in YAML — rejected; budget ms + solver selector only; cooling may be problem-size adaptive in code.

## Modules (Phase 1)

Under `packages/api/api/analytics/homeworld_locator/`:

| Module | Role |
|--------|------|
| `layout_prior.py` | Facade: eligibility → build → `solver.solve` → annotate |
| `layout_prior_problem.py` | `LayoutPriorProblem` / `SectorLayoutState` + sector build |
| `layout_prior_cost.py` | Shared cost + position assembly (outside solvers) |
| `layout_prior_solver.py` | `LayoutPriorSolver` protocol, `LayoutPriorSolution`, factory |
| `layout_prior_stop_gate.py` | `StopGate` / `NeverStopGate` |
| `layout_prior_enumerate.py` | `EnumeratingLayoutPriorSolver` (≤4 nearest-mid product) |
