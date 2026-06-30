"""NDJSON wire events and line encoding for fleet table materialization streams."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from typing import TypeAlias

from api.errors import PlanetsConsoleError

logger = logging.getLogger(__name__)

_FLEET_TABLE_STREAM_UNEXPECTED_ERROR_DETAIL = "Internal server error"

TABLE_STREAM_ALREADY_ACTIVE_DETAIL = "A fleet table stream is already active for this scope."


def fleet_ledger_updated_event(*, ledger: dict[str, object]) -> dict[str, object]:
    return {"type": "ledger_updated", "ledger": ledger}


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
