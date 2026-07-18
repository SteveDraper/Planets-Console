"""Orchestrator listener binding for compute diagnostics.

Owns bind/unbind of orchestrator observers that feed the concurrency timeline,
plus every handler those observers invoke: the dispatch gate and commit hook,
step-complete, ready, inline-start, and lifecycle forwarding onto the timeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext
from api.compute.diagnostics.bindings import BoundOrchestrator
from api.compute.diagnostics.history import CompletionSurface, CompletionTerminalState
from api.compute.diagnostics.profile_steps import profile_step_at, profile_step_is_inline
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.orchestrator_observers import LifecycleEventKind
from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.scope import ComputeScope
from api.config import get_config

if TYPE_CHECKING:
    from api.compute.diagnostics.controller import ComputeDiagnosticsController


class DiagnosticsOrchestratorBindMixin:
    """Register / unregister orchestrator observers, and their handlers.

    Owns every callback registered by :meth:`bind_orchestrator`: the dispatch
    gate/commit pair, step-complete, ready, inline-start, and lifecycle.
    """

    def bind_orchestrator(
        self: ComputeDiagnosticsController,
        orchestrator: ComputeOrchestrator,
        ctx: AnalyticQueryContext | None = None,
    ) -> None:
        """Register the diagnostics observer on ``orchestrator``.

        ``ctx`` is unavailable for a singleton bind at process startup (the
        orchestrator serves many callers, each with its own leader context); use
        placeholder shell fields in that case. Start-frozen arming needs a real
        game id and is skipped until a caller context establishes one via
        :meth:`on_shell_context`.
        """
        if not self.is_enabled():
            return
        self.ensure_wired()
        # Process-wide singleton has no single shell; ``None`` matches every shell
        # in snapshot / concurrency / single-step filters.
        game_id = ctx.game_id if ctx is not None else None
        perspective = ctx.perspective if ctx is not None else None
        ambient_turn = ctx.ambient_turn if ctx is not None else 0
        # Arm before registering the dispatch gate so early submits see freeze.
        cfg = get_config()
        if ctx is not None and cfg.compute_diagnostics and cfg.compute_diagnostics_start_frozen:
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
        unregister_dispatch_gate = orchestrator.observers.register_dispatch_gate(
            lambda node, _orch_id=registration_id: self._dispatch_gate(
                node,
                orchestrator_id=_orch_id,
            )
        )
        unregister_dispatch_commit = orchestrator.observers.register_dispatch_commit_hook(
            lambda node, _orch_id=registration_id: self._commit_single_step_dispatch(
                node,
                orchestrator_id=_orch_id,
            )
        )

        def _on_step_complete_listener(
            scope,
            node,
            step_kind,
            step_index,
            surface,
            terminal_state,
            _orch_id=registration_id,
        ):
            self._on_step_complete(
                scope,
                node,
                step_kind,
                step_index,
                surface,
                terminal_state,
                orchestrator_id=_orch_id,
            )

        unregister_step_complete = orchestrator.observers.register_step_complete_listener(
            _on_step_complete_listener
        )
        unregister_ready = orchestrator.observers.register_ready_listener(
            lambda scope, node, _orch_id=registration_id: self._on_node_ready(
                scope,
                node,
                orchestrator_id=_orch_id,
            )
        )
        unregister_ready_queue = orchestrator.observers.register_ready_queue_listener(
            self._timeline.bind_ready_queue_listener(
                orchestrator_id=registration_id,
                game_id=game_id,
                perspective=perspective,
                fallback_id=id(orchestrator),
            )
        )
        unregister_inline_start = orchestrator.observers.register_inline_start_listener(
            lambda scope, node, step_kind, _orch_id=registration_id: self._on_inline_start(
                scope,
                node,
                step_kind,
                orchestrator_id=_orch_id,
            )
        )
        unregister_lifecycle = orchestrator.observers.register_lifecycle_listener(
            lambda kind, scope, node, step_kind, step_index, detail, _orch_id=registration_id: (
                self._on_lifecycle(
                    kind,
                    scope,
                    node,
                    step_kind,
                    step_index,
                    detail,
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
                    unregister_ready()
                    unregister_ready_queue()
                    unregister_inline_start()
                    unregister_lifecycle()
                    return
            self._bound_orchestrators.append(
                BoundOrchestrator(
                    orchestrator=orchestrator,
                    game_id=game_id,
                    perspective=perspective,
                    ambient_turn=ambient_turn,
                    unregister_dispatch_gate=unregister_dispatch_gate,
                    unregister_dispatch_commit_hook=unregister_dispatch_commit,
                    unregister_step_complete_listener=unregister_step_complete,
                    unregister_ready_listener=unregister_ready,
                    unregister_ready_queue_listener=unregister_ready_queue,
                    unregister_inline_start_listener=unregister_inline_start,
                    unregister_lifecycle_listener=unregister_lifecycle,
                )
            )

    def unbind_orchestrator(
        self: ComputeDiagnosticsController,
        orchestrator: ComputeOrchestrator,
    ) -> None:
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
        bound.unregister_ready_listener()
        bound.unregister_ready_queue_listener()
        bound.unregister_inline_start_listener()
        bound.unregister_lifecycle_listener()
        orch_key = registration_id if registration_id is not None else id(orchestrator)
        self._timeline.clear_orchestrator_ready_depth(orch_key)

    def _dispatch_gate(
        self: ComputeDiagnosticsController,
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
        self: ComputeDiagnosticsController,
        node: ComputeNodeRun,
        *,
        orchestrator_id: int | None,
    ) -> bool:
        """Return whether an armed single-step may select ``node`` (no consume)."""
        if self._single_step.dispatch_slots_remaining <= 0:
            return False
        return self._single_step_may_release(
            node.scope,
            priority_band=node.priority_band,
            orchestrator_id=orchestrator_id,
        )

    def _commit_single_step_dispatch(
        self: ComputeDiagnosticsController,
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
            if self._single_step.dispatch_slots_remaining <= 0:
                return True
            if not self._single_step_may_release(
                node.scope,
                priority_band=node.priority_band,
                orchestrator_id=orchestrator_id,
            ):
                return False
            self._single_step.dispatch_slots_remaining -= 1
            if self._node_current_step_is_inline(node):
                self._single_step.clear()
            return True

    def _node_current_step_is_inline(
        self: ComputeDiagnosticsController,
        node: ComputeNodeRun,
    ) -> bool:
        """Return whether ``node``'s current profile step uses the inline backend."""
        return profile_step_is_inline(node.scope.analytic_id, node.profile_step_index)

    def _on_step_complete(
        self: ComputeDiagnosticsController,
        scope: ComputeScope,
        node: ComputeNodeRun,
        step_kind: str,
        step_index: int,
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
                step_index=step_index,
                orchestrator_id=orchestrator_id,
            )
            self._reconcile_orphan_in_flight()
        shell = self._scope_matches_active_shell(scope)
        if shell is None:
            return
        step_spec = profile_step_at(scope.analytic_id, node.profile_step_index)
        if step_spec is not None and step_spec.step_kind != step_kind:
            return
        if step_spec is None:
            backend = "inline" if surface == "inline" else None
        else:
            backend = "inline" if surface == "inline" else step_spec.backend
        self._timeline.record_finish(
            shell,
            scope=scope,
            node=node,
            step_kind=step_kind,
            step_index=step_index,
            surface=surface,
            terminal_state=terminal_state,
            orchestrator_id=orchestrator_id,
            backend=backend,
        )

    def _on_node_ready(
        self: ComputeDiagnosticsController,
        scope: ComputeScope,
        node: ComputeNodeRun,
        *,
        orchestrator_id: int | None = None,
    ) -> None:
        shell = self._scope_matches_active_shell(scope)
        if shell is None:
            return
        step_spec = profile_step_at(scope.analytic_id, node.profile_step_index)
        # Cache-only gauges: ready listeners drain under paths that may hold the scores
        # scheduler lock (enqueue -> submit -> drain). Live orch sampling deadlocks.
        self._timeline.record(
            shell,
            kind="ready",
            scope=scope,
            orchestrator_id=orchestrator_id,
            step_kind=step_spec.step_kind if step_spec is not None else None,
            step_index=node.step_index,
            priority_band=node.priority_band,
            backend=step_spec.backend if step_spec is not None else None,
            sample_ready_from_orchestrators=False,
        )

    def _on_inline_start(
        self: ComputeDiagnosticsController,
        scope: ComputeScope,
        node: ComputeNodeRun,
        step_kind: str,
        *,
        orchestrator_id: int | None = None,
    ) -> None:
        shell = self._scope_matches_active_shell(scope)
        if shell is None:
            return
        # Cache-only gauges: inline_start runs before heavy ensure work and must not
        # nest into other orchestrators' locks (same ABBA risk as ready/finish).
        self._timeline.record(
            shell,
            kind="inline_start",
            scope=scope,
            orchestrator_id=orchestrator_id,
            step_kind=step_kind,
            step_index=node.step_index,
            priority_band=node.priority_band,
            backend="inline",
            open_execution=True,
            sample_ready_from_orchestrators=False,
        )

    def _on_lifecycle(
        self: ComputeDiagnosticsController,
        kind: LifecycleEventKind,
        scope: ComputeScope,
        node: ComputeNodeRun | None,
        step_kind: str | None,
        step_index: int | None,
        detail: Mapping[str, object],
        *,
        orchestrator_id: int | None = None,
    ) -> None:
        shell = self._scope_matches_active_shell(scope)
        if shell is None:
            return
        priority_band = node.priority_band if node is not None else None
        self._timeline.record_lifecycle(
            shell,
            kind=kind,
            scope=scope,
            orchestrator_id=orchestrator_id,
            step_kind=step_kind,
            step_index=step_index,
            priority_band=priority_band,
            detail=dict(detail),
        )
