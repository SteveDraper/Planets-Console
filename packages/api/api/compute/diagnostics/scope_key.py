"""Wire-oriented compute scope key formatting for diagnostics."""

from __future__ import annotations

from collections.abc import Mapping

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


def compute_scope_from_lifecycle_detail(detail: Mapping[str, object]) -> ComputeScope:
    """Reconstruct a compute scope from orchestrator lifecycle detail fields."""
    analytic_id = detail["analyticId"]
    game_id = detail["gameId"]
    if not isinstance(analytic_id, str) or not isinstance(game_id, int):
        raise ValueError("lifecycle relatedScope requires analyticId and gameId")
    perspective = detail.get("perspective", WILDCARD)
    turn = detail.get("turn", WILDCARD)
    player_id = detail.get("playerId", WILDCARD)
    if not isinstance(perspective, int) and perspective != WILDCARD:
        raise ValueError("lifecycle relatedScope perspective must be int or wildcard")
    if not isinstance(turn, int) and turn != WILDCARD:
        raise ValueError("lifecycle relatedScope turn must be int or wildcard")
    if not isinstance(player_id, int) and player_id != WILDCARD:
        raise ValueError("lifecycle relatedScope playerId must be int or wildcard")
    raw_parameters = detail.get("parameters")
    if raw_parameters is None:
        parameters: tuple[tuple[str, str], ...] = ()
    elif isinstance(raw_parameters, Mapping):
        parameters = tuple((str(key), str(value)) for key, value in sorted(raw_parameters.items()))
    else:
        raise ValueError("lifecycle relatedScope parameters must be a mapping")
    return ComputeScope(
        analytic_id=analytic_id,
        game_id=game_id,
        perspective=perspective,
        turn=turn,
        player_id=player_id,
        parameters=parameters,
    )


def enrich_lifecycle_detail(detail: Mapping[str, object]) -> dict[str, object]:
    """Add wire scope keys to structured lifecycle detail for timeline recording."""
    payload = dict(detail)
    related_scope = payload.get("relatedScope")
    if related_scope is not None and "relatedScopeKey" not in payload:
        if isinstance(related_scope, ComputeScope):
            payload["relatedScopeKey"] = format_compute_scope_key(related_scope)
        elif isinstance(related_scope, Mapping):
            payload["relatedScopeKey"] = format_compute_scope_key(
                compute_scope_from_lifecycle_detail(related_scope),
            )
    return payload
