"""Shared export scope helpers for fleet materialization."""

from __future__ import annotations

from api.analytics.export_types import ExportScope
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetTurnSnapshot


def ledgers_for_scope(
    snapshot: FleetTurnSnapshot,
    scope: ExportScope,
) -> list[FleetAcquisitionLedger]:
    if scope.player_id is None:
        return list(snapshot.players)
    return [ledger for ledger in snapshot.players if ledger.player_id == scope.player_id]
