"""Codecs for persisted military score build inference row terminal state."""

from __future__ import annotations

from dataclasses import dataclass

from dacite import from_dict

from api.serialization.codecs import DACITE_CONFIG, dataclass_to_json


@dataclass
class PersistedInferenceRow:
    """Terminal wire ``complete`` payload fields (without ``playerId``)."""

    status: str
    summary: str
    solution_count: int
    is_complete: bool
    solutions: list[dict[str, object]]
    diagnostics: dict[str, object] | None = None


def persisted_inference_row_from_json(data: dict) -> PersistedInferenceRow:
    return from_dict(
        data_class=PersistedInferenceRow,
        data=data,
        config=DACITE_CONFIG,
    )


def persisted_inference_row_to_json(row: PersistedInferenceRow) -> dict:
    return dataclass_to_json(row)


def persisted_inference_row_from_wire_complete(
    wire_event: dict[str, object],
) -> PersistedInferenceRow:
    diagnostics = wire_event.get("diagnostics")
    wire_solutions = wire_event.get("solutions")
    return PersistedInferenceRow(
        status=str(wire_event.get("status", "")),
        summary=str(wire_event.get("summary", "")),
        solution_count=int(wire_event.get("solutionCount", 0)),
        is_complete=bool(wire_event.get("isComplete", True)),
        solutions=wire_solutions if isinstance(wire_solutions, list) else [],
        diagnostics=diagnostics if isinstance(diagnostics, dict) else None,
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
    return payload
