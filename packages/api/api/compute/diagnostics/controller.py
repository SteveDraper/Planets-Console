"""Compute diagnostics observer and freeze control."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.exports.registry import EXPORT_REGISTRY
from api.compute.diagnostics.freeze import (
    ComputeDiagnosticsFreezeState,
    ShellContextKey,
)
from api.compute.diagnostics.history import (
    DEFAULT_COMPLETION_HISTORY_CAP,
    CompletionSurface,
    CompletionTerminalState,
    ComputeCompletionHistory,
)
from api.compute.diagnostics.in_flight import (
    InFlightExecutionKey,
    InFlightPoolExecution,
    filter_live_in_flight,
    in_flight_from_pool_item,
    orphan_in_flight_object_ids,
    remove_in_flight_by_object_ids,
)
from api.compute.diagnostics.scope import (
    collect_diagnostic_ancestor_turns,
    player_id_from_scope,
    scope_in_diagnostic_scope,
)
from api.compute.diagnostics.scope_key import format_compute_scope_key
from api.compute.diagnostics.single_step_preview import (
    SingleStepDisabledReason,
    SingleStepPreview,
)
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.pools import (
    PRIORITY_BAND_RANK,
    ComputeWorkerPool,
    PoolWorkItem,
    dequeue_next_work_item,
    get_compute_worker_pool,
)
from api.compute.registry import COMPUTE_REGISTRY
from api.compute.scope import ComputeScope
from api.config import get_config

if TYPE_CHECKING:
    from api.compute.diagnostics.snapshot import ComputeDiagnosticsSnapshot

_controller_lock = threading.Lock()
_controller: ComputeDiagnosticsController | None = None


def compute_diagnostics_enabled() -> bool:
    """Return whether server compute diagnostics are enabled."""
    return get_config().compute_diagnostics


def compute_diagnostics_start_frozen() -> bool:
    """Return whether first game contact should arm freeze (requires diagnostics on)."""
    cfg = get_config()
    return cfg.compute_diagnostics and cfg.compute_diagnostics_start_frozen


@dataclass(frozen=True)
class BoundOrchestrator:
    """One orchestrator registered with the diagnostics observer."""

    orchestrator: ComputeOrchestrator
    game_id: int
    perspective: int
    ambient_turn: int
    unregister_dispatch_gate: Callable[[], None]
    unregister_dispatch_commit_hook: Callable[[], None]
    unregister_step_complete_listener: Callable[[], None]


class ComputeDiagnosticsController:
    """Analytic-agnostic observer and freeze controller for compute orchestration."""

    def __init__(self) -> None:
        self._freeze_state = ComputeDiagnosticsFreezeState()
        self._histories: dict[ShellContextKey, ComputeCompletionHistory] = {}
        self._in_flight: list[InFlightPoolExecution] = []
        self._bound_orchestrators: list[BoundOrchestrator] = []
        self._lock = threading.Lock()
        self._single_step_shell: ShellContextKey | None = None
        self._single_step_target_scope: ComputeScope | None = None
        self._single_step_target_priority_band: str | None = None
        self._single_step_target_orchestrator_id: int | None = None
        self._single_step_grants_remaining = 0
        self._single_step_dispatch_slots_remaining = 0
        self._pool: ComputeWorkerPool | None = None
        self._wired = False
        self._active_game_id: int | None = None
        self._last_shell_context: ShellContextKey | None = None

    def is_enabled(self) -> bool:
        return compute_diagnostics_enabled()

    def ensure_wired(self) -> None:
        if not self.is_enabled():
            return
        pool = get_compute_worker_pool()
        with self._lock:
            if self._wired and self._pool is pool:
                return
        # Pool hooks take the pool lock. Never call them under ``_lock`` -- pool
        # workers invoke ``on_item_dequeued`` while holding the pool lock and then
        # take ``_lock`` (pool -> controller). Controller -> pool here would ABBA.
        pool.set_dequeue_predicate(self._pool_item_is_runnable)
        pool.set_on_item_dequeued(self._on_pool_item_dequeued)
        pool.set_on_item_finished(self._on_pool_item_finished)
        with self._lock:
            if self._wired and self._pool is pool:
                return
            self._pool = pool
            self._wired = True

    def bind_orchestrator(
        self,
        orchestrator: ComputeOrchestrator,
        ctx: AnalyticQueryContext,
    ) -> None:
        if not self.is_enabled():
            return
        self.ensure_wired()
        # Arm before registering the dispatch gate so early submits see freeze.
        if compute_diagnostics_start_frozen():
            self._freeze_state.arm_start_frozen_if_needed(ctx.game_id)
        with self._lock:
            for bound in self._bound_orchestrators:
                if bound.orchestrator is orchestrator:
                    return
        # Register outside ``_lock`` so we never take orchestrator condition under
        # the controller lock (dispatch/step-complete take the opposite order).
        # Gate and commit both capture pool_registration_id so an armed single-step
        # pin rejects wrong-orchestrator nodes before commit (avoids ready-queue thrash).
        registration_id = orchestrator.pool_registration_id
        unregister_dispatch_gate = orchestrator.register_dispatch_gate(
            lambda node, _orch_id=registration_id: self._dispatch_gate(
                node,
                orchestrator_id=_orch_id,
            )
        )
        unregister_dispatch_commit = orchestrator.register_dispatch_commit_hook(
            lambda node, _orch_id=registration_id: self._commit_single_step_dispatch(
                node,
                orchestrator_id=_orch_id,
            )
        )
        unregister_step_complete = orchestrator.register_step_complete_listener(
            lambda scope, node, step_kind, surface, terminal_state, _orch_id=registration_id: (
                self._on_step_complete(
                    scope,
                    node,
                    step_kind,
                    surface,
                    terminal_state,
                    orchestrator_id=_orch_id,
                )
            )
        )
        with self._lock:
            for bound in self._bound_orchestrators:
                if bound.orchestrator is orchestrator:
                    unregister_dispatch_gate()
                    unregister_dispatch_commit()
                    unregister_step_complete()
                    return
            self._bound_orchestrators.append(
                BoundOrchestrator(
                    orchestrator=orchestrator,
                    game_id=ctx.game_id,
                    perspective=ctx.perspective,
                    ambient_turn=ctx.ambient_turn,
                    unregister_dispatch_gate=unregister_dispatch_gate,
                    unregister_dispatch_commit_hook=unregister_dispatch_commit,
                    unregister_step_complete_listener=unregister_step_complete,
                )
            )

    def unbind_orchestrator(self, orchestrator: ComputeOrchestrator) -> None:
        """Drop diagnostics binding for a released orchestrator.

        Safe no-op when diagnostics never bound this orchestrator (including when
        diagnostics are disabled). Clears in-flight pool records for the
        orchestrator's registration id (abandon path when workers cannot complete).
        """
        bound: BoundOrchestrator | None = None
        registration_id = orchestrator.pool_registration_id
        with self._lock:
            for index, candidate in enumerate(self._bound_orchestrators):
                if candidate.orchestrator is orchestrator:
                    bound = self._bound_orchestrators.pop(index)
                    break
            if registration_id is not None:
                self._in_flight = [
                    record
                    for record in self._in_flight
                    if record.orchestrator_id != registration_id
                ]
        if bound is None:
            return
        bound.unregister_dispatch_gate()
        bound.unregister_dispatch_commit_hook()
        bound.unregister_step_complete_listener()

    def on_shell_context(self, shell: ShellContextKey) -> None:
        if not self.is_enabled():
            return
        disarmed_game_id: int | None = None
        with self._lock:
            if self._active_game_id is not None and self._active_game_id != shell.game_id:
                disarmed_game_id = self._active_game_id
                self._freeze_state.set_freeze_armed(self._active_game_id, freeze_armed=False)
            self._active_game_id = shell.game_id
            if self._last_shell_context != shell:
                self._freeze_state.on_shell_context_entered(shell)
                self._last_shell_context = shell
        newly_armed = False
        if compute_diagnostics_start_frozen():
            newly_armed = self._freeze_state.arm_start_frozen_if_needed(shell.game_id)
        if disarmed_game_id is not None:
            self._redispatch_after_gate_change(disarmed_game_id)
        if newly_armed:
            self._redispatch_after_gate_change(shell.game_id)

    def snapshot(self, shell: ShellContextKey) -> ComputeDiagnosticsSnapshot:
        from api.compute.diagnostics.snapshot import build_compute_diagnostics_snapshot

        self.on_shell_context(shell)
        ancestor_turns = collect_diagnostic_ancestor_turns(
            shell.turn,
            export_registry=EXPORT_REGISTRY,
            compute_analytic_ids=frozenset(COMPUTE_REGISTRY),
        )
        freeze_armed = self._freeze_state.freeze_armed_for_game(shell.game_id)
        allowlisted = self._freeze_state.allowlisted_player_ids(shell)
        pool_queue_items = self._pool.snapshot_work_queue() if self._pool is not None else ()
        preview, disabled_reason = self.preview_single_step(
            shell,
            pool_queue_items=pool_queue_items,
        )
        return build_compute_diagnostics_snapshot(
            shell=shell,
            ancestor_turns=ancestor_turns,
            freeze_armed=freeze_armed,
            allowlisted_player_ids=allowlisted,
            bound_orchestrators=self._bound_orchestrators_snapshot(),
            pool_queue_items=pool_queue_items,
            pool_item_is_runnable=self._pool_item_is_runnable,
            in_flight=self._live_in_flight_snapshot(),
            next_single_step=preview,
            single_step_disabled_reason=disabled_reason,
            completion_history=self._history_for_shell(shell).recent(),
        )

    def preview_single_step(
        self,
        shell: ShellContextKey,
        *,
        pool_queue_items: tuple[PoolWorkItem, ...] | None = None,
    ) -> tuple[SingleStepPreview | None, SingleStepDisabledReason | None]:
        """Return the next single-step target and why stepping is disabled, if at all.

        Selection matches :meth:`single_step` and approximates unfrozen pool order:
        compare the best held focus pool item and the best focus ready node by
        priority band (then initial step before continuation). On a tie, prefer
        the held item (already queued).

        ``pool_queue_items`` when provided is the authoritative queue snapshot for
        this decision (same tuple used to render ``poolQueue``) so held preview
        cannot race ahead of an emptied queue wire.
        """
        if not self._freeze_state.freeze_armed_for_game(shell.game_id):
            return None, "freeze_not_armed"
        if not self._freeze_state.allowlisted_player_ids(shell):
            return None, "empty_allowlist"
        held = self._preview_held_focus_pool_item(shell, pool_queue_items=pool_queue_items)
        ready = self._preview_focus_ready_dispatch(shell)
        if held is None and ready is None:
            if self._has_running_focus_work(shell):
                return None, "work_in_progress"
            return None, "nothing_steppable"
        if held is None:
            return ready, None
        held_preview = SingleStepPreview(
            scope=held.scope,
            scope_key=format_compute_scope_key(held.scope),
            analytic_id=held.scope.analytic_id,
            step_kind=held.step_kind,
            step_index=held.step_index,
            priority_band=held.priority_band,
            backend=held.backend,
            source="held",
            orchestrator_id=held.orchestrator_id,
        )
        if ready is None:
            return held_preview, None
        if _single_step_release_sort_key(
            ready.priority_band,
            ready.step_index,
        ) < _single_step_release_sort_key(held.priority_band, held.step_index):
            return ready, None
        return held_preview, None

    def set_freeze_armed(self, shell: ShellContextKey, *, freeze_armed: bool) -> None:
        self.on_shell_context(shell)
        self._freeze_state.set_freeze_armed(shell.game_id, freeze_armed=freeze_armed)
        self._redispatch_after_gate_change(shell.game_id)

    def set_allowlist(self, shell: ShellContextKey, player_ids: frozenset[int]) -> None:
        """Update focus allowlist only; does not redispatch or free-run work.

        Under the focus-only model, allowlist membership gates single-step
        selection. Work advances via :meth:`single_step` (or freeze disarm),
        never by allowlist mutation alone.
        """
        self.on_shell_context(shell)
        self._freeze_state.set_allowlisted_player_ids(shell, player_ids)

    def single_step(self, shell: ShellContextKey) -> bool:
        """Release exactly one in-focus compute step for ``shell``; return whether armed.

        Decision matches :meth:`preview_single_step` (priority-band order approximating
        unfrozen pool dequeue). No-op (return ``False``, leave grants at 0) when preview
        has no target. When the target is a held focus pool item, arm a dequeue grant
        only. When the target would dispatch, arm one focus dispatch slot plus one
        dequeue grant so that item can run. The armed target scope, priority band, and
        orchestrator id are pinned so a lower-band ready node cannot steal the release.

        If the armed dispatch slot is consumed by an inline step (no pool enqueue),
        the commit hook clears the unused dequeue grant immediately so it cannot
        orphan onto a later frozen pool item.

        When the target would dispatch but no orchestrator accepts the slot (e.g. a
        later non-diagnostics gate rejected the node), arms are cleared and this
        returns ``False`` so Run does not spin on a no-op.
        """
        self.on_shell_context(shell)
        # Pool / ready snapshot before taking ``_lock`` -- pool workers call into the
        # controller while holding the pool lock, so never acquire pool lock under
        # ``_lock``. Preview owns the held-vs-dispatch decision.
        preview, _reason = self.preview_single_step(shell)
        if preview is None:
            return False
        with self._lock:
            self._single_step_shell = shell
            self._single_step_target_scope = preview.scope
            self._single_step_target_priority_band = preview.priority_band
            self._single_step_target_orchestrator_id = preview.orchestrator_id
            self._single_step_grants_remaining = 1
            self._single_step_dispatch_slots_remaining = 0 if preview.source == "held" else 1
        if preview.source == "held":
            self._pool_hold_notify()
            return True
        self._redispatch_single_step_target(
            shell.game_id,
            orchestrator_id=preview.orchestrator_id,
        )
        with self._lock:
            slots_remaining = self._single_step_dispatch_slots_remaining
            if slots_remaining > 0:
                # No commit accepted the armed slot -- clear so observers are not left
                # with a stale grant that nothing will consume.
                self._single_step_shell = None
                self._single_step_target_scope = None
                self._single_step_target_priority_band = None
                self._single_step_target_orchestrator_id = None
                self._single_step_grants_remaining = 0
                self._single_step_dispatch_slots_remaining = 0
                return False
        return True

    def freeze_status(self, shell: ShellContextKey) -> tuple[bool, frozenset[int]]:
        """Return ``(freeze_armed, allowlisted_player_ids)`` after shell-context notify.

        Lightweight alternative to :meth:`snapshot` for clients that only need freeze
        control (stream hold). Notifies shell context so game/turn/perspective sticky
        rules match stream narrowing and the full snapshot path.
        """
        self.on_shell_context(shell)
        freeze_armed = self._freeze_state.freeze_armed_for_game(shell.game_id)
        if not freeze_armed:
            return False, frozenset()
        return True, self._freeze_state.allowlisted_player_ids(shell)

    def stream_allowlisted_player_ids(self, shell: ShellContextKey) -> frozenset[int] | None:
        """When freeze is armed, return allowlisted players for stream narrowing.

        Notifies shell context first so a stream for a different game disarms the
        previous game's freeze even when diagnostics endpoints are not hit.
        """
        freeze_armed, allowlisted = self.freeze_status(shell)
        if not freeze_armed:
            return None
        return allowlisted

    def reset_for_tests(self) -> None:
        with self._lock:
            bound = list(self._bound_orchestrators)
            self._bound_orchestrators.clear()
            self._histories.clear()
            self._in_flight.clear()
            self._single_step_shell = None
            self._single_step_target_scope = None
            self._single_step_target_priority_band = None
            self._single_step_target_orchestrator_id = None
            self._single_step_grants_remaining = 0
            self._single_step_dispatch_slots_remaining = 0
            self._active_game_id = None
            self._last_shell_context = None
        for entry in bound:
            entry.unregister_dispatch_gate()
            entry.unregister_dispatch_commit_hook()
            entry.unregister_step_complete_listener()
        self._freeze_state.reset_for_tests()
        if self._pool is not None:
            self._pool.set_dequeue_predicate(None)
            self._pool.set_on_item_dequeued(None)
            self._pool.set_on_item_finished(None)
        self._pool = None
        self._wired = False

    def _history_for_shell(self, shell: ShellContextKey) -> ComputeCompletionHistory:
        with self._lock:
            history = self._histories.get(shell)
            if history is None:
                history = ComputeCompletionHistory(capacity=DEFAULT_COMPLETION_HISTORY_CAP)
                self._histories[shell] = history
            return history

    def _bound_orchestrators_snapshot(self) -> tuple[BoundOrchestrator, ...]:
        with self._lock:
            return tuple(self._bound_orchestrators)

    def _in_flight_snapshot(self) -> tuple[InFlightPoolExecution, ...]:
        with self._lock:
            return tuple(self._in_flight)

    def _running_in_flight_keys(self) -> set[InFlightExecutionKey]:
        """Return keys for bound orchestrator nodes currently in ``running`` state."""
        running_keys: set[InFlightExecutionKey] = set()
        for bound in self._bound_orchestrators_snapshot():
            orch_id = bound.orchestrator.pool_registration_id
            if orch_id is None:
                continue
            view = bound.orchestrator.diagnostics_snapshot()
            for node in view.nodes:
                if node.state != "running":
                    continue
                registration = COMPUTE_REGISTRY.get(node.scope.analytic_id)
                if registration is None:
                    continue
                steps = registration.compute_profile.steps
                if node.profile_step_index < 0 or node.profile_step_index >= len(steps):
                    continue
                step_kind = steps[node.profile_step_index].step_kind
                running_keys.add((orch_id, node.scope, step_kind, node.step_index))
        return running_keys

    def _live_in_flight_snapshot(self) -> tuple[InFlightPoolExecution, ...]:
        """Return in-flight rows that still have a matching ``running`` DAG node.

        Filters orphans left when a pool remote future outlives abort/completion on
        the orchestrator node (or when finish hooks have not yet run). Read-only:
        does not mutate ``_in_flight``; lifecycle paths call
        :meth:`_reconcile_orphan_in_flight` to purge.
        """
        records = self._in_flight_snapshot()
        if not records:
            return ()
        return filter_live_in_flight(records, running_keys=self._running_in_flight_keys())

    def _reconcile_orphan_in_flight(self) -> None:
        """Purge in-flight rows that no longer match a running DAG node.

        Authoritative cleanup for orphans (remote future vs abort). Invoked from
        pool-failed step-complete -- never from snapshot assembly. Success rows
        stay until ``on_item_finished`` so persist-before-complete remains visible.
        """
        with self._lock:
            if not self._in_flight:
                return
            recorded = list(self._in_flight)
        orphan_ids = orphan_in_flight_object_ids(
            recorded,
            running_keys=self._running_in_flight_keys(),
        )
        if not orphan_ids:
            return
        with self._lock:
            remove_in_flight_by_object_ids(self._in_flight, orphan_ids)

    def _redispatch_after_gate_change(self, game_id: int) -> None:
        """Re-dispatch ready nodes and wake held pool items after a gate change."""
        for bound in self._bound_orchestrators_snapshot():
            if bound.game_id == game_id:
                bound.orchestrator.dispatch_ready_work()
        self._pool_hold_notify()

    def _redispatch_single_step_target(
        self,
        game_id: int,
        *,
        orchestrator_id: int | None,
    ) -> None:
        """Dispatch the armed would-dispatch target on its orchestrator only.

        Preferring the previewed orchestrator avoids other bound DAGs evaluating
        the armed slot. Falls back to all game orchestrators when the preview had
        no registration id (tests without a worker pool).
        """
        if orchestrator_id is None:
            self._redispatch_after_gate_change(game_id)
            return
        for bound in self._bound_orchestrators_snapshot():
            if (
                bound.game_id == game_id
                and bound.orchestrator.pool_registration_id == orchestrator_id
            ):
                bound.orchestrator.dispatch_ready_work()
                break
        self._pool_hold_notify()

    def _pool_hold_notify(self) -> None:
        if self._pool is not None:
            self._pool.wake_workers()

    def _ancestor_turns_for_shell(self, shell: ShellContextKey) -> frozenset[int]:
        return collect_diagnostic_ancestor_turns(
            shell.turn,
            export_registry=EXPORT_REGISTRY,
            compute_analytic_ids=frozenset(COMPUTE_REGISTRY),
        )

    def _scope_matches_active_shell(self, scope: ComputeScope) -> ShellContextKey | None:
        """Return the operator shell when ``scope`` is in its diagnostic scope.

        Allowlist and completion history are keyed by the UI/operator shell
        (``_last_shell_context``), not by a bound orchestrator's ``ambient_turn``.
        Ancestor-turn work (e.g. fleet at N-1 while diagnosing scores at N) must
        use that operator shell's allowlist and history bucket.
        """
        with self._lock:
            shell = self._last_shell_context
        if shell is None:
            return None
        ancestor_turns = self._ancestor_turns_for_shell(shell)
        if scope_in_diagnostic_scope(
            scope,
            game_id=shell.game_id,
            perspective=shell.perspective,
            ancestor_turns=ancestor_turns,
        ):
            return shell
        return None

    def _is_scope_frozen(self, _scope: ComputeScope, shell: ShellContextKey) -> bool:
        """Return whether automatic dispatch/dequeue is gated for the shell's game.

        While freeze is armed, every player in diagnostic scope stays frozen -- the
        allowlist is a focus set for single-step and stream narrowing, not free-run.
        """
        return self._freeze_state.freeze_armed_for_game(shell.game_id)

    def _scope_in_focus(self, scope: ComputeScope, shell: ShellContextKey) -> bool:
        """Return whether ``scope``'s player is on the shell focus allowlist."""
        allowlisted = self._freeze_state.allowlisted_player_ids(shell)
        if not allowlisted:
            return False
        player_id = player_id_from_scope(scope)
        if player_id is None:
            return False
        return player_id in allowlisted

    def _has_running_focus_work(self, shell: ShellContextKey) -> bool:
        """Return whether any focus node in diagnostic scope is still ``running``.

        Covers persist-before-complete: the pool step may have finished (and cleared
        queues) while durable write is still outstanding and the node stays running.
        """
        ancestor_turns = self._ancestor_turns_for_shell(shell)
        for bound in self._bound_orchestrators_snapshot():
            if bound.game_id != shell.game_id or bound.perspective != shell.perspective:
                continue
            view = bound.orchestrator.diagnostics_snapshot()
            for node in view.nodes:
                if node.state != "running":
                    continue
                if not scope_in_diagnostic_scope(
                    node.scope,
                    game_id=shell.game_id,
                    perspective=shell.perspective,
                    ancestor_turns=ancestor_turns,
                ):
                    continue
                if self._scope_in_focus(node.scope, shell):
                    return True
        return False

    def _preview_held_focus_pool_item(
        self,
        shell: ShellContextKey,
        *,
        pool_queue_items: tuple[PoolWorkItem, ...] | None = None,
    ) -> PoolWorkItem | None:
        """Return the focus pool item single-step would dequeue first, if any."""
        if pool_queue_items is not None:
            queue_items = pool_queue_items
        elif self._pool is not None:
            queue_items = self._pool.snapshot_work_queue()
        else:
            return None
        ancestor_turns = self._ancestor_turns_for_shell(shell)

        def is_focus_item(item: PoolWorkItem) -> bool:
            if not scope_in_diagnostic_scope(
                item.scope,
                game_id=shell.game_id,
                perspective=shell.perspective,
                ancestor_turns=ancestor_turns,
            ):
                return False
            return self._scope_in_focus(item.scope, shell)

        queue = deque(queue_items)
        return dequeue_next_work_item(queue, predicate=is_focus_item)

    def _preview_focus_ready_dispatch(self, shell: ShellContextKey) -> SingleStepPreview | None:
        """Return the focus ready node single-step would dispatch first, if any.

        Across bound orchestrators, pick by the same priority-band / initial-step
        rules as the global pool. Ties keep bind order then ready-queue order.
        """
        ancestor_turns = self._ancestor_turns_for_shell(shell)
        best: SingleStepPreview | None = None
        best_key: tuple[int, int] | None = None
        for bound in self._bound_orchestrators_snapshot():
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
                if not self._scope_in_focus(ready_scope, shell):
                    continue
                node = nodes_by_scope[ready_scope]
                registration = COMPUTE_REGISTRY.get(ready_scope.analytic_id)
                step_kind: str | None = None
                backend: str | None = None
                if registration is not None and 0 <= node.profile_step_index < len(
                    registration.compute_profile.steps
                ):
                    step = registration.compute_profile.steps[node.profile_step_index]
                    step_kind = step.step_kind
                    backend = step.backend
                candidate = SingleStepPreview(
                    scope=ready_scope,
                    scope_key=format_compute_scope_key(ready_scope),
                    analytic_id=ready_scope.analytic_id,
                    step_kind=step_kind,
                    step_index=node.step_index,
                    priority_band=node.priority_band,
                    backend=backend,
                    source="would_dispatch",
                    orchestrator_id=bound.orchestrator.pool_registration_id,
                )
                candidate_key = _single_step_release_sort_key(
                    node.priority_band,
                    node.step_index,
                )
                if best is None or (best_key is not None and candidate_key < best_key):
                    best = candidate
                    best_key = candidate_key
        return best

    def _scope_matches_single_step_shell(self, scope: ComputeScope) -> bool:
        if self._single_step_shell is None:
            return False
        ancestor_turns = self._ancestor_turns_for_shell(self._single_step_shell)
        return scope_in_diagnostic_scope(
            scope,
            game_id=self._single_step_shell.game_id,
            perspective=self._single_step_shell.perspective,
            ancestor_turns=ancestor_turns,
        )

    def _single_step_may_release(
        self,
        scope: ComputeScope,
        *,
        priority_band: str | None = None,
        orchestrator_id: int | None = None,
    ) -> bool:
        """Return whether an armed single-step may release ``scope`` (shell + focus).

        When a target is armed, scope, priority band, and orchestrator id must match
        so the same compute scope on another orchestrator cannot steal the release.
        """
        shell = self._single_step_shell
        if shell is None:
            return False
        if self._single_step_target_scope is not None and scope != self._single_step_target_scope:
            return False
        if (
            self._single_step_target_priority_band is not None
            and priority_band != self._single_step_target_priority_band
        ):
            return False
        if (
            self._single_step_target_orchestrator_id is not None
            and orchestrator_id is not None
            and orchestrator_id != self._single_step_target_orchestrator_id
        ):
            return False
        if not self._scope_matches_single_step_shell(scope):
            return False
        return self._scope_in_focus(scope, shell)

    def _dispatch_gate(
        self,
        node: ComputeNodeRun,
        *,
        orchestrator_id: int | None = None,
    ) -> bool:
        """Side-effect free: whether freeze allows ``node`` to be selected."""
        with self._lock:
            operator_shell = self._last_shell_context
        if operator_shell is None:
            # Freeze armed (e.g. start-frozen on bind) before any operator shell:
            # hold all work for that game until shell sync / single-step.
            if not self._freeze_state.freeze_armed_for_game(node.scope.game_id):
                return True
            with self._lock:
                return self._single_step_dispatch_allowed_locked(
                    node,
                    orchestrator_id=orchestrator_id,
                )
        shell = self._scope_matches_active_shell(node.scope)
        if shell is None:
            # Operator shell set, but scope outside diagnostic scope: allow.
            # Freeze only gates players in compute diagnostic scope.
            return True
        if not self._is_scope_frozen(node.scope, shell):
            return True
        with self._lock:
            return self._single_step_dispatch_allowed_locked(
                node,
                orchestrator_id=orchestrator_id,
            )

    def _single_step_dispatch_allowed_locked(
        self,
        node: ComputeNodeRun,
        *,
        orchestrator_id: int | None,
    ) -> bool:
        """Return whether an armed single-step may select ``node`` (no consume)."""
        if self._single_step_dispatch_slots_remaining <= 0:
            return False
        return self._single_step_may_release(
            node.scope,
            priority_band=node.priority_band,
            orchestrator_id=orchestrator_id,
        )

    def _commit_single_step_dispatch(
        self,
        node: ComputeNodeRun,
        *,
        orchestrator_id: int | None,
    ) -> bool:
        """Consume one single-step dispatch slot for ``node`` after all gates passed.

        When no dispatch slot is armed, returns True so normal (unfrozen) dispatch is
        unaffected. Inline steps also clear the paired pool grant so single-step cannot
        leave an orphan for a later dequeue. Returns False when a slot is armed for a
        different target (caller requeues the node).
        """
        with self._lock:
            if self._single_step_dispatch_slots_remaining <= 0:
                return True
            if not self._single_step_may_release(
                node.scope,
                priority_band=node.priority_band,
                orchestrator_id=orchestrator_id,
            ):
                return False
            self._single_step_dispatch_slots_remaining -= 1
            if self._node_current_step_is_inline(node):
                self._single_step_grants_remaining = 0
                self._single_step_shell = None
                self._single_step_target_scope = None
                self._single_step_target_priority_band = None
                self._single_step_target_orchestrator_id = None
            return True

    def _node_current_step_is_inline(self, node: ComputeNodeRun) -> bool:
        """Return whether ``node``'s current profile step uses the inline backend."""
        registration = COMPUTE_REGISTRY.get(node.scope.analytic_id)
        if registration is None:
            return False
        steps = registration.compute_profile.steps
        if node.profile_step_index < 0 or node.profile_step_index >= len(steps):
            return False
        return steps[node.profile_step_index].backend == "inline"

    def _pool_item_is_runnable(self, item: PoolWorkItem) -> bool:
        """Return whether ``item`` may dequeue; never consumes single-step grants."""
        with self._lock:
            if self._single_step_grants_remaining > 0 and self._single_step_may_release(
                item.scope,
                priority_band=item.priority_band,
                orchestrator_id=item.orchestrator_id,
            ):
                return True
            operator_shell = self._last_shell_context
        if operator_shell is None:
            return not self._freeze_state.freeze_armed_for_game(item.scope.game_id)
        shell = self._scope_matches_active_shell(item.scope)
        if shell is None:
            # Outside diagnostic scope with an active operator shell: allow.
            return True
        return not self._is_scope_frozen(item.scope, shell)

    def _on_pool_item_dequeued(self, item: PoolWorkItem) -> None:
        """Record in-flight work and consume a single-step grant when applicable.

        Invoked under the pool lock after pop so concurrent workers cannot both
        observe a remaining grant before either burns it.
        """
        with self._lock:
            self._in_flight.append(in_flight_from_pool_item(item))
            if self._single_step_grants_remaining <= 0:
                return
            if not self._single_step_may_release(
                item.scope,
                priority_band=item.priority_band,
                orchestrator_id=item.orchestrator_id,
            ):
                return
            self._single_step_grants_remaining -= 1
            if self._single_step_grants_remaining == 0:
                self._single_step_shell = None
                self._single_step_target_scope = None
                self._single_step_target_priority_band = None
                self._single_step_target_orchestrator_id = None
                self._single_step_dispatch_slots_remaining = 0

    def _on_pool_item_finished(self, item: PoolWorkItem) -> None:
        """Clear the matching in-flight record after a pool worker finishes the item.

        Authoritative clear for success, error, orchestrator-gone, and
        ``complete_pool_step`` early-return (node already aborted). Matches by
        orchestrator id so one scope's completion cannot clear another's slot.
        """
        self._clear_in_flight_for_step(
            item.scope,
            step_kind=item.step_kind,
            step_index=item.step_index,
            orchestrator_id=item.orchestrator_id,
        )

    def _clear_in_flight_for_step(
        self,
        scope: ComputeScope,
        *,
        step_kind: str,
        step_index: int,
        orchestrator_id: int | None,
    ) -> None:
        with self._lock:
            for index, record in enumerate(self._in_flight):
                if (
                    record.scope == scope
                    and record.step_kind == step_kind
                    and record.step_index == step_index
                    and (orchestrator_id is None or record.orchestrator_id == orchestrator_id)
                ):
                    del self._in_flight[index]
                    return

    def _on_step_complete(
        self,
        scope: ComputeScope,
        node: ComputeNodeRun,
        step_kind: str,
        surface: CompletionSurface,
        terminal_state: CompletionTerminalState,
        *,
        orchestrator_id: int | None = None,
    ) -> None:
        # Clear in-flight on pool failure immediately, then reconcile other orphans.
        # On success, leave the row until pool item finished so persist-before-complete
        # stays visible (node remains ``running`` through durable write).
        if surface == "pool" and terminal_state == "failed":
            self._clear_in_flight_for_step(
                scope,
                step_kind=step_kind,
                step_index=node.step_index,
                orchestrator_id=orchestrator_id,
            )
            self._reconcile_orphan_in_flight()
        shell = self._scope_matches_active_shell(scope)
        if shell is None:
            return
        registration = COMPUTE_REGISTRY.get(scope.analytic_id)
        if registration is None:
            return
        step_spec = registration.compute_profile.steps[node.profile_step_index]
        if step_spec.step_kind != step_kind:
            return
        self._history_for_shell(shell).append(
            scope_key=format_compute_scope_key(scope),
            surface=surface,
            terminal_state=terminal_state,
            step_kind=step_kind,
            step_index=node.step_index,
            priority_band=node.priority_band,
        )


def _single_step_release_sort_key(
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


def get_compute_diagnostics_controller() -> ComputeDiagnosticsController:
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller = ComputeDiagnosticsController()
        return _controller


def reset_compute_diagnostics_for_tests() -> None:
    global _controller
    with _controller_lock:
        if _controller is not None:
            _controller.reset_for_tests()
        _controller = None
