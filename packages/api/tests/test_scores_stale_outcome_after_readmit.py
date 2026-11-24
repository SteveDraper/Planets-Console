"""An old execution's outcome cannot reach the run a reschedule re-admitted on its scope.

A durable evidence bump runs inside a scores persist callback, so its drain
defers and its wake re-admits rows before outcomes already queued for those
rows' old executions are delivered. The re-admit registers its new node in
its own lock hold and the node's dispatch pass is queued after those
outcomes, so the node is not yet terminal when they run. The listener's
"sibling still active" check then ignores a stale failure, a stale complete
is matched only to the old run it names, and the orphan fallback stays quiet.
"""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores.tier_row_run_registry import (
    ScopeIndexPolicy,
    _retire_row_run,
    get_row_run,
    new_tier_row_run,
    register_row_run,
)

from tests.scores_tier_cross_binding_test_helpers import (
    _outcome_snapshot,
    _scope_for,
    _session,
    _set_scope_node,
    _singleton_orchestrator,
    reset_cross_binding_registries,
)

OLD_EXECUTION = 1
READMITTED_EXECUTION = 2


@pytest.fixture(autouse=True)
def _reset_registries():
    with reset_cross_binding_registries():
        yield


@pytest.fixture
def readmitted(sample_turn, monkeypatch):
    """The old run is cancelled; the re-admitted run is registered on a node not yet run."""
    old_session = _session(sample_turn)
    scope = _scope_for(old_session)
    old_run = new_tier_row_run(old_session)
    register_row_run(old_run, scope_index=ScopeIndexPolicy.TAKE)
    new_run = new_tier_row_run(_session(sample_turn))
    assert new_run.run_id != old_run.run_id
    register_row_run(new_run, scope_index=ScopeIndexPolicy.TAKE)
    _retire_row_run(old_run.run_id)
    _set_scope_node(
        _singleton_orchestrator(),
        scope,
        state="ready",
        execution_generation=READMITTED_EXECUTION,
    )
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scheduler._runs[new_run.run_id] = scope
    delivered: list[object] = []
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_stream_resolution."
        "deliver_inference_domain_event_to_open_stream",
        lambda _session, event: delivered.append(event),
    )
    return scheduler, scope, old_run, new_run, delivered


def _assert_new_run_untouched(scheduler, new_run, delivered) -> None:
    assert delivered == []
    assert new_run.run_id in scheduler._runs
    assert get_row_run(new_run.run_id) is new_run


def test_a_stale_failure_does_not_fail_the_readmitted_run(readmitted):
    scheduler, scope, _old_run, new_run, delivered = readmitted

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(
            scope,
            state="failed",
            error=RuntimeError("old execution failed"),
            execution_generation=OLD_EXECUTION,
        )
    )

    _assert_new_run_untouched(scheduler, new_run, delivered)


def test_a_stale_complete_is_not_delivered_to_the_readmitted_run(readmitted):
    scheduler, scope, old_run, new_run, delivered = readmitted
    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="exact",
    )

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(
            scope,
            state="complete",
            result_wire={"runId": old_run.run_id, "rowComplete": row_complete, "onWalk": False},
            execution_generation=OLD_EXECUTION,
        )
    )

    _assert_new_run_untouched(scheduler, new_run, delivered)


def test_a_stale_skip_complete_does_not_finish_the_readmitted_run(readmitted):
    scheduler, scope, _old_run, new_run, delivered = readmitted

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(
            scope,
            state="complete",
            result_wire=None,
            execution_generation=OLD_EXECUTION,
        )
    )

    _assert_new_run_untouched(scheduler, new_run, delivered)
