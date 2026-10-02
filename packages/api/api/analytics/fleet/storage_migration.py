"""Fleet layout step in the storage migration pipeline.

The handler upgrades a legacy ``players`` array to an in-document ``ledgers``
map, then writes one document per player at ``.../analytics/fleet/{playerId}``
and deletes the parent. Row-content stamps such as ``materializationVersion``
stay on the ledger and are applied when fleet reads the player file.
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
    """Upgrade a legacy ``players`` array and write per-player fleet documents.

    ``ledgers`` map keys become ``.../analytics/fleet/{playerId}`` documents.
    The parent is deleted, including when the map is empty. Documents with
    neither shape stay as they are.
    """
    for path, document in context.iter_documents(_FLEET_PARENT_PATTERN):
        ledgers = _fleet_ledgers_map(document)
        if ledgers is None:
            continue
        for player_key, ledger in ledgers.items():
            context.put_document(f"{path}/{player_key}", ledger)
        context.delete_document(path)


def fleet_retired_document_holds_path(document: JSONValue, old_suffix: str) -> bool:
    """Return whether a copied-in parent still contains ``old_suffix``.

    ``old_suffix`` is the path the previous registry stored inside the parent.
    The player id is its first segment: a ``ledgers`` map key or a ``players``
    array ``playerId``. Nested keys that match the suffix itself are the
    generic retired-suffix check, not this hook.
    """
    player_key = old_suffix.split("/", 1)[0]
    if player_key == "" or not isinstance(document, dict):
        return False
    ledgers = document.get(FLEET_LEDGERS_KEY)
    if isinstance(ledgers, dict) and player_key in ledgers:
        return True
    return _players_array_holds_id(document.get(_PLAYERS_KEY), player_key)


def fleet_storage_migration() -> StorageMigration:
    """Return the fleet step that brings a directory to storage version 1."""
    return StorageMigration(
        version=1,
        introduced_pattern=_FLEET_PLAYER_PATTERN,
        structural_handler=migrate_fleet_breakpoint,
        holds_retired_path=fleet_retired_document_holds_path,
    )


def _fleet_ledgers_map(document: JSONValue) -> dict[str, JSONValue] | None:
    if not isinstance(document, dict):
        return None
    payload = document
    if is_legacy_fleet_turn_document(payload):
        payload = upgrade_legacy_fleet_turn_document(payload)
    ledgers = payload.get(FLEET_LEDGERS_KEY)
    if not isinstance(ledgers, dict):
        return None
    return ledgers


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
