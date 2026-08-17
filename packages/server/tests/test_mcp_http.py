"""Streamable HTTP smoke for POST /mcp (tools-only discover, Origin, login)."""

from __future__ import annotations

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.storage import clear_backend_cache
from fastapi.testclient import TestClient

MCP_PROTOCOL_VERSION = "2026-07-28"


@pytest.fixture
def _api_config_and_storage():
    clear_backend_cache()
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    yield
    clear_backend_cache()


@pytest.fixture
def mcp_http(_api_config_and_storage):
    from server.app import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1:8000") as client:
        yield client


def _mcp_headers(
    method: str,
    *,
    name: str | None = None,
    login: str | None = None,
    origin: str | None = None,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    if login is not None:
        headers["X-Planets-Nu-Login"] = login
    if origin is not None:
        headers["Origin"] = origin
    return headers


def _mcp_body(method: str, *, rpc_id: int = 1, extra_params: dict | None = None) -> dict:
    params: dict = {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    }
    if extra_params:
        params.update(extra_params)
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}


def _assert_discover_is_tools_only(response) -> None:
    assert response.status_code == 200
    result = response.json()["result"]
    capabilities = result["capabilities"]
    assert "tools" in capabilities
    assert "prompts" not in capabilities
    assert "resources" not in capabilities


def test_post_mcp_discover_is_tools_only(mcp_http: TestClient):
    response = mcp_http.post(
        "/mcp/",
        headers=_mcp_headers("server/discover"),
        json=_mcp_body("server/discover"),
    )
    _assert_discover_is_tools_only(response)


def test_post_mcp_without_trailing_slash_discovers_tools(mcp_http: TestClient):
    """Cursor mcp.json uses ``/mcp`` (no slash) and does not follow POST redirects."""
    response = mcp_http.post(
        "/mcp",
        headers=_mcp_headers("server/discover"),
        json=_mcp_body("server/discover"),
        follow_redirects=False,
    )
    _assert_discover_is_tools_only(response)


def test_spa_fallback_does_not_capture_mcp_or_oauth_discovery(
    _api_config_and_storage, tmp_path, monkeypatch
):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIST", str(dist))
    from server.app import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1:8000") as client:
        discover = client.post(
            "/mcp",
            headers=_mcp_headers("server/discover"),
            json=_mcp_body("server/discover"),
            follow_redirects=False,
        )
        _assert_discover_is_tools_only(discover)

        well_known = client.get("/.well-known/oauth-protected-resource")
        assert well_known.status_code == 404
        assert "text/html" not in well_known.headers.get("content-type", "")

        spa_page = client.get("/some-client-route")
        assert spa_page.status_code == 200
        assert spa_page.text == "<html>spa</html>"


def test_post_mcp_invalid_origin_is_403(mcp_http: TestClient):
    response = mcp_http.post(
        "/mcp/",
        headers=_mcp_headers("server/discover", origin="http://evil.example"),
        json=_mcp_body("server/discover"),
    )
    assert response.status_code == 403


def test_post_mcp_list_stored_games_without_login_fails_closed(mcp_http: TestClient):
    response = mcp_http.post(
        "/mcp/",
        headers=_mcp_headers("tools/call", name="list_stored_games"),
        json=_mcp_body(
            "tools/call",
            extra_params={"name": "list_stored_games", "arguments": {}},
        ),
    )
    assert response.status_code == 200
    payload = response.json()["result"]
    assert payload["isError"] is True
    text = payload["content"][0]["text"]
    assert "X-Planets-Nu-Login" in text


def test_post_mcp_list_stored_games_unknown_login_fails_closed(mcp_http: TestClient):
    response = mcp_http.post(
        "/mcp/",
        headers=_mcp_headers("tools/call", name="list_stored_games", login="nobody"),
        json=_mcp_body(
            "tools/call",
            extra_params={"name": "list_stored_games", "arguments": {}},
        ),
    )
    assert response.status_code == 200
    payload = response.json()["result"]
    assert payload["isError"] is True
    text = payload["content"][0]["text"]
    assert "nobody" in text
