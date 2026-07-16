"""Functional host-turn export resolution for scores analytics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from api.analytics.military_score_inference.accelerated_start import (
    first_reliable_accelerated_scoreboard_turn,
    needs_accelerated_backfill,
    scoreboard_host_turn,
)
from api.analytics.military_score_inference.host_turn_targets import HostTurnFunctionalTarget
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_STOPPED,
    STATUS_TIME_LIMITED,
)
from api.analytics.scores.export_wire import ranked_solutions_from_wire
from api.models.game import GameSettings, TurnInfo
from api.models.player import Score
from api.serialization.inference_row_persistence import PersistedInferenceRow

SearchStatus = Literal["not_started", "in_progress", "paused", "stopped", "complete"]

_COMPLETE_TARGET_STATUSES = frozenset({STATUS_EXACT, STATUS_NO_EXACT_SOLUTION})


def scores_scoreboard_turn_for_placeholder_refine(*, built_turn: int, shell_turn: int) -> int:
    """Map fleet placeholder built_turn to the scoreboard turn that holds its inference."""
    if built_turn < shell_turn:
        return built_turn + 1
    return built_turn


def host_turn_targets_from_persisted_row(
    row: PersistedInferenceRow,
) -> tuple[HostTurnFunctionalTarget, ...]:
    if row.host_turn_targets:
        return tuple(row.host_turn_targets)
    return ()


def functional_target_for_host_turn(
    targets: tuple[HostTurnFunctionalTarget, ...],
    host_turn: int,
) -> HostTurnFunctionalTarget | None:
    for target in targets:
        if target.host_turn == host_turn:
            return target
    return None


@dataclass(frozen=True)
class FunctionalHostTurnPayload:
    """Held solutions and lifecycle status for one scoreboard host turn."""

    solutions: list[dict[str, object]]
    solutions_held: int
    search_status: SearchStatus


def _search_status_from_persisted_row(row: PersistedInferenceRow) -> SearchStatus:
    if row.status in (STATUS_STOPPED, STATUS_TIME_LIMITED):
        return "stopped"
    if row.status in _COMPLETE_TARGET_STATUSES:
        return "complete"
    return "not_started"


def _search_status_from_target_status(status: object) -> SearchStatus:
    if status in (STATUS_STOPPED, STATUS_TIME_LIMITED):
        return "stopped"
    if isinstance(status, str) and status in _COMPLETE_TARGET_STATUSES:
        return "complete"
    return "not_started"


def _payload_from_functional_target(target: HostTurnFunctionalTarget) -> FunctionalHostTurnPayload:
    solutions = ranked_solutions_from_wire(target.solutions)
    return FunctionalHostTurnPayload(
        solutions=solutions,
        solutions_held=target.solution_count,
        search_status=_search_status_from_target_status(target.status),
    )


def _payload_for_host_turn_from_row(
    row: PersistedInferenceRow,
    *,
    scoreboard_turn: int,
    target_host_turn: int,
) -> FunctionalHostTurnPayload | None:
    targets = host_turn_targets_from_persisted_row(row)
    if targets:
        target = functional_target_for_host_turn(targets, target_host_turn)
        if target is None:
            return None
        return _payload_from_functional_target(target)

    if scoreboard_host_turn(scoreboard_turn) != target_host_turn:
        return None
    return FunctionalHostTurnPayload(
        solutions=ranked_solutions_from_wire(row.solutions),
        solutions_held=row.solution_count,
        search_status=_search_status_from_persisted_row(row),
    )


PersistedRowLoader = Callable[[int, int], PersistedInferenceRow | None]


def functional_host_turn_payload_from_persisted_row(
    row: PersistedInferenceRow,
    *,
    source_scoreboard_turn: int,
    target_host_turn: int,
) -> FunctionalHostTurnPayload | None:
    """Select held solutions for ``target_host_turn`` from one persisted inference row."""
    return _payload_for_host_turn_from_row(
        row,
        scoreboard_turn=source_scoreboard_turn,
        target_host_turn=target_host_turn,
    )


def resolve_accelerated_backfill_payload_when_scoreboard_turn_missing(
    *,
    scoreboard_turn: int,
    settings: GameSettings,
    get_persisted_row: PersistedRowLoader,
    player_id: int,
) -> FunctionalHostTurnPayload | None:
    """Load host-turn solutions from the first reliable row when ``scoreboard_turn`` is absent.

    Unreliable accelerated scoreboard turns (``1..N-1``) may be missing from storage
    while accelerated start is still open. Fleet placeholder refine still maps
    ``builtTurn`` to ``scores@(builtTurn + 1)``; this helper resolves the same
    functional payload from ``scores@N`` ``hostTurnTargets``.
    """
    if not needs_accelerated_backfill(scoreboard_turn, settings):
        return None
    target_host_turn = scoreboard_host_turn(scoreboard_turn)
    if target_host_turn is None:
        return None
    source_turn_number = first_reliable_accelerated_scoreboard_turn(settings)
    if source_turn_number is None:
        return None
    source_row = get_persisted_row(source_turn_number, player_id)
    if source_row is None:
        return None
    return functional_host_turn_payload_from_persisted_row(
        source_row,
        source_scoreboard_turn=source_turn_number,
        target_host_turn=target_host_turn,
    )


def resolve_functional_host_turn_payload(
    *,
    scoreboard_turn: int,
    turn: TurnInfo,
    score: Score | None,
    persisted_row: PersistedInferenceRow | None,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None,
    get_persisted_row: PersistedRowLoader | None = None,
) -> FunctionalHostTurnPayload | None:
    """Resolve functional held solutions for the host turn implied by scoreboard_turn."""
    target_host_turn = scoreboard_host_turn(scoreboard_turn)
    if target_host_turn is None:
        return None

    if persisted_row is not None:
        payload = _payload_for_host_turn_from_row(
            persisted_row,
            scoreboard_turn=scoreboard_turn,
            target_host_turn=target_host_turn,
        )
        if payload is not None:
            return payload

    if (
        score is None
        or load_scoreboard_turn is None
        or get_persisted_row is None
        or not needs_accelerated_backfill(scoreboard_turn, turn.settings)
    ):
        return None

    source_turn_number = first_reliable_accelerated_scoreboard_turn(turn.settings)
    if source_turn_number is None:
        return None

    source_row = get_persisted_row(source_turn_number, score.ownerid)
    if source_row is None:
        return None

    return _payload_for_host_turn_from_row(
        source_row,
        scoreboard_turn=source_turn_number,
        target_host_turn=target_host_turn,
    )
