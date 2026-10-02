"""Fleet layout step in the storage migration pipeline.

The handler upgrades a legacy ``players`` array to an in-document ``ledgers``
map. Generic re-home then writes one document per player at
``.../analytics/fleet/{playerId}`` and deletes the parent. Row-content stamps
such as ``materializationVersion`` stay on the ledger and are applied when
fleet reads the player file.
"""

from __future__ import annotations

from api.analytics.fleet.constants import FLEET_LEDGERS_KEY
from api.analytics.fleet.serialization import (
    is_legacy_fleet_turn_document,
    upgrade_legacy_fleet_turn_document,
)
from api.storage.base import JSONValue
from api.storage.migrations import MigrationContext, StorageMigration

# Exact shared turn document, before the per-player breakpoint.
_FLEET_PARENT_PATTERN = ("games", "*", "*", "turns", "*", "analytics", "fleet")
_FLEET_PLAYER_PATTERN = ("games", "*", "*", "turns", "*", "analytics", "fleet", "*")
_PLAYERS_KEY = "players"
_PLAYER_ID_KEY = "playerId"


def migrate_fleet_breakpoint(context: MigrationContext) -> None:
    """Upgrade a legacy ``players`` array to an in-document ``ledgers`` map.

    Documents that already use ``ledgers``, and documents with neither shape,
    stay as they are. Generic re-home writes the player files and deletes the
    parent.
    """
    for path, document in context.iter_documents(_FLEET_PARENT_PATTERN):
        if not isinstance(document, dict) or not is_legacy_fleet_turn_document(document):
            continue
        context.put_document(path, upgrade_legacy_fleet_turn_document(document))


def fleet_retired_document_holds_path(document: JSONValue, breakpoint_path: str) -> bool:
    """Return whether a legacy ``players`` array still contains ``breakpoint_path``.

    Ledgers-map membership is re-home residue: the map key is the path segment.
    This check is the pre-upgrade array, where the id is ``playerId``.
    """
    player_key = breakpoint_path.rpartition("/")[2]
    if player_key == "" or not isinstance(document, dict):
        return False
    return _players_array_holds_id(document.get(_PLAYERS_KEY), player_key)


def fleet_storage_migration() -> StorageMigration:
    """Return the fleet step that brings a directory to storage version 1."""
    return StorageMigration(
        version=1,
        introduced_pattern=_FLEET_PLAYER_PATTERN,
        structural_handler=migrate_fleet_breakpoint,
        rehome_map_suffix=FLEET_LEDGERS_KEY,
        remove_parent=True,
        holds_retired_path=fleet_retired_document_holds_path,
    )


def _players_array_holds_id(players: JSONValue, player_key: str) -> bool:
    if not isinstance(players, list):
        return False
    for entry in players:
        if not isinstance(entry, dict):
            continue
        player_id = entry.get(_PLAYER_ID_KEY)
        if isinstance(player_id, bool) or not isinstance(player_id, int):
            continue
        if str(player_id) == player_key:
            return True
    return False
