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
4. **Singleflight** -- explicit `attach_inflight` state; one pool worker per scope key; waiters share leader outcome. Same-scope dedupe is in-orchestrator only (no separate process-wide scope lease across multiple orchestrator DAGs).
5. **Scheduling** -- one global pool; priority bands (stream-attached, interactive ensure, background); scores tier-1-before-continuations fairness inside bands. Higher-priority attach may **adopt** band on an in-flight node before expensive execution starts.
6. **Backends** -- declarative per `step_kind` on registration: `inline | thread | interpreter | process`. Fleet materialization leg defaults to `interpreter`; scores tier to `thread`; not hardcoded in orchestrator.
7. **Dependencies** -- orchestrator completes ancestors first; wire builders pass `DependencyOutputs` on job wire; storage read fallback only for terminal ancestor artifacts.
8. **Persistence** -- orchestrator coordinates timing and epochs; analytic `PersistencePolicy` owns schema, write gates, merge, invalidation (ADR 0002 paths unchanged). `persist` runs only when step outcome is `persist`; `complete` and `park` omit persist (e.g. scores `stopped`, soft non-durable terminals).
9. **Step outcome** -- every `run_step` result declares `continue`, `persist`, `complete`, or `park`. Repeatable step kinds (scores `tier_solve`) use `continue` until terminal; `park` demotes the node to `parked` without promoting dependents (scores soft terminals; wake is analytic-owned -- see [ADR 0006](0006-table-stream-lifecycle-invariants.md) §5). `step_index` counts within-node executions for pool fairness.
10. **Compute request entry step** -- `ComputeRequest.step_kind` selects profile entry (e.g. scores `materialize` for export ensure, `tier_solve` for inference stream).
11. **Process-wide singleton** -- one `ComputeOrchestrator` per process. Callers submit `ComputeRequest`s with a per-node **orchestration bundle** (leader-retained `export_services` / ensure-memo ownership); perspective-visible turn loading is shell/`(game_id, perspective)`-scoped. Table streams keep [#175](https://github.com/SteveDraper/Planets-Console/issues/175) session framework and register process-wide observers/gates on the singleton (unregister on disconnect); they do not own an orchestrator instance. `PersistencePolicy.persist` owns durable writes; admission reads persistence directly. Fleet ([#199](https://github.com/SteveDraper/Planets-Console/issues/199)) and scores ([#200](https://github.com/SteveDraper/Planets-Console/issues/200)) remain reference stream adapters; singleton migration is [#209](https://github.com/SteveDraper/Planets-Console/issues/209). Table-stream cancel/drain/persist/wake ownership invariants: [ADR 0006](0006-table-stream-lifecycle-invariants.md).
12. **Phased rollout** -- v1: export ensure + stream steps; phase 2: batch `compute()`; phase 3: BFF/MCP uniform API.

## Amendment ([#209](https://github.com/SteveDraper/Planets-Console/issues/209))

Supersedes the earlier “per-stream orchestrator binding” parity wording. The bridge of one orchestrator per `AnalyticQueryContext` (plus process-wide scope lease [#222](https://github.com/SteveDraper/Planets-Console/issues/222)) is retired in favor of the singleton above. Follow-ons: process/shell-scoped export services ([#239](https://github.com/SteveDraper/Planets-Console/issues/239)); origin-set prune-on-close ([#240](https://github.com/SteveDraper/Planets-Console/issues/240)).

## Consequences

- New `packages/api/api/compute/` package; extend `TurnAnalyticRegistration` with scope profile, compute profile, persistence policy, wire builders.
- `design-analytic-exports.md` compute-graph detail defers to design-compute-orchestrator.md.
- Environment: global `COMPUTE_ORCHESTRATOR_WORKERS` supersedes per-analytic worker env vars over migration.
- Python 3.14 `InterpreterPoolExecutor` is the preferred parallel backend for fleet legs; `ProcessPoolExecutor` remains for extraction and opt-in CPU-bound steps.
- Implementation slices: GitHub [#195](https://github.com/SteveDraper/Planets-Console/issues/195)–[#203](https://github.com/SteveDraper/Planets-Console/issues/203), plus [#209](https://github.com/SteveDraper/Planets-Console/issues/209) / [#239](https://github.com/SteveDraper/Planets-Console/issues/239) / [#240](https://github.com/SteveDraper/Planets-Console/issues/240), under epic [#190](https://github.com/SteveDraper/Planets-Console/issues/190).
