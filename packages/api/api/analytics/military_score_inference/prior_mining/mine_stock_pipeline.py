"""Mine-stock replay, extract, and flush for the inference prior miner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from api.concepts.game_category import GameCategory
from api.models.game import GameInfo
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from api.transport.game_info_update import RefreshGameInfoParams

from .extraction_pool import ExtractionProcessPool, run_mine_stock_extractions_for_game
from .log import LOGGER
from .mine_stock import (
    MineStockAccumulation,
    MineStockAsset,
    load_or_bootstrap_mine_stock_asset,
    merge_mine_stock_accumulation_into_asset,
    mine_stock_path_for_category,
    write_mine_stock_asset,
)
from .prefetch import prefetch_and_process_games
from .prepare_game import PrepareGameResult
from .report import (
    GameMiningErrorDetail,
    IncompleteLoadAllDetail,
    PriorMiningReport,
    merge_mine_stock_accumulation_into_report,
)


@dataclass
class MineStockCategoryState:
    asset: MineStockAsset
    accumulation: MineStockAccumulation = field(default_factory=MineStockAccumulation)
    initial_game_ids: frozenset[int] = frozenset()
    game_ids: set[int] = field(default_factory=set)


def load_mine_stock_category_state(
    category: GameCategory, *, assets_dir: Path
) -> MineStockCategoryState:
    asset = load_or_bootstrap_mine_stock_asset(category, base_dir=assets_dir)
    ids = frozenset(asset.contributing_game_ids)
    return MineStockCategoryState(
        asset=asset,
        initial_game_ids=ids,
        game_ids=set(ids),
    )


def mine_stock_provenance_updates(state: MineStockCategoryState) -> tuple[int, ...]:
    """Game ids to append to mine-stock contributingGameIds this run."""
    return tuple(
        sorted(game_id for game_id in state.game_ids if game_id not in state.initial_game_ids)
    )


def flush_mine_stock_for_category(
    *,
    category: GameCategory,
    mine_stock: MineStockCategoryState,
    assets_dir: Path,
    report: PriorMiningReport,
    dry_run: bool,
) -> None:
    provenance_updates = mine_stock_provenance_updates(mine_stock)
    if not provenance_updates and mine_stock.accumulation.sample_count == 0:
        return
    output_path = mine_stock_path_for_category(category, base_dir=assets_dir)
    merge_mine_stock_accumulation_into_report(
        report,
        mine_stock.accumulation,
        category=category.value,
    )
    if dry_run:
        LOGGER.info(
            "category %s: dry run -- would merge %s mine-stock sample(s), "
            "%s provenance id(s) into %s",
            category.value,
            mine_stock.accumulation.sample_count,
            len(provenance_updates),
            output_path,
        )
        return
    LOGGER.info(
        "category %s: merging %s mine-stock sample(s), %s provenance id(s) into %s",
        category.value,
        mine_stock.accumulation.sample_count,
        len(provenance_updates),
        output_path,
    )
    merged_asset = merge_mine_stock_accumulation_into_asset(
        mine_stock.asset,
        mine_stock.accumulation,
        provenance_game_ids=provenance_updates,
    )
    write_mine_stock_asset(output_path, merged_asset)
    report.written_assets.append(str(output_path))
    LOGGER.info("wrote mine-stock asset %s", output_path)


def process_prepared_mine_stock_game(
    *,
    prepared: PrepareGameResult,
    game_service: GameService,
    turn_load: TurnLoadService,
    storage_root: Path,
    workers: int,
    mine_stock: MineStockCategoryState,
    report: PriorMiningReport,
    extraction_pool: ExtractionProcessPool,
) -> GameInfo | None:
    """Record this game on the mine-stock set and extract if prepare succeeded.

    Incomplete and error games still join the skip-set. Returns the loaded
    ``GameInfo`` when the game was ready (extract was attempted, including
    nominefields skip).
    """
    mine_stock.game_ids.add(prepared.game_id)
    if prepared.outcome != "ready":
        _record_unready_prepare_result(prepared, report)
        return None
    info = game_service.get_game_info(prepared.game_id)
    _extract_mine_stock_for_ready_game(
        info=info,
        game_id=prepared.game_id,
        turn_load=turn_load,
        storage_root=storage_root,
        workers=workers,
        mine_stock=mine_stock,
        report=report,
        extraction_pool=extraction_pool,
    )
    return info


def _extract_mine_stock_for_ready_game(
    *,
    info: GameInfo,
    game_id: int,
    turn_load: TurnLoadService,
    storage_root: Path,
    workers: int,
    mine_stock: MineStockCategoryState,
    report: PriorMiningReport,
    extraction_pool: ExtractionProcessPool,
) -> None:
    if info.settings.nominefields:
        report.mine_stock_nominefields_skips += 1
        LOGGER.info("game %s: skip mine-stock (nominefields)", game_id)
        return
    summary = run_mine_stock_extractions_for_game(
        game_info=info,
        game_id=game_id,
        turn_load=turn_load,
        storage_root=storage_root,
        workers=workers,
        accumulation=mine_stock.accumulation,
        report=report,
        extraction_pool=extraction_pool,
    )
    report.mine_stock_horwasp_skips += summary.horwasp_skips
    LOGGER.info(
        "game %s: mine-stock finished (%s ok, %s zero-stock, %s horwasp skips, %s errors)",
        game_id,
        summary.units_ok,
        summary.zero_stock,
        summary.horwasp_skips,
        summary.extraction_errors,
    )


def replay_mine_stock_for_category(
    *,
    category: GameCategory,
    prior_contributing_game_ids: tuple[int, ...],
    mine_stock: MineStockCategoryState,
    turn_load: TurnLoadService,
    game_service: GameService,
    storage_root: Path,
    report: PriorMiningReport,
    workers: int,
    loadall_params: RefreshGameInfoParams | None,
) -> None:
    replay_ids = [
        game_id for game_id in prior_contributing_game_ids if game_id not in mine_stock.game_ids
    ]
    LOGGER.info(
        "category %s: replaying mine-stock for %s prior contributing game(s)",
        category.value,
        len(replay_ids),
    )
    if not replay_ids:
        return

    def on_scheduled(game_id: int) -> None:
        report.mine_stock_games_attempted.append(game_id)

    def process_prepared(
        prepared: PrepareGameResult,
        extraction_pool: ExtractionProcessPool,
    ) -> None:
        LOGGER.info("replaying mine-stock for game %s (%s)", prepared.game_id, category.value)
        try:
            mined = (
                process_prepared_mine_stock_game(
                    prepared=prepared,
                    game_service=game_service,
                    turn_load=turn_load,
                    storage_root=storage_root,
                    workers=workers,
                    mine_stock=mine_stock,
                    report=report,
                    extraction_pool=extraction_pool,
                )
                is not None
            )
        except Exception as exc:
            LOGGER.exception(
                "game %s: mine-stock replay failed (%s)",
                prepared.game_id,
                category.value,
            )
            report.game_mining_errors.append(
                GameMiningErrorDetail(game_id=prepared.game_id, message=str(exc))
            )
            mined = False
        if mined:
            report.mine_stock_games_added.append(prepared.game_id)
        else:
            report.mine_stock_games_rejected.append(prepared.game_id)

    prefetch_and_process_games(
        game_ids=replay_ids,
        storage_root=storage_root,
        loadall_params=loadall_params,
        workers=workers,
        on_scheduled=on_scheduled,
        process_prepared=process_prepared,
    )


def _record_unready_prepare_result(prepared: PrepareGameResult, report: PriorMiningReport) -> None:
    """Record error/skip outcomes on the shared miner report."""
    if prepared.outcome == "error":
        report.game_mining_errors.append(
            GameMiningErrorDetail(
                game_id=prepared.game_id,
                message=prepared.error_message or "unknown prepare error",
            )
        )
        return
    if prepared.outcome == "skipped_not_finished":
        report.games_skipped_incomplete_loadall += 1
        return
    if prepared.outcome != "skipped_incomplete":
        return
    report.incomplete_loadall_details.append(
        IncompleteLoadAllDetail(
            game_id=prepared.game_id,
            gaps=[
                {
                    "perspective": gap.perspective,
                    "username": gap.username,
                    "missing_turns": list(gap.missing_turns),
                }
                for gap in prepared.incomplete_gaps
            ],
        )
    )
    report.games_skipped_incomplete_loadall += 1
