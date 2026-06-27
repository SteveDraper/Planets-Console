"""Codecs for persisted military score build inference row terminal state."""

from __future__ import annotations

from dataclasses import dataclass, replace

from dacite import from_dict

from api.analytics.military_score_inference.host_turn_targets import (
    host_turn_targets_from_accelerated_segments,
)
from api.serialization.codecs import DACITE_CONFIG, dataclass_to_json

INFERENCE_ROW_PERSISTENCE_VERSION = 2


@dataclass
class PersistedInferenceRow:
    """Terminal wire ``complete`` payload fields (without ``playerId``)."""

    status: str
    summary: str
    solution_count: int
    is_complete: bool
    solutions: list[dict[str, object]]
    diagnostics: dict[str, object] | None = None
    host_turn_targets: list[dict[str, object]] | None = None
    persistence_version: int | None = None


def persisted_inference_row_from_json(data: dict) -> PersistedInferenceRow:
    return from_dict(
        data_class=PersistedInferenceRow,
        data=data,
        config=DACITE_CONFIG,
    )


def persisted_inference_row_to_json(row: PersistedInferenceRow) -> dict:
    return dataclass_to_json(row)


def upgrade_persisted_inference_row(
    row: PersistedInferenceRow,
) -> tuple[PersistedInferenceRow, bool]:
    """Migrate legacy v1 rows to v2 functional host-turn targets on read."""
    if (
        row.persistence_version is not None
        and row.persistence_version >= INFERENCE_ROW_PERSISTENCE_VERSION
    ):
        return row, False

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
        persistence_version=INFERENCE_ROW_PERSISTENCE_VERSION,
    )
    return upgraded, upgraded != row


def persisted_inference_row_from_wire_complete(
    wire_event: dict[str, object],
) -> PersistedInferenceRow:
    from api.analytics.military_score_inference.host_turn_targets import (
        host_turn_targets_from_wire_event,
    )

    diagnostics = wire_event.get("diagnostics")
    wire_solutions = wire_event.get("solutions")
    host_turn_targets = list(host_turn_targets_from_wire_event(wire_event))
    return PersistedInferenceRow(
        status=str(wire_event.get("status", "")),
        summary=str(wire_event.get("summary", "")),
        solution_count=int(wire_event.get("solutionCount", 0)),
        is_complete=bool(wire_event.get("isComplete", True)),
        solutions=wire_solutions if isinstance(wire_solutions, list) else [],
        diagnostics=diagnostics if isinstance(diagnostics, dict) else None,
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
        payload["hostTurnTargets"] = row.host_turn_targets
    return payload
