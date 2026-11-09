"""Catalog of generic table-stream registries for diagnostics and live-stream queries."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class LiveTableStream:
    """One active scope on a registered table-stream registry, as seen by a scan.

    ``controller`` is the controller attached when the scan saw the scope; the
    catalog does not know its analytic type. ``is_live`` re-asks the registry.
    """

    analytic_id: str
    scope: TableStreamScopeBinding
    controller: object
    _registry: TableStreamRegistry[Any, Any] = field(repr=False)

    def is_live(self) -> bool:
        """Whether a controller is still attached for this scope."""
        return self._registry.controller_for_scope(self.scope) is not None


def live_table_streams(analytic_ids: Collection[str]) -> tuple[LiveTableStream, ...]:
    """Active streams with an attached controller on the registries for the given analytic ids.

    Registries are registered before the scan. An analytic id with no registry
    contributes no stream.
    """
    wanted = frozenset(analytic_ids)
    streams: list[LiveTableStream] = []
    for analytic_id, registry, _binding_wire in _registered_table_stream_entries():
        if analytic_id not in wanted:
            continue
        for scope in registry.list_active_scopes():
            controller = registry.controller_for_scope(scope)
            if controller is not None:
                streams.append(LiveTableStream(analytic_id, scope, controller, registry))
    return tuple(streams)


def active_table_stream_bindings() -> tuple[dict[str, Any], ...]:
    """Return active stream bindings from every registered table-stream registry."""
    bindings: list[dict[str, Any]] = []
    for analytic_id, registry, binding_wire in _registered_table_stream_entries():
        for scope in registry.list_active_scopes():
            wire = binding_wire(scope)
            wire["analyticId"] = analytic_id
            bindings.append(wire)
    return tuple(bindings)


def active_table_stream_turns_by_analytic(
    game_id: int,
    perspective: int,
    analytic_ids: Collection[str],
) -> dict[str, frozenset[int]]:
    """Live table-stream turns for this game and perspective, split by analytic id.

    One walk of the registered registries. An analytic id with no registry, or
    a registered analytic with no matching scope, is absent. The same turn on
    two analytics appears under each id.
    """
    found: dict[str, set[int]] = {}
    for stream in live_table_streams(analytic_ids):
        scope = stream.scope
        if scope.game_id == game_id and scope.perspective == perspective:
            found.setdefault(stream.analytic_id, set()).add(scope.turn_number)
    return {analytic_id: frozenset(turns) for analytic_id, turns in found.items()}


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
    by_analytic = active_table_stream_turns_by_analytic(game_id, perspective, analytic_ids)
    return frozenset().union(*by_analytic.values())


def reset_table_stream_registry_catalog_for_tests() -> None:
    from api.streaming.table_stream.registry_bootstrap import (
        reset_table_stream_registry_bootstrap_for_tests,
    )

    _registry_entries.clear()
    reset_table_stream_registry_bootstrap_for_tests()
