"""Catalog of generic table-stream registries for diagnostics and live-stream queries."""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Any, Protocol

from api.streaming.table_stream.registry import TableStreamRegistry


class TableStreamScopeBinding(Protocol):
    """Minimal scope attributes required for diagnostics stream bindings."""

    game_id: int
    perspective: int
    turn_number: int


_RegistryEntry = tuple[str, TableStreamRegistry[Any, Any], Callable[[Any], dict[str, Any]]]
_registry_entries: list[_RegistryEntry] = []


def scope_binding_wire(scope: TableStreamScopeBinding) -> dict[str, Any]:
    """Map a table-stream scope to the diagnostics server-stream wire fields."""
    return {
        "gameId": scope.game_id,
        "perspective": scope.perspective,
        "turn": scope.turn_number,
    }


def register_table_stream_registry(
    analytic_id: str,
    registry: TableStreamRegistry[Any, Any],
    *,
    binding_wire: Callable[[Any], dict[str, Any]] = scope_binding_wire,
) -> None:
    """Register one analytic table-stream registry for diagnostics snapshots."""
    for existing_id, _, _ in _registry_entries:
        if existing_id == analytic_id:
            return
    _registry_entries.append((analytic_id, registry, binding_wire))


def _registered_table_stream_entries() -> list[_RegistryEntry]:
    from api.streaming.table_stream.registry_bootstrap import (
        ensure_table_stream_registries_registered,
    )

    ensure_table_stream_registries_registered()
    return _registry_entries


def active_table_stream_bindings() -> tuple[dict[str, Any], ...]:
    """Return active stream bindings from every registered table-stream registry."""
    bindings: list[dict[str, Any]] = []
    for analytic_id, registry, binding_wire in _registered_table_stream_entries():
        for scope in registry.list_active_scopes():
            wire = binding_wire(scope)
            wire["analyticId"] = analytic_id
            bindings.append(wire)
    return tuple(bindings)


def active_table_stream_turns(
    game_id: int,
    perspective: int,
    analytic_ids: Collection[str],
) -> frozenset[int]:
    """Turns with a live table stream for this game, perspective, and analytics.

    Registries are registered before the scan. Each scope exposes ``game_id``,
    ``perspective``, and ``turn_number``. An analytic id with no registry
    contributes no turns. The same turn on more than one analytic is returned
    once.
    """
    wanted = frozenset(analytic_ids)
    turns: set[int] = set()
    for analytic_id, registry, _binding_wire in _registered_table_stream_entries():
        if analytic_id not in wanted:
            continue
        for scope in registry.list_active_scopes():
            if scope.game_id == game_id and scope.perspective == perspective:
                turns.add(scope.turn_number)
    return frozenset(turns)


def reset_table_stream_registry_catalog_for_tests() -> None:
    from api.streaming.table_stream.registry_bootstrap import (
        reset_table_stream_registry_bootstrap_for_tests,
    )

    _registry_entries.clear()
    reset_table_stream_registry_bootstrap_for_tests()
