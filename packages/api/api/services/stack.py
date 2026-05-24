"""Construct the default Core service dependency graph for a storage backend."""

from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_concept_service import TurnConceptService
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend


def build_service_stack(
    storage: StorageBackend,
) -> tuple[GameService, TurnLoadService, TurnConceptService, TurnAnalyticService]:
    credentials = CredentialService(storage)
    games = GameService(storage, credentials)
    turns = TurnLoadService(storage, credentials, games)
    concepts = TurnConceptService(turns)
    analytics = TurnAnalyticService(turns)
    return games, turns, concepts, analytics
