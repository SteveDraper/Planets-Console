"""File storage bootstrap for prior mining worker processes."""

from __future__ import annotations

from pathlib import Path

from api.config import ApiConfig, set_config
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from api.storage import clear_backend_cache, get_storage
from api.storage.base import StorageBackend


def make_turn_load_service_for_storage_root(storage_root: Path) -> TurnLoadService:
    storage, turn_load, _game_service = make_mining_services_for_storage_root(storage_root)
    del storage, _game_service
    return turn_load


def make_mining_services_for_storage_root(
    storage_root: Path,
) -> tuple[StorageBackend, TurnLoadService, GameService]:
    set_config(ApiConfig(storage_backend="file", storage_root=str(storage_root.resolve())))
    clear_backend_cache()
    storage = get_storage()
    game_service = GameService(storage)
    turn_load = TurnLoadService(storage, CredentialService(storage), game_service)
    return storage, turn_load, game_service
