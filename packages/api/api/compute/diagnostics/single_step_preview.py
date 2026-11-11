"""Single-step target preview for compute diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from api.compute.diagnostics.bindings import BoundOrchestrator, bound_matches_shell
from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.diagnostics.profile_steps import profile_step_at
from api.compute.diagnostics.scope import scope_in_diagnostic_scope
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


def resolve_single_step_preview(
    *,
    freeze_armed: bool,
    allowlist_empty: bool,
    held: BandedWorkItem | None,
    ready: SingleStepPreview | None,
    has_running_focus: Callable[[], bool],
) -> tuple[SingleStepPreview | None, SingleStepDisabledReason | None]:
    """Apply freeze/allowlist/WIP gates and choose held vs ready preview."""
    if not freeze_armed:
        return None, "freeze_not_armed"
    if allowlist_empty:
        return None, "empty_allowlist"
    if held is None and ready is None:
        if has_running_focus():
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
    *,
    is_focus_item: Callable[[PoolWorkItem], bool],
) -> BandedWorkItem | None:
    """Return the focus pool item single-step would dequeue first, if any."""
    return pick_next_work_item(queued for queued in queue_items if is_focus_item(queued.item))


def any_running_focus_node(
    nodes: Iterable[OrchestratorNodeSnapshot],
    *,
    in_diagnostic_scope: Callable[[ComputeScope], bool],
    in_focus: Callable[[ComputeScope], bool],
) -> bool:
    """Return whether any focus node in diagnostic scope is still ``running``."""
    for node in nodes:
        if node.state != "running":
            continue
        if not in_diagnostic_scope(node.scope):
            continue
        if in_focus(node.scope):
            return True
    return False


def has_running_focus_work(
    bound_orchestrators: Sequence[BoundOrchestrator],
    shell: ShellContextKey,
    *,
    ancestor_turns: frozenset[int],
    scope_in_focus: Callable[[ComputeScope], bool],
) -> bool:
    """Return whether any bound focus node in diagnostic scope is still ``running``."""

    def in_diagnostic_scope(scope: ComputeScope) -> bool:
        return scope_in_diagnostic_scope(
            scope,
            game_id=shell.game_id,
            perspective=shell.perspective,
            ancestor_turns=ancestor_turns,
        )

    for bound in bound_orchestrators:
        if not bound_matches_shell(bound, shell):
            continue
        view = bound.orchestrator.diagnostics_snapshot()
        if any_running_focus_node(
            view.nodes,
            in_diagnostic_scope=in_diagnostic_scope,
            in_focus=scope_in_focus,
        ):
            return True
    return False


def preview_focus_ready_dispatch(
    bound_orchestrators: Sequence[BoundOrchestrator],
    shell: ShellContextKey,
    *,
    ancestor_turns: frozenset[int],
    scope_in_focus: Callable[[ComputeScope], bool],
) -> SingleStepPreview | None:
    """Return the focus ready node single-step would dispatch first, if any."""
    candidates: list[SingleStepPreview] = []
    for bound in bound_orchestrators:
        if not bound_matches_shell(bound, shell):
            continue
        view = bound.orchestrator.diagnostics_snapshot()
        nodes_by_scope = {node.scope: node for node in view.nodes}
        for ready_scope in view.ready_scopes:
            if not scope_in_diagnostic_scope(
                ready_scope,
                game_id=shell.game_id,
                perspective=shell.perspective,
                ancestor_turns=ancestor_turns,
            ):
                continue
            if not scope_in_focus(ready_scope):
                continue
            candidates.append(
                preview_from_ready_node(
                    ready_scope,
                    nodes_by_scope[ready_scope],
                    orchestrator_id=bound.orchestrator.pool_registration_id,
                )
            )
    return select_best_ready_preview(candidates)


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
