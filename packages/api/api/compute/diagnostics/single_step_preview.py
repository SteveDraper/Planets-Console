"""Single-step target preview for compute diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from api.compute.diagnostics.bindings import BoundOrchestrator, bound_matches_shell
from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.diagnostics.profile_steps import profile_step_at
from api.compute.orchestrator import OrchestratorNodeSnapshot
from api.compute.pools import BandedWorkItem, PoolWorkItem, pick_next_work_item, work_pick_key
from api.compute.priority_band import ComputePriorityBand
from api.compute.scope import ComputeScope, format_compute_scope_key

SingleStepSource = Literal["held", "would_dispatch"]
SingleStepDisabledReason = Literal[
    "freeze_not_armed",
    "empty_allowlist",
    "nothing_steppable",
    "work_in_progress",
]


@dataclass(frozen=True)
class SingleStepPreview:
    """One schedulable compute step that single-step would release next."""

    scope: ComputeScope
    scope_key: str
    analytic_id: str
    step_kind: str | None
    execution_generation: int
    step_index: int
    priority_band: ComputePriorityBand
    backend: str | None
    source: SingleStepSource
    orchestrator_id: int | None = None


@dataclass(frozen=True)
class SingleStepPin:
    """The one compute step an armed single-step may release.

    The pin names the execution of ``scope`` it releases, so a pool item left
    by an older execution of the same scope and step index cannot use it up.
    The pin carries no band: a band may change between preview and release,
    and the pinned step stays the same step.
    """

    orchestrator_id: int | None
    scope: ComputeScope
    execution_generation: int
    step_index: int

    def matches(
        self,
        *,
        orchestrator_id: int | None,
        scope: ComputeScope,
        execution_generation: int,
        step_index: int,
    ) -> bool:
        """Return whether a step is the pinned one (ignores focus and shell).

        An unknown orchestrator id on either side does not reject the match.
        """
        if (scope, execution_generation, step_index) != (
            self.scope,
            self.execution_generation,
            self.step_index,
        ):
            return False
        return (
            self.orchestrator_id is None
            or orchestrator_id is None
            or orchestrator_id == self.orchestrator_id
        )


@dataclass
class SingleStepArm:
    """Mutable state for one armed single-step release (pin, grants, dispatch slots)."""

    shell: ShellContextKey | None = None
    target: SingleStepPin | None = None
    grants_remaining: int = 0
    dispatch_slots_remaining: int = 0

    def clear(self) -> None:
        self.shell = None
        self.target = None
        self.grants_remaining = 0
        self.dispatch_slots_remaining = 0

    def arm_from_preview(self, shell: ShellContextKey, preview: SingleStepPreview) -> None:
        self.shell = shell
        self.target = SingleStepPin(
            orchestrator_id=preview.orchestrator_id,
            scope=preview.scope,
            execution_generation=preview.execution_generation,
            step_index=preview.step_index,
        )
        self.grants_remaining = 1
        self.dispatch_slots_remaining = 0 if preview.source == "held" else 1


def _release_key(preview: SingleStepPreview) -> tuple[int, int]:
    return work_pick_key(preview.priority_band, preview.step_index)


def preview_from_held_pool_item(held: BandedWorkItem) -> SingleStepPreview:
    """Build a held-source preview from a queued pool item and its current band."""
    item = held.item
    return SingleStepPreview(
        scope=item.scope,
        scope_key=format_compute_scope_key(item.scope),
        analytic_id=item.scope.analytic_id,
        step_kind=item.step_kind,
        execution_generation=item.execution_generation,
        step_index=item.step_index,
        priority_band=held.priority_band,
        backend=item.backend,
        source="held",
        orchestrator_id=item.orchestrator_id,
    )


def preview_from_ready_node(
    scope: ComputeScope,
    node: OrchestratorNodeSnapshot,
    *,
    orchestrator_id: int | None,
) -> SingleStepPreview:
    """Build a would-dispatch preview from a ready DAG node at its snapshot band."""
    step = profile_step_at(scope.analytic_id, node.profile_step_index)
    return SingleStepPreview(
        scope=scope,
        scope_key=format_compute_scope_key(scope),
        analytic_id=scope.analytic_id,
        step_kind=None if step is None else step.step_kind,
        execution_generation=node.execution_generation,
        step_index=node.step_index,
        priority_band=node.priority_band,
        backend=None if step is None else step.backend,
        source="would_dispatch",
        orchestrator_id=orchestrator_id,
    )


def choose_held_or_ready_preview(
    held: SingleStepPreview | None,
    ready: SingleStepPreview | None,
) -> SingleStepPreview | None:
    """Prefer higher-priority ready over held; on a tie keep the held item."""
    if held is None:
        return ready
    if ready is None:
        return held
    if _release_key(ready) < _release_key(held):
        return ready
    return held


@dataclass(frozen=True)
class BoundNodesView:
    """One bound orchestrator's nodes and ready queue, read once per preview."""

    orchestrator_id: int | None
    nodes_by_scope: Mapping[ComputeScope, OrchestratorNodeSnapshot]
    ready_scopes: tuple[ComputeScope, ...]


def _read_bound_nodes_views(
    bound_orchestrators: Sequence[BoundOrchestrator],
    shell: ShellContextKey,
) -> tuple[BoundNodesView, ...]:
    """Take one diagnostics snapshot of each orchestrator bound for ``shell``."""
    views: list[BoundNodesView] = []
    for bound in bound_orchestrators:
        if not bound_matches_shell(bound, shell):
            continue
        snapshot = bound.orchestrator.diagnostics_snapshot()
        views.append(
            BoundNodesView(
                orchestrator_id=bound.orchestrator.pool_registration_id,
                nodes_by_scope={node.scope: node for node in snapshot.nodes},
                ready_scopes=snapshot.ready_scopes,
            )
        )
    return tuple(views)


def resolve_single_step_preview(
    *,
    freeze_armed: bool,
    allowlist_empty: bool,
    queue_items: Sequence[BandedWorkItem],
    bound_orchestrators: Sequence[BoundOrchestrator],
    shell: ShellContextKey,
    is_focus_scope: Callable[[ComputeScope], bool],
) -> tuple[SingleStepPreview | None, SingleStepDisabledReason | None]:
    """Apply freeze/allowlist/WIP gates and choose held vs ready preview.

    ``is_focus_scope`` says whether a scope is in the shell's diagnostic scope
    and its player is a focus player. Node snapshots are read after the
    caller took ``queue_items``, so each queued item is judged against node
    state no older than the item.
    """
    if not freeze_armed:
        return None, "freeze_not_armed"
    if allowlist_empty:
        return None, "empty_allowlist"
    views = _read_bound_nodes_views(bound_orchestrators, shell)
    held = find_held_focus_pool_item(queue_items, views, is_focus_scope=is_focus_scope)
    ready = preview_focus_ready_dispatch(views, is_focus_scope=is_focus_scope)
    if held is None and ready is None:
        if has_running_focus_work(views, is_focus_scope=is_focus_scope):
            return None, "work_in_progress"
        return None, "nothing_steppable"
    held_preview = None if held is None else preview_from_held_pool_item(held)
    return choose_held_or_ready_preview(held_preview, ready), None


def select_best_ready_preview(
    candidates: Iterable[SingleStepPreview],
) -> SingleStepPreview | None:
    """Pick the best would-dispatch preview in pool pick order; ties keep first-seen."""
    return min(candidates, key=_release_key, default=None)


def find_held_focus_pool_item(
    queue_items: Sequence[BandedWorkItem],
    views: Sequence[BoundNodesView],
    *,
    is_focus_scope: Callable[[ComputeScope], bool],
) -> BandedWorkItem | None:
    """Return the focus pool item single-step would dequeue first, if any.

    Only an item bound to the running execution of its scope is a candidate
    (``NodeExecutionBinding.is_running_execution``). An item left by an aborted
    or replaced execution would be dropped unrun when picked, so it is neither
    offered nor kept on a tie with a ready node. An item whose orchestrator is
    not bound for the shell has no node to check and is not offered.
    """
    views_by_orchestrator = {
        view.orchestrator_id: view for view in views if view.orchestrator_id is not None
    }

    def is_live_focus_item(item: PoolWorkItem) -> bool:
        if not is_focus_scope(item.scope):
            return False
        view = views_by_orchestrator.get(item.orchestrator_id)
        node = None if view is None else view.nodes_by_scope.get(item.scope)
        return node is not None and node.is_running_execution(item.execution_generation)

    return pick_next_work_item(queued for queued in queue_items if is_live_focus_item(queued.item))


def has_running_focus_work(
    views: Sequence[BoundNodesView],
    *,
    is_focus_scope: Callable[[ComputeScope], bool],
) -> bool:
    """Return whether any bound focus node is still ``running``.

    Covers persist-before-complete: the pool step may have finished (and cleared
    queues) while durable write is still outstanding and the node stays running.
    """
    return any(
        node.state == "running" and is_focus_scope(node.scope)
        for view in views
        for node in view.nodes_by_scope.values()
    )


def preview_focus_ready_dispatch(
    views: Sequence[BoundNodesView],
    *,
    is_focus_scope: Callable[[ComputeScope], bool],
) -> SingleStepPreview | None:
    """Return the focus ready node single-step would dispatch first, if any.

    Ties keep bind order, then ready-queue order.
    """
    return select_best_ready_preview(
        preview_from_ready_node(
            ready_scope,
            view.nodes_by_scope[ready_scope],
            orchestrator_id=view.orchestrator_id,
        )
        for view in views
        for ready_scope in view.ready_scopes
        if is_focus_scope(ready_scope)
    )


def single_step_preview_to_wire(
    preview: SingleStepPreview | None,
    *,
    disabled_reason: SingleStepDisabledReason | None,
) -> dict[str, Any]:
    """Return camelCase next-single-step block for the diagnostics snapshot."""
    target: dict[str, Any] | None = None
    if preview is not None:
        target = {
            "scopeKey": preview.scope_key,
            "analyticId": preview.analytic_id,
            "stepKind": preview.step_kind,
            "stepIndex": preview.step_index,
            "priorityBand": preview.priority_band,
            "backend": preview.backend,
            "source": preview.source,
            "orchestratorId": preview.orchestrator_id,
        }
    return {
        "target": target,
        "disabledReason": disabled_reason,
    }
