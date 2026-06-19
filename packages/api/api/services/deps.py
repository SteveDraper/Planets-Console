"""FastAPI dependency factories for Core services."""

from fastapi import Depends

from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.load_all_turns import LoadAllTurnsService
from api.services.stack import build_service_stack
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_concept_service import TurnConceptService
from api.services.turn_load_service import TurnLoadService
from api.storage import StorageBackend, get_storage

_service_stack_cache: (
    tuple[
        GameService,
        TurnLoadService,
        LoadAllTurnsService,
        TurnConceptService,
        TurnAnalyticService,
    ]
    | None
) = None


def clear_service_stack_cache() -> None:
    """Drop cached service graph (tests after storage reset)."""
    global _service_stack_cache
    _service_stack_cache = None


def _service_stack(
    storage: StorageBackend,
) -> tuple[
    GameService,
    TurnLoadService,
    LoadAllTurnsService,
    TurnConceptService,
    TurnAnalyticService,
]:
    global _service_stack_cache
    if _service_stack_cache is None:
        _service_stack_cache = build_service_stack(storage)
    return _service_stack_cache


def get_credential_service(
    storage: StorageBackend = Depends(get_storage),
) -> CredentialService:
    return CredentialService(storage)


def get_game_service(
    storage: StorageBackend = Depends(get_storage),
    credentials: CredentialService = Depends(get_credential_service),
) -> GameService:
    _ = credentials
    return _service_stack(storage)[0]


def get_turn_load_service(
    storage: StorageBackend = Depends(get_storage),
) -> TurnLoadService:
    return _service_stack(storage)[1]


def get_load_all_turns_service(
    storage: StorageBackend = Depends(get_storage),
) -> LoadAllTurnsService:
    return _service_stack(storage)[2]


def get_turn_concept_service(
    storage: StorageBackend = Depends(get_storage),
) -> TurnConceptService:
    return _service_stack(storage)[3]


def get_turn_analytic_service(
    storage: StorageBackend = Depends(get_storage),
) -> TurnAnalyticService:
    return _service_stack(storage)[4]
