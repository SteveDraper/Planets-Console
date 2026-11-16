"""A malformed step result on an execution whose result is not read.

An epoch-stale node is retried before its result is read, so a malformed
result does not change that outcome.
"""

from __future__ import annotations

from api.compute import ComputeOrchestrator, ComputeRequest, build_compute_registry

from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.fixtures.export_framework.diamond_exports import SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)
from tests.test_compute_orchestrator import (
    _compute_scope,
    _export_scope,
    _pool_compute_registration,
    _RecordingPersistencePolicy,
)

_MALFORMED_RESULT = {"outcome": "not-an-outcome"}


def _running_pool_node(sample_turn):
    ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    scope = _compute_scope(SHARED_ID, _export_scope(sample_turn))
    persistence = _RecordingPersistencePolicy()

    def pool_submitter(node, step, **_kwargs) -> None:
        del node, step

    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (
                _pool_compute_registration(
                    SHARED_ID, backend="thread", persistence_policy=persistence
                ),
            )
        ),
        pool_submitter=pool_submitter,
    )
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    assert orchestrator.nodes[scope].state == "running"
    assert orchestrator.nodes[scope].generation_at_submit == 0
    return orchestrator, ctx, scope, persistence


def test_malformed_result_of_an_epoch_stale_step_is_retried(sample_turn):
    orchestrator, ctx, scope, persistence = _running_pool_node(sample_turn)
    persistence.invalidate(ctx, scope)

    complete_running_pool_step(orchestrator, scope, result_wire=_MALFORMED_RESULT)

    # The retry re-dispatches the same execution at the new generation.
    node = orchestrator.nodes[scope]
    assert node.error is None
    assert node.state == "running"
    assert node.generation_at_submit == persistence.generation
    assert orchestrator.metrics.epoch_discards == 1
    assert persistence.persist_calls == []
