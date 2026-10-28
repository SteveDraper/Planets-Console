"""MCP shell tool get_backfill_earlier_turns reads the Core boolean and submits no walk."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from api.compute.orchestrator_submission import OrchestratorSubmissionMixin
from api.errors import NotFoundError
from api.serialization.backfill_earlier_turns import BACKFILL_EARLIER_TURNS_FIELD
from api.services.game_service import GameService, backfill_earlier_turns_store_key
from api.services.turn_load_service import TurnLoadService
from api.services.viewpoint_eligibility import ViewpointEligibilityService
from api.storage.memory_asset import MemoryAssetBackend
from mcp import Client
from mcp_adapter.server import GET_BACKFILL_EARLIER_TURNS_TOOL, GET_GAME_INFO_TOOL

from tests.mcp_test_support import build_test_mcp, resolve_as, run_coro

_ASSETS = Path(__file__).resolve().parents[2] / "api" / "api" / "storage" / "assets"
_GAME_ID = 628580


def _call(mcp, name: str, arguments: dict):
    async def body():
        async with Client(mcp) as client:
            return await client.call_tool(name, arguments)

    return run_coro(body())


def _stored_game(*, running: bool) -> tuple[MemoryAssetBackend, GameService]:
    storage = MemoryAssetBackend(initial={})
    with open(_ASSETS / "game_info_sample.json") as handle:
        payload = json.load(handle)
    if running:
        payload["game"]["status"] = 1
    storage.put(f"games/{_GAME_ID}/info", payload)
    return storage, GameService(storage)


def _mcp(games: GameService, login: str):
    turns = MagicMock(spec=TurnLoadService)
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as(login),
    )
    return mcp, turns


def test_tool_reads_the_stored_boolean_and_submits_no_walk(monkeypatch):
    _storage, games = _stored_game(running=True)
    games.set_backfill_earlier_turns(_GAME_ID, True)
    mcp, turns = _mcp(games, "not-a-player")
    submitted: list = []

    def submit(self, request):
        submitted.append(request)

    monkeypatch.setattr(OrchestratorSubmissionMixin, "submit", submit)
    with patch.object(ViewpointEligibilityService, "eligible_perspectives") as eligibility:
        result = _call(mcp, GET_BACKFILL_EARLIER_TURNS_TOOL, {"game_id": _GAME_ID})

    assert result.is_error is False
    assert result.structured_content == {BACKFILL_EARLIER_TURNS_FIELD: True}
    assert set(result.structured_content) == {BACKFILL_EARLIER_TURNS_FIELD}
    eligibility.assert_not_called()
    turns.ensure_turn_loaded.assert_not_called()
    turns.is_turn_stored.assert_not_called()
    assert submitted == []

    info = _call(mcp, GET_GAME_INFO_TOOL, {"game_id": _GAME_ID})
    assert info.is_error is False
    assert BACKFILL_EARLIER_TURNS_FIELD not in json.dumps(info.structured_content)


def test_tool_reads_off_when_the_setting_record_is_absent():
    storage, games = _stored_game(running=False)
    mcp, _turns = _mcp(games, "alice")

    result = _call(mcp, GET_BACKFILL_EARLIER_TURNS_TOOL, {"game_id": _GAME_ID})

    assert result.is_error is False
    assert result.structured_content == {BACKFILL_EARLIER_TURNS_FIELD: False}
    with pytest.raises(NotFoundError):
        storage.get(backfill_earlier_turns_store_key(_GAME_ID))


def test_missing_game_fails_like_get_game_info():
    _storage, games = _stored_game(running=False)
    mcp, _turns = _mcp(games, "alice")
    missing = {"game_id": 999999}

    info = _call(mcp, GET_GAME_INFO_TOOL, missing)
    backfill = _call(mcp, GET_BACKFILL_EARLIER_TURNS_TOOL, missing)

    assert info.is_error is True
    assert backfill.is_error is True
    info_detail = info.content[0].text.split(": ", 1)[1]
    backfill_detail = backfill.content[0].text.split(": ", 1)[1]
    assert backfill_detail == info_detail
    assert "games/999999/info" in backfill_detail


def test_tool_description_does_not_offer_a_write():
    _storage, games = _stored_game(running=False)
    mcp, _turns = _mcp(games, "alice")

    async def body():
        async with Client(mcp) as client:
            listed = await client.list_tools()
            by_name = {tool.name: tool for tool in listed.tools}
            description = by_name[GET_BACKFILL_EARLIER_TURNS_TOOL].description.casefold()
            assert "does not change the setting" in description
            assert "start a walk" in description
            names = [tool.name for tool in listed.tools]
            assert "set_backfill_earlier_turns" not in names

    run_coro(body())
