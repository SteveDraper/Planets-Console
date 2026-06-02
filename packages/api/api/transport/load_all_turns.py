"""Request and response models for bulk turn loading."""

import json
from collections.abc import Callable, Iterator
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field

from api.errors import PlanetsConsoleError

from api.transport.game_info_update import RefreshGameInfoParams

LoadAllTurnsRequest = RefreshGameInfoParams

class LoadAllProgressUpdate(BaseModel):
    """Progress while bulk-loading turns (perspective index, then turns within)."""

    phase: Literal["download", "import", "final_turn"]
    perspective: int = Field(ge=0, description="1-based perspective index; 0 during download.")
    perspective_total: int = Field(ge=0)
    turn: int = Field(ge=0, description="1-based turn step within the current perspective.")
    turn_total: int = Field(ge=0)
    message: str = ""


class LoadAllTurnsResponse(BaseModel):
    """Summary after a bulk load operation."""

    game_id: int
    is_game_finished: bool
    turns_written: int
    turns_skipped: int
    perspectives_touched: list[int] = Field(default_factory=list)
    final_turn_load_failures: list[int] = Field(
        default_factory=list,
        description=(
            "1-based perspective slots where the final turn could not be fetched "
            "via loadturn after a finished-game loadall archive import."
        ),
    )


class LoadAllTurnsStatusResponse(BaseModel):
    """Whether storage already holds the turns expected after a full bulk load."""

    game_id: int
    complete: bool
    is_game_finished: bool
    expected_perspectives: list[int] = Field(default_factory=list)
    latest_turn: int


LoadAllStreamItem: TypeAlias = LoadAllProgressUpdate | LoadAllTurnsResponse


def load_all_stream_event_to_dict(item: LoadAllStreamItem) -> dict[str, Any]:
    """Wire shape for one NDJSON line (progress or complete)."""
    if isinstance(item, LoadAllProgressUpdate):
        return {"type": "progress", **item.model_dump()}
    return {"type": "complete", "result": item.model_dump()}


def iter_load_all_ndjson_lines(iterator: Iterator[LoadAllStreamItem]) -> Iterator[str]:
    """Serialize each stream item as one NDJSON line."""
    for item in iterator:
        yield json.dumps(load_all_stream_event_to_dict(item)) + "\n"


def stream_load_all_turns(
    load_iterator: Callable[[], Iterator[LoadAllStreamItem]],
) -> Iterator[str]:
    """Run bulk load and yield NDJSON lines, including one error line on failure."""
    try:
        yield from iter_load_all_ndjson_lines(load_iterator())
    except PlanetsConsoleError as exc:
        yield json.dumps({"type": "error", "detail": str(exc)}) + "\n"
