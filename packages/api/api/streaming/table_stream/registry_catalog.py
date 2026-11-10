"""Catalog of table-stream registries for diagnostics and live-stream queries.

Registries are catalogued by ``registry_bootstrap`` on the stream connect path,
before any controller is attached, so a scan never registers or imports
anything. A scan reads the published catalog and each registry's published
snapshot, and takes no lock: the walk shell watch reads it under the
orchestrator lock.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Any, Protocol

from api.streaming.table_stream.controller_base import OnWalkStreamController


class TableStreamScopeBinding(Protocol):
    """Minimal scope attributes required for diagnostics stream bindings."""

    game_id: int
    perspective: int
    turn_number: int


class CatalogedTableStreamRegistry(Protocol):
    """What the catalog reads from a registered table-stream registry.

    Every registered registry holds on-walk stream controllers. Each read
    returns one published snapshot and takes no lock.
    """

    def items(self) -> tuple[tuple[Any, OnWalkStreamController], ...]: ...

    def controller_for_scope(self, scope: Any) -> OnWalkStreamController | None: ...

    def list_active_scopes(self) -> tuple[Any, ...]: ...


_RegistryEntry = tuple[str, CatalogedTableStreamRegistry, Callable[[Any], dict[str, Any]]]
_registry_entries_lock = threading.Lock()
_registry_entries: tuple[_RegistryEntry, ...] = ()


def scope_binding_wire(scope: TableStreamScopeBinding) -> dict[str, Any]:
    """Map a table-stream scope to the diagnostics server-stream wire fields."""
    return {
        "gameId": scope.game_id,
        "perspective": scope.perspective,
        "turn": scope.turn_number,
    }


def register_table_stream_registry(
    analytic_id: str,
    registry: CatalogedTableStreamRegistry,
    *,
    binding_wire: Callable[[Any], dict[str, Any]] = scope_binding_wire,
) -> None:
    """Catalog one analytic table-stream registry; a second registration of an id is ignored."""
    global _registry_entries
    with _registry_entries_lock:
        if any(existing_id == analytic_id for existing_id, _, _ in _registry_entries):
            return
        _registry_entries = (*_registry_entries, (analytic_id, registry, binding_wire))


@dataclass(frozen=True)
class LiveTableStream:
    """One active scope on a registered table-stream registry, as seen by a scan.

    ``controller`` is the controller attached when the scan saw the scope.
    ``is_live`` re-asks the registry.
    """

    analytic_id: str
    scope: TableStreamScopeBinding
    controller: OnWalkStreamController
    _registry: CatalogedTableStreamRegistry = field(repr=False)

    def is_live(self) -> bool:
        """Whether a controller is still attached for this scope."""
        return self._registry.controller_for_scope(self.scope) is not None


def live_table_streams(analytic_ids: Collection[str]) -> tuple[LiveTableStream, ...]:
    """Active streams with an attached controller on the registries for the given analytic ids.

    Each registry contributes one snapshot of its attached controllers. An
    analytic id with no catalogued registry contributes no stream.
    """
    wanted = frozenset(analytic_ids)
    return tuple(
        LiveTableStream(analytic_id, scope, controller, registry)
        for analytic_id, registry, _binding_wire in _registry_entries
        if analytic_id in wanted
        for scope, controller in registry.items()
    )


def active_table_stream_bindings() -> tuple[dict[str, Any], ...]:
    """Return active stream bindings from every registered table-stream registry."""
    bindings: list[dict[str, Any]] = []
    for analytic_id, registry, binding_wire in _registry_entries:
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

    Each scope exposes ``game_id``, ``perspective``, and ``turn_number``. An
    analytic id with no catalogued registry contributes no turns. The same turn
    on more than one analytic is returned once.
    """
    by_analytic = active_table_stream_turns_by_analytic(game_id, perspective, analytic_ids)
    return frozenset().union(*by_analytic.values())


def reset_table_stream_registry_catalog_for_tests() -> None:
    global _registry_entries
    with _registry_entries_lock:
        _registry_entries = ()
