"""Background prefetch of loadall import for the next game while extraction runs."""

from __future__ import annotations

from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path

from api.transport.game_info_update import RefreshGameInfoParams

from .prepare_game import PrepareGameResult
from .prepare_game_worker import PrepareGameJob, init_prepare_game_worker, run_prepare_game_job


class GamePreparePrefetcher:
    """Single-worker process pool that prepares the next game ahead of extraction."""

    def __init__(
        self,
        *,
        storage_root: Path,
        loadall_params: RefreshGameInfoParams | None = None,
    ) -> None:
        self._storage_root = str(storage_root.resolve())
        self._loadall_username = loadall_params.username if loadall_params is not None else ""
        self._loadall_password = loadall_params.password if loadall_params is not None else None
        self._executor: ProcessPoolExecutor | None = None

    def __enter__(self) -> GamePreparePrefetcher:
        self._executor = ProcessPoolExecutor(
            max_workers=1,
            initializer=init_prepare_game_worker,
            initargs=(self._storage_root,),
        )
        return self

    def __exit__(self, *args: object) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None

    def submit(self, game_id: int) -> Future[PrepareGameResult]:
        if self._executor is None:
            raise RuntimeError("GamePreparePrefetcher is not active")
        job = PrepareGameJob(
            game_id=game_id,
            storage_root=self._storage_root,
            loadall_username=self._loadall_username,
            loadall_password=self._loadall_password,
        )
        return self._executor.submit(run_prepare_game_job, job)
