"""FastAPI dependency factories for Core services."""

from fastapi import Depends

from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.load_all_turns import LoadAllTurnsService
from api.services.stack import ServiceStack, build_service_stack
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_concept_service import TurnConceptService
from api.services.turn_load_service import TurnLoadService
from api.storage import StorageBackend, get_storage


def get_service_stack(
    storage: StorageBackend = Depends(get_storage),
) -> ServiceStack:
    return build_service_stack(storage)


def get_credential_service(
    stack: ServiceStack = Depends(get_service_stack),
) -> CredentialService:
    return stack.credentials


def get_game_service(
    stack: ServiceStack = Depends(get_service_stack),
) -> GameService:
    return stack.games


def get_turn_load_service(
    stack: ServiceStack = Depends(get_service_stack),
) -> TurnLoadService:
    return stack.turns


def get_load_all_turns_service(
    stack: ServiceStack = Depends(get_service_stack),
) -> LoadAllTurnsService:
    return stack.load_all


def get_turn_concept_service(
    stack: ServiceStack = Depends(get_service_stack),
) -> TurnConceptService:
    return stack.concepts


def get_turn_analytic_service(
    stack: ServiceStack = Depends(get_service_stack),
) -> TurnAnalyticService:
    return stack.analytics
