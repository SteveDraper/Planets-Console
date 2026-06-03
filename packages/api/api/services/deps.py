"""FastAPI dependency factories for Core services."""

from fastapi import Depends

from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.load_all_turns import LoadAllTurnsService
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_concept_service import TurnConceptService
from api.services.turn_load_service import TurnLoadService
from api.storage import StorageBackend, get_storage


def get_credential_service(
    storage: StorageBackend = Depends(get_storage),
) -> CredentialService:
    return CredentialService(storage)


def get_game_service(
    storage: StorageBackend = Depends(get_storage),
    credentials: CredentialService = Depends(get_credential_service),
) -> GameService:
    return GameService(storage, credentials)


def get_turn_load_service(
    storage: StorageBackend = Depends(get_storage),
    credentials: CredentialService = Depends(get_credential_service),
    games: GameService = Depends(get_game_service),
) -> TurnLoadService:
    return TurnLoadService(storage, credentials, games)


def get_load_all_turns_service(
    storage: StorageBackend = Depends(get_storage),
    credentials: CredentialService = Depends(get_credential_service),
    games: GameService = Depends(get_game_service),
    turns: TurnLoadService = Depends(get_turn_load_service),
) -> LoadAllTurnsService:
    return LoadAllTurnsService(credentials, games, turns)


def get_turn_concept_service(
    turns: TurnLoadService = Depends(get_turn_load_service),
) -> TurnConceptService:
    return TurnConceptService(turns)


def get_turn_analytic_service(
    turns: TurnLoadService = Depends(get_turn_load_service),
) -> TurnAnalyticService:
    return TurnAnalyticService(turns)
