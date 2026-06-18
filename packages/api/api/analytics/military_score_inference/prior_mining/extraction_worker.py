"""Single-unit extraction jobs and process-pool worker entry points."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

from api.analytics.military_score_inference.inference_corpus_complexity import classify_complexity
from api.concepts.races import is_horwasp
from api.services.turn_load_service import TurnLoadService

from .component_name_catalog import ComponentNameCatalog, ComponentNameCatalogBuilder
from .observations import (
    PlayerHostTurnExtraction,
    _extract_player_host_turn,
    _has_turn_pair,
    _merged_inventory_for_player_host_turn,
    _score_for_player,
)
from .turn_cache import MiningTurnCache

_worker_turn_load: TurnLoadService | None = None


class ExtractionSkipReason(Enum):
    ADJUNCT = "adjunct"
    HORWASP = "horwasp"
    MISSING_SCORE = "missing_score"


@dataclass(frozen=True)
class ExtractionWorkUnit:
    game_id: int
    player_id: int
    perspective: int
    host_turn: int
    race_id: int


@dataclass(frozen=True)
class ExtractionJob:
    storage_root: str
    unit: ExtractionWorkUnit


@dataclass(frozen=True)
class ExtractionRowResult:
    unit: ExtractionWorkUnit
    outcome: Literal["ok", "skip", "error"]
    extraction: PlayerHostTurnExtraction | None = None
    skip_reason: ExtractionSkipReason | None = None
    name_catalog: ComponentNameCatalog | None = None
    error_message: str | None = None


def init_extraction_worker(storage_root: str) -> None:
    """Configure turn storage once per worker process."""
    global _worker_turn_load
    from .storage_bootstrap import make_turn_load_service_for_storage_root

    _worker_turn_load = make_turn_load_service_for_storage_root(Path(storage_root))


def run_extraction_job(job: ExtractionJob) -> ExtractionRowResult:
    """Run one extraction unit in a worker process."""
    if _worker_turn_load is None:
        init_extraction_worker(job.storage_root)
    assert _worker_turn_load is not None
    try:
        return extract_extraction_work_unit(turn_load=_worker_turn_load, unit=job.unit)
    except Exception as exc:  # noqa: BLE001 - report and continue aggregation
        return ExtractionRowResult(
            unit=job.unit,
            outcome="error",
            error_message=str(exc),
        )


def extract_extraction_work_unit(
    *,
    turn_load: TurnLoadService,
    unit: ExtractionWorkUnit,
    turn_cache: MiningTurnCache | None = None,
) -> ExtractionRowResult:
    """Extract one (game, player, host_turn) unit from stored turns."""
    if is_horwasp(unit.race_id):
        return ExtractionRowResult(
            unit=unit,
            outcome="skip",
            skip_reason=ExtractionSkipReason.HORWASP,
        )

    cache = turn_cache if turn_cache is not None else MiningTurnCache(turn_load)
    name_builder = ComponentNameCatalogBuilder()
    score_turn_number = unit.host_turn + 1

    prior_turn = cache.get_turn_info(unit.game_id, unit.perspective, unit.host_turn)
    score_turn = cache.get_turn_info(unit.game_id, unit.perspective, score_turn_number)
    name_builder.absorb_turn(prior_turn)
    name_builder.absorb_turn(score_turn)
    _absorb_peer_turn_names(
        cache=cache,
        game_id=unit.game_id,
        perspective=unit.perspective,
        host_turn=unit.host_turn,
        score_turn_number=score_turn_number,
        name_builder=name_builder,
    )

    score = _score_for_player(score_turn, unit.player_id)
    if score is None:
        return ExtractionRowResult(
            unit=unit,
            outcome="skip",
            skip_reason=ExtractionSkipReason.MISSING_SCORE,
            name_catalog=name_builder.build(),
        )

    merged = _merged_inventory_for_player_host_turn(
        turn_cache=cache,
        game_id=unit.game_id,
        perspective=unit.perspective,
        host_turn=unit.host_turn,
        score_turn_number=score_turn_number,
        prior_turn=prior_turn,
        score_turn=score_turn,
    )
    complexity, _ = classify_complexity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=unit.player_id,
        score=score,
        merged=merged,
    )
    if complexity == "adjunct":
        return ExtractionRowResult(
            unit=unit,
            outcome="skip",
            skip_reason=ExtractionSkipReason.ADJUNCT,
            name_catalog=name_builder.build(),
        )

    extraction = _extract_player_host_turn(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=unit.player_id,
        score=score,
        race_id=unit.race_id,
    )
    return ExtractionRowResult(
        unit=unit,
        outcome="ok",
        extraction=extraction,
        name_catalog=name_builder.build(),
    )


def _absorb_peer_turn_names(
    *,
    cache: MiningTurnCache,
    game_id: int,
    perspective: int,
    host_turn: int,
    score_turn_number: int,
    name_builder: ComponentNameCatalogBuilder,
) -> None:
    host_perspectives = cache.perspectives_at_turn(game_id, host_turn)
    score_perspectives = cache.perspectives_at_turn(game_id, score_turn_number)
    other_perspectives = sorted(
        other
        for other in host_perspectives & score_perspectives
        if other >= 1 and other != perspective
    )
    for other in other_perspectives:
        name_builder.absorb_turn(cache.get_turn_info(game_id, other, host_turn))
        name_builder.absorb_turn(cache.get_turn_info(game_id, other, score_turn_number))


def work_unit_has_turn_pair(
    turn_load: TurnLoadService,
    unit: ExtractionWorkUnit,
    *,
    stored_turns: frozenset[int] | None = None,
) -> bool:
    turns = (
        stored_turns
        if stored_turns is not None
        else frozenset(turn_load.list_stored_turn_numbers(unit.game_id, unit.perspective))
    )
    return _has_turn_pair(turns, unit.host_turn, unit.host_turn + 1)
