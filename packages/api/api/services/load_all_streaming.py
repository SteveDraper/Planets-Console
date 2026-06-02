"""Orchestration for NDJSON streaming of bulk turn load progress."""

import json
from collections.abc import Callable, Iterator

from api.errors import PlanetsConsoleError
from api.transport.load_all_turns import LoadAllStreamItem, iter_load_all_ndjson_lines


def stream_load_all_turns(
    load_iterator: Callable[[], Iterator[LoadAllStreamItem]],
) -> Iterator[str]:
    """Run bulk load and yield NDJSON lines, including one error line on failure."""
    try:
        yield from iter_load_all_ndjson_lines(load_iterator())
    except PlanetsConsoleError as exc:
        yield json.dumps({"type": "error", "detail": str(exc)}) + "\n"
