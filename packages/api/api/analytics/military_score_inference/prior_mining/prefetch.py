"""Submit the next game's prepare while the current game is processed."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import Future
from pathlib import Path

from api.transport.game_info_update import RefreshGameInfoParams

from .extraction_pool import ExtractionProcessPool
from .prepare_game import PrepareGameResult
from .prepare_pool import GamePreparePrefetcher


def prefetch_and_process_games(
    *,
    game_ids: Iterable[int],
    storage_root: Path,
    loadall_params: RefreshGameInfoParams | None,
    workers: int,
    on_scheduled: Callable[[int], None],
    process_prepared: Callable[[PrepareGameResult, ExtractionProcessPool], None],
) -> None:
    """Submit the next game's prepare while the current game is processed."""
    remaining = iter(game_ids)
    with GamePreparePrefetcher(
        storage_root=storage_root, loadall_params=loadall_params
    ) as prefetcher:
        with ExtractionProcessPool(workers=workers, storage_root=storage_root) as extraction_pool:

            def submit_next() -> Future[PrepareGameResult] | None:
                next_id = next(remaining, None)
                if next_id is None:
                    return None
                on_scheduled(next_id)
                return prefetcher.submit(next_id)

            pending_future = submit_next()
            while pending_future is not None:
                prepared = pending_future.result()
                pending_future = submit_next()
                process_prepared(prepared, extraction_pool)
