"""Off-mode catch-up: which fleet turns refresh, and stamp versus bump.

Backfill earlier turns is off by default. A stale open refreshes fleet from
that turn back through ``appliesFromTurn`` and does not schedule scoreboard
solves on the earlier hops. An absent mark does not walk backward. The open
turn's own scoreboard still runs. A catch-up persist of that turn stamps the
current mark. A scoreboard persist that carries new information for a later
turn bumps the mark and leaves ledger files in place.

The homeworld locator does not call this module, so opening it does not start
the walk.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from api.analytics.fleet.types import FleetEvidenceMark, PersistedFleetLedger
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.errors import NotFoundError
from api.models.game import GameSettings, TurnInfo
from api.serialization.backfill_earlier_turns import backfill_earlier_turns_enabled
from api.services.game_service import backfill_earlier_turns_store_key
from api.services.storage_json import require_dict
from api.storage.base import StorageBackend

_lock = threading.Lock()
# One in-flight off-mode open per player. The root turn is the highest scope
# the dependency walk has seen. Earlier hops are catch-up; this turn is not.
_open_turn_by_player: dict[tuple[int, int, int], int] = {}


def reset_off_mode_catch_up_for_tests() -> None:
    """Drop in-flight open turns. Tests must not leak a shell into the next case."""
    with _lock:
        _open_turn_by_player.clear()


def note_off_mode_open(
    game_id: int,
    perspective: int,
    player_id: int,
    turn: int,
) -> None:
    """Record the shell turn for one player. A higher turn replaces a lower one."""
    key = (game_id, perspective, player_id)
    with _lock:
        current = _open_turn_by_player.get(key)
        if current is None or turn > current:
            _open_turn_by_player[key] = turn


def off_mode_open_turn(game_id: int, perspective: int, player_id: int) -> int | None:
    """Shell turn of the in-flight off-mode open, or None when no open is registered."""
    with _lock:
        return _open_turn_by_player.get((game_id, perspective, player_id))


def clear_off_mode_open(game_id: int, perspective: int, player_id: int) -> None:
    """Drop the in-flight open after its scoreboard stamps or its final fleet lands."""
    with _lock:
        _open_turn_by_player.pop((game_id, perspective, player_id), None)


def read_backfill_earlier_turns(storage: StorageBackend, game_id: int) -> bool:
    """Return the stored setting. A missing record is off and does not submit a walk."""
    try:
        raw = storage.get(backfill_earlier_turns_store_key(game_id))
    except NotFoundError:
        return False
    if not isinstance(raw, dict):
        return False
    return backfill_earlier_turns_enabled(require_dict(raw, f"backfill earlier turns {game_id}"))


def ledger_matches_evidence_mark(
    turn_number: int,
    persisted: PersistedFleetLedger,
    mark: FleetEvidenceMark,
) -> bool:
    """Whether this file is already on the current mark, including an approximate fleet.

    A turn before ``appliesFromTurn`` is on the mark. Otherwise the stored
    generation must equal the mark. This is not ensure-final: provenance can
    still be open.
    """
    if mark.applies_from_turn is not None and turn_number < mark.applies_from_turn:
        return True
    return persisted.evidence_generation == mark.evidence_generation


def mark_is_absent(mark: FleetEvidenceMark) -> bool:
    """An absent mark is generation 0 with ``appliesFromTurn`` unset."""
    return mark.evidence_generation == 0 and mark.applies_from_turn is None


def scoreboard_persist_stamps_current_mark(
    *,
    backfill_enabled: bool,
    open_turn: int | None,
    host_turn: int,
    mark: FleetEvidenceMark,
) -> bool:
    """Catch-up scoreboard of the turn already being refreshed stamps and does not bump.

    An absent mark is the first originating persist: it sets generation 1
    instead of stamping. Any other persist bumps.
    """
    if backfill_enabled or open_turn is None or host_turn != open_turn:
        return False
    if mark_is_absent(mark):
        return False
    return True


def off_mode_prior_needs_catch_up(
    *,
    turn_number: int,
    settings: GameSettings,
    load_turn: Callable[[int], TurnInfo | None],
    prior_ledger: PersistedFleetLedger | None,
    mark: FleetEvidenceMark,
) -> bool:
    """Whether fleet at ``turn_number - 1`` is an off-mode catch-up hop.

    Absent mark: no backward walk. Stop at a prior already on the current mark,
    before ``appliesFromTurn``, or when that turn is not stored. A stored turn
    that is behind the mark is a hop. The hop is a fleet merge, not a scoreboard
    solve.
    """
    prior_turn = turn_number - 1
    if prior_turn < accelerated_ensure_floor(settings, turn_number):
        return False
    if mark_is_absent(mark):
        return False
    if mark.applies_from_turn is not None and prior_turn < mark.applies_from_turn:
        return False
    if load_turn(prior_turn) is None:
        return False
    if prior_ledger is not None and ledger_matches_evidence_mark(prior_turn, prior_ledger, mark):
        return False
    return True


def live_fleet_and_scores_turns(game_id: int, perspective: int) -> frozenset[int]:
    """Host turns that already have a live fleet or scoreboard table stream."""
    from api.analytics.fleet.fleet_table_stream_registry import get_fleet_table_stream_registry
    from api.analytics.military_score_inference.inference_table_stream_registry import (
        get_inference_table_stream_registry,
    )

    turns: set[int] = set()
    for scope in get_fleet_table_stream_registry().list_active_scopes():
        if scope.game_id == game_id and scope.perspective == perspective:
            turns.add(scope.turn_number)
    for scope in get_inference_table_stream_registry().list_active_scopes():
        if scope.game_id == game_id and scope.perspective == perspective:
            turns.add(scope.turn_number)
    return frozenset(turns)
