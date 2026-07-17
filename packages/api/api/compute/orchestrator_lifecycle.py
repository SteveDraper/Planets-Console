"""Lifecycle emission helpers for ComputeOrchestrator.

Owns park, epoch-retry, persist-deferred recovery, and force_fresh lifecycle
detail assembly. Emits wire-ready scope keys on lifecycle details so listeners
need not reconstruct ``ComputeScope`` from dict fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.compute.orchestrator_observers import LifecycleEventKind
from api.compute.persistence import PersistDependencyRecovery
from api.compute.scope import format_compute_scope_key

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator, ComputeRequest


class OrchestratorLifecycleMixin:
    """Park, epoch-retry, persist-deferred, and force_fresh lifecycle emission."""

    def _emit_force_fresh_lifecycle(
        self: ComputeOrchestrator,
        *,
        kind: LifecycleEventKind,
        node: ComputeNodeRun,
        request: ComputeRequest,
    ) -> None:
        """Record force_fresh replace vs attach (caller holds the orchestrator lock)."""
        self._observers.notify_lifecycle(
            kind,
            node.scope,
            node=node,
            step_index=node.step_index,
            detail={
                "reason": "submit_force_fresh",
                "priorState": node.state,
                "priorProfileStepIndex": node.profile_step_index,
                "wasRunning": node.state == "running",
                "entryStepKind": request.step_kind,
                "priorityBand": request.priority_band,
            },
        )

    def _retry_step_after_epoch_bump(self: ComputeOrchestrator, node: ComputeNodeRun) -> None:
        self._metrics.epoch_discards += 1
        prior_step_index = node.step_index
        prior_generation = node.generation_at_submit
        current_generation = self._current_invalidation_generation(node)
        node.generation_at_submit = None
        node.state = "ready"
        node.execution_sealed = False
        self._enqueue_ready(node.scope)
        self._observers.notify_ready(node)
        self._observers.notify_lifecycle(
            "epoch_retry",
            node.scope,
            node=node,
            step_index=prior_step_index,
            detail={
                "reason": "invalidation_generation_bump",
                "priorProfileStepIndex": node.profile_step_index,
                "generationAtSubmit": prior_generation,
                "currentGeneration": current_generation,
            },
        )
        # Never call pool.submit under the orchestrator lock (deadlocks with workers).
        self._observers.schedule_post_lock(self.dispatch_ready_work)

    def _recover_after_persist_deferred(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        recovery: PersistDependencyRecovery,
    ) -> None:
        """Recover onto ``waiting_deps`` and optionally force_fresh a dependency.

        Analytic ``PersistencePolicy.persist`` raises :class:`PersistDeferredError`
        when a durable write cannot complete until a dependency re-closes.
        Failing the node left dependents waiting with no wake for background DAG
        nodes (no table-stream controller). Force-freshing the declared dependency
        reopens the ENSURE edge; when it completes, readiness promotes this node.
        Persist-deferred is a real dependency wait -- not soft ``parked``.
        """
        priority_band = node.priority_band
        bundle = node.bundle
        with self._condition:
            if node.state != "running":
                return
            prior_step_index = node.step_index
            node.generation_at_submit = None
            node.error = None
            node.state = "waiting_deps"
            node.execution_sealed = False
            self._dequeue_ready(node.scope)
            self._metrics.epoch_discards += 1
            self._observers.notify_lifecycle(
                "persist_deferred",
                node.scope,
                node=node,
                step_index=prior_step_index,
                detail={
                    "reason": "persist_deferred",
                    "priorProfileStepIndex": node.profile_step_index,
                    "relatedScopeKey": format_compute_scope_key(recovery.dependency_scope),
                    "forceFresh": recovery.force_fresh,
                    "dependencyStepKind": recovery.step_kind,
                    "priorityBand": priority_band,
                },
            )

        if not recovery.force_fresh:
            return

        dependency_scope = recovery.dependency_scope
        step_kind = recovery.step_kind

        def _force_fresh_dependency() -> None:
            from api.compute.orchestrator import ComputeRequest

            self.submit(
                ComputeRequest(
                    scope=dependency_scope,
                    priority_band=priority_band,
                    force_fresh=True,
                    step_kind=step_kind,
                    bundle=bundle,
                )
            )

        self._observers.schedule_post_lock(_force_fresh_dependency)

    def _park_node_step(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        *,
        reason: str | None,
    ) -> None:
        """Park a non-progressing step until an explicit ``force_fresh`` wake.

        Soft park does **not** complete the node (dependents stay blocked), but still
        publishes an immutable outcome snapshot so scores can reattach empty stream
        delivery without unlocking same-turn fleet.
        """
        if node.state != "running":
            return

        prior_step_index = node.step_index
        node.generation_at_submit = None
        node.error = None
        node.state = "parked"
        node.execution_sealed = False
        self._dequeue_ready(node.scope)
        self._observers.notify_lifecycle(
            "step_parked",
            node.scope,
            node=node,
            step_index=prior_step_index,
            detail={
                "reason": reason or "step_parked",
                "priorProfileStepIndex": node.profile_step_index,
            },
        )
        self._observers.notify_scope_outcome(node)

    def _maybe_wake_parked_node(self: ComputeOrchestrator, node: ComputeNodeRun) -> None:
        """Re-ready a soft-parked node on explicit ``force_fresh`` attach."""
        if node.state != "parked":
            return
        node.generation_at_submit = None
        node.execution_sealed = False
        if self._deps_complete(node):
            node.state = "ready"
            self._enqueue_ready(node.scope)
            self._observers.notify_ready(node)
        else:
            node.state = "waiting_deps"
            self._dequeue_ready(node.scope)
