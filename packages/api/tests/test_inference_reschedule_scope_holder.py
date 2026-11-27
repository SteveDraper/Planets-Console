"""A stream reschedule with no row for the player cancels the run that holds the scope.

The controller asks the registry for the scope's ``REGISTERED`` holder
(``row_run_for_player``). A background run that survived its stream run's
cancel holds the scope and is cancelled. While a ``DETACHED`` stamped shell
holds the scope, there is no ``REGISTERED`` holder and nothing is cancelled.
"""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_scope import (
    InferenceStreamScope,
    scores_root_scope_for_session,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle
from api.analytics.scores.tier_row_run_registry import get_row_run, get_row_run_phase
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.compute.runtime import get_compute_orchestrator, reset_orchestrators_for_tests
from api.streaming.table_stream.row_run_admission import RowLifecycleOp, RowRunPhase

from tests.scores_exports_helpers import minimal_stream_query_context
from tests.scores_ladder_helpers import stamp_run_ladder
from tests.scores_row_lifecycle_test_helpers import (
    _patch_scores_dag_without_fleet_deps,
    _session_for_player,
)
from tests.table_stream_test_helpers import end_stream_inline

GAME_ID = 628580
PERSPECTIVE = 1

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


@pytest.fixture
def player_id(sample_turn) -> int:
    return sample_turn.scores[0].ownerid


@pytest.fixture
def scheduler(make_inference_scheduler, request) -> InferenceRowScheduler:
    reset_inference_table_stream_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)

    def cleanup() -> None:
        reset_orchestrators_for_tests()
        reset_compute_worker_pool_for_tests(worker_count=1)
        reset_inference_table_stream_registry_for_tests()

    request.addfinalizer(cleanup)
    return make_inference_scheduler()


@pytest.fixture
def controller(
    sample_turn, player_id, scheduler, monkeypatch, request
) -> InferenceTableStreamController:
    """An attached scores stream for one player that holds no row for that player."""
    scope = InferenceStreamScope(
        game_id=GAME_ID, perspective=PERSPECTIVE, turn_number=sample_turn.settings.turn
    )
    controller = InferenceTableStreamController(
        scope=scope,
        stream_token=scheduler.begin_scope(scope),
        turn=sample_turn,
        player_ids=(player_id,),
        scheduler=scheduler,
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        query_context=minimal_stream_query_context(sample_turn),
    )
    request.addfinalizer(
        lambda: end_stream_inline(scheduler, controller.scope, controller.stream_token)
    )
    controller.attach()
    _patch_scores_dag_without_fleet_deps(monkeypatch)
    return controller


def _submit_stream_run(sample_turn, player_id, scheduler, controller) -> InferenceRowStreamSession:
    """Register and submit a run the stream owns, without adding it to the stream's rows."""
    session = _session_for_player(sample_turn, player_id=player_id)
    scheduler.enqueue_tier_ladder(session, stream_token=controller.stream_token)
    scheduler.accept_pending_run(session.run_id)
    return session


def _register_background_run(sample_turn, player_id, scheduler) -> InferenceRowStreamSession:
    session = _session_for_player(sample_turn, player_id=player_id)
    scheduler.enqueue_tier_ladder(session)
    return session


def test_reschedule_cancels_a_background_run_that_survived_its_stream_run(
    sample_turn, player_id, scheduler, controller
) -> None:
    stream_run = _submit_stream_run(sample_turn, player_id, scheduler, controller)
    background = _register_background_run(sample_turn, player_id, scheduler)
    scheduler.cancel_row_run(stream_run.run_id)
    root_scope = scores_root_scope_for_session(background)

    assert controller.reschedule_player(player_id) is True

    assert background.cancel_token.is_cancelled()
    assert get_row_run(background.run_id) is None
    rescheduled = controller.scheduled_rows[player_id]
    assert rescheduled.session.run_id not in {stream_run.run_id, background.run_id}
    node = get_compute_orchestrator().nodes[root_scope]
    assert node.state == "running"
    assert node.error is None


@pytest.mark.parametrize("background_first", [True, False], ids=["before", "after"])
def test_reschedule_cancels_nothing_while_a_detached_stamped_run_holds_the_scope(
    sample_turn, player_id, scheduler, controller, background_first
) -> None:
    stream_run = _submit_stream_run(sample_turn, player_id, scheduler, controller)
    root_scope = scores_root_scope_for_session(stream_run)
    stamp_run_ladder(
        get_row_run(stream_run.run_id),
        execution_generation=get_compute_orchestrator().execution_generation_for_scope(root_scope),
    )
    if background_first:
        background = _register_background_run(sample_turn, player_id, scheduler)
        apply_scores_row_lifecycle(RowLifecycleOp.DETACH, stream_run.run_id)
    else:
        apply_scores_row_lifecycle(RowLifecycleOp.DETACH, stream_run.run_id)
        background = _register_background_run(sample_turn, player_id, scheduler)

    assert controller.reschedule_player(player_id) is True

    assert not background.cancel_token.is_cancelled()
    assert get_row_run_phase(background.run_id) is RowRunPhase.REGISTERED
    assert get_row_run_phase(stream_run.run_id) is RowRunPhase.DETACHED
