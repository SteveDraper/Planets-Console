"""Codecs for persisted military score build inference row terminal state."""

from __future__ import annotations

from dataclasses import dataclass, replace

from dacite import from_dict

from api.analytics.military_score_inference.host_turn_targets import (
    HostTurnFunctionalTarget,
    host_turn_functional_target_from_persistence_dict,
    host_turn_functional_target_to_persistence_dict,
    host_turn_functional_target_to_wire_dict,
    host_turn_targets_from_accelerated_segments,
    host_turn_targets_from_wire_event,
)
from api.serialization.codecs import DACITE_CONFIG, dataclass_to_json

INFERENCE_ROW_PERSISTENCE_VERSION = 2


@dataclass
class PersistedInferenceRow:
    """Terminal wire ``complete`` payload fields (without ``playerId``).

    Durable storage keeps functional row state: status, summary, solutions, and
    ``host_turn_targets``. Solver ``diagnostics`` (including full action catalogs)
    are wire/live-only and must not be written to storage.
    """

    status: str
    summary: str
    solution_count: int
    is_complete: bool
    solutions: list[dict[str, object]]
    diagnostics: dict[str, object] | None = None
    host_turn_targets: list[HostTurnFunctionalTarget] | None = None
    persistence_version: int | None = None


def persisted_inference_row_from_json(data: dict) -> PersistedInferenceRow:
    payload = dict(data)
    raw_targets = payload.pop("host_turn_targets", None)
    row = from_dict(
        data_class=PersistedInferenceRow,
        data=payload,
        config=DACITE_CONFIG,
    )
    if not isinstance(raw_targets, list):
        return row
    targets = [
        host_turn_functional_target_from_persistence_dict(entry)
        for entry in raw_targets
        if isinstance(entry, dict)
    ]
    if not targets:
        return row
    return replace(row, host_turn_targets=targets)


def persisted_inference_row_to_json(row: PersistedInferenceRow) -> dict:
    payload = dataclass_to_json(row)
    # Never persist wire/live solver diagnostics (action catalogs can be tens of MB).
    payload.pop("diagnostics", None)
    if row.host_turn_targets is not None:
        payload["host_turn_targets"] = [
            host_turn_functional_target_to_persistence_dict(target)
            for target in row.host_turn_targets
        ]
    return payload


def upgrade_persisted_inference_row(
    row: PersistedInferenceRow,
) -> tuple[PersistedInferenceRow, bool]:
    """Normalize a row for durable storage / read: targets yes, diagnostics no.

    Extracts ``host_turn_targets`` from legacy ``diagnostics.accelerated_segments``
    when targets are missing, then clears diagnostics so action catalogs are never
    written or left on the in-memory row after upgrade.
    """
    host_turn_targets = row.host_turn_targets
    if not host_turn_targets and row.diagnostics is not None:
        upgraded_targets = host_turn_targets_from_accelerated_segments(
            row.diagnostics.get("accelerated_segments"),
        )
        if upgraded_targets:
            host_turn_targets = list(upgraded_targets)

    upgraded = replace(
        row,
        host_turn_targets=host_turn_targets,
        diagnostics=None,
        persistence_version=INFERENCE_ROW_PERSISTENCE_VERSION,
    )
    return upgraded, upgraded != row


def persisted_inference_row_from_wire_complete(
    wire_event: dict[str, object],
) -> PersistedInferenceRow:
    """Build a durable row from a wire ``complete`` event.

    Solutions and host-turn targets are kept; solver diagnostics are omitted.
    """
    wire_solutions = wire_event.get("solutions")
    host_turn_targets = list(host_turn_targets_from_wire_event(wire_event))
    return PersistedInferenceRow(
        status=str(wire_event.get("status", "")),
        summary=str(wire_event.get("summary", "")),
        solution_count=int(wire_event.get("solutionCount", 0)),
        is_complete=bool(wire_event.get("isComplete", True)),
        solutions=wire_solutions if isinstance(wire_solutions, list) else [],
        diagnostics=None,
        host_turn_targets=host_turn_targets or None,
        persistence_version=INFERENCE_ROW_PERSISTENCE_VERSION,
    )


def wire_complete_from_persisted_row(row: PersistedInferenceRow) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "complete",
        "status": row.status,
        "summary": row.summary,
        "solutionCount": row.solution_count,
        "isComplete": row.is_complete,
        "solutions": row.solutions,
    }
    if row.diagnostics is not None:
        payload["diagnostics"] = row.diagnostics
    if row.host_turn_targets is not None:
        payload["hostTurnTargets"] = [
            host_turn_functional_target_to_wire_dict(target) for target in row.host_turn_targets
        ]
    return payload
