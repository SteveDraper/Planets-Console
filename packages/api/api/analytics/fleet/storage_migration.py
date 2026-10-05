"""Fleet layout step in the storage migration pipeline.

A current-version legacy ``players`` array is upgraded to an in-document
``ledgers`` map, then written one document per numeric player id at
``.../analytics/fleet/{playerId}``. Non-numeric keys and non-object values
are skipped. The parent is deleted after those player documents are written,
so running the step again converges on the same documents. A legacy ``players``
document whose ``materializationVersion`` is not current is deleted without
parsing player wires. ``ledgers`` documents are split as stored; per-ledger
version checks stay on fleet read.
"""

from __future__ import annotations

from typing import Any

from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.serialization import (
    _require_object_list,
    fleet_acquisition_ledger_from_json,
    fleet_materialization_version_from_json,
    is_current_fleet_materialization_version,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
from api.exceptions import ValidationError
from api.storage.base import JSONValue
from api.storage.migrations import MigrationContext, StorageMigration

# Shared-turn document keys. ``ledgers`` is the map split into per-player files.
# ``players`` is the older array that upgrades into that map first.
FLEET_LEDGERS_KEY = "ledgers"
_FLEET_PLAYERS_KEY = "players"

# Exact shared turn document, before the per-player breakpoint.
_FLEET_PARENT_PATTERN = ("games", "*", "*", "turns", "*", "analytics", "fleet")
_FLEET_PLAYER_PATTERN = ("games", "*", "*", "turns", "*", "analytics", "fleet", "*")


def migrate_fleet_breakpoint(context: MigrationContext) -> None:
    """Split fleet parent documents into per-player files.

    A current-version ``players`` array is upgraded, then each numeric
    ``ledgers`` key whose value is an object is written at
    ``.../analytics/fleet/{playerId}``. Other entries are skipped. A stale
    ``players`` document is removed without parsing. The parent is deleted
    after those writes, including when the map is empty, so a re-run
    converges. Documents with neither shape stay as they are.
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


def _require_int_field(data: dict[str, Any], key: str, *, field_name: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{field_name} {key} must be an int")
    return value


def _is_legacy_fleet_turn_document(data: dict[str, Any]) -> bool:
    """Return whether ``data`` uses the monolithic ``players`` array wire shape."""
    return FLEET_LEDGERS_KEY not in data and _FLEET_PLAYERS_KEY in data


def upgrade_legacy_fleet_turn_document(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a monolithic ``players`` array to an in-document ``ledgers`` map.

    Each entry is stored with default (non-final) provenance. The players wire
    has no materialization-closure flags, so the upgrade does not mark
    ensure-closed legs.
    """
    version = fleet_materialization_version_from_json(data)
    ledgers: dict[str, Any] = {}
    for player_wire in _require_object_list(
        data.get(_FLEET_PLAYERS_KEY, []),
        field_name="fleet turn snapshot players",
    ):
        ledger = fleet_acquisition_ledger_from_json(player_wire)
        ledgers[str(ledger.player_id)] = persisted_fleet_ledger_to_json(
            PersistedFleetLedger(
                ledger=ledger,
                provenance=FleetMaterializationProvenance(),
                materialization_version=version,
            ),
        )
    return {
        "analyticId": data.get("analyticId", ANALYTIC_ID),
        "gameId": _require_int_field(data, "gameId", field_name="fleet turn snapshot"),
        "perspective": _require_int_field(
            data,
            "perspective",
            field_name="fleet turn snapshot",
        ),
        "turn": _require_int_field(data, "turn", field_name="fleet turn snapshot"),
        FLEET_LEDGERS_KEY: ledgers,
    }


def _fleet_ledgers_map(document: JSONValue) -> dict[str, JSONValue] | None:
    """Return ledgers to write, an empty map to drop the parent, or None to keep it.

    Stale monolithic ``players`` documents are dropped before player wires are
    parsed. ``ledgers`` maps are returned unchanged.
    """
    if not isinstance(document, dict):
        return None
    payload: dict[str, Any] = document
    if _is_legacy_fleet_turn_document(payload):
        if not is_current_fleet_materialization_version(
            fleet_materialization_version_from_json(payload),
        ):
            return {}
        payload = upgrade_legacy_fleet_turn_document(payload)
    ledgers = payload.get(FLEET_LEDGERS_KEY)
    if not isinstance(ledgers, dict):
        return None
    return ledgers
