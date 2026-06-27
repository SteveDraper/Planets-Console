"""Functional host-turn target payloads for accelerated inference exports."""

from __future__ import annotations


def functional_host_turn_target_from_segment_payload(
    segment_payload: dict[str, object],
) -> dict[str, object]:
    """Strip developer diagnostics from one accelerated segment payload."""
    return {
        "hostTurn": segment_payload["hostTurn"],
        "status": segment_payload["status"],
        "solutionCount": segment_payload["solutionCount"],
        "militaryDelta2x": segment_payload["militaryDelta2x"],
        "warshipDelta": segment_payload["warshipDelta"],
        "freighterDelta": segment_payload["freighterDelta"],
        "solutions": segment_payload["solutions"],
    }


def host_turn_targets_from_accelerated_segments(
    segments_raw: object,
) -> tuple[dict[str, object], ...]:
    if not isinstance(segments_raw, list):
        return ()
    targets: list[dict[str, object]] = []
    for entry in segments_raw:
        if not isinstance(entry, dict):
            continue
        if "hostTurn" not in entry or "solutions" not in entry:
            continue
        targets.append(functional_host_turn_target_from_segment_payload(entry))
    return tuple(targets)


def host_turn_targets_from_wire_event(
    wire_event: dict[str, object],
) -> tuple[dict[str, object], ...]:
    wire_targets = wire_event.get("hostTurnTargets")
    if isinstance(wire_targets, list):
        return tuple(entry for entry in wire_targets if isinstance(entry, dict))
    diagnostics = wire_event.get("diagnostics")
    if isinstance(diagnostics, dict):
        return host_turn_targets_from_accelerated_segments(
            diagnostics.get("accelerated_segments"),
        )
    return ()
