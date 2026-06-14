"""Process-pool worker entry points for prior mining game preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from api.planets_nu import PlanetsNuClient
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend
from api.transport.game_info_update import RefreshGameInfoParams

from .prepare_game import PrepareGameResult, prepare_game_for_mining

_worker_storage: StorageBackend | None = None
_worker_turn_load: TurnLoadService | None = None
_worker_game_service: GameService | None = None
_worker_planets: PlanetsNuClient | None = None


@dataclass(frozen=True)
class PrepareGameJob:
    game_id: int
    storage_root: str
    loadall_username: str = ""
    loadall_password: str | None = None


def init_prepare_game_worker(storage_root: str) -> None:
    """Configure storage and upstream client once per prepare worker process."""
    global _worker_storage, _worker_turn_load, _worker_game_service, _worker_planets
    from .storage_bootstrap import make_mining_services_for_storage_root

    _worker_storage, _worker_turn_load, _worker_game_service = (
        make_mining_services_for_storage_root(Path(storage_root))
    )
    _worker_planets = PlanetsNuClient.from_config()


def run_prepare_game_job(job: PrepareGameJob) -> PrepareGameResult:
    """Prepare one game in a background worker process."""
    if _worker_turn_load is None or _worker_storage is None or _worker_game_service is None:
        init_prepare_game_worker(job.storage_root)
    assert _worker_storage is not None
    assert _worker_turn_load is not None
    assert _worker_game_service is not None
    assert _worker_planets is not None
    loadall_params = _loadall_params_from_job(job)
    return prepare_game_for_mining(
        game_id=job.game_id,
        storage=_worker_storage,
        turn_load=_worker_turn_load,
        game_service=_worker_game_service,
        planets=_worker_planets,
        loadall_params=loadall_params,
    )


def _loadall_params_from_job(job: PrepareGameJob) -> RefreshGameInfoParams | None:
    if not job.loadall_username.strip():
        return None
    return RefreshGameInfoParams(username=job.loadall_username, password=job.loadall_password)
