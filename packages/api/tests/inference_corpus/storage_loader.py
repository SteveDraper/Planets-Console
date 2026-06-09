"""Load turns and game info from the file storage backend for local corpus runs."""

from pathlib import Path

from api.config import ApiConfig, set_config
from api.models.game import GameInfo, TurnInfo
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from api.storage import StorageBackend, clear_backend_cache, get_storage


def configure_file_storage(*, storage_root: Path) -> StorageBackend:
    """Point the API storage layer at a file backend root and return the backend."""
    set_config(ApiConfig(storage_backend="file", storage_root=str(storage_root.resolve())))
    clear_backend_cache()
    return get_storage()


def make_turn_load_service(storage: StorageBackend) -> TurnLoadService:
    return TurnLoadService(storage, CredentialService(storage), GameService(storage))


def make_game_service(storage: StorageBackend) -> GameService:
    return GameService(storage)


def load_turn(
    turn_load: TurnLoadService,
    game_id: int,
    perspective: int,
    turn_number: int,
) -> TurnInfo:
    return turn_load.get_turn_info(game_id, perspective, turn_number)


def load_game_info(game_service: GameService, game_id: int) -> GameInfo:
    return game_service.get_game_info(game_id)


def resolve_player_id_for_case(
    game_service: GameService,
    game_id: int,
    perspective: int,
) -> int:
    info = load_game_info(game_service, game_id)
    return GameService.player_id_for_perspective(info, perspective, game_id)


def load_ground_truth_turn_snapshots(
    turn_load: TurnLoadService,
    game_info: GameInfo,
    game_id: int,
    player_id: int,
    host_turn: int,
) -> tuple[TurnInfo, TurnInfo]:
    """Load host/score turn pair from the perspective slot that owns ``player_id``."""
    perspective = GameService.perspective_for_player_id(game_info, player_id, game_id)
    prior_turn = turn_load.get_turn_info(game_id, perspective, host_turn)
    score_turn = turn_load.get_turn_info(game_id, perspective, host_turn + 1)
    return prior_turn, score_turn
