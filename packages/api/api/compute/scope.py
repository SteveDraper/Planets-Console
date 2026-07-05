"""Compute scope identity and normalization from export scope."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from api.analytics.export_types import ExportScope

WILDCARD = "*"

ScopeAxis = Literal["perspective", "turn", "player_id"]
ScopeAxisValue = int | Literal["*"]


@dataclass(frozen=True)
class ScopeKeySpec:
    """Per-analytic declaration of which axes and parameters form compute identity."""

    axes: tuple[ScopeAxis, ...]
    parameter_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComputeScope:
    """Canonical identity for one cacheable orchestrator work unit."""

    analytic_id: str
    game_id: int
    perspective: ScopeAxisValue = WILDCARD
    turn: ScopeAxisValue = WILDCARD
    player_id: ScopeAxisValue = WILDCARD
    parameters: tuple[tuple[str, str], ...] = ()


def fingerprint_parameters(
    parameters: Mapping[str, object] | None,
    *,
    parameter_fields: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    """Return a canonical sorted fingerprint for scope parameter fields."""
    if not parameter_fields:
        return ()
    if parameters is None:
        return tuple((field, "") for field in sorted(parameter_fields))
    fingerprint: list[tuple[str, str]] = []
    for field in sorted(parameter_fields):
        if field not in parameters:
            fingerprint.append((field, ""))
            continue
        fingerprint.append((field, str(parameters[field])))
    return tuple(fingerprint)


def _axis_value(
    axis: ScopeAxis,
    *,
    export_scope: ExportScope,
    scope_key_spec: ScopeKeySpec,
) -> ScopeAxisValue:
    if axis not in scope_key_spec.axes:
        return WILDCARD
    if axis == "perspective":
        return export_scope.perspective
    if axis == "turn":
        return export_scope.turn
    if export_scope.player_id is None:
        raise ValueError(f"Export scope player_id is required when {axis!r} is in scope key axes")
    return export_scope.player_id


def compute_scope_to_export_scope(scope: ComputeScope) -> ExportScope:
    """Map a concrete compute scope to export scope for dependency walks."""
    if scope.perspective == WILDCARD:
        raise ValueError("concrete perspective is required for export planning")
    if scope.turn == WILDCARD:
        raise ValueError("concrete turn is required for export planning")
    player_id = None if scope.player_id == WILDCARD else scope.player_id
    return ExportScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn,
        player_id=player_id,
    )


def normalize_export_scope_to_compute_scope(
    export_scope: ExportScope,
    *,
    analytic_id: str,
    scope_key_spec: ScopeKeySpec,
    parameters: Mapping[str, object] | None = None,
) -> ComputeScope:
    """Map an export query scope to orchestrator compute scope per analytic key spec."""
    return ComputeScope(
        analytic_id=analytic_id,
        game_id=export_scope.game_id,
        perspective=_axis_value(
            "perspective",
            export_scope=export_scope,
            scope_key_spec=scope_key_spec,
        ),
        turn=_axis_value("turn", export_scope=export_scope, scope_key_spec=scope_key_spec),
        player_id=_axis_value(
            "player_id",
            export_scope=export_scope,
            scope_key_spec=scope_key_spec,
        ),
        parameters=fingerprint_parameters(
            parameters,
            parameter_fields=scope_key_spec.parameter_fields,
        ),
    )
