"""Catalog of generic table-stream registries for diagnostics introspection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from api.streaming.table_stream.registry import TableStreamRegistry

_RegistryEntry = tuple[str, TableStreamRegistry[Any, Any], Callable[[Any], dict[str, Any]]]
_registry_entries: list[_RegistryEntry] = []


def register_table_stream_registry(
    analytic_id: str,
    registry: TableStreamRegistry[Any, Any],
    *,
    binding_wire: Callable[[Any], dict[str, Any]],
) -> None:
    """Register one analytic table-stream registry for diagnostics snapshots."""
    for existing_id, _, _ in _registry_entries:
        if existing_id == analytic_id:
            return
    _registry_entries.append((analytic_id, registry, binding_wire))


def active_table_stream_bindings() -> tuple[dict[str, Any], ...]:
    """Return active stream bindings from every registered table-stream registry."""
    bindings: list[dict[str, Any]] = []
    for analytic_id, registry, binding_wire in _registry_entries:
        for scope in registry.list_active_scopes():
            wire = binding_wire(scope)
            wire["analyticId"] = analytic_id
            bindings.append(wire)
    return tuple(bindings)


def reset_table_stream_registry_catalog_for_tests() -> None:
    _registry_entries.clear()
