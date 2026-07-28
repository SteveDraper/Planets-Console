# Budgeted, replaceable homeworld layout-prior solver

Homeworld layout prior selection must stay interactive on dense circular maps while still allowing richer (near-optimal) discrete choice and sample-grid stand-in placement. We extract a pure `LayoutPriorSolver` boundary (cost, sector build, persist, and annotate stay outside), keep the #36 capped enumerator as a selectable implementation, and deliver in two phases: encapsulate first (no `LAYOUT_PRIOR_ALGORITHM_VERSION` bump), then default to greedy frontier init plus seeded, size-aware simulated annealing under a pluggable stop-gate (wall-clock in production, step-count in tests), followed by alternating sample-grid stand-in refine outside the gate. Exact global optimality is a goal when budget allows, not a requirement on every request. See #270 and design §4.3.3.

## Considered Options

- Nested per-combo continuous stand-in search — rejected (hung map GETs on dense games).
- Hard-capped full product as the permanent production solver — rejected (blocks richer discrete choice).
- Beam search as the primary discrete strategy — deferred; SA preferred for anytime behavior and simpler partial-bound story.
- Exposing SA cooling knobs in YAML — rejected; budget ms + solver selector only; cooling may be problem-size adaptive in code.
