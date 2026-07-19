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

The full persist plan is only `PersistDecision` from `decide_scores_row_persist`:

- `allowed` -- may write
- `should_retire` -- on refuse, retire compact cancel admission after silent no-write
- `retire_after_write` -- on allow, retire the retained shell after a successful write (`DETACHED` late persist)

Production persist policy must not re-read `PersistAdmission` or `RowRunPhase` beside that decision. Stream-resolution FSM state does not gate persist.

### 4. Lifecycle mutation (scores)

Shell + admission + cancel seal + session token cancel go only through `apply_scores_row_lifecycle` (`RowLifecycleOp`: `DETACH` | `CANCEL` | `RETIRE`).

- No parallel `cancel_intent` module or second cancel entrypoint.
- Scheduler `abort_scope` and stream-map pops stay on the scheduler plane (outside the lifecycle command), invoked from `cancel_run` after CANCEL -- not from DETACH.

### 5. Soft park wake

Soft park wake is **scores-owned** (`wake_if_parked` / `ScoresWakeReason` coordination in scores compute orchestration).

- The orchestrator does **not** demand-wake or ENSURE-ancestor auto-wake parked nodes.
- Soft provisional / pending-wire upgrade is stream policy, not DAG state.

### 6. Overlay / observation locks stay out of lifecycle PRs

Fleet observation option-lock refine (foreign-hull drop, keep-prior empty refine, hull catalog masks) is a separate plane from cancel/persist/drain. Do not bundle observation-lock fixes into lifecycle ownership changes.

### 7. Fleet cancel (intentional asymmetry)

Fleet does **not** adopt scores shell/admission machinery.

- `cancel_player_run` is **token-only** (cancel session token + drop scheduler map).
- Drain silence uses the generic multiplex token-observed `seal_canceled` path.
- No `abort_scope` on fleet cancel; reschedule submits with `force_fresh=True`.

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
