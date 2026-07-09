"""Compute diagnostics observer and freeze control."""

from __future__ import annotations

import threading
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
from api.compute.diagnostics.scope import (
    collect_diagnostic_ancestor_turns,
    player_id_from_scope,
    scope_in_diagnostic_scope,
)
from api.compute.diagnostics.scope_key import format_compute_scope_key
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.pools import ComputeWorkerPool, PoolWorkItem, get_compute_worker_pool
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


@dataclass(frozen=True)
class BoundOrchestrator:
    """One orchestrator registered with the diagnostics observer."""

    orchestrator: ComputeOrchestrator
    game_id: int
    perspective: int
    ambient_turn: int


class ComputeDiagnosticsController:
    """Analytic-agnostic observer and freeze controller for compute orchestration."""

    def __init__(self) -> None:
        self._freeze_state = ComputeDiagnosticsFreezeState()
        self._histories: dict[ShellContextKey, ComputeCompletionHistory] = {}
        self._bound_orchestrators: list[BoundOrchestrator] = []
        self._lock = threading.Lock()
        self._single_step_shell: ShellContextKey | None = None
        self._single_step_grants_remaining = 0
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
            pool.set_dequeue_predicate(self._pool_dequeue_predicate)
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
        with self._lock:
            for bound in self._bound_orchestrators:
                if bound.orchestrator is orchestrator:
                    return
            self._bound_orchestrators.append(
                BoundOrchestrator(
                    orchestrator=orchestrator,
                    game_id=ctx.game_id,
                    perspective=ctx.perspective,
                    ambient_turn=ctx.ambient_turn,
                )
            )
        orchestrator.set_dispatch_gate(self._dispatch_gate)
        orchestrator.register_step_complete_listener(self._on_step_complete)

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
        if disarmed_game_id is not None:
            self._redispatch_after_gate_change(disarmed_game_id)
        if self._freeze_state.freeze_armed_for_game(shell.game_id):
            self._apply_gates_for_game(shell.game_id)

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
        return build_compute_diagnostics_snapshot(
            shell=shell,
            ancestor_turns=ancestor_turns,
            freeze_armed=freeze_armed,
            allowlisted_player_ids=allowlisted,
            bound_orchestrators=self._bound_orchestrators_snapshot(),
            pool=self._pool,
            pool_dequeue_predicate=self._pool_dequeue_predicate,
            completion_history=self._history_for_shell(shell).recent(),
        )

    def set_freeze_armed(self, shell: ShellContextKey, *, freeze_armed: bool) -> None:
        self.on_shell_context(shell)
        self._freeze_state.set_freeze_armed(shell.game_id, freeze_armed=freeze_armed)
        self._apply_gates_for_game(shell.game_id)
        self._redispatch_after_gate_change(shell.game_id)

    def set_allowlist(self, shell: ShellContextKey, player_ids: frozenset[int]) -> None:
        self.on_shell_context(shell)
        self._freeze_state.set_allowlisted_player_ids(shell, player_ids)
        self._apply_gates_for_game(shell.game_id)
        self._redispatch_after_gate_change(shell.game_id)

    def single_step(self, shell: ShellContextKey) -> bool:
        """Release exactly one pool work item for ``shell``; return whether release was armed."""
        if not self._freeze_state.freeze_armed_for_game(shell.game_id):
            return False
        self.on_shell_context(shell)
        with self._lock:
            self._single_step_shell = shell
            self._single_step_grants_remaining = 1
        self._redispatch_after_gate_change(shell.game_id)
        return True

    def stream_allowlisted_player_ids(self, shell: ShellContextKey) -> frozenset[int] | None:
        """When freeze is armed, return allowlisted players for stream narrowing."""
        if not self._freeze_state.freeze_armed_for_game(shell.game_id):
            return None
        return self._freeze_state.allowlisted_player_ids(shell)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._bound_orchestrators.clear()
            self._histories.clear()
            self._single_step_shell = None
            self._single_step_grants_remaining = 0
            self._active_game_id = None
            self._last_shell_context = None
        self._freeze_state.reset_for_tests()
        if self._pool is not None:
            self._pool.set_dequeue_predicate(None)

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

    def _apply_gates_for_game(self, game_id: int) -> None:
        for bound in self._bound_orchestrators_snapshot():
            if bound.game_id == game_id:
                bound.orchestrator.set_dispatch_gate(self._dispatch_gate)

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
        for bound in self._bound_orchestrators_snapshot():
            shell = ShellContextKey(
                game_id=bound.game_id,
                perspective=bound.perspective,
                turn=bound.ambient_turn,
            )
            ancestor_turns = self._ancestor_turns_for_shell(shell)
            if scope_in_diagnostic_scope(
                scope,
                game_id=shell.game_id,
                perspective=shell.perspective,
                ancestor_turns=ancestor_turns,
            ):
                return shell
        return None

    def _is_scope_frozen(self, scope: ComputeScope, shell: ShellContextKey) -> bool:
        if not self._freeze_state.freeze_armed_for_game(shell.game_id):
            return False
        allowlisted = self._freeze_state.allowlisted_player_ids(shell)
        player_id = player_id_from_scope(scope)
        if player_id is None:
            return True
        return player_id not in allowlisted

    def _dispatch_gate(self, node: ComputeNodeRun) -> bool:
        with self._lock:
            if self._single_step_grants_remaining > 0 and self._single_step_shell is not None:
                ancestor_turns = self._ancestor_turns_for_shell(self._single_step_shell)
                if scope_in_diagnostic_scope(
                    node.scope,
                    game_id=self._single_step_shell.game_id,
                    perspective=self._single_step_shell.perspective,
                    ancestor_turns=ancestor_turns,
                ):
                    return True
        shell = self._scope_matches_active_shell(node.scope)
        if shell is None:
            return True
        return not self._is_scope_frozen(node.scope, shell)

    def _pool_dequeue_predicate(self, item: PoolWorkItem) -> bool:
        with self._lock:
            if self._single_step_grants_remaining > 0 and self._single_step_shell is not None:
                ancestor_turns = self._ancestor_turns_for_shell(self._single_step_shell)
                if scope_in_diagnostic_scope(
                    item.scope,
                    game_id=self._single_step_shell.game_id,
                    perspective=self._single_step_shell.perspective,
                    ancestor_turns=ancestor_turns,
                ):
                    self._single_step_grants_remaining -= 1
                    if self._single_step_grants_remaining == 0:
                        self._single_step_shell = None
                    return True
        shell = self._scope_matches_active_shell(item.scope)
        if shell is None:
            return True
        return not self._is_scope_frozen(item.scope, shell)

    def _on_step_complete(
        self,
        scope: ComputeScope,
        node: ComputeNodeRun,
        step_kind: str,
        surface: CompletionSurface,
        terminal_state: CompletionTerminalState,
    ) -> None:
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
