"""Scores turn-write consumers: cancel with queued aborts now, re-admit later.

``cancel_for_turn_write`` cancels the open stream's row runs at a stored turn's
host turns with lifecycle CANCEL and a queued abort of their nodes, draining
nothing and keeping the stream's scheduled rows. ``wake_for_turn_write`` then
re-admits every row; its own cancel finds nothing left to cancel. The abort
listeners of the old runs, drained by that re-admit, close no new run.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_scope import (
    scores_root_scope_for_session,
)
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.scores.tier_row_run_registry import (
    decide_scores_row_persist,
    get_persist_admission,
)
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.compute.runtime import get_compute_orchestrator, reset_orchestrators_for_tests
from api.compute.scope import ComputeScope
from api.models.turn_write import TurnWrite
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend
from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.row_run_admission import PersistAdmission

from tests.scores_row_lifecycle_test_helpers import (
    _patch_scores_dag_without_fleet_deps,
    attach_active_table_stream,
)
from tests.table_stream_test_helpers import end_stream_inline

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


class _OpenStream:
    """A scores stream at the sample turn whose rows run on the process orchestrator."""

    def __init__(self, sample_turn, scheduler: InferenceRowScheduler) -> None:
        self.player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
        self.scheduler = scheduler
        self.controller: InferenceTableStreamController
        self.controller, _rows, _wake = attach_active_table_stream(
            sample_turn, scheduler, self.player_ids
        )
        self.orchestrator: ComputeOrchestrator = get_compute_orchestrator()
        self.outcomes: list[ScopeLifecycleSnapshot] = []
        self.orchestrator.observers.register_scope_outcome_listener(self.outcomes.append)
        self.turn_write = TurnWrite(
            game_id=628580, perspective=1, turn_number=sample_turn.settings.turn
        )

    def run_ids(self) -> dict[int, str]:
        return {
            player_id: row.session.run_id
            for player_id, row in self.controller.scheduled_rows.items()
        }

    def scope(self, player_id: int) -> ComputeScope:
        return scores_root_scope_for_session(self.controller.scheduled_rows[player_id].session)

    def aborted_outcomes(self) -> list[ScopeLifecycleSnapshot]:
        return [snapshot for snapshot in self.outcomes if snapshot.is_intentional_abort]


@pytest.fixture
def open_stream(sample_turn, monkeypatch, make_inference_scheduler) -> Iterator[_OpenStream]:
    reset_inference_table_stream_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    _patch_scores_dag_without_fleet_deps(monkeypatch)
    stream = _OpenStream(sample_turn, make_inference_scheduler())
    yield stream
    end_stream_inline(stream.scheduler, stream.controller.scope, stream.controller.stream_token)
    reset_inference_table_stream_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=1)


@pytest.fixture
def invalidation(open_stream, make_inference_scheduler) -> InferenceInvalidationService:
    """The service wired to a scheduler other than the stream's.

    The cancel and the wake both reach runs through the stream's own
    scheduler, so the service's scheduler never splits them.
    """
    return InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        scheduler=make_inference_scheduler(),
    )


def test_cancel_for_turn_write_aborts_with_queued_listeners_and_keeps_the_rows(
    open_stream, invalidation
):
    before = open_stream.run_ids()

    invalidation.cancel_for_turn_write(open_stream.turn_write)

    assert open_stream.run_ids() == before
    for player_id, run_id in before.items():
        assert run_id not in open_stream.scheduler._runs
        assert get_persist_admission(run_id) is PersistAdmission.CANCEL_DENY
        node = open_stream.orchestrator.nodes[open_stream.scope(player_id)]
        assert node.state == "failed"
        assert isinstance(node.error, ComputeScopeAbortedError)
    assert open_stream.aborted_outcomes() == []

    open_stream.orchestrator.drain_post_lock_callbacks()

    assert {snapshot.scope for snapshot in open_stream.aborted_outcomes()} == {
        open_stream.scope(player_id) for player_id in before
    }


def test_cancel_and_wake_use_the_stream_scheduler_not_the_service_scheduler(
    open_stream, invalidation, monkeypatch
):
    service_scheduler = invalidation._scheduler_instance()
    assert service_scheduler is not open_stream.scheduler
    service_cancels: list[str] = []
    for method in ("cancel_run", "cancel_run_queued", "cancel_row_run"):
        monkeypatch.setattr(service_scheduler, method, service_cancels.append)
    before = open_stream.run_ids()

    invalidation.cancel_for_turn_write(open_stream.turn_write)
    invalidation.wake_for_turn_write(open_stream.turn_write)

    assert service_cancels == []
    after = open_stream.run_ids()
    for player_id, run_id in before.items():
        assert run_id not in open_stream.scheduler._runs
        assert after[player_id] in open_stream.scheduler._runs


@pytest.mark.parametrize(
    ("cancel_method", "drains_listeners"),
    [("cancel_run", True), ("cancel_run_queued", False)],
)
def test_cancel_run_variants_differ_only_in_draining(open_stream, cancel_method, drains_listeners):
    player_id = open_stream.player_ids[0]
    run_id = open_stream.run_ids()[player_id]

    getattr(open_stream.scheduler, cancel_method)(run_id)

    assert open_stream.orchestrator.nodes[open_stream.scope(player_id)].state == "failed"
    assert get_persist_admission(run_id) is PersistAdmission.CANCEL_DENY
    assert bool(open_stream.aborted_outcomes()) is drains_listeners


@pytest.mark.parametrize("cancel_method", ["cancel_run", "cancel_run_queued"])
def test_cancel_run_variants_skip_the_abort_while_a_sibling_owns_the_scope(
    open_stream, sample_turn, cancel_method
):
    from tests.scores_row_lifecycle_test_helpers import _session_for_player

    player_id = open_stream.player_ids[0]
    run_id = open_stream.run_ids()[player_id]
    sibling = _session_for_player(sample_turn, player_id=player_id)
    open_stream.scheduler.enqueue_tier_ladder(sibling)

    getattr(open_stream.scheduler, cancel_method)(run_id)

    assert open_stream.orchestrator.nodes[open_stream.scope(player_id)].state == "running"
    assert sibling.run_id in open_stream.scheduler._runs


def test_wake_after_the_cancel_only_re_admits(open_stream, invalidation, monkeypatch):
    before = open_stream.run_ids()
    invalidation.cancel_for_turn_write(open_stream.turn_write)
    wake_aborts: list[tuple] = []
    monkeypatch.setattr(
        open_stream.scheduler,
        "_abort_orchestrator_scope",
        lambda *args: wake_aborts.append(args),
    )

    invalidation.wake_for_turn_write(open_stream.turn_write)

    assert wake_aborts == []
    after = open_stream.run_ids()
    assert set(after) == set(before)
    for player_id, run_id in after.items():
        assert run_id != before[player_id]
        assert run_id in open_stream.scheduler._runs
        assert not decide_scores_row_persist(before[player_id]).allowed
        assert open_stream.orchestrator.nodes[open_stream.scope(player_id)].state == "running"


def test_old_runs_late_abort_listeners_close_no_re_admitted_run(open_stream, invalidation):
    invalidation.cancel_for_turn_write(open_stream.turn_write)
    assert open_stream.aborted_outcomes() == []

    assert open_stream.controller.reschedule_all_rows(force_schedule=True)
    open_stream.orchestrator.drain_post_lock_callbacks()

    assert len(open_stream.aborted_outcomes()) == len(open_stream.player_ids)
    for run_id in open_stream.run_ids().values():
        assert run_id in open_stream.scheduler._runs
        assert not stream_drain.is_closed(run_id)
    assert [
        event
        for event in open_stream.controller.drain_pending_wire_events()
        if event.get("type") in {"complete", "error"}
    ] == []
