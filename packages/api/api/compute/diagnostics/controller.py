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
    InFlightPoolExecution,
    in_flight_from_pool_item,
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
        unregister_dispatch_gate = orchestrator.register_dispatch_gate(self._dispatch_gate)
        unregister_step_complete = orchestrator.register_step_complete_listener(
            self._on_step_complete
        )
        with self._lock:
            for bound in self._bound_orchestrators:
                if bound.orchestrator is orchestrator:
                    unregister_dispatch_gate()
                    unregister_step_complete()
                    return
            self._bound_orchestrators.append(
                BoundOrchestrator(
                    orchestrator=orchestrator,
                    game_id=ctx.game_id,
                    perspective=ctx.perspective,
                    ambient_turn=ctx.ambient_turn,
                    unregister_dispatch_gate=unregister_dispatch_gate,
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
        preview, disabled_reason = self.preview_single_step(shell)
        return build_compute_diagnostics_snapshot(
            shell=shell,
            ancestor_turns=ancestor_turns,
            freeze_armed=freeze_armed,
            allowlisted_player_ids=allowlisted,
            bound_orchestrators=self._bound_orchestrators_snapshot(),
            pool=self._pool,
            pool_item_is_runnable=self._pool_item_is_runnable,
            in_flight=self._in_flight_snapshot(),
            next_single_step=preview,
            single_step_disabled_reason=disabled_reason,
            completion_history=self._history_for_shell(shell).recent(),
        )

    def preview_single_step(
        self,
        shell: ShellContextKey,
    ) -> tuple[SingleStepPreview | None, SingleStepDisabledReason | None]:
        """Return the next single-step target and why stepping is disabled, if at all.

        Selection matches :meth:`single_step`: prefer a held focus pool item (pool
        priority order), else the first focus ready node that would dispatch.
        """
        if not self._freeze_state.freeze_armed_for_game(shell.game_id):
            return None, "freeze_not_armed"
        if not self._freeze_state.allowlisted_player_ids(shell):
            return None, "empty_allowlist"
        held = self._preview_held_focus_pool_item(shell)
        if held is not None:
            return (
                SingleStepPreview(
                    scope_key=format_compute_scope_key(held.scope),
                    analytic_id=held.scope.analytic_id,
                    step_kind=held.step_kind,
                    step_index=held.step_index,
                    priority_band=held.priority_band,
                    backend=held.backend,
                    source="held",
                ),
                None,
            )
        ready = self._preview_focus_ready_dispatch(shell)
        if ready is not None:
            return ready, None
        return None, "nothing_steppable"

    def set_freeze_armed(self, shell: ShellContextKey, *, freeze_armed: bool) -> None:
        self.on_shell_context(shell)
        self._freeze_state.set_freeze_armed(shell.game_id, freeze_armed=freeze_armed)
        self._redispatch_after_gate_change(shell.game_id)

    def set_allowlist(self, shell: ShellContextKey, player_ids: frozenset[int]) -> None:
        self.on_shell_context(shell)
        self._freeze_state.set_allowlisted_player_ids(shell, player_ids)
        self._redispatch_after_gate_change(shell.game_id)

    def single_step(self, shell: ShellContextKey) -> bool:
        """Release exactly one in-focus compute step for ``shell``; return whether armed.

        Decision matches :meth:`preview_single_step`: no-op (return ``False``, leave
        grants at 0) when preview has no target. When the target is a held focus pool
        item, arm a dequeue grant only. When the target would dispatch, arm one focus
        dispatch slot plus one dequeue grant so that item can run.

        If the armed dispatch slot is consumed by an inline step (no pool enqueue),
        ``_dispatch_gate`` clears the unused dequeue grant immediately so it cannot
        orphan onto a later frozen pool item.
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
            self._single_step_grants_remaining = 1
            self._single_step_dispatch_slots_remaining = (
                0 if preview.source == "held" else 1
            )
        self._redispatch_after_gate_change(shell.game_id)
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
            self._single_step_grants_remaining = 0
            self._single_step_dispatch_slots_remaining = 0
            self._active_game_id = None
            self._last_shell_context = None
        for entry in bound:
            entry.unregister_dispatch_gate()
            entry.unregister_step_complete_listener()
        self._freeze_state.reset_for_tests()
        if self._pool is not None:
            self._pool.set_dequeue_predicate(None)
            self._pool.set_on_item_dequeued(None)
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

    def _redispatch_after_gate_change(self, game_id: int) -> None:
        """Re-dispatch ready nodes and wake held pool items after a gate change."""
        for bound in self._bound_orchestrators_snapshot():
            if bound.game_id == game_id:
                bound.orchestrator.dispatch_ready_work()
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

    def _preview_held_focus_pool_item(self, shell: ShellContextKey) -> PoolWorkItem | None:
        """Return the focus pool item single-step would dequeue first, if any."""
        if self._pool is None:
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

        queue = deque(self._pool.snapshot_work_queue())
        return dequeue_next_work_item(queue, predicate=is_focus_item)

    def _preview_focus_ready_dispatch(self, shell: ShellContextKey) -> SingleStepPreview | None:
        """Return the focus ready node single-step would dispatch first, if any."""
        ancestor_turns = self._ancestor_turns_for_shell(shell)
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
                return SingleStepPreview(
                    scope_key=format_compute_scope_key(ready_scope),
                    analytic_id=ready_scope.analytic_id,
                    step_kind=step_kind,
                    step_index=node.step_index,
                    priority_band=node.priority_band,
                    backend=backend,
                    source="would_dispatch",
                )
        return None

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

    def _single_step_may_release(self, scope: ComputeScope) -> bool:
        """Return whether an armed single-step may release ``scope`` (shell + focus)."""
        shell = self._single_step_shell
        if shell is None:
            return False
        if not self._scope_matches_single_step_shell(scope):
            return False
        return self._scope_in_focus(scope, shell)

    def _try_consume_single_step_dispatch(self, node: ComputeNodeRun) -> bool:
        """Consume one single-step dispatch slot for ``node`` if armed.

        Caller must hold ``self._lock``. Inline steps also clear the paired pool
        grant so single-step cannot leave an orphan for a later dequeue.
        """
        if self._single_step_dispatch_slots_remaining <= 0:
            return False
        if not self._single_step_may_release(node.scope):
            return False
        self._single_step_dispatch_slots_remaining -= 1
        if self._node_current_step_is_inline(node):
            self._single_step_grants_remaining = 0
            self._single_step_shell = None
        return True

    def _dispatch_gate(self, node: ComputeNodeRun) -> bool:
        with self._lock:
            operator_shell = self._last_shell_context
        if operator_shell is None:
            # Freeze armed (e.g. start-frozen on bind) before any operator shell:
            # hold all work for that game until shell sync / single-step.
            if not self._freeze_state.freeze_armed_for_game(node.scope.game_id):
                return True
            with self._lock:
                return self._try_consume_single_step_dispatch(node)

        shell = self._scope_matches_active_shell(node.scope)
        if shell is None:
            # Operator shell set, but scope outside diagnostic scope: allow.
            # Freeze only gates players in compute diagnostic scope.
            return True
        if not self._is_scope_frozen(node.scope, shell):
            return True
        with self._lock:
            return self._try_consume_single_step_dispatch(node)

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
            if self._single_step_grants_remaining > 0 and self._single_step_may_release(item.scope):
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
            if not self._single_step_may_release(item.scope):
                return
            self._single_step_grants_remaining -= 1
            if self._single_step_grants_remaining == 0:
                self._single_step_shell = None
                self._single_step_dispatch_slots_remaining = 0

    def _clear_in_flight_for_step(
        self,
        scope: ComputeScope,
        *,
        step_kind: str,
        step_index: int,
    ) -> None:
        with self._lock:
            for index, record in enumerate(self._in_flight):
                if (
                    record.scope == scope
                    and record.step_kind == step_kind
                    and record.step_index == step_index
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
    ) -> None:
        if surface == "pool":
            self._clear_in_flight_for_step(
                scope,
                step_kind=step_kind,
                step_index=node.step_index,
            )
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
