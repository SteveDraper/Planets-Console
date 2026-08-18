"""Service graph builders: full stack vs game+credential pair."""

from __future__ import annotations

from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.stack import (
    build_default_game_credential_services,
    build_game_credential_services,
    clear_process_service_stack,
    get_process_service_stack,
)
from api.storage.memory_asset import MemoryAssetBackend


def test_build_game_credential_services_returns_games_and_credentials(monkeypatch):
    constructed: list[str] = []

    class TrackingTurnAnalyticService:
        def __init__(self, *args, **kwargs) -> None:
            constructed.append("TurnAnalyticService")

    def tracking_scheduler(**kwargs):
        constructed.append("inference_scheduler")
        raise AssertionError("inference scheduler must not be created")

    monkeypatch.setattr(
        "api.services.stack.TurnAnalyticService",
        TrackingTurnAnalyticService,
    )
    monkeypatch.setattr(
        "api.services.stack.create_inference_row_scheduler",
        tracking_scheduler,
    )

    storage = MemoryAssetBackend(initial={})
    games, credentials = build_game_credential_services(storage)

    assert isinstance(games, GameService)
    assert isinstance(credentials, CredentialService)
    assert constructed == []


def test_build_default_game_credential_services_uses_process_storage(monkeypatch):
    storage = MemoryAssetBackend(initial={})
    monkeypatch.setattr("api.storage.get_storage", lambda: storage)
    constructed: list[str] = []

    class TrackingTurnAnalyticService:
        def __init__(self, *args, **kwargs) -> None:
            constructed.append("TurnAnalyticService")

    monkeypatch.setattr(
        "api.services.stack.TurnAnalyticService",
        TrackingTurnAnalyticService,
    )

    games, credentials = build_default_game_credential_services()

    assert isinstance(games, GameService)
    assert isinstance(credentials, CredentialService)
    assert constructed == []


def test_get_process_service_stack_is_a_singleton(monkeypatch):
    storage = MemoryAssetBackend(initial={})
    monkeypatch.setattr("api.storage.get_storage", lambda: storage)
    clear_process_service_stack()
    try:
        first = get_process_service_stack()
        second = get_process_service_stack()
        assert first is second
        assert first.games is second.games
        assert first.turns is second.turns
    finally:
        clear_process_service_stack()
