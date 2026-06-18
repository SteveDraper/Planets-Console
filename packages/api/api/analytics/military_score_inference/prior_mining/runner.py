"""Orchestration for inference prior mining."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from api.analytics.military_score_inference.prior_mining.report import (
    PriorMiningReport,
    pattern_report_from_discovery,
)
from api.analytics.military_score_inference.prior_weights_asset import (
    PriorWeightsAsset,
    default_prior_weights_dir,
)
from api.concepts.game_category import GameCategory
from api.planets_nu import PlanetsNuClient
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend
from api.transport.game_info_update import RefreshGameInfoParams

from .accumulation import PriorMiningAccumulation
from .component_name_catalog import ComponentNameCatalogBuilder
from .discovery import (
    PatternDiscoveryCounters,
    PatternDiscoveryResult,
    iter_accepted_games_for_pattern,
)
from .extraction_pool import ExtractionProcessPool, run_extractions_for_game
from .log import LOGGER
from .merge import (
    is_prior_weights_asset_present,
    load_or_bootstrap_asset,
    merge_accumulation_into_asset,
    prior_weights_path_for_category,
    write_prior_weights_asset,
)
from .patterns import PriorMiningPattern, PriorMiningPatternConfig, load_prior_mining_patterns
from .prepare_game import PrepareGameResult
from .prepare_pool import GamePreparePrefetcher
from .report import (
    GameMiningErrorDetail,
    IncompleteLoadAllDetail,
    merge_accumulation_into_report,
)


@dataclass
class CategoryMiningState:
    asset: PriorWeightsAsset
    initial_contributing_game_ids: frozenset[int] = frozenset()
    contributing_game_ids: set[int] = field(default_factory=set)
    pattern_contributed_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    accumulation: PriorMiningAccumulation = field(default_factory=PriorMiningAccumulation)
    new_game_ids: list[int] = field(default_factory=list)
    rejected_game_ids: list[int] = field(default_factory=list)
    name_catalog: ComponentNameCatalogBuilder = field(default_factory=ComponentNameCatalogBuilder)


def run_prior_miner(
    *,
    patterns_path: Path,
    storage_root: Path,
    assets_dir: Path,
    planets: PlanetsNuClient,
    turn_load: TurnLoadService,
    game_service: GameService,
    storage: StorageBackend,
    dry_run: bool = False,
    debug: bool = False,
    workers: int = 1,
    loadall_params: RefreshGameInfoParams | None = None,
) -> PriorMiningReport:
    if workers < 1:
        raise ValueError("workers must be at least 1")

    pattern_config = load_prior_mining_patterns(patterns_path)
    report = PriorMiningReport(dry_run=dry_run, debug=debug)
    LOGGER.info(
        "starting prior miner (dry_run=%s, debug=%s, workers=%s, patterns=%s, storage_root=%s)",
        dry_run,
        debug,
        workers,
        patterns_path,
        storage_root,
    )
    category_states = _initialize_category_states(pattern_config, assets_dir=assets_dir)
    for category, state in category_states.items():
        LOGGER.info(
            "category %s: %s prior contributing game(s)",
            category.value,
            len(state.contributing_game_ids),
        )

    try:
        for pattern in pattern_config.patterns:
            category = pattern.game_category
            state = category_states[category]
            LOGGER.info("running pattern %s for category %s", pattern.id, category.value)
            pattern_result = _mine_pattern(
                pattern=pattern,
                state=state,
                planets=planets,
                turn_load=turn_load,
                game_service=game_service,
                storage_root=storage_root,
                report=report,
                debug=debug,
                workers=workers,
                loadall_params=loadall_params,
            )
            report.patterns.append(pattern_report_from_discovery(pattern_result))
    except Exception as exc:
        report.aborted = True
        report.abort_message = str(exc)
        LOGGER.exception("prior miner stopped before completing all patterns")
    finally:
        _flush_mined_category_results(
            category_states=category_states,
            assets_dir=assets_dir,
            report=report,
            dry_run=dry_run,
        )

    return report


def _flush_mined_category_results(
    *,
    category_states: dict[GameCategory, CategoryMiningState],
    assets_dir: Path,
    report: PriorMiningReport,
    dry_run: bool,
) -> None:
    """Merge accumulated counts into prior weight assets and record written paths."""
    for category, state in category_states.items():
        provenance_updates = _provenance_updates_for_state(state)
        if not provenance_updates and not state.new_game_ids:
            continue
        output_path = prior_weights_path_for_category(category, base_dir=assets_dir)
        if state.new_game_ids:
            report.merged_categories.append(category.value)
            merge_accumulation_into_report(report, state.accumulation)
        if dry_run:
            LOGGER.info(
                "category %s: dry run -- would merge %s new game(s), "
                "%s provenance id(s) (%s rejected)",
                category.value,
                len(state.new_game_ids),
                len(provenance_updates),
                len(state.rejected_game_ids),
            )
            continue
        LOGGER.info(
            "category %s: merging %s new game(s), %s provenance id(s) into %s",
            category.value,
            len(state.new_game_ids),
            len(provenance_updates),
            output_path,
        )
        if not is_prior_weights_asset_present(category, base_dir=assets_dir):
            LOGGER.info(
                "category %s: creating new prior weights asset from template at %s",
                category.value,
                output_path,
            )
        merged_asset = merge_accumulation_into_asset(
            state.asset,
            state.accumulation,
            provenance_game_ids=provenance_updates,
        )
        write_prior_weights_asset(
            output_path,
            merged_asset,
            name_catalog=state.name_catalog.build(),
        )
        report.written_assets.append(str(output_path))
        LOGGER.info("wrote prior weights asset %s", output_path)


def _mine_pattern(
    *,
    pattern: PriorMiningPattern,
    state: CategoryMiningState,
    planets: PlanetsNuClient,
    turn_load: TurnLoadService,
    game_service: GameService,
    storage_root: Path,
    report: PriorMiningReport,
    debug: bool,
    workers: int,
    loadall_params: RefreshGameInfoParams | None,
) -> PatternDiscoveryResult:
    target_successes = max(0, pattern.max_games - state.pattern_contributed_counts[pattern.id])
    LOGGER.info(
        "pattern %s (%s): target %s successful game(s) (cap %s, already contributed %s, debug=%s)",
        pattern.id,
        pattern.game_category.value,
        target_successes,
        pattern.max_games,
        state.pattern_contributed_counts[pattern.id],
        debug,
    )
    if target_successes == 0:
        return PatternDiscoveryResult(
            pattern_id=pattern.id,
            game_category=pattern.game_category,
            candidates_examined=0,
            category_mismatches=0,
            already_contributed=0,
            games_attempted=(),
            games_rejected=(),
            games_added=(),
            slots_remaining=0,
        )

    counters = PatternDiscoveryCounters()
    games_added: list[int] = []
    games_attempted: list[int] = []
    games_rejected: list[int] = []
    attempted_ids: set[int] = set()

    game_source = _iter_games_for_pattern(
        pattern,
        planets=planets,
        contributing_game_ids=frozenset(state.contributing_game_ids),
        counters=counters,
        attempted_ids=attempted_ids,
        target_successes=target_successes,
        debug=debug,
        games_attempted=games_attempted,
        games_added=games_added,
    )

    with GamePreparePrefetcher(
        storage_root=storage_root, loadall_params=loadall_params
    ) as prefetcher:
        with ExtractionProcessPool(workers=workers, storage_root=storage_root) as extraction_pool:
            scheduled_id = next(game_source, None)
            pending_future = None
            if scheduled_id is not None:
                games_attempted.append(scheduled_id)
                attempted_ids.add(scheduled_id)
                pending_future = prefetcher.submit(scheduled_id)

            while pending_future is not None:
                prepared = pending_future.result()

                next_scheduled_id = next(game_source, None)
                if next_scheduled_id is not None:
                    games_attempted.append(next_scheduled_id)
                    attempted_ids.add(next_scheduled_id)
                    pending_future = prefetcher.submit(next_scheduled_id)
                else:
                    pending_future = None

                LOGGER.info("mining game %s (pattern %s)", prepared.game_id, pattern.id)
                try:
                    mined = _process_prepared_game(
                        prepared=prepared,
                        game_service=game_service,
                        turn_load=turn_load,
                        storage_root=storage_root,
                        workers=workers,
                        state=state,
                        report=report,
                        extraction_pool=extraction_pool,
                    )
                except Exception as exc:
                    LOGGER.exception(
                        "game %s: mining failed with unexpected error (pattern %s)",
                        prepared.game_id,
                        pattern.id,
                    )
                    report.game_mining_errors.append(
                        GameMiningErrorDetail(game_id=prepared.game_id, message=str(exc))
                    )
                    mined = False
                if mined:
                    games_added.append(prepared.game_id)
                    state.contributing_game_ids.add(prepared.game_id)
                    state.pattern_contributed_counts[pattern.id] += 1
                    state.new_game_ids.append(prepared.game_id)
                    LOGGER.info(
                        "game %s mined successfully (pattern %s)",
                        prepared.game_id,
                        pattern.id,
                    )
                else:
                    games_rejected.append(prepared.game_id)
                    state.contributing_game_ids.add(prepared.game_id)
                    state.rejected_game_ids.append(prepared.game_id)
                    LOGGER.warning(
                        "game %s skipped during mining (pattern %s)",
                        prepared.game_id,
                        pattern.id,
                    )

    if debug:
        slots_remaining = max(0, target_successes - len(games_attempted))
    else:
        slots_remaining = max(0, target_successes - len(games_added))

    LOGGER.info(
        "pattern %s complete: %s game(s) mined, %s rejected, %s slot(s) remaining",
        pattern.id,
        len(games_added),
        len(games_rejected),
        slots_remaining,
    )
    return PatternDiscoveryResult(
        pattern_id=pattern.id,
        game_category=pattern.game_category,
        candidates_examined=counters.candidates_examined,
        category_mismatches=counters.category_mismatches,
        already_contributed=counters.already_contributed,
        games_attempted=tuple(games_attempted),
        games_rejected=tuple(games_rejected),
        games_added=tuple(games_added),
        slots_remaining=slots_remaining,
    )


def _initialize_category_states(
    pattern_config: PriorMiningPatternConfig,
    *,
    assets_dir: Path,
) -> dict[GameCategory, CategoryMiningState]:
    categories = {pattern.game_category for pattern in pattern_config.patterns}
    states: dict[GameCategory, CategoryMiningState] = {}
    for category in categories:
        asset = load_or_bootstrap_asset(category, base_dir=assets_dir)
        state = CategoryMiningState(asset=asset)
        if is_prior_weights_asset_present(category, base_dir=assets_dir):
            state.initial_contributing_game_ids = frozenset(asset.contributing_game_ids)
            state.contributing_game_ids.update(asset.contributing_game_ids)
            state.pattern_contributed_counts = _pattern_counts_from_asset(
                pattern_config,
                asset.contributing_game_ids,
            )
        states[category] = state
    return states


def _provenance_updates_for_state(state: CategoryMiningState) -> tuple[int, ...]:
    """Game ids to append to contributingGameIds (successful and rejected this run)."""
    return tuple(
        sorted(
            game_id
            for game_id in state.contributing_game_ids
            if game_id not in state.initial_contributing_game_ids
        )
    )


def _pattern_counts_from_asset(
    pattern_config: PriorMiningPatternConfig,
    contributing_game_ids: tuple[int, ...],
) -> dict[str, int]:
    """Approximate per-pattern contributed counts from global provenance only."""
    del pattern_config, contributing_game_ids
    return defaultdict(int)


def _iter_games_for_pattern(
    pattern: PriorMiningPattern,
    *,
    planets: PlanetsNuClient,
    contributing_game_ids: frozenset[int],
    counters: PatternDiscoveryCounters,
    attempted_ids: set[int],
    target_successes: int,
    debug: bool,
    games_attempted: list[int],
    games_added: list[int],
):
    for game_id in iter_accepted_games_for_pattern(
        pattern,
        planets=planets,
        contributing_game_ids=contributing_game_ids,
        counters=counters,
        attempted_game_ids=attempted_ids,
    ):
        if debug and len(games_attempted) >= target_successes:
            break
        if not debug and len(games_added) >= target_successes:
            break
        yield game_id


def _process_prepared_game(
    *,
    prepared: PrepareGameResult,
    game_service: GameService,
    turn_load: TurnLoadService,
    storage_root: Path,
    workers: int,
    state: CategoryMiningState,
    report: PriorMiningReport,
    extraction_pool: ExtractionProcessPool,
) -> bool:
    if prepared.outcome == "error":
        report.game_mining_errors.append(
            GameMiningErrorDetail(
                game_id=prepared.game_id,
                message=prepared.error_message or "unknown prepare error",
            )
        )
        return False

    if prepared.outcome == "skipped_not_finished":
        report.games_skipped_incomplete_loadall += 1
        return False

    if prepared.outcome == "skipped_incomplete":
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
        return False

    game_id = prepared.game_id
    info = game_service.get_game_info(game_id)
    extraction_summary = run_extractions_for_game(
        game_info=info,
        game_id=game_id,
        turn_load=turn_load,
        storage_root=storage_root,
        workers=workers,
        accumulation=state.accumulation,
        name_catalog=state.name_catalog,
        report=report,
        extraction_pool=extraction_pool,
    )
    report.adjunct_skips += extraction_summary.adjunct_skips
    report.horwasp_skips += extraction_summary.horwasp_skips
    report.ship_build_validation_drops += extraction_summary.ship_build_validation_drops
    LOGGER.info(
        "game %s: extraction finished (%s ok, %s adjunct skips, %s horwasp skips, %s errors)",
        game_id,
        extraction_summary.units_ok,
        extraction_summary.adjunct_skips,
        extraction_summary.horwasp_skips,
        extraction_summary.extraction_errors,
    )
    return True


def _mine_game(
    *,
    game_id: int,
    turn_load: TurnLoadService,
    game_service: GameService,
    storage: StorageBackend,
    storage_root: Path,
    planets: PlanetsNuClient,
    state: CategoryMiningState,
    report: PriorMiningReport,
    workers: int,
    loadall_params: RefreshGameInfoParams | None,
) -> bool:
    """Prepare and extract one game on the main process (tests and direct callers)."""
    from .prepare_game import prepare_game_for_mining

    prepared = prepare_game_for_mining(
        game_id=game_id,
        storage=storage,
        turn_load=turn_load,
        game_service=game_service,
        planets=planets,
        loadall_params=loadall_params,
    )
    with ExtractionProcessPool(workers=workers, storage_root=storage_root) as extraction_pool:
        return _process_prepared_game(
            prepared=prepared,
            game_service=game_service,
            turn_load=turn_load,
            storage_root=storage_root,
            workers=workers,
            state=state,
            report=report,
            extraction_pool=extraction_pool,
        )


def default_assets_dir() -> Path:
    return default_prior_weights_dir()
