# Design: Compute orchestrator

The **compute orchestrator** is the Core API's unified execution layer for turn analytics. It schedules work on a dependency graph, runs steps through declarative worker backends, coordinates caching and invalidation, and is the long-term uniform entry point for export ensure, table streams, table/map compute, BFF proxies, and future analytic MCP.

GitHub epic: [#190](https://github.com/SteveDraper/Planets-Console/issues/190).

Related:

- [ADR 0005](adr/0005-compute-orchestrator.md) -- locked architectural decisions
- [Analytic exports](design-analytic-exports.md) -- export catalogs, JSONPath, probe/query envelopes (orchestrator consumes `ENSURE_DEPENDENCIES`)
- [Analytics module structure](design-analytics-structure.md) -- layer roles and registration
- [ADR 0004 addendum: table-stream session framework](adr/0004-addendum-table-stream-session-framework.md) -- stream multiplex/connect (orchestrator replaces per-analytic worker pools only)
- [CONTEXT.md](../CONTEXT.md) -- glossary (**Compute scope**, **Compute orchestrator**, **Compute step**)

---

## Summary (human-readable model)

Think of the backend as two cooperating planes:

```text
┌─────────────────────────────────────────────────────────────────┐
│  ORCHESTRATION PLANE (main interpreter)                         │
│  • Accepts ComputeRequest(analytic, scope, step_kind, …)        │
│  • Walks ENSURE_DEPENDENCIES → DAG of compute scopes           │
│  • Singleflight + attach_inflight for duplicate requests         │
│  • Builds job wire from completed dependency outputs           │
│  • Submits ready steps to worker pools (priority bands)        │
│  • Re-checks invalidation epoch; calls analytic persist hooks  │
│  • Emits stream / ensure progress events                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │ JobWire → ResultWire (serializable)
┌───────────────────────────▼─────────────────────────────────────┐
│  COMPUTE PLANE (inline | thread | interpreter | process)         │
│  • Pure leaf functions: no ctx.query(), no blocking ensure       │
│  • Reads prefetched wire and/or storage_root (read-only)       │
│  • Returns result wire to orchestrator                         │
└─────────────────────────────────────────────────────────────────┘
```

**Compute scope** identifies one cacheable unit of work. It generalizes the earlier `(analytic, game, perspective, turn, player)` tuple:

- Some analytics omit axes (e.g. connections ignore `player_id`).
- Some add **parameters** (e.g. connection warp speed) fingerprinted into the scope key.

**Compute node** = one DAG vertex at a compute scope. **Compute step** = one schedulable pool unit *inside* a node (scores: one tier; fleet: one turn leg). A node may need several step continuations before it is **complete**.

**Dependencies** are never resolved by blocking inside a worker. The orchestrator completes ancestor nodes first, then passes their outputs explicitly on the dependent analytic's **job wire** (or lets the worker read the persisted artifact after the ancestor is terminal).

**Persistence** is conceptually a durable cache of `compute scope → result`, but **schema, write gates, merge, and invalidation** stay per analytic via registered **persistence policy** hooks. The orchestrator coordinates *when* to persist; analytics own *what* and *how*.

**North star:** all Core compute callers (export ensure, streams, table/map handlers, later BFF and MCP) submit through the same orchestrator. v1 migrates export-ensure and table-stream execution; routing batch `compute()` handlers is a follow-on phase.

---

## Goals

1. **Analytic-neutral scheduling** -- one DAG walker, one global worker pool, one singleflight model.
2. **True parallelism** -- cross-analytic and cross-player work shares cores; no pool starvation from blocking `ensure_export` inside workers.
3. **Declarative execution** -- backends (`inline`, `thread`, `interpreter`, `process`) and scope key axes declared on registration, not hardcoded in the orchestrator.
4. **Explicit dependency data** -- dependents receive ancestor outputs on job wire, not live `ctx.query()` in parallel workers.
5. **Uniform API trajectory** -- same `ComputeRequest` surface for ensure jobs, streams, and (later) table/map compute and MCP.

Non-goals (v1 / #190 epic):

- Separate worker service or containers.
- Rewiring every `TurnAnalyticService.compute()` handler (phase 2).
- BFF/MCP uniform proxy (phase 3).
- Connections parameter keying (ships with [#110](https://github.com/SteveDraper/Planets-Console/issues/110); mechanism defined here).

---

## Compute scope

```python
WILDCARD = "*"  # axis intentionally excluded from scope identity

@dataclass(frozen=True)
class ComputeScope:
    analytic_id: str
    game_id: int
    perspective: int | Literal["*"] = WILDCARD
    turn: int | Literal["*"] = WILDCARD
    player_id: int | Literal["*"] = WILDCARD
    parameters: tuple[tuple[str, str], ...] = ()  # canonical sorted fingerprint
```

| Concept | Meaning |
|---------|---------|
| **Concrete axis** | Integer (or analytic-specific value) participates in dedup, singleflight, persistence lookup |
| **WILDCARD** | Axis does not distinguish cache entries (not "missing required field") |
| **parameters** | Extra key material when analytic declares `parameter_fields` (connection options, etc.) |

Per-analytic **scope key spec** on registration:

```python
@dataclass(frozen=True)
class ScopeKeySpec:
    axes: tuple[Literal["perspective", "turn", "player_id"], ...]
    parameter_fields: tuple[str, ...] = ()
```

| Analytic (examples) | Key axes | Parameters |
|---------------------|----------|------------|
| scores, fleet | perspective, turn, player_id | -- |
| connections (future) | perspective, turn | connection option fields ([#110](https://github.com/SteveDraper/Planets-Console/issues/110)) |
| homeworld export branches | varies by path prefix | per export catalog |

`ExportScope` in [design-analytic-exports.md](design-analytic-exports.md) remains the export-query projection for row-scoped analytics; orchestrator normalization maps it to `ComputeScope`.

---

## Dependency graph

Provider-declared edges live on export catalogs today:

```python
ENSURE_DEPENDENCIES = (
    EnsureDependency(analytic_id="fleet", turn_delta=-1, player_id="same"),
)
```

The orchestrator builds a **DAG of compute scopes** from these edges (same walk as `walk_dependency_tree`, but execution is asynchronous and non-blocking).

| Rule | Detail |
|------|--------|
| **Cross-player** | No edges; batch callers fan out to N scopes |
| **Cross-turn unwind** | Gap turns `M..N` expand to forward-by-turn nodes (not one monolithic job) |
| **Shared read-only inputs** | e.g. `FleetTurnContext` from RST -- not graph edges; prefetch once per turn in wire builder |
| **Cycle** | Ensure-graph cycle → `ensure_cycle` (probe); resolution-stack cycle unchanged |

### Node and step granularity

| Level | Grain | Example |
|-------|-------|---------|
| **Compute node** | One DAG vertex at one scope | `scores@8,P`, `fleet@5,P` |
| **Compute step** | One pool submission inside a node | scores tier-1; fleet one turn leg |
| **Continuation** | Next step for same node after prior step completes | scores tier-2; invalidation retry leg |

Fleet gap-fill `M..N` for one player is **`2 × (N − M + 1)` nodes** (scores + fleet per turn), not one `FleetPlayerJob` chain on a single worker.

---

## Node lifecycle and singleflight

```text
waiting_deps → ready → running → complete | failed
                    ↘ attach_inflight (waiter; no pool worker)
```

| State | Meaning |
|-------|---------|
| **waiting_deps** | Ancestor nodes incomplete; not in ready queue |
| **ready** | Dependencies satisfied; eligible for pool |
| **running** | Leader step executing on a worker (or inline) |
| **attach_inflight** | Duplicate request joins leader; **no second pool worker** |
| **complete** | Node terminal (persisted / satisfied per analytic policy) |

**Hard invariant:** pool workers never call `ensure_export` or block on another node's completion.

---

## Execution backends

Declared per analytic on `AnalyticComputeProfile` (`ComputeStepSpec` per `step_kind`):

| Backend | Use | v1 default examples |
|---------|-----|-------------------|
| **inline** | Cheap, dependency-free work on orchestrator thread | cache probe, materialize-from-persistence, JSONPath projection |
| **thread** | In-process; shared memory for session state | scores tier steps (CP-SAT releases GIL) |
| **interpreter** | `InterpreterPoolExecutor` (Python 3.14); true multi-core without process overhead | fleet materialization leg |
| **process** | `ProcessPoolExecutor`; strongest isolation | prior-mining extraction (existing) |

Registry built at import; unknown `step_kind` or backend → `RuntimeError` at startup.

### Parallel worker contract

Interpreter/process steps:

- Receive **serializable `JobWire`** (orchestrator may prefetch `turn_wire`, `prior_ledger_wire`, dependency slices).
- May read storage via worker-local `StorageBackend(storage_root)` when wire omits large payloads (ancestor already **complete**).
- Return **`ResultWire`**; orchestrator persists after epoch re-check.
- **Never** hold `AnalyticQueryContext`, schedulers, or gap-fill coordinators.

Thread steps (scores tiers) may use session-bound state (`RowRun`) but still must not block on cross-node ensure.

### Job wire and dependency outputs

Wire builders run on the **orchestration plane** and may use `AnalyticQueryContext` to assemble inputs:

```python
def build_fleet_materialization_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
) -> FleetMaterializationJobWire:
    scores = dependency_outputs.require(
        analytic_id="scores",
        scope=scope.with_same_player(),
        paths=("$.solutions", "$.meta.searchStatus"),
    )
    return FleetMaterializationJobWire(..., scores_held_wire=scores)
```

Leaf step:

```python
def run_fleet_materialization_leg(job: FleetMaterializationJobWire) -> FleetLegResultWire:
    ...  # no ctx.query
```

This replaces in-worker `FleetInferenceMaterialization.held_inference_for_scoreboard_turn(...)` and stream-time `ensure_fleet_export` chains.

### Caching

| Layer | Mechanism |
|-------|-----------|
| **Orchestrator LRU** | Read-through turn cache on main interpreter |
| **Job wire prefetch** | Dependency outputs and turns already loaded included in wire |
| **Per-worker LRU** | Optional initializer cache for sequential legs on same worker |
| **Persistence** | Durable cache; analytic `PersistencePolicy` hooks |

Defer cross-worker shared mutable caches; prefetch-first is sufficient for v1.

---

## Scheduling

**One global worker pool** (configurable `COMPUTE_ORCHESTRATOR_WORKERS`; replaces per-analytic `*_SCHEDULER_WORKERS` over time).

**Priority bands** (high → low):

1. **Stream-attached** -- scope has active table-stream token (`TableStreamScopeGuard`).
2. **Interactive ensure** -- user-confirmed BFF export-ensure job ([#109](https://github.com/SteveDraper/Planets-Console/issues/109)).
3. **Background** -- export warm, dependency-only materialization.

**Within each band:**

| Analytic | Fairness rule |
|----------|---------------|
| scores | Tier-1 steps before continuation steps (port from `InferenceRowScheduler`) |
| fleet | Round-robin across distinct `(turn, player_id)` scopes |
| cross-analytic | Round-robin across ready steps at same band |

---

## Invalidation epochs

Fleet (and similar) expose per-player **invalidation generation** today. Orchestrator generalizes:

| Checkpoint | Action |
|------------|--------|
| **Submit** | Record `generation_at_submit` |
| **Complete** | If `generation != generation_at_submit`, discard result and re-queue node |
| **Persist** | Orchestrator calls analytic `persist` hook only after epoch check |

Same semantics as gap-fill coordinator leader/waiter retry, applied to all node kinds.

---

## Persistence ownership

| Owner | Responsibility |
|-------|----------------|
| **Orchestrator** | When to compute; singleflight; epoch gates; invoke persist hook |
| **Analytic** (`PersistencePolicy` on registration) | Record shape; write gates; merge (e.g. homeworld user-asserted); invalidation rules |

Storage paths remain per [ADR 0002](adr/0002-analytic-persistence.md). Orchestrator is cache **coordinator**, not cache **schema** owner.

---

## Registration surface

Extend `TurnAnalyticRegistration`:

| Field | Purpose |
|-------|---------|
| `scope_key_spec` | Which axes and parameters form compute identity |
| `compute_profile` | `ComputeStepSpec` list (step_kind, backend) |
| `persistence_policy` | satisfied / persist / invalidate hooks |
| `build_step_job_wire` | Per step_kind: scope + dependency outputs → JobWire |
| `run_step` | Per step_kind: JobWire → ResultWire (or reference to leaf function) |

Export catalog (`ENSURE_DEPENDENCIES`, materializers) stays on `export_catalog`; orchestrator reads it for the DAG.

---

## Relationship to table streams ([#175](https://github.com/SteveDraper/Planets-Console/issues/175))

**Keep** under `packages/api/api/streaming/table_stream/`:

- Multiplex, connect `finally` teardown, `TableStreamScopeGuard`, controller base, registry attach/detach.

**Replace:**

- `InferenceRowScheduler` and `FleetTableStreamScheduler` worker dequeue loops.

**Thin adapters:**

- Stream controllers submit compute steps / continuations to orchestrator and map completion to wire events.

---

## Callers and migration phases

| Phase | Callers routed through orchestrator |
|-------|-------------------------------------|
| **v1 (#190 epic)** | Export ensure materialization; fleet/scores table-stream steps; internal wire builders for `ctx.query` |
| **Phase 2** | `TurnAnalyticService.get_turn_analytics` batch compute |
| **Phase 3** | BFF uniform proxy; analytic MCP `query_compute` |

Until phase 2, table/map REST responses may still call `compute()` handlers directly; export ensure and streams migrate first.

---

## Package layout (target)

```text
packages/api/api/compute/
  scope.py           # ComputeScope, ScopeKeySpec, normalization
  profile.py         # AnalyticComputeProfile, ComputeStepSpec
  orchestrator.py    # DAG, singleflight, submit, complete
  pools.py           # Global pool, priority dequeue, backend dispatch
  wire.py            # DependencyOutputs, base JobWire/ResultWire types
  registry.py        # Built from TurnAnalyticRegistration at import
```

Existing `export_dependency_walk.py` remains the canonical ENSURE_DEPENDENCIES walk; orchestrator calls it for planning.

---

## Implementation slices

Tracked under [#190](https://github.com/SteveDraper/Planets-Console/issues/190):

| Slice | Issue | Deliverable |
|-------|-------|-------------|
| Foundation | [#195](https://github.com/SteveDraper/Planets-Console/issues/195) | `ComputeScope`, profiles, registry validation |
| Core scheduler | [#196](https://github.com/SteveDraper/Planets-Console/issues/196) | DAG gating, singleflight, `attach_inflight`, inline backend |
| Worker pools | [#197](https://github.com/SteveDraper/Planets-Console/issues/197) | Global pool, priority bands, four backends |
| Job wire + epochs | [#198](https://github.com/SteveDraper/Planets-Console/issues/198) | Wire builders, `DependencyOutputs`, invalidation re-check, persist coordination |
| Fleet migration | [#199](https://github.com/SteveDraper/Planets-Console/issues/199) | Fleet leg steps; retire `FleetTableStreamScheduler` workers |
| Scores migration | [#200](https://github.com/SteveDraper/Planets-Console/issues/200) | Tier steps; retire `InferenceRowScheduler` workers |
| Turn cache | [#201](https://github.com/SteveDraper/Planets-Console/issues/201) | Orchestrator LRU + prefetch into job wire |
| Phase 2 | [#202](https://github.com/SteveDraper/Planets-Console/issues/202) | Route table/map `compute()` through orchestrator |
| Phase 3 | [#203](https://github.com/SteveDraper/Planets-Console/issues/203) | BFF / MCP uniform compute API |

---

## Testing

- Unit: scope normalization, WILDCARD keys, priority dequeue, epoch discard, dependency gating (no worker without deps).
- Integration: fixture analytics with mutual dependencies; fleet+scores cold gap-fill parallelism; attach_inflight does not double pool workers.
- Regression: existing `test_export_dependency_walk`, `test_gap_fill_coordinator`, scheduler fairness tests ported to orchestrator.
