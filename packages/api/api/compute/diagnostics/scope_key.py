"""Wire-oriented compute scope key formatting for diagnostics."""

from __future__ import annotations

from api.compute.scope import WILDCARD, ComputeScope


def format_compute_scope_key(scope: ComputeScope) -> str:
    """Return a stable string key for one compute scope."""
    parts = [scope.analytic_id, f"g{scope.game_id}"]
    if scope.perspective != WILDCARD:
        parts.append(f"p{scope.perspective}")
    if scope.turn != WILDCARD:
        parts.append(f"t{scope.turn}")
    if scope.player_id != WILDCARD:
        parts.append(f"pl{scope.player_id}")
    if scope.parameters:
        param_parts = ",".join(f"{key}={value}" for key, value in scope.parameters)
        parts.append(f"params({param_parts})")
    return "@".join(parts)
