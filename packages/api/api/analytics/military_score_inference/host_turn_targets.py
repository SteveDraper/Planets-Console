"""Functional host-turn target payloads for accelerated inference exports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HostTurnFunctionalTarget:
    """Held solutions and scoreboard deltas for one accelerated host turn."""

    host_turn: int
    status: str
    solution_count: int
    military_delta_2x: int
    warship_delta: int
    freighter_delta: int
    solutions: list[dict[str, object]]


def _required_int(data: dict[str, object], *keys: str) -> int:
    for key in keys:
        value = data.get(key)
        if isinstance(value, int):
            return value
    raise ValueError(f"missing or invalid integer field (tried {keys!r})")


def _required_str(data: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            return value
    raise ValueError(f"missing or invalid string field (tried {keys!r})")


def _required_solutions(data: dict[str, object]) -> list[dict[str, object]]:
    solutions = data.get("solutions")
    if not isinstance(solutions, list):
        raise ValueError("missing or invalid solutions field")
    return [entry for entry in solutions if isinstance(entry, dict)]


def host_turn_functional_target_from_wire_dict(
    data: dict[str, object],
) -> HostTurnFunctionalTarget:
    return HostTurnFunctionalTarget(
        host_turn=_required_int(data, "hostTurn"),
        status=_required_str(data, "status"),
        solution_count=_required_int(data, "solutionCount"),
        military_delta_2x=_required_int(data, "militaryDelta2x"),
        warship_delta=_required_int(data, "warshipDelta"),
        freighter_delta=_required_int(data, "freighterDelta"),
        solutions=_required_solutions(data),
    )


def host_turn_functional_target_from_persistence_dict(
    data: dict[str, object],
) -> HostTurnFunctionalTarget:
    return HostTurnFunctionalTarget(
        host_turn=_required_int(data, "host_turn", "hostTurn"),
        status=_required_str(data, "status"),
        solution_count=_required_int(data, "solution_count", "solutionCount"),
        military_delta_2x=_required_int(data, "military_delta_2x", "militaryDelta2x"),
        warship_delta=_required_int(data, "warship_delta", "warshipDelta"),
        freighter_delta=_required_int(data, "freighter_delta", "freighterDelta"),
        solutions=_required_solutions(data),
    )


def host_turn_functional_target_to_wire_dict(
    target: HostTurnFunctionalTarget,
) -> dict[str, object]:
    return {
        "hostTurn": target.host_turn,
        "status": target.status,
        "solutionCount": target.solution_count,
        "militaryDelta2x": target.military_delta_2x,
        "warshipDelta": target.warship_delta,
        "freighterDelta": target.freighter_delta,
        "solutions": target.solutions,
    }


def host_turn_functional_target_to_persistence_dict(
    target: HostTurnFunctionalTarget,
) -> dict[str, object]:
    return {
        "host_turn": target.host_turn,
        "status": target.status,
        "solution_count": target.solution_count,
        "military_delta_2x": target.military_delta_2x,
        "warship_delta": target.warship_delta,
        "freighter_delta": target.freighter_delta,
        "solutions": target.solutions,
    }


def functional_host_turn_target_from_segment_payload(
    segment_payload: dict[str, object],
) -> HostTurnFunctionalTarget:
    """Strip developer diagnostics from one accelerated segment payload."""
    return host_turn_functional_target_from_wire_dict(segment_payload)


def host_turn_functional_targets_from_wire_list(
    wire_targets: object,
) -> list[HostTurnFunctionalTarget] | None:
    if not isinstance(wire_targets, list):
        return None
    targets: list[HostTurnFunctionalTarget] = []
    for entry in wire_targets:
        if not isinstance(entry, dict):
            continue
        try:
            targets.append(host_turn_functional_target_from_wire_dict(entry))
        except ValueError:
            continue
    return targets or None


def host_turn_targets_from_accelerated_segments(
    segments_raw: object,
) -> tuple[HostTurnFunctionalTarget, ...]:
    if not isinstance(segments_raw, list):
        return ()
    targets: list[HostTurnFunctionalTarget] = []
    for entry in segments_raw:
        if not isinstance(entry, dict):
            continue
        if "hostTurn" not in entry or "solutions" not in entry:
            continue
        targets.append(functional_host_turn_target_from_segment_payload(entry))
    return tuple(targets)


def host_turn_targets_from_wire_event(
    wire_event: dict[str, object],
) -> tuple[HostTurnFunctionalTarget, ...]:
    wire_targets = wire_event.get("hostTurnTargets")
    if isinstance(wire_targets, list):
        parsed = host_turn_functional_targets_from_wire_list(wire_targets)
        if parsed:
            return tuple(parsed)
    diagnostics = wire_event.get("diagnostics")
    if isinstance(diagnostics, dict):
        return host_turn_targets_from_accelerated_segments(
            diagnostics.get("accelerated_segments"),
        )
    return ()
