"""Construct the default Core service dependency graph for a storage backend."""

from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.inference_hull_catalog_service import InferenceHullCatalogService
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
    turns = TurnLoadService(storage, credentials, games)
    load_all = LoadAllTurnsService(credentials, games, turns)
    concepts = TurnConceptService(turns)
    hull_catalog_masks = InferenceHullCatalogService(storage, turns)
    analytics = TurnAnalyticService(turns, hull_catalog_masks)
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
