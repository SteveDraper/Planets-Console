"""Parallel extraction orchestration for inference prior mining."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from api.models.game import GameInfo
from api.services.game_service import GameService
from api.services.player_elimination import is_eliminated_at_turn, last_meaningful_turn
from api.services.turn_load_service import TurnLoadService

from .accumulation import PriorMiningAccumulation
from .component_name_catalog import ComponentNameCatalogBuilder
from .extraction_worker import (
    ExtractionJob,
    ExtractionRowResult,
    ExtractionSkipReason,
    ExtractionWorkUnit,
    extract_extraction_work_unit,
    init_extraction_worker,
    run_extraction_job,
    work_unit_has_turn_pair,
)
from .log import LOGGER
from .report import ExtractionErrorDetail, PriorMiningReport
from .turn_cache import MiningTurnCache

DEFAULT_EXTRACTION_CHUNK_SIZE = 256


@dataclass
class ExtractionRunSummary:
    units_enqueued: int = 0
    units_ok: int = 0
    adjunct_skips: int = 0
    ship_build_validation_drops: int = 0
    extraction_errors: int = 0


class ExtractionProcessPool:
    """Reusable extraction worker pool for an entire pattern mining run."""

    def __init__(self, *, workers: int, storage_root: Path) -> None:
        self.workers = workers
        self.storage_root = storage_root
        self._resolved_storage_root = str(storage_root.resolve())
        self._pool: ProcessPoolExecutor | None = None

    def __enter__(self) -> ExtractionProcessPool:
        if self.workers > 1:
            self._pool = ProcessPoolExecutor(
                max_workers=self.workers,
                initializer=init_extraction_worker,
                initargs=(self._resolved_storage_root,),
            )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None

    @property
    def is_parallel(self) -> bool:
        return self._pool is not None


def enumerate_extraction_work_units(
    game_info: GameInfo,
    game_id: int,
    turn_load: TurnLoadService,
) -> list[ExtractionWorkUnit]:
    """List every (game, player, host_turn) unit eligible for extraction."""
    units: list[ExtractionWorkUnit] = []
    latest_turn = game_info.game.turn

    for player in game_info.players:
        player_id = player.id
        perspective = GameService.perspective_for_player_id(game_info, player_id, game_id)
        last_turn = last_meaningful_turn(player, latest_turn)
        if last_turn < 2:
            continue

        stored_turns = frozenset(turn_load.list_stored_turn_numbers(game_id, perspective))
        for host_turn in range(1, last_turn):
            score_turn_number = host_turn + 1
            if is_eliminated_at_turn(player, score_turn_number):
                continue
            unit = ExtractionWorkUnit(
                game_id=game_id,
                player_id=player_id,
                perspective=perspective,
                host_turn=host_turn,
                race_id=player.raceid,
            )
            if not work_unit_has_turn_pair(turn_load, unit, stored_turns=stored_turns):
                continue
            units.append(unit)

    return units


def run_extractions_for_game(
    *,
    game_info: GameInfo,
    game_id: int,
    turn_load: TurnLoadService,
    storage_root: Path,
    workers: int,
    accumulation: PriorMiningAccumulation,
    name_catalog: ComponentNameCatalogBuilder,
    report: PriorMiningReport,
    chunk_size: int = DEFAULT_EXTRACTION_CHUNK_SIZE,
    extraction_pool: ExtractionProcessPool | None = None,
) -> ExtractionRunSummary:
    units = enumerate_extraction_work_units(game_info, game_id, turn_load)
    summary = ExtractionRunSummary(units_enqueued=len(units))
    if not units:
        LOGGER.info("game %s: no extraction units to process", game_id)
        return summary

    LOGGER.info(
        "game %s: processing %s extraction unit(s) with %s worker(s)",
        game_id,
        len(units),
        workers,
    )

    if workers <= 1:
        cache = MiningTurnCache(turn_load)
        for unit in units:
            result = extract_extraction_work_unit(turn_load=turn_load, unit=unit, turn_cache=cache)
            _apply_extraction_row_result(
                result,
                accumulation=accumulation,
                name_catalog=name_catalog,
                report=report,
                summary=summary,
            )
        return summary

    resolved_storage_root = str(storage_root.resolve())
    if extraction_pool is not None and extraction_pool.is_parallel:
        pool = extraction_pool._pool
        assert pool is not None
        _run_extraction_batches(
            pool=pool,
            units=units,
            resolved_storage_root=resolved_storage_root,
            accumulation=accumulation,
            name_catalog=name_catalog,
            report=report,
            summary=summary,
            chunk_size=chunk_size,
        )
        return summary

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=init_extraction_worker,
        initargs=(resolved_storage_root,),
    ) as pool:
        _run_extraction_batches(
            pool=pool,
            units=units,
            resolved_storage_root=resolved_storage_root,
            accumulation=accumulation,
            name_catalog=name_catalog,
            report=report,
            summary=summary,
            chunk_size=chunk_size,
        )

    return summary


def _run_extraction_batches(
    *,
    pool: ProcessPoolExecutor,
    units: list[ExtractionWorkUnit],
    resolved_storage_root: str,
    accumulation: PriorMiningAccumulation,
    name_catalog: ComponentNameCatalogBuilder,
    report: PriorMiningReport,
    summary: ExtractionRunSummary,
    chunk_size: int,
) -> None:
    index = 0
    while index < len(units):
        batch = units[index : index + chunk_size]
        jobs = [ExtractionJob(storage_root=resolved_storage_root, unit=unit) for unit in batch]
        for result in pool.map(run_extraction_job, jobs):
            _apply_extraction_row_result(
                result,
                accumulation=accumulation,
                name_catalog=name_catalog,
                report=report,
                summary=summary,
            )
        index += len(batch)


def _apply_extraction_row_result(
    result: ExtractionRowResult,
    *,
    accumulation: PriorMiningAccumulation,
    name_catalog: ComponentNameCatalogBuilder,
    report: PriorMiningReport,
    summary: ExtractionRunSummary,
) -> None:
    if result.name_catalog is not None:
        name_catalog.absorb_catalog(result.name_catalog)

    if result.outcome == "skip":
        if result.skip_reason == ExtractionSkipReason.ADJUNCT:
            summary.adjunct_skips += 1
        return

    if result.outcome == "error":
        summary.extraction_errors += 1
        report.extraction_errors.append(
            ExtractionErrorDetail(
                game_id=result.unit.game_id,
                player_id=result.unit.player_id,
                host_turn=result.unit.host_turn,
                message=result.error_message or "unknown extraction error",
            )
        )
        LOGGER.warning(
            "game %s player %s host turn %s: extraction error: %s",
            result.unit.game_id,
            result.unit.player_id,
            result.unit.host_turn,
            result.error_message,
        )
        return

    if result.extraction is None:
        summary.extraction_errors += 1
        report.extraction_errors.append(
            ExtractionErrorDetail(
                game_id=result.unit.game_id,
                player_id=result.unit.player_id,
                host_turn=result.unit.host_turn,
                message="extraction row marked ok without payload",
            )
        )
        return

    accumulation.add_player_host_turn(result.extraction)
    summary.units_ok += 1
    summary.ship_build_validation_drops += result.extraction.ship_build_validation_drops
