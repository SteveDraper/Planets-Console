# Table-stream lifecycle invariants (anti-thrash)

Status: accepted

## Context

Scores and fleet table streams share multiplex/connect infrastructure ([ADR 0004 addendum](0004-addendum-table-stream-session-framework.md)) and submit work through the process-wide compute orchestrator ([ADR 0005](0005-compute-orchestrator.md)). While closing concurrency thrash (cancel-after-unregister persist races, soft-park hangs, dual drain ledgers), implementation briefly oscillated across several cancel/persist memory designs:

- UUID tombstones for cancelled runs
- Process-lifetime / FIFO cancel fences
- Retained `CANCELLED` RowRun shells as persist denial
- Dual drain ledgers (`finished_run_ids` vs `multiplex_closed`)
- Orchestrator demand / ENSURE auto-wake of parked nodes

Those experiments converged on a multi-plane ownership model. Reopening “where cancel memory lives” or adding a second persist gate beside `PersistDecision` restarts the thrash. This ADR freezes the invariants.

Full behavioral specification: [design-compute-orchestrator.md](../design-compute-orchestrator.md) (table-stream relationship section). Shared framework modules: [ADR 0004 addendum](0004-addendum-table-stream-session-framework.md).

## Decision

The following are **invariants**, not preferences. A bug that seems to need a new store, fence, shell phase, or parallel cancel API is a design discussion first -- not a local `if` in persist or teardown.

### 1. Cancel memory (scores)

Cancel memory lives only as **scope-keyed compact** `PersistAdmission.CANCEL_DENY` in the scores row-run registry (`tier_row_run_registry`).

- Never a retained shell phase (`RowRunPhase` is `REGISTERED` | `DETACHED` only).
- Never a UUID tombstone set.
- Never a cancel-fence side table parallel to admission or stream resolution.
- At most one outstanding cancelled `run_id` per scores scope; a later `REGISTERED` for that scope supersedes it.

### 2. Drain closed

Drain-closed is only `RowStreamResolution.multiplex_closed`, written/read through `streaming.table_stream.stream_drain` (`close` / `reopen_if_soft` / `is_closed` / `seal_canceled`).

- No parallel finished-set on controllers or adapters.
- Cancel silence is one operation: `stream_drain.seal_canceled` (FSM `CANCELED` + drain closed).
- Exactly two justified **immediate or token-observed** seal callers: multiplex (generic token-observed, any analytic) and scores `apply_scores_row_lifecycle(CANCEL)` (immediate). A second seal is a no-op.

### 3. Persist write / refuse / retire plan (scores)

The full persist plan is only `PersistDecision` from
`tier_row_run_registry.decide_scores_row_persist` (admission + shell phase under
one lock; pure map in `persist_decision.persist_decision_from_admission`):

- `allowed` -- may write
- `should_retire` -- on refuse, retire compact cancel admission after silent no-write
- `retire_after_write` -- on allow, retire the retained shell after a successful write (`DETACHED` late persist)

Admission and shell phase are snapshotted atomically into that decision. Once
the decision is taken, a later cancel does not revoke it for that persist
attempt -- the policy writes or refuses from the decision alone and must not
re-probe admission. Production persist policy must not re-read
`PersistAdmission` or `RowRunPhase` beside that decision. Stream-resolution FSM
state does not gate persist.

### 4. Lifecycle mutation (scores)

Shell + admission + cancel seal + session token cancel go only through `apply_scores_row_lifecycle` (`RowLifecycleOp`: `DETACH` | `CANCEL` | `RETIRE`).

- No parallel `cancel_intent` module or second cancel entrypoint.
- Scheduler `abort_scope` and stream-map pops stay on the scheduler plane (outside the lifecycle command), invoked from `cancel_run` after CANCEL -- not from DETACH.
- The tier registry applies the same RETIRE side internally, without a new op, when a `tier_solve` ladder claim stamps one run for a scope, the top of the scope's ranking (the latest stream run, then the stamped run, then the earliest background run; `tier_row_run_registry._rank_scope_runs_locked`): every other `REGISTERED` or `DETACHED` run for that scope is retired (ladder hand-over), as a `DETACHED` shell whose ladder lost the scope already was. Until that claim, a run that loses the ranking stays registered, so it can win once the runs above it leave.
- `DETACH` keeps a shell, as `DETACHED`, only while the scope's ladder stamp names it (a mid-ladder row that may resume, be handed over or persist late). Any other run has no step in flight and no persist to come, so `DETACH` applies the RETIRE side to it ([#698](https://github.com/SteveDraper/Planets-Console/issues/698)).
- A ladder rebuild ([#656](https://github.com/SteveDraper/Planets-Console/issues/656)) replaces a run's ladder without a lifecycle op: the shell, its phase and its admission are unchanged.
- `CANCEL` takes a run id or a guarded target, `StampedLadderRun(scope, execution_generation)`: the run the scope's tier-ladder stamp names for that scores node execution. The registry releases the stamp and applies the CANCEL side to the shell it names in one hold, and only while the stamp still has that generation; a stamp written for a newer execution is untouched. This is the same op through the same entry point, not a second cancel API.
- Two orders reach CANCEL. Explicit `cancel_run` applies CANCEL, then aborts. When the orchestrator aborts first (a game change stopping a walk), the scores scope-outcome listener applies CANCEL on the stamped target for the aborted execution, in place of its plain stamp release, then forgets the run on the scheduler plane. In that order a persist whose `PersistDecision` was taken before the CANCEL may still write (§3).
- An intentional abort is not a row terminal. `ScopeLifecycleSnapshot.is_intentional_abort` (failed with `ComputeScopeAbortedError`) is the one test, read by the scores listener above and by the fleet listener (§7). Whoever ended the node owns the row's next step: an explicit cancel re-admits or tears down the row itself, and a settle reschedules the live rows whose own root it stopped (`analytics/walk_row_reschedule.py`, through `OnWalkStreamController.reschedule_player`). The **Backfill walk stop** does this in its follow-up, after its drain, so a row still open on the game (a second tab, or a stop that arrives late) restarts its walk instead of erroring or hanging.
- A `tier_solve` claim made for an execution that has already ended changes nothing: it neither stamps nor retires, so a late wire build cannot take a reopened stream's run.

### 5. Scores has no soft wait

A scores ``tier_solve`` step never waits for a wake:

- A tier terminal whose status does not close turn evidence is a broken
  contract: the step raises ``ScoresTierOutcomeError`` and the node fails. There
  is no soft stream row for it; the stream sees the failure through
  ``SCOPE_OUTCOME`` like any other failed node.
- A step that finds its claimed RowRun gone returns ``continue``, and the
  rebuilt wire re-claims, admits, skips on closed evidence or raises.

The only ways a scores node is reopened are the stream reschedule (a plain
``force_fresh`` ``tier_solve`` submit) and fleet's persist-deferred recovery
below.

- Entering the DAG does not make a dependent wake a ``waiting_deps`` / parked
  node. Every fresh submission (``_apply_root_registration``) does re-resolve the
  readiness of every ``waiting_deps`` and ``ready`` node, so an unrelated submit
  can promote a waiting node whose dependencies are complete; nothing relies on
  that as a wake.
- Admission's soft-provisional claim is stream policy
  (``stream_terminal_policy``), not DAG completion.
- **Fleet's reopen:** when fleet finalization persist refuses for open turn
  evidence, it raises ``FleetScoresEvidenceOpenError`` carrying a
  ``PersistDependencyRecovery`` of the scores scope from ``tier_solve``.
  Orchestrator persist-deferred recovery then ``submit``s that scope with
  ``force_fresh=True``, which recreates absent or terminal nodes and attaches to
  a live one. Fleet must **not** also submit scores for the same reopen -- that
  would be a second encoding of one policy. If fleet defers again at the same
  invalidation generation after that recreation completed, the orchestrator
  fails fleet with ``PersistDependencyRecoveryExhaustedError`` instead of
  recreating scores again. Details:
  [design-compute-orchestrator.md](../design-compute-orchestrator.md).

Generic orchestrator ``park`` / ``wake_if_parked`` machinery may remain for
non-scores use; scores production no longer emits ``outcome="park"``.

### 6. Overlay / observation locks stay out of lifecycle PRs

Fleet observation option-lock refine (foreign-hull drop, keep-prior empty refine, hull catalog masks) is a separate plane from cancel/persist/drain. Do not bundle observation-lock fixes into lifecycle ownership changes.

### 7. Fleet cancel (intentional asymmetry)

Fleet does **not** adopt scores shell/admission machinery.

- `cancel_player_run` is **token-only** (cancel session token + drop scheduler map).
- Drain silence uses the generic multiplex token-observed `seal_canceled` path.
- No `abort_scope` on fleet cancel; reschedule submits with `force_fresh=True`.
- The fleet scope-outcome listener paints no error for an intentional abort of any node on a row's chain (§4); the settle that ended it reschedules the row.

Copying scores `PersistAdmission` / retained shells into fleet to “unify cancel” is out of scope unless a future ADR revises this asymmetry.

## Consequences

- Scores persist policy branches only on `PersistDecision` fields.
- New cancel/persist races are fixed inside the existing planes (admission, `stream_drain`, lifecycle op, wake reasons) or by amending this ADR.
- Design doc table-stream section and ADR 0004 addendum defer to these invariants for ownership; ADR 0005 remains the orchestrator singleton decision.
- Tests for lifecycle should stay split by ownership plane (shell/admission, drain/resolution, detach persist, scope preempt) so the next race fix does not grow a single scrapbook suite.

## See also

- [design-compute-orchestrator.md](../design-compute-orchestrator.md)
- [ADR 0004 addendum](0004-addendum-table-stream-session-framework.md)
- [ADR 0005](0005-compute-orchestrator.md)
