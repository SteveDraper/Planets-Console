# Design: Compute orchestrator

The **compute orchestrator** is the Core API's unified execution layer for turn analytics. It schedules work on a dependency graph, runs steps through declarative worker backends, coordinates caching and invalidation, and is the long-term uniform entry point for export ensure, table streams, table/map compute, BFF proxies, and future analytic MCP.

GitHub epic: [#190](https://github.com/SteveDraper/Planets-Console/issues/190).

Related:

- [ADR 0005](adr/0005-compute-orchestrator.md) -- locked architectural decisions
- [ADR 0006](adr/0006-table-stream-lifecycle-invariants.md) -- anti-thrash table-stream lifecycle invariants (cancel / drain / persist / wake)
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

**North star:** all Core compute callers (export ensure, streams, table/map handlers, later BFF HTTP, **MCP** hatch ensure) submit through the **same process-wide** orchestrator. There is one scheduler and one DAG per process -- not one orchestrator per stream or **analytic query context**. MCP never exposes `ComputeRequest`; it calls Core **analytic export ensure** in-process ([How this MCP product relates to orchestrator phase 3](https://github.com/SteveDraper/Planets-Console/issues/320)). v1 migrates export-ensure and table-stream execution; routing batch `compute()` handlers is [#202](https://github.com/SteveDraper/Planets-Console/issues/202). Singleton migration: [#209](https://github.com/SteveDraper/Planets-Console/issues/209).

---

## Goals

1. **Analytic-neutral scheduling** -- one DAG walker, one global worker pool, one singleflight model.
2. **True parallelism** -- cross-analytic and cross-player work shares cores; no pool starvation from blocking `ensure_export` inside workers.
3. **Declarative execution** -- backends (`inline`, `thread`, `interpreter`, `process`) and scope key axes declared on registration, not hardcoded in the orchestrator.
4. **Explicit dependency data** -- dependents receive ancestor outputs on job wire, not live `ctx.query()` in parallel workers.
5. **Uniform API trajectory** -- same `ComputeRequest` surface for ensure jobs, streams, and (later) table/map compute and BFF HTTP. The **MCP adapter** is an in-process Core caller of **analytic export ensure**, not a `ComputeRequest` API ([How this MCP product relates to orchestrator phase 3](https://github.com/SteveDraper/Planets-Console/issues/320)).

Non-goals (v1 / #190 epic):

- Separate worker service or containers.
- BFF uniform HTTP proxy (phase 3).
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
| **Cross-player** | Default: no edges; batch callers fan out to N scopes. ``EnsureDependency.player_id="all"`` expands to one scope per roster player at the dependency turn. The homeworld locator does not declare a fleet edge; it reads on-disk ledgers, stores a **fleet-age input stamp** on each aggregate, and relies on a durable **fleet-age stale marker** for staleness ([Homeworld locator reading a non-final fleet ledger](https://github.com/SteveDraper/Planets-Console/issues/615)). |
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
| **`persist`** | After epoch re-check, call analytic `PersistencePolicy.persist`; when `persist_then_continue` is set, increment `step_index` instead of completing (fleet observation → finalization). Otherwise mark node `complete`. |
| **`complete`** | Mark node `complete` **without** calling `persist` |
| **`park`** | (Generic orchestrator machinery; scores production path retired.) Demote node to `parked` until an explicit `force_fresh` wake. |

Analytics own **what** `persist` writes and **how readers** gate on terminal quality. Examples:

- **Fleet** -- two-step profile: `observation_leg` writes an **approximate fleet** (full prior ledger plus this turn's sightings; `turnEvidenceAtN` stays false; no ensure-final side channel). `finalization_leg` replaces that file once same-turn scores are terminal. A non-terminal scoreboard row leaves the approximate file in place. `EnsureDependency.quality` distinguishes observation (`has_ledger`) vs final (`has_final_ledger`). ENSURE catalog lists only prior-turn fleet `quality="final"`; same-turn scores couples on finalization via `PersistDeferredError`, not ENSURE.
- **Scores inference** -- `persist` for durable turn-evidence row statuses. Every status a tier terminal can carry is durable (`DURABLE_TURN_EVIDENCE_ROW_STATUSES`; a test pins every `STATUS_*` constant to it), and a tier job ends only in `TierJobContinue` or `TierJobRowComplete`, so there is no empty outcome. A terminal whose status is not durable breaks that contract: the step raises `ScoresTierOutcomeError` and the node fails, releasing its waiters and cascading to dependents such as same-turn fleet finalization; a later `force_fresh` replaces it. Evidence-closed skip may still `complete` without persist.

**Scores has no soft wait.** A `tier_solve` step whose claimed RowRun was retired
before the step ran (a peer claim, a cancel landing before its abort, a scheduler
clear) returns `continue`. The re-queued step builds its wire again, and wire
build re-claims a run, admits one, emits the evidence-closed skip, or raises the
"no attachable RowRun" invariant error, so the node always moves on with nothing
having to wake it. A step cannot return `waiting_deps`: the only way a node
defers onto a dependency is `PersistDeferredError` from `persist`. The scores
stream reschedule is a plain `force_fresh` `tier_solve` submit.

Ensure edges may carry `EnsureDependency.quality` (`observation` | `final`, default
`final`). Scores declares `fleet@(N-1, quality=final)` so belief-ready prior fleet
satisfies ENSURE before tier work starts.

**Scores `tier_solve` wire invariant:** when ensure is satisfied and turn evidence is
still open, wire build must attach a `runId` (tier registry or successful scheduler
adopt) or emit the evidence-closed skip sentinel. A bare `{runId: null}` open-evidence
wait wire is forbidden.

Fleet finalization refuses persist while same-turn scores evidence is open
(`PersistDeferredError` on scores `tier_solve`). The orchestrator demotes fleet to
`waiting_deps` and recreates scores from `tier_solve` -- the sole reopen mechanism for this case.

---

## Compute request entry step

`ComputeRequest` may name an entry `step_kind` so one registration profile serves multiple callers on the same scope. Example scores profile: `(materialize, tier_solve)`.

- **Export ensure / DAG satisfaction** -- submit from profile step 0 (`materialize`, inline).
- **Inference table stream** -- submit with `step_kind="tier_solve"`. The request asks for no band: the live stream watching the shell gives the node `stream_attached` (see [Band derivation](#band-derivation)).

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

One **TurnInfo LRU per process**, keyed by `(game_id, perspective, turn)`. Scores and storage `TurnInfo` loads (`TurnLoadService.get_turn_info`) share that cache. The fleet observation job does not carry a turn, so fleet legs do not fill this cache from the job wire. Parent orchestrator `ctx.load_turn` splice uses the same type and key; worker heaps are separate (no cross-process shared memory). This is **not** a `StorageBackend` document cache -- storage stays `JSONValue` only. The file backend may keep a distinct bounded LRU of admitted breakpoint JSON (`packages/api/api/storage/document_lru.py`); that cache does not hold `TurnInfo` and does not admit turn RST. Put the written `TurnInfo` after a turn document write; drop the key only when the writer has JSON and no `TurnInfo`. `turn_cache.clear` on orchestrator shutdown still applies. Interpreter pools call `init_worker_turn_cache`; SAT-session children never import the cache.

### Fleet persist correlation

Fleet ledger persist notifications must **not** use `id(AnalyticQueryContext)` as causal origin. In-DAG completion correlates via **compute scope** and materialization/generation identity (leaf compute treated as deterministic for a given job wire).

---

## Node lifecycle and singleflight

```text
waiting_deps → ready → running → complete | failed
                    ↘ attach_inflight (waiter; no pool worker)
running → ready | waiting_deps | failed   (requeue: epoch retry, continue)
running → waiting_deps | failed          (persist-deferred: never promoted; waits for the recreation of a superseded dependency)
running → parked   (soft park; wake only on force_fresh → ready | waiting_deps | failed)
```

**Readiness on re-entry.** A `running` or `parked` node takes no dependency-terminal refresh, so a dependency can fail without reaching it. Every path that returns such a node to dispatch (epoch retry, `continue`, parked wake) resolves its readiness (`_resolve_readiness`) instead of writing the next state: a dependency failure that cascades fails the node, exactly as it would a waiting node (an abort-failed dependency, `ComputeScopeAbortedError`, leaves it `waiting_deps`); otherwise it is `ready` when every dependency is complete, else `waiting_deps`. Dependency sweeps (`_refresh_node_readiness`) apply the same resolution to `waiting_deps` and `ready` nodes only. The dispatch pick refreshes a `ready` node whose dependencies are incomplete rather than demoting it by hand, as a backstop for that invariant. The persist-deferred demotion applies only the cascade (`_fail_on_failed_dependency`) and otherwise writes `waiting_deps`: it must not promote the node in the hold where the analytic asked it to wait. A persist-deferred recovery always recreates its dependency: it is a `force_fresh` submit entering at the recovery's named `step_kind`, which forces the dependency's root so a dependency already satisfied on disk is re-run. The step kind must be in the dependency's compute profile and the dependency analytic must be walkable (a non-empty export catalog); otherwise the node fails at demotion with `InvalidPersistDependencyRecoveryError`, before the graft, with no `persist_deferred` event and no dependency submit. Persist-deferred grafts its recovery dependency, then, before the cascade check, records the deferral on the node as `ComputeNodeRun.last_persist_deferral` (a `PersistDeferral`: the dependency scope, the node's invalidation generation, and the dependency execution it is replacing). Its `superseded` (read as `ComputeNodeRun.superseded_dependency`) is that node's `ExecutionRef` when the dependency is terminal (`complete` or `failed`), else None (an absent dependency already reads incomplete; a live one is what the `force_fresh` submit attaches to and the node waits on). Readiness reads every dependency through one lookup, `_readiness_dependency`, which treats the superseded execution as not there; the cascade check (`_failed_dependency_error`), the completeness check (`_deps_complete`, used by `_resolve_readiness` and the dispatch pick) and the recreate-aborted walk all use it. So between the demotion and the recreation's registration, a refresh that reaches the node (the plan refresh of an unrelated submission, a dependency-terminal callback, a `force_fresh` attach) neither cascades the superseded failure nor promotes the node on a superseded `complete` dependency, and the walk does not queue a second recreate of it; the node settles on the recreation's outcome. The marker goes inert once the recreation registers: execution generations are unique, so a replaced execution matches no later node. It is not cleared on success or on requeue; a later persist-deferred overwrites it. The `persist_deferred` event's detail carries `supersededExecutionGeneration` (the superseded execution's generation, or null), which explains a waiting node whose dependency reads `complete`. A cascaded persist-deferred node records no `persist_deferred` event and queues no dependency submit.

| State | Meaning |
|-------|---------|
| **waiting_deps** | Ancestor nodes incomplete; not in ready queue |
| **parked** | Soft-parked after a `park` step outcome; idle until explicit `force_fresh` wake (not dispatchable; distinct from dependency wait) |
| **ready** | Dependencies satisfied; eligible for pool |
| **running** | Leader step executing on a worker (or inline) |
| **attach_inflight** | Duplicate request joins leader; **no second pool worker** |
| **complete** | Node terminal (persisted / satisfied per analytic policy) |

**Hard invariant:** pool workers never call `ensure_export` or block on another node's completion.

Same-scope dedupe is **only** in-orchestrator singleflight on the singleton DAG. The former process-wide scope lease ([#222](https://github.com/SteveDraper/Planets-Console/issues/222)) is **retired** by [#209](https://github.com/SteveDraper/Planets-Console/issues/209) -- it compensated for multiple per-context orchestrator DAGs. Soft-park uses the first-class node state `parked` above (see [Compute step outcome](#compute-step-outcome)), not that retired lease.

### Band derivation

A node's band is derived, not stored. `ComputeRequest.priority_band` is a **standing band**, `interactive_ensure` or `background`; `stream_attached` is never requested. A submission raises the standing band of its own scope only, whether it plans the scope or attaches to it. Planned dependencies keep the default standing band.

Every dispatch pass starts by deriving each non-terminal node's band (`priority_band.derive_priority_bands`):

- A node's own band is `stream_attached` when its registration's `shell_stream_watch` reports the node's `(game, perspective, turn, player)` as watched, and its standing band otherwise. Fleet and scores register the walk watch (`walk_shell_watch.WALK_SHELL_STREAM_WATCH`), which reports every player on a live fleet or scoreboard table stream. Other registrations default to `UNWATCHED`.
- Its derived band is the highest own band over the node and every non-terminal node that transitively depends on it. Parked dependents count; terminal nodes carry no band. The walk is `dag_reach.dependency_closure`, run once per band from the nodes that hold it. Running dependents carry a band like any other non-terminal dependent.

Each watch is read once per pass, from lock-free registry snapshots. The pass writes the derived band to every non-terminal node, picks ready nodes by band (FIFO within a band), and publishes the derivation for the worker pool. A hop, a persist-deferred dependency and a recreated abort-failed dependency ask for no band: their dependents' bands reach them through the derivation. No mid-run preempt: a step keeps the band a worker picked it at.

**Scores `tier_solve` empty complete:** the skip sentinel (`runId: null`, `evidenceClosed: true`) is allowed only when turn evidence is already closed under the **same materialization probe fleet uses** (no ensure-ephemeral). Cheap ImmediateRowAdmission ensure admits write fallback-complete inference rows to disk so that probe can close; when evidence is still open, wire build must attach a `RowRun` (or fail loud if ensure claimed satisfaction without an attachable row) -- not empty-complete and not a bare open-evidence wait wire. Empty-complete falsely unlocked same-turn fleet and left the scoreboard without `rowComplete`.

### Terminal reuse and `force_fresh`

`ComputeRequest.force_fresh` controls terminal reuse vs supersede, parked wake, and whether a `waiting_deps` attach recreates abort-failed dependencies.

| `force_fresh` | Existing node state | Behavior |
|---------------|---------------------|----------|
| `False` (default) | `complete` or `failed` | Attach to the terminal node; return its cached `result_wire` or error. No new pool work. |
| `False` (default) | `waiting_deps`, `ready`, `running` | Singleflight: attach as waiter (`attach_inflight`) or join the leader; no second worker. Raises the node's standing band (see [Band derivation](#band-derivation)). |
| `False` (default) | `parked` | Attach / singleflight; node stays `parked` (no wake without `force_fresh`). |
| `True` | `complete` or `failed` | **Supersede** the terminal node: remove it from the orchestrator map, clear any waiters, re-plan the DAG from the request's entry `step_kind`, and dispatch fresh work. |
| `True` | `parked` | **Wake** the soft-parked node: resolve its readiness (fail on a cascading dependency failure, else `ready` if deps complete, else `waiting_deps`); then attach / dispatch. |
| `True` | `waiting_deps`, `ready` | Singleflight attach; in-flight work is never superseded. Refresh readiness. If the node stays `waiting_deps`, walk the `waiting_deps` chain and `force_fresh`-submit abort-failed dependencies (`ComputeScopeAbortedError`). Abort does not cascade-fail dependents and does not recreate on abort itself. |
| `True` | `running` | Same as default -- singleflight preserved; in-flight work is never superseded. |

**A dependency submit belongs to its requester's live execution.** The two dependency submits a node queues for after the lock is released -- the persist-deferred recreate of the declared dependency (a `force_fresh` submit from the recovery's `step_kind`), and the `waiting_deps` recreate of abort-failed dependencies -- carry that node's execution as `ComputeRequest.requester` (`ExecutionRef`: scope and execution generation). No other caller sets it. `_submit_locked` checks `NodeExecutionBinding.is_live_execution` (the same generation, and not terminal) in the hold that would register the plan, so an abort or replace that lands before the submit, or while it fetches its dependency chain outside the lock, refuses it. A refused submit changes nothing except to record a `dependency_submit_refused` lifecycle event on the requester's execution (detail `relatedScopeKey` names the refused dependency, as for `persist_deferred`), and raises `ComputeRequesterEndedError` from `submit`; the orchestrator's own callers treat that as the requester's end and stop submitting that batch. A node demoted to `waiting_deps` while it waits on the dependency it asked for is still live, so persist-deferred recovery is unaffected. Both submit paths share that one refusal handling (`_submit_dependencies`; the persist-deferred recovery submit, `_submit_recovery_dependency`, goes through it).

**A persist-deferred recovery submit has three outcomes.** It registers the recreation, and nothing more is needed: the replacement makes the node's superseded execution inert. It is refused because the requester ended, which only happens once that execution is terminal, so the node is not waiting and its marker is never read. Or it raises some other error, which `_settle_failed_recovery_submit` settles in one lock hold before the error is re-raised for the post-lock drain to log. The settle decides from the DAG, not from where the error came from, because `submit` can raise after it registered (from the root plan's `plan_registered` or its `__exit__`). A dispatch gate or commit hook that raises in the pass the submit scheduled is logged by the post-lock drain and does not reach the submitter. It fails the node with the submit's error only while the node is still its scope's node, live as the execution that queued the submit, `waiting_deps`, with that submit's deferral still its `last_persist_deferral`, and the recovery scope holds nothing readiness counts (`_readiness_dependency`): no node, or still the superseded execution. That covers a raise before the plan opens (turn fetch, root plan open) and a plan that raises after `force_fresh` popped the superseded execution (turn unavailable at plan time, a plan validation error). Otherwise the node is left alone: a registered replacement, or the live dependency a markerless recovery attached to, settles it, and a node that has moved on (running, re-deferred with a new marker, aborted or replaced) is not touched. The failure is a plain `_fail_node`, with its full blast radius: every waiter is released with the error, the scope outcome reaches streams and tiles, and the non-abort error cascades to waiting dependents (for fleet, the later-turn fleet chain and what ensures it). A later `force_fresh` replaces the terminal nodes.

**A recovery that changed nothing is not retried.** Before the graft, `_recover_after_persist_deferred` compares the new deferral with `last_persist_deferral`. When both name the same dependency scope at the same invalidation generation of the deferring node, the recreation the last recovery asked for has completed (a `waiting_deps` node only runs again once its dependencies are complete) and the persist still could not land, so recreating it again would loop. The node fails with `PersistDependencyRecoveryExhaustedError` (a `CoreAPIError`, not an abort, so it cascades to waiting dependents) and records a `persist_recovery_exhausted` lifecycle event, with no graft, no `persist_deferred` record and no dependency submit. The check, the record and the graft share one hold; reading the generation takes the analytic's generation lock under the orchestrator lock, the order the epoch check already uses. This bounds the fleet -> same-turn scores cycle when scores completes without writing its row (no scores persistence, a refused persist decision, no export scope, or fleet and scores disagreeing on whether turn evidence is closed). The key is the deferring node's own generation, which is not the dependency's evidence, so two gaps are accepted and pinned by tests: recreations that move that generation every round (for fleet, held scores solutions bump it) are not bounded, and a dependency reopened without moving it (for fleet, a scores row deleted when fleet@N-1 re-persists, after the recovery wrote it) fails a re-deferral that had a real cause. A cancel that denies scores' persist just before its abort lands is the same narrow window.

Default behavior treats terminal nodes as a **cache hit**: repeat callers for the same normalized `ComputeScope` get the prior outcome without re-execution. Opt-in `force_fresh=True` is the generic lifecycle primitive for callers that need a new run after terminal completion or failure (for example scores inference stream reschedule paths that must re-enter `tier_solve` on an already-failed or completed scope), and for a later-turn attach of a `waiting_deps` waiter (fleet after scores row-run cancel) that must restart abort-failed dependencies.

Supersession clears orchestrator node state only; analytic persistence invalidation and reader gates remain the analytic's responsibility.

### Settling in-flight work

`settle_in_flight_work(work, policy)` (`orchestrator_settle.py`) is the one operation that changes in-flight work on a caller's behalf. Under the orchestrator lock it selects the non-terminal nodes `work` names, asks `policy` for each one's disposition, and applies them. It returns the scopes it stopped: the nodes it ended, and the running nodes whose `running_step` it raised that no kept work needs (they end after their step). A node kept by the needed exemption is not returned. `then`, when given, runs after the settle in the same lock hold, whether or not anything was stopped: the fleet evidence bump publishes its new mark and epoch there, so no plan registers between the settle and the publish. The lock order is orchestrator, then the fleet generation lock, as planning already takes them; no holder of the generation lock calls into the orchestrator. The settle does no I/O of its own (a `then` may write one small mark file) and drains no post-lock callbacks. Post-lock callbacks share one queue, so the caller's drain, or another thread's drain that runs first, applies them. The types live in `in_flight_settle.py`, and `compute/` holds no knowledge of which analytics or callers settle.

- **Selection.** `PlayerWork(game_id, perspective, player_id, analytic_ids)` selects one player's nodes; `GameWork(game_id, analytic_ids)` selects every perspective and player in a game. Scopes whose turn is not a concrete int are skipped.
- **Policy.** An `InFlightSettlePolicy` subclass decides from an `InFlightCandidate` (scope and submission open). A `running` node takes `policy.running`; any other non-terminal node (`waiting_deps`, `ready`, `parked`) takes `policy.unstarted`.

| Disposition | Applied as |
|---|---|
| `UnstartedDisposition.KEEP`, `RunningDisposition.KEEP` | Nothing changes. |
| `UnstartedDisposition.ABORT`, `RunningDisposition.ABORT` | `_abort_node_locked` fails the node with `ComputeScopeAbortedError` and records an `abort` lifecycle event (reason `settle`). Dependents do not inherit it: they stay `waiting_deps` until a later submit replaces the node. A running node also records its step as finished `failed`, and its worker's late finish is ignored. |
| `RunningDisposition.END_AFTER_STEP` | The node's `running_step` is raised to `END_AFTER_STEP`. |

**Needed exemption.** An `ABORT` becomes `KEEP` when non-running, non-terminal work the settle leaves alive still depends on the node, directly or through other non-terminal nodes. "Needed" has one home, `dag_reach.needed_scopes(nodes, alive)`: the dependency closure (`dag_reach.dependency_closure`, the band derivation's walk) started from the scopes in `alive` whose node is not running. A running node's job wire took its dependency outputs when it was dispatched, so it keeps no dependency alive on its own account; when other needed work depends on it, the walk carries on through it, because it may run again. For the bump this makes the exemption a no-op: only fleet and scores ensure fleet or scores, only for the same player, and the persist-deferred graft from fleet to scores is same-player too (all pinned by `test_fleet_walk_dependency_edges.py`), so the only live work that can depend on one of its aborts is that player's own running fleet or scores node, which keeps nothing alive. A dependency replaced under a running node (a `force_fresh` or a hollow-terminal rebuild) is therefore aborted. `END_AFTER_STEP` is never exempted at the settle: the start-or-requeue gate re-derives "needed" each time it asks.

**Running-step lattice.** `ComputeNodeRun.running_step: RunningStepDisposition` (`running_step.py`) is how far a running execution may go past the step a worker picked. It has two levels, `CONTINUE < END_AFTER_STEP`, and a settle only raises it. Only a root attach lowers it, back to `CONTINUE` (in `_attach_to_existing`): a submit rooted at the node needs it again. A planned join needs no lowering, because it adds the dependent edge "needed" is derived from. `RunningStepDisposition.permits(step_exit, *, is_needed)` is the one table of what each value lets the execution do at a `StepExit` ("while needed" means only while `needed_scopes`, started from every other node, reaches it). `is_needed` is a thunk: only a cell whose answer depends on "needed" derives it, so an exit whose answer does not pays no walk:

| Exit | `CONTINUE` | `END_AFTER_STEP` |
|---|---|---|
| `PERSIST` | yes | yes |
| `COMPLETE` | yes | yes |
| `START` (pool pick, inline start, continue into the next step) | yes | while needed |
| `REQUEUE` (epoch retry, park, persist-deferred `waiting_deps`) | yes | while needed |

`END_AFTER_STEP` is what a **Backfill walk stop** leaves a picked fleet step: it finishes, persists and may stamp, and the node then starts or requeues no further step unless other non-terminal work still depends on it.

After a step succeeds, an epoch-stale step is retried first, whatever it returned, so a malformed result on a stale execution retries it rather than raising. On a current execution a malformed result (`MalformedStepResultError` from `coerce_step_result`) fails the node exactly as a step that raises: the pool and inline finishes share `_finish_step`, which reports the step `failed` and settles the node, so dependents and waiters settle. Otherwise the outcome names the exit the step takes (`persist`, `complete`, `continue` → `START`, `park` → `REQUEUE`). The persist leg checks `PERSIST` before its hook and `COMPLETE` (or `START` for persist-then-continue) after it, each before its epoch retry. Only `END_AFTER_STEP` refuses an exit, a start or requeue that no work needs; the node then fails with `ComputeScopeAbortedError` (`_fail_refused_execution`), which dependents do not inherit, so a later submit replaces it. It persists nothing further and is not retried.

**Start-or-requeue gate.** `_refuse_step_exit(node, StepExit.START | StepExit.REQUEUE)` is the one gate every start and requeue passes, and it is separate from `_reset_for_requeue`. It is asked at the pool pick and again after a thread step's wire build (`begin_pool_step`, which then drops the item as `pool_item_dropped` with reason `start_refused`), at the inline post-wire-build re-check, in `_dispatch` when a continued or re-queued execution is dispatched, and at the head of `_retry_step_after_epoch_bump` and `_recover_after_persist_deferred` (before it queues its dependency submit); park takes its gate from the outcome check in `_apply_step_result`, in the same lock hold. So the worker pick is the boundary between a step that is executing and one that is not, with no "picked" bit: a fleet hop queued before a stop is dropped at its pick, and an `END_AFTER_STEP` node whose step was epoch-stale ends at the retry rather than re-running. A fresh execution is `CONTINUE` and always passes. A step a bump aborted before a worker picked it is dropped at its pick as `pool_item_dropped` with reason `node_not_running`.

**Abort.** `abort_scope` (explicit cancel) lives in the same mixin. Its lock-held body is `_abort_node_locked`, and it drains after releasing the lock.

**Draining after a settle.** `drain_post_lock_callbacks()` is the public drain for a caller that settled outside a drain of its own. The **Backfill walk stop** route (`POST /api/v1/games/{G}/backfill-walks/stop`, and the BFF's `POST /bff/games/{G}/backfill-walks/stop`) settles through `services/backfill_walk_stop.py` (`WalkStopPolicy`: on the walk, unstarted → `ABORT`, running → `analytics/fleet_walk_analytics.WALK_ANALYTIC_RUNNING_DISPOSITION`, fleet `END_AFTER_STEP` and scores `ABORT`; off the walk → `KEEP`). `stop_backfill_walks` returns its follow-up (`WalkStopFollowUp`) without running it, so the stop and its follow-up have one home. The follow-up drains that orchestrator, then rescans the live walk rows and reschedules each one whose own root the settle stopped (`analytics/walk_row_reschedule.py`). Each route schedules exactly that callable as the response's background task and returns 204, so inline steps, turn fetches and reschedules never sit on the response path. The BFF reaches the follow-up only as the value its Core client's stop returns, and never names the compute drain itself. A process with no orchestrator yet settles and drains through the stand-in in `services/in_flight_orchestrator.py`, which does nothing.

---

## Execution backends

Declared per analytic on `AnalyticComputeProfile` (`ComputeStepSpec` per `step_kind`):

| Backend | Use | v1 default examples |
|---------|-----|-------------------|
| **inline** | Cheap, dependency-free work on orchestrator thread | cache probe, materialize-from-persistence, JSONPath projection |
| **thread** | In-process; shared memory for session state | scores tier steps (CP-SAT releases GIL) |
| **interpreter** | `InterpreterPoolExecutor` (Python 3.14); true multi-core without process overhead | fleet observation leg. **Packaged (`sys.frozen`) runtime remaps this to `thread`**: PyInstaller subinterpreters do not get the frozen importer, so the initializer cannot import `api` (`NotShareableError` / `BrokenInterpreterPool`; [#451](https://github.com/SteveDraper/Planets-Console/issues/451)). Unpackaged/dev can match that remap with `api.remap_interpreter_backend_to_thread: true`. Fleet observation is Python ledger/JSON bookkeeping, not SAT, so the GIL trade is acceptable for the packaged path. |
| **process** | `ProcessPoolExecutor`; strongest isolation | prior-mining extraction (existing) |

Registry built at import; unknown `step_kind` or backend → `RuntimeError` at startup.

### Parallel worker contract

Interpreter/process steps:

- Receive **serializable `JobWire`** (orchestrator may prefetch `turn_wire`, `prior_ledger_wire`, dependency slices).
- May read storage via worker-local `StorageBackend(storage_root)` when wire omits large payloads (ancestor already **complete**).
- Return **`ResultWire`** with an explicit **step outcome** (`continue`, `persist`, `complete`, or `park`); see [Compute step outcome](#compute-step-outcome).
- **Never** hold `AnalyticQueryContext`, schedulers, or gap-fill coordinators.

Thread steps (scores tiers) resolve per-row adapter state (`RowRun`) by `run_id` on the job wire; ladder progress stays adapter-owned between continuations. They must not block on cross-node ensure or call `ensure_fleet_export` in the worker.

### Job wire and dependency outputs

The orchestrator snapshots a step's builder inputs (`BuildStepJobWireKwargs`) once, under its lock, when it dispatches the step. Builders run outside the lock from that snapshot: inline, interpreter and process wires are built before the step runs or is submitted, and a thread step carries the snapshot to its pool worker (`ThreadStepWork`), which builds the wire there.

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
3. **Stream open** submits orchestrator `fleet@(host_turn - 1)` per player with the `background` standing band (replaces ad-hoc warm threads). The node is stream-attached while a watched scores node depends on it.
4. **Readers** of prior-turn fleet for overlay must use `has_final_ledger`, not `has_ledger` ([#200](https://github.com/SteveDraper/Planets-Console/issues/200) fixes `prior_turn_fleet_torp_overlay`).

---

| Layer | Mechanism |
|-------|-----------|
| **TurnInfo LRU** | One in-process cache keyed by `(game_id, perspective, turn)`. Scores and storage TurnInfo loads share it. The fleet observation job does not carry a turn. Parent splice and workers use the same type/key; heaps stay separate. Distinct from the file-backend JSON-document LRU. |
| **Job wire prefetch** | Dependency outputs and turns already loaded included in wire |
| **Worker fill** | Same TurnInfo LRU in interpreter workers (`init_worker_turn_cache`). Fleet observation legs do not fill it; the job does not carry a turn. |
| **Persistence** | Durable cache; analytic `PersistencePolicy` hooks |

Defer cross-process shared mutable caches; parent and worker heaps stay separate.

---

## Scheduling

**One global worker pool** (configurable `COMPUTE_ORCHESTRATOR_WORKERS`; replaces per-analytic `*_SCHEDULER_WORKERS` over time).

**Priority bands** (high → low):

1. **Stream-attached** -- a live shell watches the node or a non-terminal dependent of it. Never requested; derived each pass (see [Band derivation](#band-derivation)).
2. **Interactive ensure** -- the standing band of a user-confirmed BFF export-ensure job ([#109](https://github.com/SteveDraper/Planets-Console/issues/109)), or of any node it depends on.
3. **Background** -- export warm, dependency-only materialization, and any node nothing above it reaches.

An accepted **Backfill earlier turns** walk with both the fleet analytic and the scoreboard disabled keeps running. Steps no worker has picked yet, and later hops, run at background. A shell-turn change while either toggle stays on leaves the walk you left running in that same waiting band, except for the turns the new shell's walk reaches: a later shell turn reaches the whole earlier walk and keeps it stream-attached, and an earlier one leaves the turns above it at background. Reopening that turn makes every step not yet picked stream-attached again. A perspective change uses that same waiting band. On a turn or perspective change an in-flight scoreboard step may persist. A homeworld locator stream watches nothing, so it never lifts a walk. A game change stops that game's accepted walks: queued hops are dropped, an in-flight scoreboard step does not persist, and an in-flight fleet step may still stamp. See [design-fleet-analytic.md](design-fleet-analytic.md) section 5.2.

A queued pool step carries no band of its own. Each dispatch pass starts by deriving and publishing an immutable `{scope: PublishedExecution}` map of the orchestrator's non-terminal nodes (`_derive_and_publish_bands`, the only publish site): each node's band and its execution generation. The worker pool ranks every queued candidate by that map each time a worker picks, without taking the orchestrator lock (`published_execution`). A step whose scope has no published entry (orchestrator gone, or node terminal) ranks as background. A step keeps the band it was picked at: in-flight rows, remote-future rows, and completion history report that band.

A dequeue predicate (compute-diagnostics freeze) holds live work only. An item whose execution is not the one published for its scope, or whose scope has none, has ended: the pool picks it first, in queue order and whatever the predicate says, and the binding check below drops it. An ended item ranks background, not at a replacement execution's band. The diagnostics snapshot labels each queued item held or not by the pick's own rule, in the same locked pass that captures the queue. This never releases live work. An item's generation is fixed when its node is created and is published by the pass that dispatches it, before the item is queued, and it stays published until the node goes terminal or is replaced. A pass always follows a terminal transition (`_handle_dependency_terminal` schedules one, and an abort or settle caller drains it), so an ended item does not wait long; workers re-poll every 0.25 s. A mismatch is a lock-free sufficient condition of staleness. `NodeExecutionBinding.is_running_execution` stays the definition the drop applies.

A pool item is bound to the execution of its scope that dispatched it (its `execution_generation`): once that execution is no longer running, for example aborted and replaced by a newer `force_fresh` execution, a worker drops the item without running its step (recorded as `pool_item_dropped`). The record's `reason` (`StepItemIgnoredReason`) says why: `stale_execution` when the node is a newer execution, `node_not_running` when the item's own execution has ended, `missing_node` when the scope has no node, and `start_refused` when the execution was still running and the start-or-requeue gate ended it at the pick or the thread re-check; the detail's `runningStep` names the node's running-step disposition, so a stopped walk's step (`end_after_step`) and a bump-discarded one (`finish_without_stamp`) are told apart. A worker checks at the pick and, for a thread step, again after it builds the wire and before it runs the step, since the execution can end during the build; the inline path makes the same re-check after its wire build. A step that finishes late does not complete the newer node (recorded as `pool_finish_ignored`). An inline step is bound the same way: its execution can end while the step runs outside the lock (an abort, or a settle that aborts it), and its return or raise then applies to nothing (recorded as `inline_finish_ignored`), so an ended node is never re-queued by an epoch retry or continued into its next step. `_running_execution_or_record_ignored` is the one binding check for both surfaces. Compute diagnostics identify a pool step by orchestrator registration id, scope, execution generation, step kind, and step index, so an older execution's item never clears or overwrites the newer execution's in-flight row or open timeline execution, and its drop closes its own open timeline execution.

**Dispatch and hand-off.** `_run_dispatch_pass` is the one place work is dispatched. Under the orchestrator lock, `_dispatch` picks ready nodes and commits each one into a per-pass `DispatchedWork`. Everything that can raise for a node happens first, in this order: step spec, durable-satisfaction short-circuit, the start-or-requeue gate, the invalidation-generation read, and the job-wire snapshot. Only then is the node marked `running` and its record appended, which cannot raise. So a node is `running` only once its record exists. A raise while preparing one node fails that node and the pass goes on. A dispatch gate or commit hook that raises ends the pass with that error. After the lock is released, the hand-off runs in a `finally`, so every committed record is handed off even when the pass raised: inline records run one by one, then pool records are submitted, then post-lock callbacks drain. The hand-off never raises. A record whose hand-off fails fails only its own attempt, and only while its node still runs the execution it was dispatched for and its inline finish has not started to apply (`PendingStep.is_finish_applied`). An epoch retry keeps the execution generation and step index, so that flag is what tells the attempt from its retry. A raise while an inline finish applies fails the execution in the same lock hold if the finish left it running. A pass with no `pool_submitter` configured requeues pool work instead of committing it, so the hand-off never meets pool work it cannot submit.

**Submission does not dispatch.** `submit`, `wake_if_parked` and `ensure_scopes` register or join work and schedule a dispatch pass on the post-lock queue (`schedule_post_lock(dispatch_ready_work)`, as a terminal transition does); every accepted submission, join or fresh, schedules one. Each entry point drains that queue in a `finally`, so work it registered is dispatched even when its root plan raises as it closes. Passes are not merged: a pass commits at most one pool step, so an ensure batch of N roots relies on its N passes to put N pool steps in flight. The drain logs a raise inside the pass rather than passing it to the submitter. Two consequences: between the submitter's lock release and its pass, new nodes are visible as `ready`, not `running`, so a settle landing then applies its `unstarted` policy; and another thread's drain may run the pass first, so `submit` can return before its inline work has run. Callers wait on handles; none relies on that ordering.

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
| **Persist** | Orchestrator calls analytic `persist` hook only after epoch check and only when step outcome is `persist`. `generation_at_submit` is kept through persist-then-complete (post-lock). If the epoch advances before persist or before `_complete_node`, discard and re-queue -- do not stamp `complete` over a deleted ledger. Post-lock callbacks (persist, the notification `persist` returns, outcome listeners, dependent dispatch) run in one drain; one that raises is logged with its stack trace and the rest of the drain still runs. |

Which mechanism catches which stale-work race:

| Mechanism | Race |
|-----------|------|
| **Orchestrator epoch retry** | Before persist, and again before the node is marked complete, `generation_at_submit` is compared with the scope's current invalidation generation. A mismatch discards the result and re-queues the node. The persist hook runs only after that check releases the orchestrator lock. |
| **Bump abort** | A durable bump's settle (`BumpSettlePolicy`) aborted this node in the same lock hold that publishes the new epoch (see [Settling in-flight work](#settling-in-flight-work)). Its worker's finish is ignored, pool or inline, so it persists, stamps and retries nothing. |
| **Fleet wire epoch refusal** | `refuse_stale_fleet_epoch` is a fast fail before the ledger is built. It compares `playerInvalidationGeneration` on the fleet job wire with the player's current epoch. A missing value raises `ValidationError`. The ledger write repeats that compare under the generation lock in the same decision as the generation it stamps, and writes before releasing that lock. A concrete player whose epoch differs raises `DiscardedWorkRefused` and does not write. A durable bump publishes the new evidence mark and the player epoch before it releases the generation lock. An `END_AFTER_STEP` node (a fleet step a **Backfill walk stop** left running) reaches the epoch retry and is re-queued only while other work still needs it; otherwise it ends there with `ComputeScopeAbortedError`. A running off-walk node the bump kept (the setting off, on a turn a live row shows) is re-queued through the orchestrator epoch retry. The compare is inside fleet persist, which runs after the orchestrator releases its lock, and on persist callers outside the orchestrator. |

Same semantics as former gap-fill coordinator epoch abort ([#233](https://github.com/SteveDraper/Planets-Console/issues/233); coordinator deleted in [#204](https://github.com/SteveDraper/Planets-Console/issues/204)): mid-chain generation bumps exit the leg (`FleetGapFillEpochInvalidated`) instead of spinning sync rematerializations; orchestrator / stream reschedule / later ensure re-queues when the epoch advances or scores turn-evidence closes. Scores `invalidation_generation` reads the **turn-scoped** fleet epoch for `fleet@(host_turn - 1)` so in-flight `tier_solve` work is discarded when that prior fleet changes -- not when same-player scores/fleet activity on unrelated turns advances the player-scoped counter used by fleet compute / gap-fill. Fleet final `on_ledger_persisted` may wipe/reschedule ambient scores; **own-DAG elision** (#204) skips wipe and reschedule when `scores@(fleet_turn+1)` is already a non-terminal dependent of that fleet scope on the same DAG.

**Follow-on ([#280](https://github.com/SteveDraper/Planets-Console/issues/280)):** generalize ancestor-repersist → dependent wipe + `force_fresh` as orchestrator **reverse-ENSURE** routing (derived from catalog edges, including `player_id="all"`). Migrate scores↔fleet off the scores-specific ledger callback onto that path. Homeworld ownership does not use that path: it has no fleet `ENSURE` edge, and the **fleet-age stale marker** a changed build-turn map moves is what reopens it ([Homeworld locator reading a non-final fleet ledger](https://github.com/SteveDraper/Planets-Console/issues/615)). Does **not** demand-wake `waiting_deps` / parked nodes (ADR 0006).

**Backfill earlier turns:** persists produced by an on-walk execution stamp **fleet evidence generation** and do not bump it, so the rest of that walk is not discarded. A scoreboard persist bumps only when no on-walk execution for that player produced it. Membership is carried, not read from the live node: the scores `tier_solve` job wire carries `onWalk` from the node's `SubmissionOpen` through the `BuildStepJobWireKwargs` channel, the persist payload copies it, and `ScoresPersistencePolicy` passes it as a typed `on_walk` to the row persistence callback. A payload without it is a `ValidationError`. A persist admitted before its node is aborted therefore still stamps. The off-screen walk submits no further hop and its discarded scopes are not re-queued by that walk. With the setting on, each live shell and live table stream submits a new walk from that turn back to the baseline for scopes that are not ensure-final. With the setting off, earlier turns are not re-queued. **Compute diagnostic mode** does not exempt that submitted work ([Diagnostics freeze during a stale recompute](https://github.com/SteveDraper/Planets-Console/issues/619)). See [design-fleet-analytic.md](design-fleet-analytic.md) section 5.2 and [ADR 0034](adr/0034-backfill-walk-stamps-without-bumping.md).

---

## Persistence ownership

| Owner | Responsibility |
|-------|----------------|
| **Orchestrator** | When to compute; singleflight; epoch gates; invoke `persist` only on `persist` outcome; handle analytic-agnostic `PersistDeferredError` (demote to `waiting_deps` + recreate the dependency from the recovery's named step; fail on a recovery it cannot recreate or on a cascading failed dependency; not soft `parked`) |
| **Analytic** (`PersistencePolicy` on registration) | Record shape; write gates; merge (e.g. homeworld user-asserted); invalidation rules; terminal-quality metadata on stored artifacts; map write-gate refuses to `PersistDeferredError` + `PersistDependencyRecovery` when rematerialization must wait on a dependency (the dependency scope and the `step_kind` its recreation enters at; the dependency must be a walkable analytic) |

Storage paths remain per [ADR 0002](adr/0002-analytic-persistence.md). Orchestrator is cache **coordinator**, not cache **schema** owner.

### Table-stream terminal persistence (fleet-aligned template)

All table-stream analytics follow the same adapter template ([#199](https://github.com/SteveDraper/Planets-Console/issues/199) fleet, [#200](https://github.com/SteveDraper/Planets-Console/issues/200) scores):

| Concern | Owner |
|---------|--------|
| Per-stream observers / gates / query-context binding | Stream adapter (registers on the **process-wide** singleton orchestrator; released on disconnect -- not one orchestrator instance per stream) |
| Durable terminal write | `PersistencePolicy.persist` on `persist` outcome |
| NDJSON wire events | Adapter `register_scope_outcome_listener` (and mid-step callbacks for incremental events) |
| Cache replay at admission | Probe persistence directly (`has_final_ledger`, inference row store, etc.) |

Stream adapters never write durable rows themselves; `PersistencePolicy.persist` is the only durable writer.

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

**Two planes.** The compute orchestrator owns DAG scheduling (`continue` / `persist` / `complete` / `park`). The table-stream framework owns NDJSON multiplex drain and row-terminal delivery. Soft provisional / pending-wire upgrade is **stream** policy, not orchestrator DAG state -- adapters translate park/complete snapshots into shared stream-resolution triggers.

**Analytic freshness** is table presentation, not a DAG state. For a player with no stored row, the table shows turn-load only until the orchestrator accepts that player's work. From that accept until the write that stamps the mark, including while a scoreboard node waits on prior fleet, the table shows the existing in-flight chrome. See [design-fleet-analytic.md](design-fleet-analytic.md) §8.4.

**Keep** under `packages/api/api/streaming/table_stream/`:

- Multiplex, connect `finally` teardown, `TableStreamScopeGuard`, `SchedulerOrchestratorAttachment`, controller base, registry attach/detach.
- Shared `RowStreamResolution` FSM + `multiplex_closed` drain bit + `route_terminal` (queue / pending / silence). Soft is a shared capability; scores supplies soft triggers, fleet does not.
- `multiplex_closed` is the sole drain-closed source of truth (stored on the resolution registry). Sole **public** writer/reader facade is `streaming.table_stream.stream_drain` (`close` / `reopen_if_soft` / `is_closed` / `seal_canceled`) -- adapters must not call registry-private `_mark_multiplex_closed` / `_seal_canceled_finish` helpers. UUID run ids are never reused.
- Generic retained-shell / persist-admission vocabulary (`row_run_admission.py`: `RowRunPhase`, `PersistAdmission`, `RowLifecycleOp`). Per-analytic registries own shells; production persist gates use analytic `PersistDecision` / registry `decide_*` (write + retire plan; scores: `tier_row_run_registry.decide_scores_row_persist`); scores applies lifecycle via `apply_scores_row_lifecycle` in `scores/row_lifecycle.py`. Ownership invariants: [ADR 0006](adr/0006-table-stream-lifecycle-invariants.md).

**Thin adapters** (same template for fleet and scores):

- Submit `ComputeRequest` scopes to the **process-wide** orchestrator with the default `background` standing band. An open stream's work is stream-attached because the stream watches it, not because the request asks.
- Register one process-wide `scope_outcome` listener per scheduler, and at most one pause **dispatch gate**, through `SchedulerOrchestratorAttachment`. Both live for the scheduler, outside the scheduler lock. The listener and gate filter on analytic id (and, for pause, `_globally_paused`). Adapters do **not** own an orchestrator instance, and disconnect does not unregister these callbacks.
- Retain stream-only state (scope guard, per-row run registry, global pause flag). Stream bindings store query context only.
- **Do not** own durable persistence -- that is `PersistencePolicy.persist`.
- Stream teardown drops stream ownership (and clears scores pause) without cancelling in-flight singleton DAG work or aborting a pending `persist` solely because the stream ended ([#209](https://github.com/SteveDraper/Planets-Console/issues/209)); origin-set prune is [#240](https://github.com/SteveDraper/Planets-Console/issues/240).

**Table-stream row-run shell / persist admission (generic).** Any table-stream analytic that retains per-row shells across stream detach (detach ≠ cancel) reuses `RowRunPhase` (`REGISTERED` / `DETACHED` only), registry-internal `PersistAdmission` (`ALLOW` | `CANCEL_DENY` | `ABSENT`), and `RowLifecycleOp` (`DETACH` | `CANCEL` | `RETIRE`) from `streaming/table_stream/row_run_admission.py`. Cancel never becomes a retained shell phase. Soft/hard stream resolutions stay FIFO-bounded (`MAX_STREAM_RESOLUTIONS`) and delivery-only -- they do not gate persist. Multi-step tier DAG scheduling stays in `compute/` -- do not conflate.

**Scores instance.** `tier_row_run_registry` is the scores owner of shells + compact cancel admission. `decide_scores_row_persist` on that registry is the only production persist gate (atomic under one lock: maps `PersistAdmission` and shell phase into `PersistDecision` write/refuse **and** retire plan via `persist_decision_from_admission`). Once that decision is taken, a later cancel does not revoke it for that persist attempt; production writers must not branch on admission or shell phase beside that decision. Scores applies the three lifecycle ops through one command: `apply_scores_row_lifecycle` in `scores/row_lifecycle.py` (`RowLifecycleOp` from `row_run_admission.py`). Scheduler abort_scope and stream-map pops stay on the scheduler plane.

| Op | RowRun shell | PersistAdmission | Stream resolution / drain | Compute token / abort |
|----|--------------|------------------|---------------------------|------------------------|
| detach | `REGISTERED` → `DETACHED` (retained); a started tier ladder stays resumable by the same scores node execution and epoch, and a run that takes the scope over (a reopened stream's run) continues it through **ladder hand-over** | `ALLOW` | unchanged | no token cancel; no `abort_scope` |
| cancel | drop immediately (no cancel phase) | `CANCEL_DENY` (scope-keyed compact memory) | `CANCELED` + drain closed via `stream_drain.seal_canceled` | cancel token, then `abort_scope` outside scheduler lock. Stream `reschedule_player` that cancelled a run re-admits with `force_schedule` (`force_fresh` submit when scheduled) while the stream still includes the player -- cached-complete must not skip replace of the aborted node; Immediate/skip admission still applies. |
| retire | drop | clear (`ABSENT`) | leave resolution (evict only on full invalidate) | -- (also applied inside the tier registry to every run that loses a ladder claim; the scheduler then forgets those run ids) |

Cancel silence is one operation (`stream_drain.seal_canceled`) with two justified callers: multiplex (generic token-observed seal for any analytic) and scores `apply_scores_row_lifecycle(CANCEL)` (scores-specific immediate seal before multiplex notices). That CANCEL command is: compact cancel admission → immediate `stream_drain.seal_canceled` → session cancel token. Scheduler `cancel_run` then aborts the orchestrator scope outside the lock. When the orchestrator aborts a scores node first, the scores scope-outcome listener applies the same CANCEL to the run the scope's ladder stamp names for the aborted execution (a `StampedLadderRun` target, guarded on that execution generation) in place of its plain stamp release. Detach must never be routed as cancel -- detached workers may still finish and persist. Cancelled admission is at most one outstanding cancelled `run_id` per scores scope; a later `REGISTERED` for that scope supersedes it. Live `REGISTERED` persist leaves the shell for peer bindings (stream finalize retires) -- `ALLOW(retire_after_write=False)`; late `DETACHED` persist is `ALLOW(retire_after_write=True)` and the policy retires after write from that flag alone; cancel deny is `REFUSE(should_retire=True)`. Mapping: `REGISTERED` → `ALLOW(retire_after_write=False)`; `DETACHED` → `ALLOW(retire_after_write=True)`; `CANCEL_DENY` → `REFUSE(should_retire=True)`; `ABSENT` → `REFUSE(should_retire=False)` -- both refuses are silent no-ops (never raise).

**Fleet cancel (intentional asymmetry).** Fleet does **not** retain row-run shells or compact cancel admission. `FleetTableStreamScheduler.cancel_player_run` is **token-only**: cancel the session token and drop the scheduler map entry. Drain silence comes from the generic multiplex token-observed `stream_drain.seal_canceled` path; fleet does not call an immediate seal or `abort_scope`. Reschedule uses `force_fresh=True` on submit. Do not copy scores shell/admission machinery into fleet -- see [ADR 0006](adr/0006-table-stream-lifecycle-invariants.md).

**Inference global pause** (scores): soft freeze via a **dispatch gate** -- orchestrator checks adapter pause state before submitting `tier_solve` to the pool. In-flight tier steps finish; deferred continuations stay in adapter held buffer. Background fleet warm and gap-fill legs are not paused.

**Replaced (#199, #200, #209):**

- Legacy `InferenceRowScheduler` and `FleetTableStreamScheduler` private worker dequeue loops (`_worker_loop`, `_work_queue`). Both are thin orchestrator stream adapters; tier and fleet leg work submits through the global compute pool.
- Per-stream / per-`AnalyticQueryContext` orchestrator instances and the process-wide scope lease that papered over them.

---

## Callers and migration phases

| Phase | Callers routed through orchestrator |
|-------|-------------------------------------|
| **v1 (#190 epic)** | Export ensure materialization; fleet/scores table-stream steps; internal wire builders for `ctx.query` |
| **Phase 2 ([#202](https://github.com/SteveDraper/Planets-Console/issues/202))** | `TurnAnalyticService.get_turn_analytics` batch compute |
| **Phase 3** | BFF uniform proxy; analytic MCP `query_compute` |

Phase 2: `get_turn_analytics` builds the analytic query context, then `ensure_table_map_compute` fans out to roster player scopes when `player_id` is in the scope key (fleet) or one unscoped node (homeworld-locator). It calls `ensure_scopes` (`interactive_ensure`, submit-all-then-wait) so cache misses share the DAG instead of serializing per player. Durable hits short-circuit on the **inline** backend via `PersistencePolicy.is_satisfied`. `compute()` then shapes the table/map wire from persistence / `TurnInfo`.

Self-chained analytics (`turn_delta=-1`) need contiguous stored turns from the ensure floor through the shell turn. `submit` and `ensure_scopes` call `prepare_dependency_chain_turns` **before** taking the orchestrator lock, using the login-backed `AnalyticQueryContext.ensure_turn` hook. `TurnAnalyticService` builds that context once for `(game_id, perspective, turn, username)` and every in-process compute caller uses it (table/map, fleet table-stream, scores table-stream, catalog export ensure, homeworld rematerialize). Stream adapters keep that leader ctx (scores may `replace` only the scheduler-bound scores bundle) and must not reconstruct from an analytic service bundle in a way that drops `ensure_turn`. Scores table-stream admit raises if the leader ctx is missing; scores-stream fleet warm submits that same factory ctx. That fetches missing TurnInfo via `ensure_turn` / loadturn. `plan_compute_dag` then walks only already-stored turns -- loadturn must not run under the orchestrator lock. If auto-fetch is unavailable or a fetch fails, Core raises `ValidationError` (422), not an uncaught `ValueError` 500.

Scores REST sets `AnalyticComputeProfile.route_table_map=False`: the scoreboard table is a `TurnInfo` projection; inference remains stream/ensure-only. Analytics with no compute profile (base-map, connections, visibility, stellar-cartography) skip ensure and keep calling `compute()` directly.

BFF table/map contracts are unchanged.

### Export ensure migration ([#204](https://github.com/SteveDraper/Planets-Console/issues/204))

**Ensure means DAG unwind, not a second walker.** Bringing export scope `S` to terminal quality is `orchestrator.submit(S)` (plans `ENSURE_DEPENDENCIES` via `plan_compute_dag`) plus, for designated in-process callers, **orchestration-plane** `ComputeHandle.wait(timeout=…)` (default 300s, ported from the former gap-fill waiter). Pool workers and leaf `run_step` never wait.

| Lock | Rule |
|------|------|
| Mechanism | One engine only — nested sync ensure production work and **`FleetGapFillCoordinator`** are retired (no thin Event-wait shim). Walk-time unavailability is `dependency_walk_unavailable` only (no second ensure walker). |
| Callers | All production ensure paths (fleet, scores, homeworld, `ctx.query` when not `ensure_blocked`) migrate in #204. |
| Priority | Standing band: cold ensure `interactive_ensure`; warm `background`. `stream_attached` is derived from live streams, never requested. |
| `force_fresh` | Ensure defaults `false` (attach / `is_satisfied` short-circuit). Wipe / reschedule callers pass `true` when they must replace a terminal; ensure does not silently override to `true` on the unsatisfied path. Hollow terminals (durable wiped, node still `complete`) are dropped for the ensure root and for every unsatisfied planned DAG scope so `force_fresh=False` rebuilds dependency chains instead of treating hollow dep `complete` as ready. |
| Wait timeout | Fails the **waiter** only; in-flight DAG continues for attach/retry/streams. |
| `#109` | Separate BFF probe + opt-in job UX; preserve Core `probe` / `ensure_blocked` so oversized `query` does not auto full-DAG wait. |
| Fleet→scores notify | Fire `on_ledger_persisted` on each fleet **final** node complete (no end-of-chain batch). **Own-DAG elision:** if `scores@(fleet_turn+1)` is already a non-terminal dependent of that fleet scope on this DAG, do **not** wipe or reschedule — first-pass dataflow is DependencyOutputs. Keep the side channel for ambient/external scores consumers. |

Follow-ons (not #204): early RST-observed stream before same-turn scores ([#301](https://github.com/SteveDraper/Planets-Console/issues/301)); generic reverse-ENSURE ([#280](https://github.com/SteveDraper/Planets-Console/issues/280)); BFF ensure job surface ([#109](https://github.com/SteveDraper/Planets-Console/issues/109)).

---

## Package layout (target)

```text
packages/api/api/compute/
  scope.py           # ComputeScope, ScopeKeySpec, normalization
  orchestration_bundle.py  # Leader-retained export_services + ensure-memo (#209)
  orchestrator_observers.py  # Immutable outcome snapshots and lifecycle observers
  profile.py         # AnalyticComputeProfile, ComputeStepSpec
  orchestrator.py    # DAG, singleflight, submit, complete (process-wide singleton)
  orchestrator_settle.py  # settle_in_flight_work, abort_scope
  in_flight_settle.py     # Settle selection, policy protocol and dispositions
  running_step.py    # RunningStepDisposition lattice, its permits and refusal-error tables
  dag_reach.py       # dependency_closure, and needed_scopes: what non-running live work still needs
  turn_cache.py      # Process-wide TurnInfo LRU keyed by (game_id, perspective, turn)
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
| Export ensure migration | [#204](https://github.com/SteveDraper/Planets-Console/issues/204) | Ensure = orchestrator DAG `submit(root)` + orchestration-plane wait; **`FleetGapFillCoordinator`** + nested sync ensure retired; fleet→scores notify per final persist with own-DAG elision; #109 stays separate |
| Turn cache | [#201](https://github.com/SteveDraper/Planets-Console/issues/201) | Orchestrator LRU + prefetch into job wire |
| Shared TurnInfo LRU | [#511](https://github.com/SteveDraper/Planets-Console/issues/511) | One process TurnInfo LRU; scores/storage fills; fleet observation jobs do not carry a turn |
| Singleton orchestrator | [#209](https://github.com/SteveDraper/Planets-Console/issues/209) | Process-wide orchestrator; retire per-ctx bindings + scope lease; observer registry |
| Process-scoped export services | [#239](https://github.com/SteveDraper/Planets-Console/issues/239) | Retire per-node sticky `export_services` bags |
| Origin-set prune | [#240](https://github.com/SteveDraper/Planets-Console/issues/240) | Interest tracking; cancel when no origins remain |
| Phase 2 | [#202](https://github.com/SteveDraper/Planets-Console/issues/202) | Route table/map `compute()` through orchestrator |
| Phase 3 | [#203](https://github.com/SteveDraper/Planets-Console/issues/203) | BFF uniform compute API (HTTP). MCP is in-process Core ensure, not this slice ([How this MCP product relates to orchestrator phase 3](https://github.com/SteveDraper/Planets-Console/issues/320)) |

---

## Testing

- Unit: scope normalization, WILDCARD keys, priority dequeue, epoch discard, dependency gating (no worker without deps).
- Integration: fixture analytics with mutual dependencies; fleet+scores cold gap-fill parallelism; attach_inflight does not double pool workers.
- Regression: existing `test_export_dependency_walk`, gap-fill/epoch scenarios ported off `FleetGapFillCoordinator` onto orchestrator (#204), scheduler fairness tests ported to orchestrator.
- #204: own-DAG fleet→scores elision; `ensure_blocked` without submit-and-wait; wait timeout does not abort shared work.
