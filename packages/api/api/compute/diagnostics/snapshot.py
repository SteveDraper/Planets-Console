"""Wire shapes for compute diagnostics snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from api.compute.diagnostics.bindings import BoundOrchestrator, bound_matches_shell
from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.diagnostics.history import ComputeCompletionRecord
from api.compute.diagnostics.in_flight import InFlightPoolExecution, in_flight_to_wire
from api.compute.diagnostics.profile_steps import registration_step_kind
from api.compute.diagnostics.remote_futures import (
    build_remote_pool_wire,
    index_remote_futures_by_key,
)
from api.compute.diagnostics.rollup import (
    build_concurrency_timeline_rollup,
    rollup_to_wire,
)
from api.compute.diagnostics.scope import scope_in_diagnostic_scope
from api.compute.diagnostics.scope_key import format_compute_scope_key
from api.compute.diagnostics.single_step_preview import (
    SingleStepDisabledReason,
    SingleStepPreview,
    single_step_preview_to_wire,
)
from api.compute.diagnostics.timeline import ComputeConcurrencyEvent
from api.compute.orchestrator import OrchestratorNodeSnapshot
from api.compute.pools import PoolWorkItem
from api.compute.remote_futures import (
    RemotePoolFutureRecord,
    classify_future_state,
    future_exception_type,
)
from api.compute.scope import ComputeScope
from api.streaming.table_stream.registry_catalog import active_table_stream_bindings


def event_to_wire(event: ComputeConcurrencyEvent) -> dict[str, Any]:
    """CamelCase wire shape for one concurrency timeline event."""
    return {
        "kind": event.kind,
        "timestamp": event.timestamp,
        "scopeKey": event.scope_key,
        "stepKind": event.step_kind,
        "stepIndex": event.step_index,
        "priorityBand": event.priority_band,
        "backend": event.backend,
        "executionKey": event.execution_key,
        "terminalState": event.terminal_state,
        "durationMs": event.duration_ms,
        "gauges": {
            "scopedReadyDepth": event.gauges.scoped_ready_depth,
            "scopedInFlightCount": event.gauges.scoped_in_flight_count,
            "globalInFlightCount": event.gauges.global_in_flight_count,
            "globalQueueDepth": event.gauges.global_queue_depth,
            "configuredWorkers": event.gauges.configured_workers,
        },
    }


def live_occupancy_to_wire(
    *,
    configured_workers: int,
    scoped_ready_depth: int,
    scoped_in_flight_count: int,
    global_in_flight_count: int,
    global_queue_depth: int,
    backend_mix: dict[str, int],
) -> dict[str, Any]:
    """CamelCase live occupancy snapshot fields."""
    return {
        "configuredWorkers": configured_workers,
        "scopedReadyDepth": scoped_ready_depth,
        "scopedInFlightCount": scoped_in_flight_count,
        "globalInFlightCount": global_in_flight_count,
        "globalQueueDepth": global_queue_depth,
        "backendMix": backend_mix,
    }


@dataclass(frozen=True)
class ComputeDiagnosticsSnapshot:
    shell: ShellContextKey
    freeze_armed: bool
    allowlisted_player_ids: tuple[int, ...]
    pool_queue: tuple[dict[str, Any], ...]
    in_flight: tuple[dict[str, Any], ...]
    dag_nodes: tuple[dict[str, Any], ...]
    ready_queue: tuple[dict[str, Any], ...]
    next_single_step: dict[str, Any]
    completion_history: tuple[dict[str, Any], ...]
    server_streams: tuple[dict[str, Any], ...]
    remote_pool: dict[str, Any]
    live_occupancy: dict[str, Any]
    concurrency_timeline: tuple[dict[str, Any], ...]
    concurrency_rollup: dict[str, Any]


def _node_wire(
    node: OrchestratorNodeSnapshot,
    *,
    registration_step_kind: str | None,
    orchestrator_id: int | None,
) -> dict[str, Any]:
    return {
        "scopeKey": format_compute_scope_key(node.scope),
        "analyticId": node.scope.analytic_id,
        "state": node.state,
        "stepKind": registration_step_kind,
        "stepIndex": node.step_index,
        "priorityBand": node.priority_band,
        "profileStepIndex": node.profile_step_index,
        "orchestratorId": orchestrator_id,
    }


def _pool_item_wire(
    item: PoolWorkItem,
    *,
    runnable: bool,
) -> dict[str, Any]:
    return {
        "scopeKey": format_compute_scope_key(item.scope),
        "analyticId": item.scope.analytic_id,
        "stepKind": item.step_kind,
        "stepIndex": item.step_index,
        "priorityBand": item.priority_band,
        "backend": item.backend,
        "state": "held" if not runnable else "queued",
    }


def _scope_in_shell(
    scope: ComputeScope,
    *,
    shell: ShellContextKey,
    ancestor_turns: frozenset[int],
) -> bool:
    return scope_in_diagnostic_scope(
        scope,
        game_id=shell.game_id,
        perspective=shell.perspective,
        ancestor_turns=ancestor_turns,
    )


def build_compute_diagnostics_snapshot(
    *,
    shell: ShellContextKey,
    ancestor_turns: frozenset[int],
    freeze_armed: bool,
    allowlisted_player_ids: frozenset[int],
    bound_orchestrators: tuple[BoundOrchestrator, ...],
    pool_queue_items: tuple[PoolWorkItem, ...],
    pool_item_is_runnable: Callable[[PoolWorkItem], bool] | None,
    in_flight: tuple[InFlightPoolExecution, ...],
    next_single_step: SingleStepPreview | None,
    single_step_disabled_reason: SingleStepDisabledReason | None,
    completion_history: tuple[ComputeCompletionRecord, ...],
    concurrency_timeline: tuple[ComputeConcurrencyEvent, ...] = (),
    global_in_flight_count: int = 0,
    configured_workers: int = 0,
    remote_futures: tuple[RemotePoolFutureRecord, ...] = (),
    remote_executor_probe: dict[str, object] | None = None,
) -> ComputeDiagnosticsSnapshot:
    dag_nodes: list[dict[str, Any]] = []
    ready_queue: list[dict[str, Any]] = []
    for bound in bound_orchestrators:
        if not bound_matches_shell(bound, shell):
            continue
        orchestrator_view = bound.orchestrator.diagnostics_snapshot()
        orch_id = bound.orchestrator.pool_registration_id
        nodes_by_scope = {node.scope: node for node in orchestrator_view.nodes}
        for node in orchestrator_view.nodes:
            if not _scope_in_shell(node.scope, shell=shell, ancestor_turns=ancestor_turns):
                continue
            dag_nodes.append(
                _node_wire(
                    node,
                    registration_step_kind=registration_step_kind(
                        node.scope.analytic_id,
                        node.profile_step_index,
                    ),
                    orchestrator_id=orch_id,
                )
            )
        for ready_scope in orchestrator_view.ready_scopes:
            if not _scope_in_shell(ready_scope, shell=shell, ancestor_turns=ancestor_turns):
                continue
            node = nodes_by_scope[ready_scope]
            ready_queue.append(
                _node_wire(
                    node,
                    registration_step_kind=registration_step_kind(
                        node.scope.analytic_id,
                        node.profile_step_index,
                    ),
                    orchestrator_id=orch_id,
                )
            )

    pool_queue: list[dict[str, Any]] = []
    for item in pool_queue_items:
        if not _scope_in_shell(item.scope, shell=shell, ancestor_turns=ancestor_turns):
            continue
        runnable = pool_item_is_runnable(item) if pool_item_is_runnable is not None else True
        pool_queue.append(_pool_item_wire(item, runnable=runnable))

    scoped_remote_futures = tuple(
        record
        for record in remote_futures
        if _scope_in_shell(record.scope, shell=shell, ancestor_turns=ancestor_turns)
    )
    futures_by_key = index_remote_futures_by_key(scoped_remote_futures)

    in_flight_rows: list[dict[str, Any]] = []
    for record in in_flight:
        if not _scope_in_shell(record.scope, shell=shell, ancestor_turns=ancestor_turns):
            continue
        row = in_flight_to_wire(record)
        matched = futures_by_key.get(
            (record.orchestrator_id, record.scope, record.step_kind, record.step_index)
        )
        if matched is None:
            row["futureState"] = None
        else:
            state = classify_future_state(matched.future)
            row["futureState"] = state
            row["futureSubmittedAt"] = matched.submitted_at
            if state == "done":
                row["futureExceptionType"] = future_exception_type(matched.future)
        in_flight_rows.append(row)

    server_streams = tuple(
        binding
        for binding in active_table_stream_bindings()
        if binding["gameId"] == shell.game_id
        and binding["perspective"] == shell.perspective
        and binding["turn"] == shell.turn
    )

    probe = remote_executor_probe or {}
    remote_pool = build_remote_pool_wire(
        records=scoped_remote_futures,
        interpreter_max_workers=_optional_int(probe.get("interpreterMaxWorkers")),
        process_max_workers=_optional_int(probe.get("processMaxWorkers")),
        interpreter_queue_depth=_optional_int(probe.get("interpreterQueueDepth")),
        process_queue_depth=_optional_int(probe.get("processQueueDepth")),
    )

    backend_mix: dict[str, int] = {}
    for record in in_flight:
        backend_mix[record.backend] = backend_mix.get(record.backend, 0) + 1
    for item in pool_queue_items:
        if not _scope_in_shell(item.scope, shell=shell, ancestor_turns=ancestor_turns):
            continue
        backend_mix[item.backend] = backend_mix.get(item.backend, 0) + 1

    live_occupancy = live_occupancy_to_wire(
        configured_workers=configured_workers,
        scoped_ready_depth=len(ready_queue),
        scoped_in_flight_count=len(in_flight_rows),
        global_in_flight_count=global_in_flight_count,
        global_queue_depth=len(pool_queue_items),
        backend_mix=dict(sorted(backend_mix.items())),
    )
    timeline_wire = tuple(event_to_wire(event) for event in concurrency_timeline)
    concurrency_rollup = rollup_to_wire(build_concurrency_timeline_rollup(concurrency_timeline))

    return ComputeDiagnosticsSnapshot(
        shell=shell,
        freeze_armed=freeze_armed,
        allowlisted_player_ids=tuple(sorted(allowlisted_player_ids)),
        pool_queue=tuple(pool_queue),
        in_flight=tuple(in_flight_rows),
        dag_nodes=tuple(dag_nodes),
        ready_queue=tuple(ready_queue),
        next_single_step=single_step_preview_to_wire(
            next_single_step,
            disabled_reason=single_step_disabled_reason,
        ),
        completion_history=tuple(asdict(record) for record in completion_history),
        server_streams=server_streams,
        remote_pool=remote_pool,
        live_occupancy=live_occupancy,
        concurrency_timeline=timeline_wire,
        concurrency_rollup=concurrency_rollup,
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise TypeError(f"expected int | None, got {type(value)!r}")


def snapshot_to_wire(snapshot: ComputeDiagnosticsSnapshot) -> dict[str, Any]:
    completion_history = [
        {
            "scopeKey": record["scope_key"],
            "surface": record["surface"],
            "terminalState": record["terminal_state"],
            "stepKind": record["step_kind"],
            "stepIndex": record["step_index"],
            "priorityBand": record["priority_band"],
            "completedAt": record["completed_at"],
            "backend": record.get("backend"),
            "durationMs": record.get("duration_ms"),
        }
        for record in snapshot.completion_history
    ]
    return {
        "shell": {
            "gameId": snapshot.shell.game_id,
            "perspective": snapshot.shell.perspective,
            "turn": snapshot.shell.turn,
        },
        "freezeArmed": snapshot.freeze_armed,
        "allowlistedPlayerIds": list(snapshot.allowlisted_player_ids),
        "poolQueue": list(snapshot.pool_queue),
        "inFlight": list(snapshot.in_flight),
        "dagNodes": list(snapshot.dag_nodes),
        "readyQueue": list(snapshot.ready_queue),
        "nextSingleStep": snapshot.next_single_step,
        "completionHistory": completion_history,
        "serverStreams": list(snapshot.server_streams),
        "remotePool": snapshot.remote_pool,
        "liveOccupancy": snapshot.live_occupancy,
        "concurrencyTimeline": list(snapshot.concurrency_timeline),
        "concurrencyRollup": snapshot.concurrency_rollup,
    }
