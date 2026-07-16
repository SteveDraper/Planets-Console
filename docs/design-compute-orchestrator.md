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

**North star:** all Core compute callers (export ensure, streams, table/map handlers, later BFF and MCP) submit through the **same process-wide** orchestrator. There is one scheduler and one DAG per process -- not one orchestrator per stream or **analytic query context**. v1 migrates export-ensure and table-stream execution; routing batch `compute()` handlers is a follow-on phase. Singleton migration: [#209](https://github.com/SteveDraper/Planets-Console/issues/209).

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
| **Continuation** | Next pool submission for the **same** node after prior step completes | scores tier *n+1* (repeatable `step_kind`); invalidation retry leg |

Repeatable step kinds (scores `tier_solve`): the orchestrator re-queues the **same** `step_kind` until the result wire signals a terminal outcome. `step_index` on the node counts executions within that node (`0` = tier-1, `>0` = continuations) for pool fairness -- it is **not** an index into a fixed multi-entry profile when ladder length is dynamic.

Fleet gap-fill `M..N` for one player is **`2 × (N − M + 1)` nodes** (scores + fleet per turn), not one `FleetPlayerJob` chain on a single worker.

DAG **vertices** are registered on first `submit` for a scope chain; **pool work** is dependency-gated and dispatched incrementally (only `ready` nodes are submitted; dependents promote when ancestors complete).

---

## Compute step outcome

Every `run_step` result wire carries an explicit **step outcome** the orchestrator interprets:

| Outcome | Orchestrator action |
|---------|---------------------|
| **`continue`** | Increment `step_index`; re-queue the same `step_kind` for the same node |
| **`persist`** | After epoch re-check, call analytic `PersistencePolicy.persist`, then mark node `complete` |
| **`complete`** | Mark node `complete` **without** calling `persist` |

Analytics own **what** `persist` writes and **how readers** gate on terminal quality. Examples:

- **Fleet** -- `persist` on every materialization leg; `provenance.is_final` distinguishes gap-fill intermediates from ensure-satisfied finals. Readers use `has_final_ledger` / `is_fleet_export_ensure_satisfied`, not raw `has_ledger`, where terminal quality matters.
- **Scores inference** -- `persist` only for terminal `exact` / `no_exact_solution`; `stopped` uses `complete` without persist. Ladder state between tiers stays in the stream adapter (`RowRun`), not on the wire.

Fleet and scores share the orchestrator contract; persistence semantics differ by domain.

---

## Compute request entry step

`ComputeRequest` may name an entry `step_kind` so one registration profile serves multiple callers on the same scope. Example scores profile: `(materialize, tier_solve)`.

- **Export ensure / DAG satisfaction** -- submit from profile step 0 (`materialize`, inline).
- **Inference table stream** -- submit with `step_kind="tier_solve"` and `priority_band="stream_attached"`.

The orchestrator honors the entry step when creating or attaching to a node.

---

## Process-wide singleton ([#209](https://github.com/SteveDraper/Planets-Console/issues/209))

One `ComputeOrchestrator` per process. Callers submit `ComputeRequest`s; they do not own an orchestrator instance.

### Orchestration bundle (context-on-request)

The orchestrator is **not** constructed with a bound `AnalyticQueryContext`. Orchestration-plane work (DAG plan helpers, job-wire builders, `is_satisfied`, `persist`, `invalidation_generation`) uses a per-node **orchestration bundle** retained from the submitting **leader**:

| Retained on the node | Not sticky per caller |
|----------------------|------------------------|
| Analytic `export_services` injections | Perspective-visible **`load_turn`** -- keyed by `(game_id, perspective)` / shell |
| Ensure-memo ownership for orchestration-plane ensure/materialize | Full request-local query-context memo for stream admission / listeners |

Stream teardown unregisters observers only; **in-flight nodes keep their bundle until terminal**. Interest-set prune-on-close is a follow-on ([#240](https://github.com/SteveDraper/Planets-Console/issues/240)). Process/shell-scoped export services (no per-node service bag) is a follow-on ([#239](https://github.com/SteveDraper/Planets-Console/issues/239)).

### Turn cache

Orchestration-plane turn cache is process-wide and keyed by `(game_id, perspective, turn)`.

### Fleet persist correlation

Fleet ledger persist notifications must **not** use `id(AnalyticQueryContext)` as causal origin. In-DAG completion correlates via **compute scope** and materialization/generation identity (leaf compute treated as deterministic for a given job wire).

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

Same-scope dedupe is **only** in-orchestrator singleflight on the singleton DAG. The former process-wide scope lease / `parked` state ([#222](https://github.com/SteveDraper/Planets-Console/issues/222)) is **retired** by [#209](https://github.com/SteveDraper/Planets-Console/issues/209) -- it compensated for multiple per-context orchestrator DAGs.

### Priority adopt on attach

When a higher-priority `ComputeRequest` attaches to an in-flight node (e.g. `stream_attached` joining `background` warm) and the node is not yet past the point where adopt is allowed (not mid expensive inline/pool execution -- same rule as the former lease “seal”), upgrade `node.priority_band` and adjust ready-queue ordering as needed. No mid-run preempt once expensive work has started.

**Scores `tier_solve` empty complete:** the skip sentinel (`runId: null`, `evidenceClosed: true`) is allowed only when turn evidence is already closed under the **same materialization probe fleet uses** (no ensure-ephemeral). Cheap ImmediateRowAdmission ensure admits write fallback-complete inference rows to disk so that probe can close; a missing `RowRun` while evidence is still open must `continue` (rebuild wire / re-ensure), not empty-complete -- that falsely unlocked same-turn fleet and left the scoreboard without `rowComplete`.

### Terminal reuse and `force_fresh`

`ComputeRequest.force_fresh` controls whether a duplicate submission for an already-terminal scope starts new work or reuses the cached node outcome.

| `force_fresh` | Existing node state | Behavior |
|---------------|---------------------|----------|
| `False` (default) | `complete` or `failed` | Attach to the terminal node; return its cached `result_wire` or error. No new pool work. |
| `False` (default) | `waiting_deps`, `ready`, `running` | Singleflight: attach as waiter (`attach_inflight`) or join the leader; no second worker. May **priority-adopt** (see above). |
| `True` | `complete` or `failed` | **Supersede** the terminal node: remove it from the orchestrator map, clear any waiters, re-plan the DAG from the request's entry `step_kind`, and dispatch fresh work. |
| `True` | non-terminal | Same as default -- singleflight preserved; in-flight work is never superseded. |

Default behavior treats terminal nodes as a **cache hit**: repeat callers for the same normalized `ComputeScope` get the prior outcome without re-execution. Opt-in `force_fresh=True` is the generic lifecycle primitive for callers that need a new run after terminal completion or failure (for example scores inference stream reschedule paths that must re-enter `tier_solve` on an already-failed or completed scope).

Supersession clears orchestrator node state only; analytic persistence invalidation and reader gates remain the analytic's responsibility.

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
- Return **`ResultWire`** with an explicit **step outcome** (`continue`, `persist`, or `complete`); see [Compute step outcome](#compute-step-outcome).
- **Never** hold `AnalyticQueryContext`, schedulers, or gap-fill coordinators.

Thread steps (scores tiers) resolve per-row adapter state (`RowRun`) by `run_id` on the job wire; ladder progress stays adapter-owned between continuations. They must not block on cross-node ensure or call `ensure_fleet_export` in the worker.

### Job wire and dependency outputs

Wire builders run on the **orchestration plane** and may use the node's orchestration bundle (`export_services`, ensure-memo, shell-scoped `load_turn`) to assemble inputs:

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

#### Scores prior-turn fleet overlay (inference stream)

Scores `ENSURE_DEPENDENCIES` already declare `fleet@(host_turn - 1, same player)`. For inference stream `tier_solve` wire build:

1. **No `ensure_fleet_export` inside workers or tier steps.**
2. **Pending-first, then refresh** -- first `tier_solve` wire may use `fleetTorpInputStatus: pending` when `fleet@(host_turn - 1)` is not yet terminal; when that fleet node completes, fleet invalidation bumps scores epoch, drops inference row persistence, and reschedules the open-stream row so later wires read overlay from `DependencyOutputs`.
3. **Stream open** submits orchestrator `background`-band `fleet@(host_turn - 1)` per player (replaces ad-hoc warm threads).
4. **Readers** of prior-turn fleet for overlay must use `has_final_ledger`, not `has_ledger` ([#200](https://github.com/SteveDraper/Planets-Console/issues/200) fixes `prior_turn_fleet_torp_overlay`).

---

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
| **Persist** | Orchestrator calls analytic `persist` hook only after epoch check and only when step outcome is `persist` |

Same semantics as gap-fill coordinator epoch abort ([#233](https://github.com/SteveDraper/Planets-Console/issues/233)): mid-chain generation bumps exit the leg (`FleetGapFillEpochInvalidated`) instead of spinning sync rematerializations; orchestrator / stream reschedule / later ensure re-queues when the epoch advances or scores turn-evidence closes. Scores `invalidation_generation` aligns with per-player fleet epoch so in-flight `tier_solve` work is discarded when `fleet@(host_turn - 1)` lands; `InferenceInvalidationService` still deletes inference row persistence and reschedules the open-stream row.

---

## Persistence ownership

| Owner | Responsibility |
|-------|----------------|
| **Orchestrator** | When to compute; singleflight; epoch gates; invoke `persist` only on `persist` outcome; handle analytic-agnostic `PersistDeferredError` (park `waiting_deps` + optional dependency `force_fresh`) |
| **Analytic** (`PersistencePolicy` on registration) | Record shape; write gates; merge (e.g. homeworld user-asserted); invalidation rules; terminal-quality metadata on stored artifacts; map write-gate refuses to `PersistDeferredError` + `PersistDependencyRecovery` when rematerialization must wait on a dependency |

Storage paths remain per [ADR 0002](adr/0002-analytic-persistence.md). Orchestrator is cache **coordinator**, not cache **schema** owner.

### Table-stream terminal persistence (fleet-aligned template)

All table-stream analytics follow the same adapter template ([#199](https://github.com/SteveDraper/Planets-Console/issues/199) fleet, [#200](https://github.com/SteveDraper/Planets-Console/issues/200) scores):

| Concern | Owner |
|---------|--------|
| Per-stream `ComputeOrchestrator` binding | Stream adapter (one orchestrator per stream token; released on disconnect) |
| Durable terminal write | `PersistencePolicy.persist` on `persist` outcome |
| NDJSON wire events | Adapter `register_node_complete_listener` (and mid-step callbacks for incremental events) |
| Cache replay at admission | Probe persistence directly (`has_final_ledger`, inference row store, etc.) |

Do not use adapter `on_row_complete` callbacks for durable persistence once migrated.

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

**Thin adapters** (same template for fleet and scores):

- Submit `ComputeRequest` scopes to the **process-wide** orchestrator (`stream_attached` band for interactive work; `background` for warm-up deps).
- Register process-wide `node_complete` / related listeners (and pause **dispatch gates**) with analytic/scope filters; unregister on disconnect. Adapters do **not** own an orchestrator instance.
- Retain stream-only state (scope guard, per-row run registry, global pause gate).
- **Do not** own durable persistence -- that is `PersistencePolicy.persist`.
- Stream teardown does not cancel in-flight singleton DAG work solely because the observer left ([#209](https://github.com/SteveDraper/Planets-Console/issues/209)); origin-set prune is [#240](https://github.com/SteveDraper/Planets-Console/issues/240).

**Inference global pause** (scores): soft freeze via a **dispatch gate** -- orchestrator checks adapter pause state before submitting `stream_attached` `tier_solve` to the pool. In-flight tier steps finish; deferred continuations stay in adapter held buffer. Background fleet warm and gap-fill legs are not paused.

**Replaced (#199, #200, #209):**

- Legacy `InferenceRowScheduler` and `FleetTableStreamScheduler` private worker dequeue loops (`_worker_loop`, `_work_queue`). Both are thin orchestrator stream adapters; tier and fleet leg work submits through the global compute pool.
- Per-stream / per-`AnalyticQueryContext` orchestrator instances and the process-wide scope lease that papered over them.

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
  orchestration_bundle.py  # Leader-retained export_services + ensure-memo (#209)
  scope_terminal_fanout.py  # Process-wide terminal notify for stream adapters
  profile.py         # AnalyticComputeProfile, ComputeStepSpec
  orchestrator.py    # DAG, singleflight, submit, complete (process-wide singleton)
  turn_cache.py      # Process-wide LRU keyed by (game_id, perspective, turn)
  pools.py           # Global pool, priority dequeue, backend dispatch
  wire.py            # DependencyOutputs, base JobWire/ResultWire types
  registry.py        # Built from TurnAnalyticRegistration at import
  runtime.py         # get_compute_orchestrator singleton wiring
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
| Fleet migration | [#199](https://github.com/SteveDraper/Planets-Console/issues/199) | Fleet leg steps; delete `FleetTableStreamScheduler` worker pool |
| Scores migration | [#200](https://github.com/SteveDraper/Planets-Console/issues/200) | Tier steps; orchestrator primitives; delete `InferenceRowScheduler` worker pool; fleet overlay + `has_final_ledger` fix |
| Export ensure migration | [#204](https://github.com/SteveDraper/Planets-Console/issues/204) | Ensure/gap-fill via orchestrator; retire coordinator + blocking ensure |
| Turn cache | [#201](https://github.com/SteveDraper/Planets-Console/issues/201) | Orchestrator LRU + prefetch into job wire |
| Singleton orchestrator | [#209](https://github.com/SteveDraper/Planets-Console/issues/209) | Process-wide orchestrator; retire per-ctx bindings + scope lease; observer registry |
| Process-scoped export services | [#239](https://github.com/SteveDraper/Planets-Console/issues/239) | Retire per-node sticky `export_services` bags |
| Origin-set prune | [#240](https://github.com/SteveDraper/Planets-Console/issues/240) | Interest tracking; cancel when no origins remain |
| Phase 2 | [#202](https://github.com/SteveDraper/Planets-Console/issues/202) | Route table/map `compute()` through orchestrator |
| Phase 3 | [#203](https://github.com/SteveDraper/Planets-Console/issues/203) | BFF / MCP uniform compute API |

---

## Testing

- Unit: scope normalization, WILDCARD keys, priority dequeue, epoch discard, dependency gating (no worker without deps).
- Integration: fixture analytics with mutual dependencies; fleet+scores cold gap-fill parallelism; attach_inflight does not double pool workers.
- Regression: existing `test_export_dependency_walk`, `test_gap_fill_coordinator`, scheduler fairness tests ported to orchestrator.
