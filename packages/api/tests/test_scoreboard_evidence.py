"""Stored scoreboard rows compare a missing generation as 0 against the fleet mark."""

from __future__ import annotations

from pathlib import Path

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.fleet.injected_services import FleetComputeServices
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import fleet_evidence_mark_to_json
from api.analytics.fleet.types import FleetEvidenceMark
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_rows import (
    ImmediateRowAdmission,
    session_domain_event_to_wire_events,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scoreboard_evidence import (
    annotate_scoreboard_paint,
    stamp_scoreboard_row_for_context,
)
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores.exports import _persist_immediate_row_admission
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_row_persistence_service import InferenceRowPersistenceService

from tests.scores_exports_helpers import GAME_ID

_API_ROOT = Path(__file__).resolve().parents[1] / "api"
_MARK_READER_SOURCES = (
    _API_ROOT / "analytics/military_score_inference/inference_table_stream_controller.py",
    _API_ROOT / "analytics/military_score_inference/inference_stream_rows.py",
    _API_ROOT / "analytics/scores/exports.py",
    _API_ROOT / "services/inference_row_persistence_service.py",
)


def _dead_complete() -> dict[str, object]:
    return {
        "type": "complete",
        "status": "dead",
        "summary": "Player is dead",
        "solutionCount": 0,
        "isComplete": True,
    }


def _stored_skip(persistence: InferenceRowPersistenceService, *, turn: int, player_id: int) -> None:
    persistence.put_row(
        GAME_ID,
        1,
        turn,
        player_id,
        PersistedInferenceRow(
            status="dead",
            summary="Player is dead",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )


def _context_with_mark(storage, turn, *, player_id: int, mark: int, persistence):
    fleet_persistence = FleetSnapshotPersistenceService(storage)
    if mark != 0:
        storage.put(
            fleet_persistence.evidence_mark_key(GAME_ID, 1, player_id),
            fleet_evidence_mark_to_json(FleetEvidenceMark(evidence_generation=mark)),
        )
    return make_analytic_query_context(
        turn,
        TurnAnalyticsOptions(),
        game_id=GAME_ID,
        perspective=1,
        export_services={
            "fleet": FleetComputeServices(
                persistence=fleet_persistence,
                game_id=GAME_ID,
                perspective=1,
                load_turn=lambda turn_number: turn if turn_number == turn.settings.turn else None,
            ),
            "scores": ScoresExportContext(persistence=persistence),
        },
    )


def _controller(sample_turn, persistence, query_context) -> InferenceTableStreamController:
    player_id = sample_turn.scores[0].ownerid
    return InferenceTableStreamController(
        scope=InferenceStreamScope(
            game_id=GAME_ID,
            perspective=1,
            turn_number=sample_turn.settings.turn,
        ),
        stream_token="scoreboard-evidence",
        turn=sample_turn,
        player_ids=(player_id,),
        scheduler=InferenceRowScheduler(worker_count=0),
        game_id=GAME_ID,
        perspective=1,
        persistence=persistence,
        query_context=query_context,
    )


def _replay_dead_skip(controller, player_id: int) -> dict[str, object]:
    dispatched = controller.dispatch_admission(
        player_id,
        ImmediateRowAdmission(events=(_dead_complete(),)),
    )
    assert len(dispatched.wire_events) == 1
    return dispatched.wire_events[0]


def test_replay_of_omitted_generation_at_mark_zero_is_current(
    sample_turn,
    persistence,
    memory_backend,
):
    player_id = sample_turn.scores[0].ownerid
    turn = sample_turn.settings.turn
    _stored_skip(persistence, turn=turn, player_id=player_id)
    stored_json = memory_backend.get(persistence.row_store_key(GAME_ID, 1, turn, player_id))
    assert "evidenceGeneration" not in stored_json

    controller = _controller(
        sample_turn,
        persistence,
        _context_with_mark(
            memory_backend,
            sample_turn,
            player_id=player_id,
            mark=0,
            persistence=persistence,
        ),
    )
    event = _replay_dead_skip(controller, player_id)
    assert event["evidenceGeneration"] == 0
    assert event["evidenceMark"] == 0
    assert event["status"] == "dead"


def test_replay_of_omitted_generation_behind_a_positive_mark(
    sample_turn,
    persistence,
    memory_backend,
):
    player_id = sample_turn.scores[0].ownerid
    turn = sample_turn.settings.turn
    _stored_skip(persistence, turn=turn, player_id=player_id)
    stored_json = memory_backend.get(persistence.row_store_key(GAME_ID, 1, turn, player_id))
    assert "evidenceGeneration" not in stored_json

    controller = _controller(
        sample_turn,
        persistence,
        _context_with_mark(
            memory_backend,
            sample_turn,
            player_id=player_id,
            mark=4,
            persistence=persistence,
        ),
    )
    event = _replay_dead_skip(controller, player_id)
    assert event["status"] == "dead"
    assert event["evidenceGeneration"] == 0
    assert event["evidenceMark"] == 4


def test_replay_without_a_stored_row_stays_unmarked(sample_turn, persistence, memory_backend):
    player_id = sample_turn.scores[0].ownerid
    controller = _controller(
        sample_turn,
        persistence,
        _context_with_mark(
            memory_backend,
            sample_turn,
            player_id=player_id,
            mark=4,
            persistence=persistence,
        ),
    )
    event = _replay_dead_skip(controller, player_id)
    assert event["type"] == "complete"
    assert event["status"] == "dead"
    assert "evidenceGeneration" not in event
    assert "evidenceMark" not in event
    assert event.get("type") != "no_stored_row"


def test_both_write_paths_call_the_persist_stamp(
    monkeypatch: pytest.MonkeyPatch,
    sample_turn,
    persistence,
    memory_backend,
) -> None:
    calls: list[tuple[int, int]] = []
    real = stamp_scoreboard_row_for_context

    def spy(row, query_context, *, game_id, perspective, player_id):
        calls.append((game_id, player_id))
        return real(
            row,
            query_context,
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
        )

    monkeypatch.setattr(
        "api.services.inference_row_persistence_service.stamp_scoreboard_row_for_context",
        spy,
    )
    monkeypatch.setattr(
        "api.analytics.scores.exports.stamp_scoreboard_row_for_context",
        spy,
    )

    turn = sample_turn.settings.turn
    durable_player = 41
    immediate_player = 42
    fleet_persistence = FleetSnapshotPersistenceService(memory_backend)
    for player_id in (durable_player, immediate_player):
        memory_backend.put(
            fleet_persistence.evidence_mark_key(GAME_ID, 1, player_id),
            fleet_evidence_mark_to_json(FleetEvidenceMark(evidence_generation=5)),
        )
    context = _context_with_mark(
        memory_backend,
        sample_turn,
        player_id=durable_player,
        mark=0,
        persistence=persistence,
    )

    persistence.persist_row_complete_for_scope(
        row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary="Best build",
        ),
        game_id=GAME_ID,
        perspective=1,
        host_turn=turn,
        player_id=durable_player,
        query_context=context,
    )
    _persist_immediate_row_admission(
        ScoresExportContext(persistence=persistence),
        ExportScope(game_id=GAME_ID, perspective=1, turn=turn, player_id=immediate_player),
        ImmediateRowAdmission(events=(_dead_complete(),)),
        query_context=context,
    )

    assert calls == [(GAME_ID, durable_player), (GAME_ID, immediate_player)]
    durable = persistence.get_row(GAME_ID, 1, turn, durable_player)
    immediate = persistence.get_row(GAME_ID, 1, turn, immediate_player)
    assert durable is not None and durable.evidence_generation == 5
    assert immediate is not None and immediate.evidence_generation == 5


def test_live_durable_complete_reads_the_generation_persist_just_wrote(
    sample_turn,
    persistence,
    memory_backend,
) -> None:
    """Ordering contract: persist stamps the row, then the live paint reads it.

    ``evidenceGeneration`` is that stored integer. The paint does not copy the
    mark it reads at the same moment onto both fields.
    """
    player_id = sample_turn.scores[0].ownerid
    turn = sample_turn.settings.turn
    context = _context_with_mark(
        memory_backend,
        sample_turn,
        player_id=player_id,
        mark=3,
        persistence=persistence,
    )
    complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="Best build",
    )
    persistence.persist_row_complete_for_scope(
        complete,
        game_id=GAME_ID,
        perspective=1,
        host_turn=turn,
        player_id=player_id,
        query_context=context,
    )
    session = InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(sample_turn.scores[0], sample_turn),
        turn=sample_turn,
        game_id=GAME_ID,
        perspective=1,
        turn_number=turn,
        persistence=persistence,
        query_context=context,
    )
    wire = session_domain_event_to_wire_events(session, complete)
    stored = persistence.get_row(GAME_ID, 1, turn, player_id)
    assert stored is not None
    assert len(wire) == 1
    assert wire[0]["evidenceGeneration"] == stored.evidence_generation == 3
    assert wire[0]["evidenceMark"] == 3


def test_live_durable_complete_does_not_copy_the_mark_onto_both_fields(
    sample_turn,
    persistence,
    memory_backend,
) -> None:
    player_id = sample_turn.scores[0].ownerid
    turn = sample_turn.settings.turn
    _stored_skip(persistence, turn=turn, player_id=player_id)
    context = _context_with_mark(
        memory_backend,
        sample_turn,
        player_id=player_id,
        mark=4,
        persistence=persistence,
    )
    session = InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(sample_turn.scores[0], sample_turn),
        turn=sample_turn,
        game_id=GAME_ID,
        perspective=1,
        turn_number=turn,
        persistence=persistence,
        query_context=context,
    )
    complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="Best build",
    )
    wire = session_domain_event_to_wire_events(session, complete)
    assert wire[0]["evidenceGeneration"] == 0
    assert wire[0]["evidenceMark"] == 4


def test_missing_generation_on_a_stored_row_is_zero_and_a_missing_row_is_unmarked(
    sample_turn,
    persistence,
    memory_backend,
) -> None:
    event = _dead_complete()
    player_id = sample_turn.scores[0].ownerid
    turn = sample_turn.settings.turn
    stored = PersistedInferenceRow(
        status="dead",
        summary="Player is dead",
        solution_count=0,
        is_complete=True,
        solutions=[],
        evidence_generation=True,  # type: ignore[arg-type]
    )

    class _Rows:
        def __init__(self, row: PersistedInferenceRow | None) -> None:
            self._row = row

        def get_row(
            self,
            game_id: int,
            perspective: int,
            host_turn: int,
            player_id: int,
        ) -> PersistedInferenceRow | None:
            del game_id, perspective, host_turn, player_id
            return self._row

    context = _context_with_mark(
        memory_backend,
        sample_turn,
        player_id=player_id,
        mark=2,
        persistence=persistence,
    )
    marked = annotate_scoreboard_paint(
        event,
        persistence=_Rows(stored),
        query_context=context,
        game_id=GAME_ID,
        perspective=1,
        turn=turn,
        player_id=player_id,
    )
    assert marked["evidenceGeneration"] == 0
    assert marked["evidenceMark"] == 2

    unmarked = annotate_scoreboard_paint(
        event,
        persistence=_Rows(None),
        query_context=context,
        game_id=GAME_ID,
        perspective=1,
        turn=turn,
        player_id=player_id,
    )
    assert unmarked is event
    assert "evidenceGeneration" not in unmarked

    progress = {"type": "progress"}
    assert (
        annotate_scoreboard_paint(
            progress,
            persistence=_Rows(stored),
            query_context=context,
            game_id=GAME_ID,
            perspective=1,
            turn=turn,
            player_id=player_id,
        )
        is progress
    )

    unchanged = stamp_scoreboard_row_for_context(
        stored,
        None,
        game_id=GAME_ID,
        perspective=1,
        player_id=player_id,
    )
    assert unchanged.evidence_generation is True
    # Absent fleet mark reads as generation 0. Use a player with no mark written.
    zero_player = player_id + 1
    stamped = stamp_scoreboard_row_for_context(
        stored,
        _context_with_mark(
            memory_backend,
            sample_turn,
            player_id=zero_player,
            mark=0,
            persistence=persistence,
        ),
        game_id=GAME_ID,
        perspective=1,
        player_id=zero_player,
    )
    assert stamped.evidence_generation == 0


def test_mark_readers_do_not_import_the_fleet_analytic() -> None:
    for path in _MARK_READER_SOURCES:
        text = path.read_text()
        assert "fleet.injected_services" not in text
        assert "fleet_evidence_generation_for_player" not in text
