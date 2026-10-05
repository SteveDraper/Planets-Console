"""Fleet layout step in the storage migration pipeline.

A current-version legacy ``players`` array is upgraded to an in-document
``ledgers`` map, then written one document per numeric player id at
``.../analytics/fleet/{playerId}``. Non-numeric keys and non-object values
are skipped. The parent is deleted. A legacy ``players`` document whose
``materializationVersion`` is not current is deleted without parsing player
wires. ``ledgers`` documents are split as stored; per-ledger version checks
stay on fleet read.
"""

from __future__ import annotations

from api.analytics.fleet.constants import FLEET_LEDGERS_KEY
from api.analytics.fleet.serialization import (
    fleet_materialization_version_from_json,
    is_current_fleet_materialization_version,
    is_legacy_fleet_turn_document,
    upgrade_legacy_fleet_turn_document,
)
from api.storage.base import JSONValue
from api.storage.migrations import MigrationContext, StorageMigration

# Exact shared turn document, before the per-player breakpoint.
_FLEET_PARENT_PATTERN = ("games", "*", "*", "turns", "*", "analytics", "fleet")
_FLEET_PLAYER_PATTERN = ("games", "*", "*", "turns", "*", "analytics", "fleet", "*")


def migrate_fleet_breakpoint(context: MigrationContext) -> None:
    """Split fleet parent documents into per-player files.

    A current-version ``players`` array is upgraded, then each numeric
    ``ledgers`` key whose value is an object is written at
    ``.../analytics/fleet/{playerId}``. Other entries are skipped. A stale
    ``players`` document is removed without parsing. The parent is deleted,
    including when the map is empty. Documents with neither shape stay as
    they are.
    """
    for path, document in context.iter_documents(_FLEET_PARENT_PATTERN):
        ledgers = _fleet_ledgers_map(document)
        if ledgers is None:
            continue
        for player_key, ledger in ledgers.items():
            if not player_key.isdigit() or not isinstance(ledger, dict):
                continue
            context.put_document(f"{path}/{player_key}", ledger)
        context.delete_document(path)


def fleet_storage_migration() -> StorageMigration:
    """Return the fleet step that brings a directory to storage version 1."""
    return StorageMigration(
        version=1,
        introduced_pattern=_FLEET_PLAYER_PATTERN,
        structural_handler=migrate_fleet_breakpoint,
    )


def _fleet_ledgers_map(document: JSONValue) -> dict[str, JSONValue] | None:
    """Return ledgers to write, an empty map to drop the parent, or None to keep it.

    Stale monolithic ``players`` documents are dropped before player wires are
    parsed. ``ledgers`` maps are returned unchanged.
    """
    if not isinstance(document, dict):
        return None
    payload = document
    if is_legacy_fleet_turn_document(payload):
        if not is_current_fleet_materialization_version(
            fleet_materialization_version_from_json(payload),
        ):
            return {}
        payload = upgrade_legacy_fleet_turn_document(payload)
    ledgers = payload.get(FLEET_LEDGERS_KEY)
    if not isinstance(ledgers, dict):
        return None
    return ledgers
