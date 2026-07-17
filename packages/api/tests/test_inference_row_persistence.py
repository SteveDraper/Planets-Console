"""Tests for scores inference row persistence and invalidation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api.analytics.military_score_inference.host_turn_targets import HostTurnFunctionalTarget
from api.analytics.military_score_inference.inference_scheduler import (
    get_inference_row_scheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    iter_scores_table_inference_events,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reschedule_inference_row,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.serialization.inference_row_persistence import (
    INFERENCE_ROW_PERSISTENCE_VERSION,
    PersistedInferenceRow,
    upgrade_persisted_inference_row,
)
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    return backend


@pytest.fixture
def persistence(memory_backend):
    return InferenceRowPersistenceService(memory_backend)


def test_persistence_row_round_trip(persistence):
    row = PersistedInferenceRow(
        status=STATUS_EXACT,
        summary="cached",
        solution_count=1,
        is_complete=True,
        solutions=[{"objectiveValue": 1.0, "actions": [], "shipBuilds": []}],
        diagnostics={"actionCatalog": {"shipBuildCombos": [{"comboId": "x"}] * 1000}},
        persistence_version=INFERENCE_ROW_PERSISTENCE_VERSION,
    )
    persistence.put_row(628580, 1, 111, 8, row)
    loaded = persistence.get_row(628580, 1, 111, 8)
    assert loaded is not None
    assert loaded.status == row.status
    assert loaded.summary == row.summary
    assert loaded.solutions == row.solutions
    assert loaded.diagnostics is None
    raw = persistence._storage.get(persistence.row_store_key(628580, 1, 111, 8))
    assert isinstance(raw, dict)
    assert "diagnostics" not in raw


def test_put_row_notify_false_skips_on_row_persisted(persistence):
    notified: list[tuple[int, int, int, int]] = []
    persistence.on_row_persisted = lambda game_id, perspective, host_turn, player_id: (
        notified.append((game_id, perspective, host_turn, player_id))
    )
    row = PersistedInferenceRow(
        status=STATUS_EXACT,
        summary="cached",
        solution_count=0,
        is_complete=True,
        solutions=[],
    )
    persistence.put_row(628580, 1, 111, 8, row, notify=False)
    assert persistence.get_row(628580, 1, 111, 8) is not None
    assert notified == []
    persistence.put_row(628580, 1, 111, 8, row, notify=True)
    assert notified == [(628580, 1, 111, 8)]


def test_put_row_promotes_accelerated_segments_before_dropping_diagnostics(persistence):
    _, player_id, legacy_row = _legacy_v1_split_row_from_turn_three()
    persistence.put_row(628580, 1, 3, player_id, legacy_row)
    raw = persistence._storage.get(persistence.row_store_key(628580, 1, 3, player_id))
    assert isinstance(raw, dict)
    assert "diagnostics" not in raw
    assert raw.get("host_turn_targets")
    assert raw.get("persistence_version") == INFERENCE_ROW_PERSISTENCE_VERSION
    loaded = persistence.get_row(628580, 1, 3, player_id)
    assert loaded is not None
    assert loaded.diagnostics is None
    assert loaded.host_turn_targets is not None
    assert loaded.host_turn_targets[0].host_turn


def test_persisted_inference_row_from_wire_complete_omits_diagnostics():
    from api.serialization.inference_row_persistence import (
        persisted_inference_row_from_wire_complete,
        persisted_inference_row_to_json,
    )

    row = persisted_inference_row_from_wire_complete(
        {
            "type": "complete",
            "status": STATUS_EXACT,
            "summary": "done",
            "solutionCount": 1,
            "isComplete": True,
            "solutions": [{"objectiveValue": 1.0, "actions": [], "shipBuilds": []}],
            "diagnostics": {
                "actionCatalog": {
                    "shipBuildCombos": [{"comboId": f"combo_{i}"} for i in range(10_000)],
                    "meta": {"shipBuildComboIds": [f"combo_{i}" for i in range(10_000)]},
                }
            },
        }
    )
    assert row.diagnostics is None
    assert row.solutions
    stored = persisted_inference_row_to_json(row)
    assert "diagnostics" not in stored
    assert stored["solutions"] == row.solutions


def test_invalidate_for_turn_write_deletes_pair_documents(memory_backend, persistence):
    persistence.put_row(
        628580,
        1,
        110,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="t110",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="t111",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    cleared = persistence.invalidate_for_turn_write(628580, 1, 111)
    assert cleared == {111, 110}
    assert persistence.get_row(628580, 1, 111, 8) is None
    assert persistence.get_row(628580, 1, 110, 8) is None


def test_stream_replays_persisted_row_without_scheduler_work(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    reset_inference_table_stream_registry_for_tests()
    player_id = sample_turn.scores[0].ownerid
    persistence.put_row(
        628580,
        1,
        sample_turn.settings.turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="from cache",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    scheduler = get_inference_row_scheduler()
    stream = iter_scores_table_inference_events(
        sample_turn,
        (player_id,),
        game_id=628580,
        perspective=1,
        persistence=persistence,
    )
    events = [next(stream), next(stream)]
    stream.close()
    assert events[0] == {"type": "globalPause", "paused": False}
    assert events[1]["type"] == "complete"
    assert events[1]["playerId"] == player_id
    assert events[1]["summary"] == "from cache"
    assert len(scheduler._runs) == 0


def test_mask_change_deletes_persisted_row(memory_backend):
    persistence = InferenceRowPersistenceService(memory_backend)
    invalidation = InferenceInvalidationService(persistence)
    persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="before mask",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    invalidation.on_hull_mask_changed(628580, 1, 111, 8)
    assert persistence.get_row(628580, 1, 111, 8) is None


def test_recompute_clears_host_turn_document(memory_backend):
    _, _, _, _, analytics = build_service_stack(memory_backend)
    persistence = InferenceRowPersistenceService(memory_backend)
    persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="cached",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    analytics.recompute_scores_inference(628580, 1, 111)
    assert persistence.get_row(628580, 1, 111, 8) is None


def test_turn_store_invalidates_inference_persistence(memory_backend):
    _, turns, _, _, _ = build_service_stack(memory_backend)
    persistence = InferenceRowPersistenceService(memory_backend)
    persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="cached",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    with open(ASSETS_DIR / "turn_sample.json") as f:
        turns._store_turn_rst(628580, 1, 111, json.load(f))
    assert persistence.get_row(628580, 1, 111, 8) is None


def test_reschedule_without_active_stream_is_noop():
    reset_inference_table_stream_registry_for_tests()
    scope = InferenceStreamScope(game_id=628580, perspective=1, turn_number=111)
    assert reschedule_inference_row(scope, 8) is False


def _legacy_v1_split_row_from_turn_three():
    from api.analytics.military_score_inference.analytic import infer_military_score_build
    from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete

    from tests.inference_corpus.fixtures import load_turn_fixture

    turn_three = load_turn_fixture("628580/1/turns/3.json")
    player_id = 11
    score = next(entry for entry in turn_three.scores if entry.ownerid == player_id)
    inference_payload = infer_military_score_build(score, turn_three)
    wire_complete = inference_api_payload_to_wire_complete(inference_payload)
    diagnostics = wire_complete.get("diagnostics")
    assert isinstance(diagnostics, dict)
    assert diagnostics.get("accelerated_segments")
    return (
        turn_three,
        player_id,
        PersistedInferenceRow(
            status=str(inference_payload["status"]),
            summary=str(inference_payload["summary"]),
            solution_count=int(inference_payload["solutionCount"]),
            is_complete=True,
            solutions=inference_payload["solutions"],
            diagnostics=diagnostics,
            host_turn_targets=None,
            persistence_version=None,
        ),
    )


def test_upgrade_persisted_inference_row_copies_accelerated_segments():
    _, _, legacy_row = _legacy_v1_split_row_from_turn_three()
    upgraded, changed = upgrade_persisted_inference_row(legacy_row)
    assert changed is True
    assert upgraded.persistence_version == INFERENCE_ROW_PERSISTENCE_VERSION
    assert upgraded.host_turn_targets
    assert all(
        isinstance(target, HostTurnFunctionalTarget) for target in upgraded.host_turn_targets
    )
    assert upgraded.host_turn_targets[0].host_turn
    assert upgraded.diagnostics is None


def test_get_row_upgrades_legacy_v1_split_row_with_write_back(memory_backend):
    turn_three, player_id, legacy_row = _legacy_v1_split_row_from_turn_three()
    persistence = InferenceRowPersistenceService(memory_backend)
    store_key = persistence.row_store_key(
        628580,
        1,
        turn_three.settings.turn,
        player_id,
    )
    # Seed raw legacy v1 JSON (pre-strip) so diagnostics.accelerated_segments exist on disk.
    memory_backend.put(
        store_key,
        {
            "status": legacy_row.status,
            "summary": legacy_row.summary,
            "solution_count": legacy_row.solution_count,
            "is_complete": legacy_row.is_complete,
            "solutions": legacy_row.solutions,
            "diagnostics": legacy_row.diagnostics,
        },
    )

    stored_before = memory_backend.get(store_key)
    assert stored_before is not None
    assert stored_before.get("host_turn_targets") is None
    assert stored_before.get("persistence_version") is None
    assert stored_before.get("diagnostics") is not None

    loaded = persistence.get_row(628580, 1, turn_three.settings.turn, player_id)
    assert loaded is not None
    assert loaded.persistence_version == INFERENCE_ROW_PERSISTENCE_VERSION
    assert loaded.host_turn_targets
    assert loaded.diagnostics is None

    stored_after = memory_backend.get(store_key)
    assert stored_after is not None
    assert stored_after.get("persistence_version") == INFERENCE_ROW_PERSISTENCE_VERSION
    assert stored_after.get("host_turn_targets")
    assert "diagnostics" not in stored_after

    reloaded = persistence.get_row(628580, 1, turn_three.settings.turn, player_id)
    assert reloaded == loaded


def test_legacy_v1_upgrade_enables_functional_backfill_without_diagnostics():
    from dataclasses import replace

    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.export_types import ExportScope
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.exports import held_scores_for_scope
    from api.analytics.scores.host_turn_export import host_turn_targets_from_persisted_row

    turn_three, player_id, legacy_row = _legacy_v1_split_row_from_turn_three()
    turn_two = replace(turn_three, settings=replace(turn_three.settings, turn=2))
    turn_two = replace(
        turn_two,
        scores=[replace(score, turn=2) for score in turn_two.scores],
    )
    backend = MemoryAssetBackend(initial={})
    persistence = InferenceRowPersistenceService(backend)
    store_key = persistence.row_store_key(628580, 1, turn_three.settings.turn, player_id)
    backend.put(
        store_key,
        {
            "status": legacy_row.status,
            "summary": legacy_row.summary,
            "solution_count": legacy_row.solution_count,
            "is_complete": legacy_row.is_complete,
            "solutions": legacy_row.solutions,
            "diagnostics": legacy_row.diagnostics,
        },
    )
    loaded = persistence.get_row(628580, 1, turn_three.settings.turn, player_id)
    assert loaded is not None
    assert host_turn_targets_from_persisted_row(loaded)

    def load_turn(turn_number: int):
        if turn_number == 2:
            return turn_two
        if turn_number == 3:
            return turn_three
        return None

    ctx = make_analytic_query_context(
        turn_two,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services={"scores": ScoresExportContext(persistence=persistence)},
    )
    resolved = held_scores_for_scope(
        ctx,
        ExportScope(game_id=628580, perspective=1, turn=2, player_id=player_id),
        turn=turn_two,
    )
    assert resolved.decision.branch == "functional_backfill"
    assert resolved.payload.diagnostics is None
    assert resolved.payload.solutions
    assert resolved.payload.solutions_held > 0


def test_scores_persistence_policy_persists_exact_terminal_row(sample_turn, memory_backend):
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.analytic import build_inference_observation
    from api.analytics.military_score_inference.inference_stream_session import (
        InferenceRowStreamSession,
    )
    from api.analytics.military_score_inference.models import InferenceResult
    from api.analytics.military_score_inference.row_complete_factory import (
        row_complete_with_summary,
    )
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.compute.scope import ComputeScope

    reset_tier_row_run_registry_for_tests()
    score = sample_turn.scores[0]
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    run = RowRun(session)
    register_row_run(run)
    persistence = InferenceRowPersistenceService(memory_backend)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={"scores": ScoresExportContext(persistence=persistence)},
    )
    policy = ScoresPersistencePolicy()
    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="orchestrator exact",
    )
    policy.persist(
        ctx,
        ComputeScope(
            analytic_id="scores",
            game_id=628580,
            perspective=1,
            turn=sample_turn.settings.turn,
            player_id=score.ownerid,
        ),
        {"runId": run.run_id, "rowComplete": row_complete},
    )

    stored = persistence.get_row(628580, 1, sample_turn.settings.turn, score.ownerid)
    assert stored is not None
    assert stored.summary == "orchestrator exact"


def test_scores_persistence_policy_persists_stopped_terminal_row(
    sample_turn,
    memory_backend,
):
    """Stopped closes turnEvidenceAtN when durable -- must persist, not soft-complete."""
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.analytic import build_inference_observation
    from api.analytics.military_score_inference.inference_row_runner import TierJobOutcome
    from api.analytics.military_score_inference.inference_stream_session import (
        InferenceRowStreamSession,
    )
    from api.analytics.military_score_inference.models import InferenceResult
    from api.analytics.military_score_inference.row_complete_factory import (
        row_complete_with_summary,
    )
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.military_score_inference.solver import STATUS_STOPPED
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.compute_orchestration import (
        ScoresPersistencePolicy,
        tier_job_outcome_to_step_result,
    )
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.compute.scope import ComputeScope

    reset_tier_row_run_registry_for_tests()
    score = sample_turn.scores[0]
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    run = RowRun(session)
    register_row_run(run)
    step_result = tier_job_outcome_to_step_result(
        run,
        TierJobOutcome(
            row_complete=row_complete_with_summary(
                InferenceResult(status=STATUS_STOPPED, solutions=(), diagnostics={}),
                summary="stopped",
            ),
        ),
    )
    assert step_result.outcome == "persist"

    persistence = InferenceRowPersistenceService(memory_backend)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={"scores": ScoresExportContext(persistence=persistence)},
    )
    policy = ScoresPersistencePolicy()
    policy.persist(
        ctx,
        ComputeScope(
            analytic_id="scores",
            game_id=628580,
            perspective=1,
            turn=sample_turn.settings.turn,
            player_id=score.ownerid,
        ),
        step_result.payload,
    )

    stored = persistence.get_row(628580, 1, sample_turn.settings.turn, score.ownerid)
    assert stored is not None
    assert stored.status == STATUS_STOPPED


def test_scores_persistence_policy_raises_when_rowrun_missing_for_persistable(
    sample_turn,
    memory_backend,
):
    """Persistable tier outcome without a live RowRun must not quiet-complete."""
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.analytic import build_inference_observation
    from api.analytics.military_score_inference.inference_stream_session import (
        InferenceRowStreamSession,
    )
    from api.analytics.military_score_inference.models import InferenceResult
    from api.analytics.military_score_inference.row_complete_factory import (
        row_complete_with_summary,
    )
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        register_row_run,
        reset_tier_row_run_registry_for_tests,
        unregister_row_run,
    )
    from api.compute.scope import ComputeScope

    reset_tier_row_run_registry_for_tests()
    score = sample_turn.scores[0]
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    run = RowRun(session)
    register_row_run(run)
    run_id = run.run_id
    unregister_row_run(run_id)

    persistence = InferenceRowPersistenceService(memory_backend)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={"scores": ScoresExportContext(persistence=persistence)},
    )
    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="orphan persist",
    )
    with pytest.raises(RuntimeError, match="missing RowRun"):
        ScoresPersistencePolicy().persist(
            ctx,
            ComputeScope(
                analytic_id="scores",
                game_id=628580,
                perspective=1,
                turn=sample_turn.settings.turn,
                player_id=score.ownerid,
            ),
            {"runId": run_id, "rowComplete": row_complete},
        )
    assert persistence.get_row(628580, 1, sample_turn.settings.turn, score.ownerid) is None
