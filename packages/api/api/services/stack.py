"""Construct the default Core service dependency graph for a storage backend."""

from typing import NamedTuple

from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.military_score_inference.inference_scheduler import (
    create_inference_row_scheduler,
)
from api.concepts.homeworld_layout import homeworld_settings_fingerprint
from api.models.game import GameInfo
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.services.load_all_turns import LoadAllTurnsService
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_concept_service import TurnConceptService
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend


class ServiceStack(NamedTuple):
    """Process service graph for one storage backend."""

    games: GameService
    turns: TurnLoadService
    load_all: LoadAllTurnsService
    concepts: TurnConceptService
    analytics: TurnAnalyticService
    credentials: CredentialService


def build_service_stack(storage: StorageBackend) -> ServiceStack:
    credentials = CredentialService(storage)
    fleet_persistence = FleetSnapshotPersistenceService(storage)
    homeworld_persistence = HomeworldLocatorPersistenceService(storage)
    inference_persistence = InferenceRowPersistenceService(storage)
    inference_invalidation = InferenceInvalidationService(
        inference_persistence,
        scheduler=None,
        fleet_persistence=fleet_persistence,
    )
    inference_invalidation.wire_fleet_invalidation_to_persistence()
    inference_invalidation.wire_scores_invalidation_to_fleet_persistence()

    def on_game_info_refreshed(
        game_id: int,
        previous: GameInfo | None,
        updated: GameInfo,
    ) -> None:
        if previous is None:
            return
        if homeworld_settings_fingerprint(previous.settings) == homeworld_settings_fingerprint(
            updated.settings
        ):
            return
        homeworld_persistence.invalidate_inferred_game_state(game_id)

    games = GameService(
        storage,
        credentials,
        on_game_info_refreshed=on_game_info_refreshed,
    )

    def on_held_solutions_updated(session) -> None:
        inference_invalidation.on_inference_evidence_updated(
            session.game_id,
            session.perspective,
            session.turn_number,
            session.player_id,
        )

    inference_scheduler = create_inference_row_scheduler(
        on_held_solutions_updated=on_held_solutions_updated,
    )
    inference_invalidation.bind_scheduler(inference_scheduler)

    def on_turn_stored(game_id: int, perspective: int, turn_number: int) -> None:
        inference_invalidation.on_turn_stored(game_id, perspective, turn_number)
        fleet_persistence.invalidate_for_turn_write(game_id, perspective, turn_number)
        homeworld_persistence.invalidate_evidence_from_turn(game_id, perspective, turn_number)

    turns = TurnLoadService(
        storage,
        credentials,
        games,
        on_turn_stored=on_turn_stored,
    )
    load_all = LoadAllTurnsService(credentials, games, turns)
    concepts = TurnConceptService(turns)
    analytics = TurnAnalyticService(
        turns,
        storage=storage,
        inference_persistence=inference_persistence,
        inference_invalidation=inference_invalidation,
        inference_scheduler=inference_scheduler,
        fleet_persistence=fleet_persistence,
        homeworld_persistence=homeworld_persistence,
    )
    return ServiceStack(
        games=games,
        turns=turns,
        load_all=load_all,
        concepts=concepts,
        analytics=analytics,
        credentials=credentials,
    )


_process_stack: ServiceStack | None = None


def build_default_service_stack() -> ServiceStack:
    """Service graph for the active process storage backend (BFF in-process adapter, tests)."""
    from api.storage import get_storage

    return build_service_stack(get_storage())


def get_process_service_stack() -> ServiceStack:
    """Process-singleton service graph for the active storage backend.

    BFF and the MCP adapter share this so mutating shell tools (game-info refresh,
    turn-ensure) fire the same invalidation hooks as the SPA path.
    """
    global _process_stack
    if _process_stack is None:
        _process_stack = build_default_service_stack()
    return _process_stack


def clear_process_service_stack() -> None:
    """Drop the cached stack (tests after storage or config change)."""
    global _process_stack
    stack = _process_stack
    _process_stack = None
    if stack is not None:
        stack.analytics.shutdown_background_workers()


def build_game_credential_services(
    storage: StorageBackend,
) -> tuple[GameService, CredentialService]:
    """CredentialService and GameService for ``storage`` (stored-game listing and login probe)."""
    credentials = CredentialService(storage)
    games = GameService(storage, credentials)
    return games, credentials


def build_default_game_credential_services() -> tuple[GameService, CredentialService]:
    """CredentialService and GameService for the active process storage backend."""
    from api.storage import get_storage

    return build_game_credential_services(get_storage())
