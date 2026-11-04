"""On-disk fleet ages for one homeworld refine turn.

Each roster player's ledger file contributes its known ``ship_id -> built_turn``
map. A missing file is its own stamp value, distinct from a file with no known
build turns. The read does not require ensure-final provenance or a current
fleet evidence generation.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.field_constraints import known_ship_built_turns
from api.analytics.fleet.injected_services import lookup_fleet_compute_services
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.turn_roster import iter_turn_players
from api.models.game import TurnInfo


@dataclass(frozen=True)
class FleetAgePlayerStamp:
    """One roster player's build-turn map, or a missing ledger file."""

    player_id: int
    missing: bool
    built_turns: tuple[tuple[int, int], ...] = ()
    """Sorted ``(ship_id, built_turn)`` pairs. Empty when the file is missing."""


@dataclass(frozen=True)
class FleetAgeInputStamp:
    """Per roster player, the build-turn map a refine turn read from disk."""

    players: tuple[FleetAgePlayerStamp, ...]
    """Sorted by ``player_id``."""


def merged_built_turns(stamp: FleetAgeInputStamp) -> dict[int, int]:
    """Ship ages from players who have a file. Missing files contribute nothing."""
    built_turns: dict[int, int] = {}
    for player in stamp.players:
        if player.missing:
            continue
        for ship_id, built_turn in player.built_turns:
            built_turns[ship_id] = built_turn
    return built_turns


def read_fleet_age_input_stamp(
    persistence: FleetSnapshotPersistenceService | None,
    *,
    game_id: int,
    perspective: int,
    turn: TurnInfo,
) -> FleetAgeInputStamp:
    """Read every roster player's ledger at ``turn``, including non-final files."""
    players: list[FleetAgePlayerStamp] = []
    player_ids = sorted({player.id for player in iter_turn_players(turn)})
    for player_id in player_ids:
        if persistence is None:
            players.append(FleetAgePlayerStamp(player_id=player_id, missing=True))
            continue
        persisted = persistence.get_ledger(game_id, perspective, turn.settings.turn, player_id)
        if persisted is None:
            players.append(FleetAgePlayerStamp(player_id=player_id, missing=True))
            continue
        built_turns = tuple(sorted(known_ship_built_turns(persisted.ledger.records).items()))
        players.append(
            FleetAgePlayerStamp(
                player_id=player_id,
                missing=False,
                built_turns=built_turns,
            )
        )
    return FleetAgeInputStamp(players=tuple(players))


def fleet_persistence_from_context(
    ctx: AnalyticQueryContext,
) -> FleetSnapshotPersistenceService | None:
    fleet = lookup_fleet_compute_services(ctx)
    if fleet is None:
        return None
    return fleet.persistence
