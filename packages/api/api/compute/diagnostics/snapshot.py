"""Wire shapes for compute diagnostics snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from api.compute.diagnostics.controller import BoundOrchestrator
from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.diagnostics.history import ComputeCompletionRecord
from api.compute.diagnostics.scope import scope_in_diagnostic_scope
from api.compute.diagnostics.scope_key import format_compute_scope_key
from api.compute.orchestrator import ComputeNodeRun
from api.compute.pools import ComputeWorkerPool, PoolWorkItem
from api.compute.registry import COMPUTE_REGISTRY
from api.compute.scope import ComputeScope
from api.streaming.table_stream.registry_catalog import active_table_stream_bindings


@dataclass(frozen=True)
class ComputeDiagnosticsSnapshot:
    shell: ShellContextKey
    freeze_armed: bool
    allowlisted_player_ids: tuple[int, ...]
    pool_queue: tuple[dict[str, Any], ...]
    dag_nodes: tuple[dict[str, Any], ...]
    ready_queue: tuple[dict[str, Any], ...]
    completion_history: tuple[dict[str, Any], ...]
    server_streams: tuple[dict[str, Any], ...]


def _node_wire(
    node: ComputeNodeRun,
    *,
    registration_step_kind: str | None,
) -> dict[str, Any]:
    return {
        "scopeKey": format_compute_scope_key(node.scope),
        "analyticId": node.scope.analytic_id,
        "state": node.state,
        "stepKind": registration_step_kind,
        "stepIndex": node.step_index,
        "priorityBand": node.priority_band,
        "profileStepIndex": node.profile_step_index,
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
    pool: ComputeWorkerPool | None,
    pool_item_is_runnable: Callable[[PoolWorkItem], bool] | None,
    completion_history: tuple[ComputeCompletionRecord, ...],
) -> ComputeDiagnosticsSnapshot:
    dag_nodes: list[dict[str, Any]] = []
    ready_queue: list[dict[str, Any]] = []
    for bound in bound_orchestrators:
        if bound.game_id != shell.game_id or bound.perspective != shell.perspective:
            continue
        for scope, node in bound.orchestrator.nodes.items():
            if not _scope_in_shell(scope, shell=shell, ancestor_turns=ancestor_turns):
                continue
            registration = COMPUTE_REGISTRY.get(scope.analytic_id)
            step_kind = None
            if registration is not None and node.profile_step_index < len(
                registration.compute_profile.steps
            ):
                step_kind = registration.compute_profile.steps[node.profile_step_index].step_kind
            dag_nodes.append(_node_wire(node, registration_step_kind=step_kind))
        for ready_scope in bound.orchestrator.ready_scopes():
            if not _scope_in_shell(ready_scope, shell=shell, ancestor_turns=ancestor_turns):
                continue
            node = bound.orchestrator.nodes[ready_scope]
            registration = COMPUTE_REGISTRY.get(ready_scope.analytic_id)
            step_kind = None
            if registration is not None and node.profile_step_index < len(
                registration.compute_profile.steps
            ):
                step_kind = registration.compute_profile.steps[node.profile_step_index].step_kind
            ready_queue.append(_node_wire(node, registration_step_kind=step_kind))

    pool_queue: list[dict[str, Any]] = []
    if pool is not None:
        for item in pool.snapshot_work_queue():
            if not _scope_in_shell(item.scope, shell=shell, ancestor_turns=ancestor_turns):
                continue
            runnable = pool_item_is_runnable(item) if pool_item_is_runnable is not None else True
            pool_queue.append(_pool_item_wire(item, runnable=runnable))

    server_streams = tuple(
        binding
        for binding in active_table_stream_bindings()
        if binding["gameId"] == shell.game_id
        and binding["perspective"] == shell.perspective
        and binding["turn"] == shell.turn
    )

    return ComputeDiagnosticsSnapshot(
        shell=shell,
        freeze_armed=freeze_armed,
        allowlisted_player_ids=tuple(sorted(allowlisted_player_ids)),
        pool_queue=tuple(pool_queue),
        dag_nodes=tuple(dag_nodes),
        ready_queue=tuple(ready_queue),
        completion_history=tuple(asdict(record) for record in completion_history),
        server_streams=server_streams,
    )


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
        "dagNodes": list(snapshot.dag_nodes),
        "readyQueue": list(snapshot.ready_queue),
        "completionHistory": completion_history,
        "serverStreams": list(snapshot.server_streams),
    }
