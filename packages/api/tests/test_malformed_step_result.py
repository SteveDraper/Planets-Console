"""A step that returns a malformed result wire.

On a current execution the result is read, and a malformed one fails the node
with ``MalformedStepResultError``, exactly as a step that raises, so its
dependents and waiters settle. An epoch-stale node is retried before its
result is read, so a malformed result does not change that outcome.
"""

from __future__ import annotations

import pytest
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    AnalyticComputeProfile,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeStepSpec,
    build_compute_registry,
)
from api.compute.wire import MalformedStepResultError

from tests.compute_orchestrator_fixtures import (
    ROW_SCOPE_KEY,
    RecordingPersistencePolicy,
    catalog_entry,
    inline_compute_registration,
    make_compute_scope,
    make_export_scope,
    pool_compute_registration,
)
from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.fixtures.export_framework.diamond_exports import (
    BRANCH_B_ID,
    BRANCH_C_ID,
    ROOT_ID,
    SHARED_ID,
)
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)

_MALFORMED_RESULT = {"outcome": "not-an-outcome"}

_MALFORMED_RESULTS = (
    pytest.param(_MALFORMED_RESULT, id="unknown-outcome"),
    pytest.param({"outcome": "park", "parkReason": 7}, id="non-string-park-reason"),
    pytest.param({"outcome": "waiting_deps", "waitRecovery": {}}, id="untyped-wait-recovery"),
)


def _record_step_completions(orchestrator: ComputeOrchestrator) -> list[str]:
    completions: list[str] = []

    def on_step_complete(_scope, _node, step_kind, _step_index, surface, terminal_state) -> None:
        completions.append(f"{surface}:{step_kind}:{terminal_state}")

    orchestrator.observers.register_step_complete_listener(on_step_complete)
    return completions


def _inline_registration_returning(
    analytic_id: str, result_wire: object
) -> TurnAnalyticRegistration:
    return TurnAnalyticRegistration(
        catalog_entry=catalog_entry(analytic_id),
        compute=lambda _ctx: {"analyticId": analytic_id},
        export_catalog=empty_export_catalog_for(analytic_id),
        scope_key_spec=ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
        ),
        persistence_policy=RecordingPersistencePolicy(),
        build_step_job_wires=(("materialize", lambda _scope, **_kwargs: {}),),
        run_steps=(("materialize", lambda _job: result_wire),),
    )


def _running_pool_node(sample_turn):
    ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    scope = make_compute_scope(SHARED_ID, make_export_scope(sample_turn))
    persistence = RecordingPersistencePolicy()

    def pool_submitter(node, step, **_kwargs) -> None:
        del node, step

    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (
                pool_compute_registration(
                    SHARED_ID, backend="thread", persistence_policy=persistence
                ),
            )
        ),
        pool_submitter=pool_submitter,
    )
    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    assert orchestrator.nodes[scope].state == "running"
    assert orchestrator.nodes[scope].generation_at_submit == 0
    return orchestrator, ctx, scope, persistence, handle


@pytest.mark.parametrize("malformed_result", _MALFORMED_RESULTS)
def test_malformed_result_of_a_pool_step_fails_its_node(sample_turn, malformed_result):
    orchestrator, _ctx, scope, persistence, handle = _running_pool_node(sample_turn)
    step_completions = _record_step_completions(orchestrator)

    complete_running_pool_step(orchestrator, scope, result_wire=malformed_result)

    assert step_completions == ["pool:materialize:failed"]
    assert handle.state == "failed"
    assert isinstance(handle.error, MalformedStepResultError)
    assert persistence.persist_calls == []


@pytest.mark.parametrize("malformed_result", _MALFORMED_RESULTS)
def test_malformed_result_of_an_inline_step_fails_its_node_and_dependents(
    sample_turn, malformed_result
):
    ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    export_scope = make_export_scope(sample_turn)
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (
                inline_compute_registration(ROOT_ID),
                inline_compute_registration(BRANCH_B_ID),
                inline_compute_registration(BRANCH_C_ID),
                _inline_registration_returning(SHARED_ID, malformed_result),
            )
        )
    )
    step_completions = _record_step_completions(orchestrator)

    root_handle = orchestrator.submit(
        ComputeRequest(ctx=ctx, scope=make_compute_scope(ROOT_ID, export_scope))
    )

    shared = orchestrator.nodes[make_compute_scope(SHARED_ID, export_scope)]
    assert step_completions == ["inline:materialize:failed"]
    assert shared.state == "failed"
    assert isinstance(shared.error, MalformedStepResultError)
    assert root_handle.state == "failed"


def test_malformed_result_of_an_epoch_stale_step_is_retried(sample_turn):
    orchestrator, ctx, scope, persistence, _handle = _running_pool_node(sample_turn)
    persistence.invalidate(ctx, scope)

    complete_running_pool_step(orchestrator, scope, result_wire=_MALFORMED_RESULT)

    # The retry re-dispatches the same execution at the new generation.
    node = orchestrator.nodes[scope]
    assert node.error is None
    assert node.state == "running"
    assert node.generation_at_submit == persistence.generation
    assert orchestrator.metrics.epoch_discards == 1
    assert persistence.persist_calls == []
