"""Production MCP mount wires the process service stack."""

from __future__ import annotations

from unittest.mock import MagicMock

from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from mcp_adapter.app import create_mcp_mount


def test_create_mcp_mount_uses_process_service_stack(monkeypatch):
    games = MagicMock(spec=GameService)
    turns = MagicMock(spec=TurnLoadService)
    credentials = MagicMock(spec=CredentialService)
    stack = MagicMock()
    stack.games = games
    stack.turns = turns
    stack.credentials = credentials
    captured: dict[str, object] = {}

    def fake_stack():
        return stack

    def fake_build_mcp_server(
        *,
        game_service,
        turn_load_service=None,
        credential_service=None,
        resolve_login=None,
        planets_client_factory=None,
    ):
        captured["game_service"] = game_service
        captured["turn_load_service"] = turn_load_service
        captured["credential_service"] = credential_service
        captured["planets_client_factory"] = planets_client_factory
        mcp = MagicMock()
        mcp.streamable_http_app.return_value = MagicMock(name="mcp_asgi")
        return mcp

    monkeypatch.setattr("mcp_adapter.app.get_process_service_stack", fake_stack)
    monkeypatch.setattr("mcp_adapter.app.build_mcp_server", fake_build_mcp_server)

    mcp, asgi = create_mcp_mount()

    assert captured["game_service"] is games
    assert captured["turn_load_service"] is turns
    assert captured["credential_service"] is credentials
    assert captured["planets_client_factory"] is not None
    mcp.streamable_http_app.assert_called_once_with(streamable_http_path="/")
    assert asgi is mcp.streamable_http_app.return_value
