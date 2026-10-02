"""Fleet layout step in the storage migration pipeline.

Turns a legacy shared turn document (``players`` array or ``ledgers`` map) into
one document per player at ``.../analytics/fleet/{playerId}``. Row-content
stamps such as ``materializationVersion`` stay on the ledger and are applied
when fleet reads the player file.
"""

from __future__ import annotations

from api.analytics.fleet.constants import FLEET_LEDGERS_KEY
from api.analytics.fleet.serialization import (
    is_legacy_fleet_turn_document,
    upgrade_legacy_fleet_turn_document,
)
from api.storage.migrations import MigrationContext, StorageMigration

# Exact shared turn document, before the per-player breakpoint.
_FLEET_PARENT_PATTERN = ("games", "*", "*", "turns", "*", "analytics", "fleet")
_FLEET_PLAYER_PATTERN = ("games", "*", "*", "turns", "*", "analytics", "fleet", "*")


def migrate_fleet_breakpoint(context: MigrationContext) -> None:
    """Split each legacy fleet turn document into per-player documents."""
    for path, document in context.iter_documents(_FLEET_PARENT_PATTERN):
        if not isinstance(document, dict):
            continue
        if not is_legacy_fleet_turn_document(document) and FLEET_LEDGERS_KEY not in document:
            continue
        data = document
        if is_legacy_fleet_turn_document(data):
            data = upgrade_legacy_fleet_turn_document(data)
        ledgers = data.get(FLEET_LEDGERS_KEY, {})
        if isinstance(ledgers, dict):
            for player_key, wire in ledgers.items():
                if not isinstance(player_key, str) or not player_key.isdigit():
                    continue
                if not isinstance(wire, dict):
                    continue
                context.put_document(f"{path}/{player_key}", wire)
        context.delete_document(path)


def fleet_storage_migration() -> StorageMigration:
    """Return the fleet step that brings a directory to storage version 1."""
    return StorageMigration(
        version=1,
        introduced_pattern=_FLEET_PLAYER_PATTERN,
        structural_handler=migrate_fleet_breakpoint,
        retires_parent=True,
        retired_keys=("players", "ledgers"),
    )
