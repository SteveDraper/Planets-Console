"""Construct the default Core service dependency graph for a storage backend."""

from api.analytics.military_score_inference.inference_scheduler import set_row_complete_listener
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.services.load_all_turns import LoadAllTurnsService
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_concept_service import TurnConceptService
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend


def build_service_stack(
    storage: StorageBackend,
) -> tuple[
    GameService,
    TurnLoadService,
    LoadAllTurnsService,
    TurnConceptService,
    TurnAnalyticService,
]:
    credentials = CredentialService(storage)
    games = GameService(storage, credentials)
    inference_persistence = InferenceRowPersistenceService(storage)
    inference_invalidation = InferenceInvalidationService(inference_persistence)
    turns = TurnLoadService(
        storage,
        credentials,
        games,
        on_turn_stored=inference_invalidation.on_turn_stored,
    )
    load_all = LoadAllTurnsService(credentials, games, turns)
    concepts = TurnConceptService(turns)
    analytics = TurnAnalyticService(
        turns,
        storage=storage,
        inference_persistence=inference_persistence,
        inference_invalidation=inference_invalidation,
    )
    set_row_complete_listener(inference_persistence.persist_row_complete)
    return games, turns, load_all, concepts, analytics


def build_default_service_stack() -> tuple[
    GameService,
    TurnLoadService,
    LoadAllTurnsService,
    TurnConceptService,
    TurnAnalyticService,
]:
    """Service graph for the active process storage backend (BFF in-process adapter, tests)."""
    from api.storage import get_storage

    return build_service_stack(get_storage())
