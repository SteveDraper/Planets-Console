"""Inference admission skip and build-inference availability."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_DEAD,
    STATUS_FULL_ALLIANCE,
    STATUS_HORWASP,
    STATUS_NO_PRIOR_TURN,
    STATUS_PLAYER_NOT_FOUND,
    STATUS_VIEWPOINT_OWNER,
)
from api.analytics.military_score_inference.inference_path import (
    InferencePath,
    resolve_inference_path,
)
from api.analytics.military_score_inference.inference_target import ScoreboardTurnLoader
from api.analytics.turn_roster import players_by_id
from api.concepts.diplomacy import is_live_inbound_full_alliance, is_team_locked_full_alliance
from api.concepts.races import is_horwasp
from api.models.game import TurnInfo
from api.models.player import Player, Score
from api.services.player_elimination import is_eliminated_at_turn
from api.transport.inference_stream import inference_complete_event

_SKIP_SUMMARIES = {
    STATUS_VIEWPOINT_OWNER: "Viewpoint owner's builds are already known",
    STATUS_DEAD: "Player is dead",
    STATUS_FULL_ALLIANCE: "Inbound Full Alliance already reveals hulls and mounts",
    STATUS_HORWASP: "Horwasp production is not modeled",
    STATUS_NO_PRIOR_TURN: "Prior turn score data unavailable",
}

BUILD_INFERENCE_UNAVAILABLE_SUMMARY = "Build inference is unavailable"


@dataclass(frozen=True)
class InferenceAdmissionSkip:
    """Cheap terminal for a row that must never submit ``tier_solve``."""

    status: str
    summary: str


def is_build_inference_available(turn: TurnInfo) -> bool:
    """False when Stealth Mode unpublished the military column for every row."""
    return not turn.settings.stealthmode


def resolve_inference_admission_skip(
    turn: TurnInfo,
    player_id: int,
    *,
    perspective: int,
    load_scoreboard_turn: ScoreboardTurnLoader | None = None,
) -> InferenceAdmissionSkip | None:
    """Return a skip terminal when this row must not submit ``tier_solve``.

    Identity and visibility checks run before the scoreboard delta. Stealth Mode
    is build-inference availability, not a per-row skip.
    """
    score = _scoreboard_row(turn, player_id)
    if score is None:
        return InferenceAdmissionSkip(
            status=STATUS_PLAYER_NOT_FOUND,
            summary=f"No score row for player {player_id}",
        )

    if _is_viewpoint_owner(player_id, perspective):
        return _skip(STATUS_VIEWPOINT_OWNER)

    roster = players_by_id(turn)
    target = roster.get(player_id)
    if target is not None and is_eliminated_at_turn(target, turn.settings.turn):
        return _skip(STATUS_DEAD)

    if _is_full_alliance_skip(
        turn,
        perspective=perspective,
        target_player_id=player_id,
        roster=roster,
    ):
        return _skip(STATUS_FULL_ALLIANCE)

    if target is not None and is_horwasp(target.raceid):
        return _skip(STATUS_HORWASP)

    path, _segments = resolve_inference_path(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    if path == InferencePath.NO_PRIOR_TURN:
        return _skip(STATUS_NO_PRIOR_TURN)
    return None


def admission_skip_api_payload(skip: InferenceAdmissionSkip) -> dict[str, object]:
    """Skip product payload: status and summary only (no solver diagnostics)."""
    return {
        "status": skip.status,
        "summary": skip.summary,
        "solutionCount": 0,
        "isComplete": True,
        "solutions": [],
    }


def admission_skip_complete_event(skip: InferenceAdmissionSkip) -> dict[str, object]:
    """Table-stream ``complete`` for a skip row: status and summary only."""
    return inference_complete_event(
        status=skip.status,
        summary=skip.summary,
        solution_count=0,
        is_complete=True,
        solutions=[],
    )


def build_inference_unavailable_api_payload(player_id: int) -> dict[str, object]:
    """GET envelope when build inference availability is off (not a row status)."""
    return {
        "playerId": player_id,
        "summary": BUILD_INFERENCE_UNAVAILABLE_SUMMARY,
        "solutionCount": 0,
        "isComplete": True,
        "solutions": [],
    }


def _skip(status: str) -> InferenceAdmissionSkip:
    return InferenceAdmissionSkip(status=status, summary=_SKIP_SUMMARIES[status])


def _scoreboard_row(turn: TurnInfo, player_id: int) -> Score | None:
    return next((row for row in turn.scores if row.ownerid == player_id), None)


def _is_viewpoint_owner(player_id: int, perspective: int) -> bool:
    return perspective >= 1 and player_id == perspective


def _is_full_alliance_skip(
    turn: TurnInfo,
    *,
    perspective: int,
    target_player_id: int,
    roster: dict[int, Player],
) -> bool:
    if perspective < 1:
        return False
    if is_live_inbound_full_alliance(
        turn.relations,
        viewpoint_player_id=perspective,
        target_player_id=target_player_id,
    ):
        return True
    return is_team_locked_full_alliance(roster.get(perspective), roster.get(target_player_id))
