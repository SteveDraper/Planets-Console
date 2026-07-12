"""Single-step target preview for compute diagnostics."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from api.compute.diagnostics.bindings import BoundOrchestrator
from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.diagnostics.profile_steps import profile_step_at
from api.compute.diagnostics.scope import scope_in_diagnostic_scope
from api.compute.diagnostics.scope_key import format_compute_scope_key
from api.compute.orchestrator import OrchestratorNodeSnapshot
from api.compute.pools import PRIORITY_BAND_RANK, PoolWorkItem, dequeue_next_work_item
from api.compute.scope import ComputeScope

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
    step_index: int
    priority_band: str | None
    backend: str | None
    source: SingleStepSource
    orchestrator_id: int | None = None


@dataclass
class SingleStepArm:
    """Mutable pin for one armed single-step release (grants + dispatch slots)."""

    shell: ShellContextKey | None = None
    target_scope: ComputeScope | None = None
    target_priority_band: str | None = None
    target_orchestrator_id: int | None = None
    grants_remaining: int = 0
    dispatch_slots_remaining: int = 0

    def clear(self) -> None:
        self.shell = None
        self.target_scope = None
        self.target_priority_band = None
        self.target_orchestrator_id = None
        self.grants_remaining = 0
        self.dispatch_slots_remaining = 0

    def arm_from_preview(self, shell: ShellContextKey, preview: SingleStepPreview) -> None:
        self.shell = shell
        self.target_scope = preview.scope
        self.target_priority_band = preview.priority_band
        self.target_orchestrator_id = preview.orchestrator_id
        self.grants_remaining = 1
        self.dispatch_slots_remaining = 0 if preview.source == "held" else 1


def single_step_release_sort_key(
    priority_band: str | None,
    step_index: int,
) -> tuple[int, int]:
    """Sort key matching pool dequeue: lower band rank, then initial step first."""
    if priority_band in PRIORITY_BAND_RANK:
        band_rank = PRIORITY_BAND_RANK[priority_band]  # type: ignore[index]
    else:
        band_rank = max(PRIORITY_BAND_RANK.values()) + 1
    continuation = 0 if step_index == 0 else 1
    return (band_rank, continuation)


def preview_from_held_pool_item(item: PoolWorkItem) -> SingleStepPreview:
    """Build a held-source preview from a pool work item."""
    return SingleStepPreview(
        scope=item.scope,
        scope_key=format_compute_scope_key(item.scope),
        analytic_id=item.scope.analytic_id,
        step_kind=item.step_kind,
        step_index=item.step_index,
        priority_band=item.priority_band,
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
    """Build a would-dispatch preview from a ready DAG node."""
    step = profile_step_at(scope.analytic_id, node.profile_step_index)
    return SingleStepPreview(
        scope=scope,
        scope_key=format_compute_scope_key(scope),
        analytic_id=scope.analytic_id,
        step_kind=None if step is None else step.step_kind,
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
    if single_step_release_sort_key(
        ready.priority_band,
        ready.step_index,
    ) < single_step_release_sort_key(held.priority_band, held.step_index):
        return ready
    return held


def resolve_single_step_preview(
    *,
    freeze_armed: bool,
    allowlist_empty: bool,
    held: PoolWorkItem | None,
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
    """Pick the best would-dispatch preview by release sort key; ties keep first-seen."""
    best: SingleStepPreview | None = None
    best_key: tuple[int, int] | None = None
    for candidate in candidates:
        candidate_key = single_step_release_sort_key(
            candidate.priority_band,
            candidate.step_index,
        )
        if best is None or (best_key is not None and candidate_key < best_key):
            best = candidate
            best_key = candidate_key
    return best


def find_held_focus_pool_item(
    queue_items: Sequence[PoolWorkItem],
    *,
    is_focus_item: Callable[[PoolWorkItem], bool],
) -> PoolWorkItem | None:
    """Return the focus pool item single-step would dequeue first, if any."""
    queue = deque(queue_items)
    return dequeue_next_work_item(queue, predicate=is_focus_item)


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
        if bound.game_id != shell.game_id or bound.perspective != shell.perspective:
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
        if bound.game_id != shell.game_id or bound.perspective != shell.perspective:
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


def single_step_pin_matches(
    *,
    target_scope: ComputeScope | None,
    target_priority_band: str | None,
    target_orchestrator_id: int | None,
    scope: ComputeScope,
    priority_band: str | None,
    orchestrator_id: int | None,
) -> bool:
    """Return whether ``scope`` matches an armed single-step pin (ignores focus/shell)."""
    if target_scope is not None and scope != target_scope:
        return False
    if target_priority_band is not None and priority_band != target_priority_band:
        return False
    if (
        target_orchestrator_id is not None
        and orchestrator_id is not None
        and orchestrator_id != target_orchestrator_id
    ):
        return False
    return True


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
