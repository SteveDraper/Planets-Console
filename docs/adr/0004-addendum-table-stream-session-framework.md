# ADR 0004 addendum: shared table-stream session framework

Status: accepted (addendum to [ADR 0004](0004-fleet-per-player-persistence-and-ensure-provenance.md))

## Context

Scores table inference stream and fleet table NDJSON stream (ADR 0004 section 6) duplicated connect orchestration, multiplex draining, scope ownership, registry attach/detach, and controller lifecycle mechanics. Near-term lifecycle alignment reduced behavioral drift but left ~300 lines of parallel code per analytic and a scope-teardown gap on early connect exit paths.

## Decision

Extract a **thin shared framework** under `packages/api/api/streaming/table_stream/`:

| Module | Responsibility |
|--------|----------------|
| `multiplex.py` | Generic round-robin drain over per-row `event_queue`, `is_stream_active`, `wake_event`, terminal-type predicate |
| `scope_guard.py` | `TableStreamScopeGuard` composed into both schedulers (`begin_scope`, `owns_table_stream`, `end_table_stream`) |
| `registry.py` | Generic scope-keyed controller registry (attach/detach, in-place reschedule lookup) |
| `controller_base.py` | Shared controller state (`pending_wire_events`, `wake_multiplex`, `finished_run_ids`, scheduled-row map) |
| `connect.py` | `iter_table_stream_connect` / `iter_table_stream_connect_with_scope` with guaranteed `finally` scope teardown |

Per-analytic code keeps:

- Worker/job execution (scores tier ladder + global pause vs fleet one-shot materialize)
- Wire event builders and transport schemas
- Admission resolution (`ImmediateRowAdmission`, cached-complete, schedule)
- Invalidation policy wiring
- Thin `*ConnectPolicy` dataclass implementing `TableStreamConnectPolicy`

## Boundaries (explicitly not unified)

- Same-scope reconnect **preempts** the prior stream token via `TableStreamScopeGuard`; there is no reject-and-retry contract.
- Wire event schemas and Zod/BFF contracts
- Scheduler classes (`InferenceRowScheduler`, `FleetTableStreamScheduler`) worker dequeue loops -- superseded by [compute orchestrator](../design-compute-orchestrator.md) ([#190](https://github.com/SteveDraper/Planets-Console/issues/190))
- Domain materialization / tier inference jobs
- Cross-analytic imports between `analytics/fleet` and `analytics/military_score_inference`

## Consequences

- Early-exit connect paths (empty `playerIds`, `schedule_failed`, mid-connect loss of stream ownership) always run `end_sessions` + `detach` via shared `finally`.
- Regression tests: `tests/test_table_stream_scope_teardown.py`.
- Tracked by [#175](https://github.com/SteveDraper/Planets-Console/issues/175).
