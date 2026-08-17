"""Production MCP mount wires GameService and CredentialService only."""

from __future__ import annotations

from unittest.mock import MagicMock

from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from mcp_adapter.app import create_mcp_mount


def test_create_mcp_mount_uses_game_credential_services(monkeypatch):
    games = MagicMock(spec=GameService)
    credentials = MagicMock(spec=CredentialService)
    captured: dict[str, object] = {}

    def fake_slim():
        return games, credentials

    def fake_build_mcp_server(
        *,
        game_service,
        credential_service=None,
        resolve_login=None,
    ):
        captured["game_service"] = game_service
        captured["credential_service"] = credential_service
        mcp = MagicMock()
        mcp.streamable_http_app.return_value = MagicMock(name="mcp_asgi")
        return mcp

    monkeypatch.setattr(
        "mcp_adapter.app.build_default_game_credential_services",
        fake_slim,
    )
    monkeypatch.setattr("mcp_adapter.app.build_mcp_server", fake_build_mcp_server)

    mcp, asgi = create_mcp_mount()

    assert captured["game_service"] is games
    assert captured["credential_service"] is credentials
    mcp.streamable_http_app.assert_called_once_with(streamable_http_path="/")
    assert asgi is mcp.streamable_http_app.return_value
