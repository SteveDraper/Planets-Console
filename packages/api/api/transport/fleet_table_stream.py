"""NDJSON wire events and line encoding for fleet table materialization streams."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from typing import Literal, TypeAlias

from api.errors import PlanetsConsoleError

logger = logging.getLogger(__name__)

_FLEET_TABLE_STREAM_UNEXPECTED_ERROR_DETAIL = "Internal server error"


def fleet_evidence_freshness_fields(
    *,
    evidence_generation: int | None = None,
    evidence_mark: int | None = None,
) -> dict[str, object]:
    """Stored generation and the current mark. The table compares them."""
    fields: dict[str, object] = {}
    if evidence_generation is not None:
        fields["evidenceGeneration"] = evidence_generation
    if evidence_mark is not None:
        fields["evidenceMark"] = evidence_mark
    return fields


def fleet_ledger_updated_event(
    *,
    ledger: dict[str, object],
    replaces_turn_load: bool = True,
    evidence_generation: int | None = None,
    evidence_mark: int | None = None,
) -> dict[str, object]:
    event: dict[str, object] = {"type": "ledger_updated", "ledger": ledger}
    if not replaces_turn_load:
        event["replacesTurnLoad"] = False
    event.update(
        fleet_evidence_freshness_fields(
            evidence_generation=evidence_generation,
            evidence_mark=evidence_mark,
        )
    )
    return event


def fleet_roster_paint_event(
    *,
    paint: Literal["sightings", "ledger"],
    ledger: dict[str, object],
    evidence_generation: int | None = None,
    evidence_mark: int | None = None,
) -> dict[str, object]:
    """Turn-load roster. The table shows it until a host-turn ledger save."""
    event: dict[str, object] = {"type": "roster_paint", "paint": paint, "ledger": ledger}
    event.update(
        fleet_evidence_freshness_fields(
            evidence_generation=evidence_generation,
            evidence_mark=evidence_mark,
        )
    )
    return event


def fleet_work_accepted_event() -> dict[str, object]:
    """The orchestrator has accepted this player's fleet work."""
    return {"type": "work_accepted"}


def fleet_ledger_write_event(*, writing: bool) -> dict[str, object]:
    """This turn's ledger file is being written."""
    return {"type": "ledger_write", "writing": writing}


def fleet_record_refined_event(*, record: dict[str, object]) -> dict[str, object]:
    return {"type": "record_refined", "record": record}


def fleet_provenance_event(
    *,
    turn_evidence_at_n: bool,
    prior_ledger_at_n_minus_1: bool,
    is_final: bool,
) -> dict[str, object]:
    return {
        "type": "provenance",
        "turnEvidenceAtN": turn_evidence_at_n,
        "priorLedgerAtNMinus1": prior_ledger_at_n_minus_1,
        "isFinal": is_final,
    }


def fleet_complete_event(*, is_final: bool, summary: str) -> dict[str, object]:
    return {"type": "complete", "isFinal": is_final, "summary": summary}


def fleet_error_event(detail: str) -> dict[str, object]:
    return {"type": "error", "detail": detail}


FleetTableStreamItem: TypeAlias = dict[str, object]


def iter_fleet_table_ndjson_lines(iterator: Iterator[FleetTableStreamItem]) -> Iterator[str]:
    for item in iterator:
        yield json.dumps(item) + "\n"


def _fleet_table_stream_error_detail(exc: BaseException) -> str:
    if isinstance(exc, PlanetsConsoleError):
        return str(exc) or _FLEET_TABLE_STREAM_UNEXPECTED_ERROR_DETAIL
    return _FLEET_TABLE_STREAM_UNEXPECTED_ERROR_DETAIL


def stream_fleet_table_ndjson(
    stream_iterator: Callable[[], Iterator[FleetTableStreamItem]],
) -> Iterator[str]:
    """Run a fleet table event iterator and yield NDJSON lines."""
    try:
        yield from iter_fleet_table_ndjson_lines(stream_iterator())
    except Exception as exc:
        if not isinstance(exc, PlanetsConsoleError):
            logger.exception("Fleet table NDJSON stream failed")
        yield json.dumps(fleet_error_event(_fleet_table_stream_error_detail(exc))) + "\n"
