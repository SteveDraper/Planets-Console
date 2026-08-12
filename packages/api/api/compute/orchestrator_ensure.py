"""Orchestration-plane ensure: satisfied short-circuit or submit+wait."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from api.compute.constants import ENSURE_WAIT_TIMEOUT_SEC
from api.compute.orchestrator_pending import PendingInlineExecution, PendingPoolSubmission
from api.compute.orchestrator_state import ComputeHandle, ComputeRequest

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator


def _wait_ensure_handle(
    handle: ComputeHandle,
    *,
    timeout: float | None,
) -> ComputeHandle:
    if handle._node.is_terminal:
        error = handle.error
        if error is not None:
            raise error
        return handle
    return handle.wait(timeout=timeout)


class OrchestratorEnsureMixin:
    """Public ensure entry for designated in-process callers (#204, #202)."""

    def ensure_scope(
        self: ComputeOrchestrator,
        request: ComputeRequest,
        *,
        timeout: float | None = ENSURE_WAIT_TIMEOUT_SEC,
    ) -> ComputeHandle:
        """Bring ``request.scope`` to terminal quality on the orchestration plane.

        If durable satisfaction already holds, returns a terminal handle without
        blocking on pool work (submit may still short-circuit to ``complete``).
        Otherwise submits with the caller's ``force_fresh`` (default ``False`` per
        F1) and waits until the scope is terminal or ``timeout``.

        When durable satisfaction fails but a terminal node remains (hollow after
        wipe / invalidate), that cache-hit node is dropped under the orchestrator
        lock before submit so ``force_fresh=False`` plans fresh work instead of
        attaching to a stale ``complete``. ``_plan_and_register`` also drops
        hollow terminals on planned dependency scopes (same wipe class -- root-only
        eviction left chains ready against empty durable state). Explicit
        ``force_fresh=True`` remains the wipe / reschedule wake path; ensure does
        not silently set it.

        Defaults match grill locks: cold ensure → ``interactive_ensure`` priority.
        Pool workers and leaf ``run_step`` must never call this.
        """
        handles = self.ensure_scopes((request,), timeout=timeout)
        return handles[0]

    def ensure_scopes(
        self: ComputeOrchestrator,
        requests: Sequence[ComputeRequest],
        *,
        timeout: float | None = ENSURE_WAIT_TIMEOUT_SEC,
    ) -> tuple[ComputeHandle, ...]:
        """Bring many scopes to terminal quality, submitting all before waiting.

        Same per-request semantics as :meth:`ensure_scope` (satisfaction
        short-circuit, hollow-terminal drop). The returned tuple is aligned to
        ``requests``: ``handles[i]`` is the terminal handle for ``requests[i]``.
        Batch table/map callers fan out to N player scopes and must not wait on
        the first before submitting the rest -- that would serialize cross-player
        DAG work.
        """
        if not requests:
            return ()

        handles_by_index: dict[int, ComputeHandle] = {}
        unsatisfied: list[tuple[int, ComputeRequest]] = []
        for index, request in enumerate(requests):
            bundle = self._require_bundle(request)
            ctx = self._ctx_for_bundle(bundle)
            registration = self._compute_registry[request.scope.analytic_id]
            already_satisfied = registration.persistence_policy.is_satisfied(
                ctx,
                request.scope,
            )
            if already_satisfied:
                handles_by_index[index] = self.submit(request)
            else:
                unsatisfied.append((index, request))

        if unsatisfied:
            pending_inline: list[PendingInlineExecution] = []
            pending_pool: list[PendingPoolSubmission] = []
            with self._condition:
                for index, request in unsatisfied:
                    existing = self._nodes.get(request.scope)
                    # Hollow terminal: durable gone, node still complete/failed. Drop so
                    # default force_fresh=False can plan fresh work (F1). Leave non-terminal
                    # nodes alone for attach / singleflight; parked wake stays explicit.
                    if existing is not None and existing.is_terminal and not request.force_fresh:
                        self._replace_terminal_node(existing)
                    submission = self._submit_locked(request, wake_if_parked_only=False)
                    if submission is None:
                        raise RuntimeError(
                            "ensure submit_locked returned None without wake_if_parked_only"
                        )
                    handle, inlines, pools = submission
                    handles_by_index[index] = handle
                    pending_inline.extend(inlines)
                    pending_pool.extend(pools)
            self._execute_pending_inlines(tuple(pending_inline))
            self._flush_pending_pool_submissions(tuple(pending_pool))
            self._observers.drain_post_lock_callbacks()

        return tuple(
            _wait_ensure_handle(handles_by_index[index], timeout=timeout)
            for index in range(len(requests))
        )
