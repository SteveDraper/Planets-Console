# Compute orchestrator

Status: accepted

## Context

Turn analytics today mix three execution patterns: synchronous export ensure walks, per-analytic thread schedulers (`InferenceRowScheduler`, `FleetTableStreamScheduler`), and a process pool for offline prior mining. Dependency graphs are analytic-neutral (`walk_dependency_tree`, `ENSURE_DEPENDENCIES`), but workers block on cross-analytic `ensure_export`, pool starvation is possible, and parallelism does not span analytics. [#190](https://github.com/SteveDraper/Planets-Console/issues/190) design discussion locked a unified model.

## Decision

Introduce a **compute orchestrator** in Core API as the long-term uniform compute entry point. See [design-compute-orchestrator.md](../design-compute-orchestrator.md) for full specification.

Locked choices:

1. **Two planes** -- orchestration (DAG, singleflight, wire build, persist coordination) vs compute leaf steps (`JobWire` → `ResultWire`). Parallel workers never call `ctx.query()` or blocking ensure.
2. **`ComputeScope`** -- generalized identity with per-analytic `ScopeKeySpec`, `WILDCARD` axes, and optional `parameters` fingerprint (connections [#110](https://github.com/SteveDraper/Planets-Console/issues/110) later).
3. **Node vs step** -- DAG vertex = compute node; pool job = analytic-declared step with continuations until node complete. Gap-fill is many nodes, not one monolithic fleet job.
4. **Singleflight** -- explicit `attach_inflight` state; one pool worker per scope key; waiters share leader outcome.
5. **Scheduling** -- one global pool; priority bands (stream-attached, interactive ensure, background); scores tier-1-before-continuations fairness inside bands.
6. **Backends** -- declarative per `step_kind` on registration: `inline | thread | interpreter | process`. Fleet materialization leg defaults to `interpreter`; scores tier to `thread`; not hardcoded in orchestrator.
7. **Dependencies** -- orchestrator completes ancestors first; wire builders pass `DependencyOutputs` on job wire; storage read fallback only for terminal ancestor artifacts.
8. **Persistence** -- orchestrator coordinates timing and epochs; analytic `PersistencePolicy` owns schema, write gates, merge, invalidation (ADR 0002 paths unchanged).
9. **Table streams** -- keep [#175](https://github.com/SteveDraper/Planets-Console/issues/175) session framework; replace per-analytic scheduler worker pools with orchestrator adapters.
10. **Phased rollout** -- v1: export ensure + stream steps; phase 2: batch `compute()`; phase 3: BFF/MCP uniform API.

## Consequences

- New `packages/api/api/compute/` package; extend `TurnAnalyticRegistration` with scope profile, compute profile, persistence policy, wire builders.
- `design-analytic-exports.md` compute-graph detail defers to design-compute-orchestrator.md.
- Environment: global `COMPUTE_ORCHESTRATOR_WORKERS` supersedes per-analytic worker env vars over migration.
- Python 3.14 `InterpreterPoolExecutor` is the preferred parallel backend for fleet legs; `ProcessPoolExecutor` remains for extraction and opt-in CPU-bound steps.
- Implementation slices: GitHub [#195](https://github.com/SteveDraper/Planets-Console/issues/195)–[#203](https://github.com/SteveDraper/Planets-Console/issues/203) under epic [#190](https://github.com/SteveDraper/Planets-Console/issues/190).
