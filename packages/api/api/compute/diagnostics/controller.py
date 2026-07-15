"""Compute diagnostics observer and freeze control."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.exports.registry import EXPORT_REGISTRY
from api.compute.diagnostics.bindings import BoundOrchestrator
from api.compute.diagnostics.concurrency_recorder import ConcurrencyTimelineRecorder
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
    clear_in_flight_for_step,
    filter_live_in_flight,
    in_flight_from_pool_item,
    orphan_in_flight_object_ids,
    remove_in_flight_by_object_ids,
    running_in_flight_keys_for_nodes,
)
from api.compute.diagnostics.profile_steps import (
    profile_step_at,
    profile_step_is_inline,
    registration_step_kind,
)
from api.compute.diagnostics.scope import (
    collect_diagnostic_ancestor_turns,
    player_id_from_scope,
    scope_in_diagnostic_scope,
)
from api.compute.diagnostics.single_step_preview import (
    SingleStepArm,
    SingleStepDisabledReason,
    SingleStepPreview,
    find_held_focus_pool_item,
    has_running_focus_work,
    preview_focus_ready_dispatch,
    resolve_single_step_preview,
    single_step_pin_matches,
)
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator, OrchestratorNodeSnapshot
from api.compute.pools import (
    ComputeWorkerPool,
    PoolWorkItem,
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


def compute_diagnostics_timeline_capacity() -> int:
    """Return configured concurrency-timeline ring capacity (at least 1)."""
    return max(1, get_config().compute_diagnostics_timeline_capacity)


class ComputeDiagnosticsController:
    """Analytic-agnostic observer and freeze controller for compute orchestration."""

    def __init__(self) -> None:
        self._freeze_state = ComputeDiagnosticsFreezeState()
        self._histories: dict[ShellContextKey, ComputeCompletionHistory] = {}
        self._in_flight: list[InFlightPoolExecution] = []
        self._bound_orchestrators: list[BoundOrchestrator] = []
        self._lock = threading.Lock()
        self._single_step = SingleStepArm()
        self._pool: ComputeWorkerPool | None = None
        self._wired = False
        self._active_game_id: int | None = None
        self._last_shell_context: ShellContextKey | None = None
        self._timeline = ConcurrencyTimelineRecorder(
            timeline_capacity=compute_diagnostics_timeline_capacity,
            bound_orchestrators=self._bound_orchestrators_snapshot,
            in_flight_records=self._in_flight_snapshot,
            global_queue_depth=self._global_queue_depth,
            configured_workers=self._configured_workers,
            ancestor_turns=self._ancestor_turns_for_shell,
            history_for_shell=self._history_for_shell,
            active_shell=self._active_shell_context,
        )

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
        pool.set_on_item_enqueued(self._on_pool_item_enqueued)
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
        unregister_ready = orchestrator.register_ready_listener(
            lambda scope, node, _orch_id=registration_id: self._on_node_ready(
                scope,
                node,
                orchestrator_id=_orch_id,
            )
        )
        unregister_ready_queue = orchestrator.register_ready_queue_listener(
            self._timeline.bind_ready_queue_listener(
                orchestrator_id=registration_id,
                game_id=ctx.game_id,
                perspective=ctx.perspective,
                fallback_id=id(orchestrator),
            )
        )
        unregister_inline_start = orchestrator.register_inline_start_listener(
            lambda scope, node, step_kind, _orch_id=registration_id: self._on_inline_start(
                scope,
                node,
                step_kind,
                orchestrator_id=_orch_id,
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
                    unregister_ready_listener=unregister_ready,
                    unregister_ready_queue_listener=unregister_ready_queue,
                    unregister_inline_start_listener=unregister_inline_start,
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
        bound.unregister_ready_listener()
        bound.unregister_ready_queue_listener()
        bound.unregister_inline_start_listener()
        orch_key = registration_id if registration_id is not None else id(orchestrator)
        self._timeline.clear_orchestrator_ready_depth(orch_key)

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
        remote_futures = self._pool.snapshot_remote_futures() if self._pool is not None else ()
        remote_executor_probe = (
            self._pool.remote_executor_probe() if self._pool is not None else None
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
            concurrency_timeline=self._timeline.recent(shell),
            global_in_flight_count=len(self._in_flight_snapshot()),
            configured_workers=self._configured_workers(),
            remote_futures=remote_futures,
            remote_executor_probe=remote_executor_probe,
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
        held = self._preview_held_focus_pool_item(shell, pool_queue_items=pool_queue_items)
        ready = self._preview_focus_ready_dispatch(shell)
        return resolve_single_step_preview(
            freeze_armed=self._freeze_state.freeze_armed_for_game(shell.game_id),
            allowlist_empty=not self._freeze_state.allowlisted_player_ids(shell),
            held=held,
            ready=ready,
            has_running_focus=lambda: self._has_running_focus_work(shell),
        )

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
            self._single_step.arm_from_preview(shell, preview)
        if preview.source == "held":
            self._pool_hold_notify()
            return True
        self._redispatch_single_step_target(
            shell.game_id,
            orchestrator_id=preview.orchestrator_id,
        )
        with self._lock:
            if self._single_step.dispatch_slots_remaining > 0:
                # No commit accepted the armed slot -- clear so observers are not left
                # with a stale grant that nothing will consume.
                self._single_step.clear()
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
            self._single_step.clear()
            self._active_game_id = None
            self._last_shell_context = None
        self._timeline.clear()
        for entry in bound:
            entry.unregister_dispatch_gate()
            entry.unregister_dispatch_commit_hook()
            entry.unregister_step_complete_listener()
            entry.unregister_ready_listener()
            entry.unregister_ready_queue_listener()
            entry.unregister_inline_start_listener()
        self._freeze_state.reset_for_tests()
        if self._pool is not None:
            self._pool.set_dequeue_predicate(None)
            self._pool.set_on_item_dequeued(None)
            self._pool.set_on_item_enqueued(None)
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

    def timeline_recent(self, shell: ShellContextKey) -> tuple:
        """Return recent concurrency timeline events for ``shell`` (tests / snapshot)."""
        return self._timeline.recent(shell)

    def _global_queue_depth(self) -> int:
        if self._pool is not None:
            return len(self._pool.snapshot_work_queue())
        return 0

    def _configured_workers(self) -> int:
        return self._pool.worker_count if self._pool is not None else 0

    def _bound_orchestrators_snapshot(self) -> tuple[BoundOrchestrator, ...]:
        with self._lock:
            return tuple(self._bound_orchestrators)

    def _in_flight_snapshot(self) -> tuple[InFlightPoolExecution, ...]:
        with self._lock:
            return tuple(self._in_flight)

    def _running_in_flight_keys(self) -> set[InFlightExecutionKey]:
        """Return keys for bound orchestrator nodes currently in ``running`` state."""
        running_keys: set[InFlightExecutionKey] = set()

        def step_kind_for_node(node: OrchestratorNodeSnapshot) -> str | None:
            return registration_step_kind(node.scope.analytic_id, node.profile_step_index)

        for bound in self._bound_orchestrators_snapshot():
            orch_id = bound.orchestrator.pool_registration_id
            if orch_id is None:
                continue
            view = bound.orchestrator.diagnostics_snapshot()
            running_keys.update(
                running_in_flight_keys_for_nodes(
                    orchestrator_id=orch_id,
                    nodes=view.nodes,
                    step_kind_for_node=step_kind_for_node,
                )
            )
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

    def _active_shell_context(self) -> ShellContextKey | None:
        with self._lock:
            return self._last_shell_context

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
        return has_running_focus_work(
            self._bound_orchestrators_snapshot(),
            shell,
            ancestor_turns=self._ancestor_turns_for_shell(shell),
            scope_in_focus=lambda scope: self._scope_in_focus(scope, shell),
        )

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

        return find_held_focus_pool_item(queue_items, is_focus_item=is_focus_item)

    def _preview_focus_ready_dispatch(self, shell: ShellContextKey) -> SingleStepPreview | None:
        """Return the focus ready node single-step would dispatch first, if any.

        Across bound orchestrators, pick by the same priority-band / initial-step
        rules as the global pool. Ties keep bind order then ready-queue order.
        """
        return preview_focus_ready_dispatch(
            self._bound_orchestrators_snapshot(),
            shell,
            ancestor_turns=self._ancestor_turns_for_shell(shell),
            scope_in_focus=lambda scope: self._scope_in_focus(scope, shell),
        )

    def _scope_matches_single_step_shell(self, scope: ComputeScope) -> bool:
        if self._single_step.shell is None:
            return False
        ancestor_turns = self._ancestor_turns_for_shell(self._single_step.shell)
        return scope_in_diagnostic_scope(
            scope,
            game_id=self._single_step.shell.game_id,
            perspective=self._single_step.shell.perspective,
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
        shell = self._single_step.shell
        if shell is None:
            return False
        if not single_step_pin_matches(
            target_scope=self._single_step.target_scope,
            target_priority_band=self._single_step.target_priority_band,
            target_orchestrator_id=self._single_step.target_orchestrator_id,
            scope=scope,
            priority_band=priority_band,
            orchestrator_id=orchestrator_id,
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
        if self._single_step.dispatch_slots_remaining <= 0:
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

    def _node_current_step_is_inline(self, node: ComputeNodeRun) -> bool:
        """Return whether ``node``'s current profile step uses the inline backend."""
        return profile_step_is_inline(node.scope.analytic_id, node.profile_step_index)

    def _pool_item_is_runnable(self, item: PoolWorkItem) -> bool:
        """Return whether ``item`` may dequeue; never consumes single-step grants."""
        with self._lock:
            if self._single_step.grants_remaining > 0 and self._single_step_may_release(
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

    def _on_pool_item_dequeued(self, item: PoolWorkItem, queue_depth: int = 0) -> None:
        """Record in-flight work and consume a single-step grant when applicable.

        Invoked under the pool lock after pop so concurrent workers cannot both
        observe a remaining grant before either burns it.
        """
        with self._lock:
            self._in_flight.append(in_flight_from_pool_item(item))
            if self._single_step.grants_remaining > 0:
                if self._single_step_may_release(
                    item.scope,
                    priority_band=item.priority_band,
                    orchestrator_id=item.orchestrator_id,
                ):
                    self._single_step.grants_remaining -= 1
                    if self._single_step.grants_remaining == 0:
                        self._single_step.clear()
        shell = self._scope_matches_active_shell(item.scope)
        if shell is None:
            return
        # Release controller lock before timeline recording (recorder may sample
        # in-flight under ``_lock`` via snapshot callbacks).
        self._timeline.record(
            shell,
            kind="start",
            scope=item.scope,
            orchestrator_id=item.orchestrator_id,
            step_kind=item.step_kind,
            step_index=item.step_index,
            priority_band=item.priority_band,
            backend=item.backend,
            open_execution=True,
            global_queue_depth=queue_depth,
        )

    def _on_pool_item_enqueued(self, item: PoolWorkItem, queue_depth: int) -> None:
        """Record a pool enqueue timeline event when the scope matches the operator shell."""
        shell = self._scope_matches_active_shell(item.scope)
        if shell is None:
            return
        self._timeline.record(
            shell,
            kind="enqueue",
            scope=item.scope,
            orchestrator_id=item.orchestrator_id,
            step_kind=item.step_kind,
            step_index=item.step_index,
            priority_band=item.priority_band,
            backend=item.backend,
            global_queue_depth=queue_depth,
        )

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
            clear_in_flight_for_step(
                self._in_flight,
                scope,
                step_kind=step_kind,
                step_index=step_index,
                orchestrator_id=orchestrator_id,
            )

    def _on_node_ready(
        self,
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
        self,
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
            surface=surface,
            terminal_state=terminal_state,
            orchestrator_id=orchestrator_id,
            backend=backend,
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
