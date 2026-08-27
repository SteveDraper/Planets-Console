"""Inference admission skip detectors, persist statuses, and stealth availability."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_admission import (
    is_build_inference_available,
    resolve_inference_admission_skip,
)
from api.analytics.military_score_inference.inference_api_payload import (
    INFERENCE_ADMISSION_SKIP_STATUSES,
    STATUS_DEAD,
    STATUS_FULL_ALLIANCE,
    STATUS_HORWASP,
    STATUS_NO_PRIOR_TURN,
    STATUS_PLAYER_NOT_FOUND,
    STATUS_VIEWPOINT_OWNER,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    ImmediateRowAdmission,
    iter_scores_table_inference_events,
    resolve_row_stream_admission,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_MINE_SCORE_RESIDUAL,
    STATUS_MODERATE_RESIDUAL,
    STATUS_NO_EXACT_SOLUTION,
)
from api.analytics.scores.export_precedence import (
    is_durable_turn_evidence_row_status,
    is_persistable_inference_status,
)
from api.analytics.scores.exports import admit_scores_export_work
from api.analytics.turn_roster import player_by_id
from api.concepts.diplomacy import is_team_locked_full_alliance
from api.concepts.races import HORWASP_RACE_ID
from api.models.enums import PlayerStatus
from api.models.player import Relation
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.scores_exports_helpers import GAME_ID, scores_query_context


def _non_viewpoint_score(turn):
    viewpoint = turn.player.id
    return next(score for score in turn.scores if score.ownerid != viewpoint)


def _replace_player(turn, player_id: int, **overrides):
    players = [
        replace(player, **overrides) if player.id == player_id else player
        for player in turn.players
    ]
    viewpoint = replace(turn.player, **overrides) if turn.player.id == player_id else turn.player
    return replace(turn, players=players, player=viewpoint)


def _relation(
    *,
    playerid: int,
    playertoid: int,
    relationto: int,
    relationfrom: int,
) -> Relation:
    return Relation(
        id=1,
        playerid=playerid,
        playertoid=playertoid,
        relationto=relationto,
        relationfrom=relationfrom,
        conflictlevel=0,
        color="",
    )


def test_is_build_inference_available_false_in_stealth(sample_turn) -> None:
    stealth = replace(
        sample_turn,
        settings=replace(sample_turn.settings, stealthmode=True),
    )
    assert is_build_inference_available(sample_turn) is True
    assert is_build_inference_available(stealth) is False


def test_viewpoint_owner_skip_for_slots_one_through_n(sample_turn) -> None:
    owner_id = sample_turn.player.id
    skip = resolve_inference_admission_skip(
        sample_turn,
        owner_id,
        perspective=owner_id,
    )
    assert skip is not None
    assert skip.status == STATUS_VIEWPOINT_OWNER
    spectator = resolve_inference_admission_skip(
        sample_turn,
        owner_id,
        perspective=0,
    )
    assert spectator is None or spectator.status != STATUS_VIEWPOINT_OWNER


def test_dead_skip_inclusive_of_elimination_turn(sample_turn) -> None:
    target = _non_viewpoint_score(sample_turn)
    death_turn = sample_turn.settings.turn
    dead_turn = _replace_player(
        sample_turn,
        target.ownerid,
        status=int(PlayerStatus.ELIMINATED),
        statusturn=death_turn,
    )
    skip = resolve_inference_admission_skip(
        dead_turn,
        target.ownerid,
        perspective=dead_turn.player.id,
    )
    assert skip is not None
    assert skip.status == STATUS_DEAD

    before_death = _replace_player(
        sample_turn,
        target.ownerid,
        status=int(PlayerStatus.ELIMINATED),
        statusturn=death_turn + 1,
    )
    living = resolve_inference_admission_skip(
        before_death,
        target.ownerid,
        perspective=before_death.player.id,
    )
    assert living is None or living.status != STATUS_DEAD


def test_full_alliance_skip_mutual_not_one_way_or_share_intel(sample_turn) -> None:
    target = _non_viewpoint_score(sample_turn)
    viewpoint = sample_turn.player.id
    mutual = replace(
        sample_turn,
        relations=[
            _relation(
                playerid=viewpoint,
                playertoid=target.ownerid,
                relationto=4,
                relationfrom=4,
            )
        ],
    )
    skip = resolve_inference_admission_skip(
        mutual,
        target.ownerid,
        perspective=viewpoint,
    )
    assert skip is not None
    assert skip.status == STATUS_FULL_ALLIANCE

    one_way = replace(
        sample_turn,
        relations=[
            _relation(
                playerid=viewpoint,
                playertoid=target.ownerid,
                relationto=4,
                relationfrom=1,
            )
        ],
    )
    one_way_skip = resolve_inference_admission_skip(
        one_way,
        target.ownerid,
        perspective=viewpoint,
    )
    assert one_way_skip is None or one_way_skip.status != STATUS_FULL_ALLIANCE

    share_intel = replace(
        sample_turn,
        relations=[
            _relation(
                playerid=viewpoint,
                playertoid=target.ownerid,
                relationto=3,
                relationfrom=3,
            )
        ],
    )
    share_skip = resolve_inference_admission_skip(
        share_intel,
        target.ownerid,
        perspective=viewpoint,
    )
    assert share_skip is None or share_skip.status != STATUS_FULL_ALLIANCE


def test_full_alliance_skip_team_locked(sample_turn) -> None:
    target = _non_viewpoint_score(sample_turn)
    viewpoint = sample_turn.player.id
    teamed = _replace_player(sample_turn, viewpoint, teamid=7)
    teamed = _replace_player(teamed, target.ownerid, teamid=7)
    skip = resolve_inference_admission_skip(
        teamed,
        target.ownerid,
        perspective=viewpoint,
    )
    assert skip is not None
    assert skip.status == STATUS_FULL_ALLIANCE
    assert is_team_locked_full_alliance(
        player_by_id(teamed, viewpoint),
        player_by_id(teamed, target.ownerid),
    )


def test_horwasp_skip(sample_turn) -> None:
    target = _non_viewpoint_score(sample_turn)
    horwasp_turn = _replace_player(sample_turn, target.ownerid, raceid=HORWASP_RACE_ID)
    skip = resolve_inference_admission_skip(
        horwasp_turn,
        target.ownerid,
        perspective=horwasp_turn.player.id,
    )
    assert skip is not None
    assert skip.status == STATUS_HORWASP


def test_no_prior_turn_skip(first_turn) -> None:
    target = _non_viewpoint_score(first_turn)
    skip = resolve_inference_admission_skip(
        first_turn,
        target.ownerid,
        perspective=first_turn.player.id,
    )
    assert skip is not None
    assert skip.status == STATUS_NO_PRIOR_TURN


def test_player_not_found_skip(sample_turn) -> None:
    skip = resolve_inference_admission_skip(
        sample_turn,
        player_id=99_999,
        perspective=sample_turn.player.id,
    )
    assert skip is not None
    assert skip.status == STATUS_PLAYER_NOT_FOUND


def test_skip_complete_has_status_and_summary_only(sample_turn) -> None:
    owner_id = sample_turn.player.id
    admission = resolve_row_stream_admission(
        sample_turn,
        owner_id,
        game_id=GAME_ID,
        perspective=owner_id,
        turn_number=sample_turn.settings.turn,
    )
    assert isinstance(admission, ImmediateRowAdmission)
    event = admission.events[0]
    assert event["type"] == "complete"
    assert event["status"] == STATUS_VIEWPOINT_OWNER
    assert event["summary"]
    assert event["solutionCount"] == 0
    assert "diagnostics" not in event


def test_skip_rows_never_enqueue_tier_ladder(sample_turn, monkeypatch) -> None:
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    enqueued: list[object] = []
    monkeypatch.setattr(
        scheduler,
        "enqueue_tier_ladder",
        lambda *args, **kwargs: enqueued.append((args, kwargs)),
    )
    owner_id = sample_turn.player.id
    admission = resolve_row_stream_admission(
        sample_turn,
        owner_id,
        game_id=GAME_ID,
        perspective=owner_id,
        turn_number=sample_turn.settings.turn,
        force_schedule=True,
    )
    assert isinstance(admission, ImmediateRowAdmission)
    assert admission.events[0]["status"] == STATUS_VIEWPOINT_OWNER
    assert enqueued == []


def test_stealth_does_not_start_stream_or_tier_solve(sample_turn, monkeypatch) -> None:
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    enqueued: list[object] = []
    monkeypatch.setattr(
        scheduler,
        "enqueue_tier_ladder",
        lambda *args, **kwargs: enqueued.append((args, kwargs)),
    )
    stealth = replace(
        sample_turn,
        settings=replace(sample_turn.settings, stealthmode=True),
    )
    player_ids = tuple(score.ownerid for score in stealth.scores)
    events = list(
        iter_scores_table_inference_events(
            stealth,
            player_ids,
            game_id=GAME_ID,
            perspective=stealth.player.id,
            scheduler=scheduler,
        )
    )
    assert events == []
    assert enqueued == []


def test_stealth_ensure_does_not_schedule(sample_turn, persistence) -> None:
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    stealth = replace(
        sample_turn,
        settings=replace(sample_turn.settings, stealthmode=True),
    )
    target = _non_viewpoint_score(stealth)
    ctx = scores_query_context(
        stealth,
        persistence=persistence,
        scheduler=scheduler,
    )
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=stealth.player.id,
        turn=stealth.settings.turn,
        player_id=target.ownerid,
    )
    with patch(
        "api.analytics.scores.exports.schedule_inference_row",
        side_effect=AssertionError("stealth must not schedule tier_solve"),
    ):
        assert admit_scores_export_work(ctx, scope) is True
    stream_scope = InferenceStreamScope(
        game_id=GAME_ID,
        perspective=stealth.player.id,
        turn_number=stealth.settings.turn,
    )
    assert scheduler.row_run_for_player(stream_scope, target.ownerid) is None
    assert (
        persistence.get_row(
            GAME_ID,
            stealth.player.id,
            stealth.settings.turn,
            target.ownerid,
        )
        is None
    )


@pytest.mark.parametrize(
    "status",
    [
        STATUS_EXACT,
        STATUS_NO_EXACT_SOLUTION,
        STATUS_MODERATE_RESIDUAL,
        STATUS_MINE_SCORE_RESIDUAL,
        *sorted(INFERENCE_ADMISSION_SKIP_STATUSES),
    ],
)
def test_persist_admits_functional_and_skip_statuses(status, persistence) -> None:
    assert is_durable_turn_evidence_row_status(status)
    if status in {
        STATUS_EXACT,
        STATUS_NO_EXACT_SOLUTION,
        STATUS_MODERATE_RESIDUAL,
        STATUS_MINE_SCORE_RESIDUAL,
    }:
        assert is_persistable_inference_status(status)
    else:
        assert not is_persistable_inference_status(status)
    persistence.persist_row_complete_for_scope(
        row_complete_with_summary(
            InferenceResult(status=status, solutions=(), diagnostics={"reason": "solver"}),
            summary=status,
        ),
        game_id=GAME_ID,
        perspective=8,
        host_turn=111,
        player_id=3,
    )
    stored = persistence.get_row(GAME_ID, 8, 111, 3)
    assert stored is not None
    assert stored.status == status
    assert stored.diagnostics is None


@pytest.mark.parametrize("status", ["paused", "fetch_error", "pending"])
def test_persist_rejects_non_durable_statuses(status, persistence) -> None:
    assert not is_durable_turn_evidence_row_status(status)
    persistence.persist_row_complete_for_scope(
        row_complete_with_summary(
            InferenceResult(status=status, solutions=(), diagnostics={}),
            summary=status,
        ),
        game_id=GAME_ID,
        perspective=8,
        host_turn=111,
        player_id=3,
    )
    assert persistence.get_row(GAME_ID, 8, 111, 3) is None


def test_mine_residual_sticky_prior_from_persisted_status(persistence) -> None:
    persistence.put_row(
        GAME_ID,
        8,
        110,
        3,
        PersistedInferenceRow(
            status=STATUS_MINE_SCORE_RESIDUAL,
            summary="mine residual",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    assert persistence.has_mine_residual_sticky_prior(GAME_ID, 8, 111, 3) is True
    persistence.put_row(
        GAME_ID,
        8,
        110,
        3,
        PersistedInferenceRow(
            status=STATUS_MODERATE_RESIDUAL,
            summary="moderate",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    assert persistence.has_mine_residual_sticky_prior(GAME_ID, 8, 111, 3) is False
    persistence.put_row(
        GAME_ID,
        8,
        110,
        3,
        PersistedInferenceRow(
            status=STATUS_NO_EXACT_SOLUTION,
            summary="none",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    assert persistence.has_mine_residual_sticky_prior(GAME_ID, 8, 111, 3) is False
    persistence.put_row(
        GAME_ID,
        8,
        110,
        3,
        PersistedInferenceRow(
            status=STATUS_VIEWPOINT_OWNER,
            summary="skip",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    assert persistence.has_mine_residual_sticky_prior(GAME_ID, 8, 111, 3) is False


def test_scores_table_exposes_build_inference_availability(sample_turn) -> None:
    from api.analytics.scores import get_scores_table

    available = get_scores_table(sample_turn)
    assert available["buildInferenceAvailable"] is True
    stealth = replace(
        sample_turn,
        settings=replace(sample_turn.settings, stealthmode=True),
    )
    unavailable = get_scores_table(stealth)
    assert unavailable["buildInferenceAvailable"] is False
