"""Parallel extraction orchestration for inference prior mining."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal, Protocol, TypeVar

from api.concepts.races import is_horwasp
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
    MineStockRowResult,
    extract_extraction_work_unit,
    extract_mine_stock_work_unit,
    init_extraction_worker,
    run_extraction_job,
    run_mine_stock_job,
    work_unit_has_turn_pair,
)
from .log import LOGGER
from .mine_stock import MineStockAccumulation
from .report import ExtractionErrorDetail, PriorMiningReport
from .turn_cache import MiningTurnCache

TResult = TypeVar("TResult")
TSummary = TypeVar("TSummary")


class _RowOutcome(Protocol):
    unit: ExtractionWorkUnit
    outcome: Literal["ok", "skip", "error"]
    skip_reason: ExtractionSkipReason | None
    error_message: str | None


class _ErrorSkipSummary(Protocol):
    extraction_errors: int
    horwasp_skips: int


DEFAULT_EXTRACTION_CHUNK_SIZE = 256


@dataclass
class ExtractionRunSummary:
    units_enqueued: int = 0
    units_ok: int = 0
    adjunct_skips: int = 0
    horwasp_skips: int = 0
    ship_build_validation_drops: int = 0
    extraction_errors: int = 0


@dataclass
class MineStockRunSummary:
    units_enqueued: int = 0
    units_ok: int = 0
    horwasp_skips: int = 0
    extraction_errors: int = 0
    infoturn_mismatches: int = 0
    zero_stock: int = 0


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

    def executor(self) -> ProcessPoolExecutor | None:
        """Shared process pool when this run is parallel; None for serial."""
        return self._pool


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
        if is_horwasp(player.raceid):
            continue
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


def enumerate_mine_stock_work_units(
    game_info: GameInfo,
    game_id: int,
    turn_load: TurnLoadService,
) -> list[ExtractionWorkUnit]:
    """List every (game, player, host_turn) snapshot eligible for mine-stock."""
    units: list[ExtractionWorkUnit] = []
    latest_turn = game_info.game.turn

    for player in game_info.players:
        player_id = player.id
        if is_horwasp(player.raceid):
            continue
        perspective = GameService.perspective_for_player_id(game_info, player_id, game_id)
        last_turn = last_meaningful_turn(player, latest_turn)
        if last_turn < 1:
            continue

        stored_turns = frozenset(turn_load.list_stored_turn_numbers(game_id, perspective))
        for host_turn in range(1, last_turn + 1):
            if is_eliminated_at_turn(player, host_turn):
                continue
            if host_turn not in stored_turns:
                continue
            units.append(
                ExtractionWorkUnit(
                    game_id=game_id,
                    player_id=player_id,
                    perspective=perspective,
                    host_turn=host_turn,
                    race_id=player.raceid,
                )
            )

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

    def apply_result(result: ExtractionRowResult) -> None:
        _apply_extraction_row_result(
            result,
            accumulation=accumulation,
            name_catalog=name_catalog,
            report=report,
            summary=summary,
        )

    return _process_work_units(
        units=units,
        game_id=game_id,
        turn_load=turn_load,
        storage_root=storage_root,
        workers=workers,
        summary=summary,
        extract_unit=extract_extraction_work_unit,
        run_job=run_extraction_job,
        apply_result=apply_result,
        chunk_size=chunk_size,
        extraction_pool=extraction_pool,
        unit_label="extraction",
    )


def run_mine_stock_extractions_for_game(
    *,
    game_info: GameInfo,
    game_id: int,
    turn_load: TurnLoadService,
    storage_root: Path,
    workers: int,
    accumulation: MineStockAccumulation,
    report: PriorMiningReport,
    chunk_size: int = DEFAULT_EXTRACTION_CHUNK_SIZE,
    extraction_pool: ExtractionProcessPool | None = None,
) -> MineStockRunSummary:
    units = enumerate_mine_stock_work_units(game_info, game_id, turn_load)
    summary = MineStockRunSummary(units_enqueued=len(units))

    def apply_result(result: MineStockRowResult) -> None:
        _apply_mine_stock_row_result(
            result,
            accumulation=accumulation,
            report=report,
            summary=summary,
        )

    return _process_work_units(
        units=units,
        game_id=game_id,
        turn_load=turn_load,
        storage_root=storage_root,
        workers=workers,
        summary=summary,
        extract_unit=extract_mine_stock_work_unit,
        run_job=run_mine_stock_job,
        apply_result=apply_result,
        chunk_size=chunk_size,
        extraction_pool=extraction_pool,
        unit_label="mine-stock",
    )


def _process_work_units(
    *,
    units: list[ExtractionWorkUnit],
    game_id: int,
    turn_load: TurnLoadService,
    storage_root: Path,
    workers: int,
    summary: TSummary,
    extract_unit: Callable[..., TResult],
    run_job: Callable[[ExtractionJob], TResult],
    apply_result: Callable[[TResult], None],
    chunk_size: int,
    extraction_pool: ExtractionProcessPool | None,
    unit_label: str,
) -> TSummary:
    if not units:
        LOGGER.info("game %s: no %s units to process", game_id, unit_label)
        return summary

    LOGGER.info(
        "game %s: processing %s %s unit(s) with %s worker(s)",
        game_id,
        len(units),
        unit_label,
        workers,
    )

    if workers <= 1:
        cache = MiningTurnCache(turn_load)
        for unit in units:
            apply_result(extract_unit(turn_load=turn_load, unit=unit, turn_cache=cache))
        return summary

    resolved_storage_root = str(storage_root.resolve())
    shared_pool = extraction_pool.executor() if extraction_pool is not None else None
    if shared_pool is not None:
        _map_work_unit_batches(
            pool=shared_pool,
            units=units,
            resolved_storage_root=resolved_storage_root,
            run_job=run_job,
            apply_result=apply_result,
            chunk_size=chunk_size,
        )
        return summary

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=init_extraction_worker,
        initargs=(resolved_storage_root,),
    ) as pool:
        _map_work_unit_batches(
            pool=pool,
            units=units,
            resolved_storage_root=resolved_storage_root,
            run_job=run_job,
            apply_result=apply_result,
            chunk_size=chunk_size,
        )

    return summary


def _map_work_unit_batches(
    *,
    pool: ProcessPoolExecutor,
    units: list[ExtractionWorkUnit],
    resolved_storage_root: str,
    run_job: Callable[[ExtractionJob], TResult],
    apply_result: Callable[[TResult], None],
    chunk_size: int,
) -> None:
    index = 0
    while index < len(units):
        batch = units[index : index + chunk_size]
        jobs = [ExtractionJob(storage_root=resolved_storage_root, unit=unit) for unit in batch]
        for result in pool.map(run_job, jobs):
            apply_result(result)
        index += len(batch)


def _apply_shared_row_outcome(
    result: _RowOutcome,
    *,
    summary: _ErrorSkipSummary,
    report: PriorMiningReport,
    payload_present: bool,
    missing_payload_message: str,
    default_error_message: str,
    error_kind: str,
    on_skip: Callable[[ExtractionSkipReason | None], None] | None = None,
) -> bool:
    """Handle skip, error, and missing-payload. Return True when the ok payload applies."""
    if result.outcome == "skip":
        if result.skip_reason == ExtractionSkipReason.HORWASP:
            summary.horwasp_skips += 1
        if on_skip is not None:
            on_skip(result.skip_reason)
        return False

    if result.outcome == "error":
        summary.extraction_errors += 1
        report.extraction_errors.append(
            ExtractionErrorDetail(
                game_id=result.unit.game_id,
                player_id=result.unit.player_id,
                host_turn=result.unit.host_turn,
                message=result.error_message or default_error_message,
            )
        )
        LOGGER.warning(
            "game %s player %s host turn %s: %s error: %s",
            result.unit.game_id,
            result.unit.player_id,
            result.unit.host_turn,
            error_kind,
            result.error_message,
        )
        return False

    if not payload_present:
        summary.extraction_errors += 1
        report.extraction_errors.append(
            ExtractionErrorDetail(
                game_id=result.unit.game_id,
                player_id=result.unit.player_id,
                host_turn=result.unit.host_turn,
                message=missing_payload_message,
            )
        )
        return False

    return True


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

    def on_skip(reason: ExtractionSkipReason | None) -> None:
        if reason == ExtractionSkipReason.ADJUNCT:
            summary.adjunct_skips += 1

    if not _apply_shared_row_outcome(
        result,
        summary=summary,
        report=report,
        payload_present=result.extraction is not None,
        missing_payload_message="extraction row marked ok without payload",
        default_error_message="unknown extraction error",
        error_kind="extraction",
        on_skip=on_skip,
    ):
        return

    extraction = result.extraction
    assert extraction is not None
    accumulation.add_player_host_turn(extraction)
    summary.units_ok += 1
    summary.ship_build_validation_drops += extraction.ship_build_validation_drops


def _apply_mine_stock_row_result(
    result: MineStockRowResult,
    *,
    accumulation: MineStockAccumulation,
    report: PriorMiningReport,
    summary: MineStockRunSummary,
) -> None:
    if not _apply_shared_row_outcome(
        result,
        summary=summary,
        report=report,
        payload_present=result.sample is not None,
        missing_payload_message="mine-stock row marked ok without payload",
        default_error_message="unknown mine-stock extraction error",
        error_kind="mine-stock extraction",
    ):
        return

    sample = result.sample
    assert sample is not None
    accumulation.add_sample(sample)
    summary.units_ok += 1
    summary.infoturn_mismatches += sample.infoturn_mismatches
    if sample.total_units == 0:
        summary.zero_stock += 1
