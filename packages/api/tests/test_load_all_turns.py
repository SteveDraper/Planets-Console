"""Tests for bulk turn loading."""

import io
import json
import zipfile
from unittest.mock import MagicMock

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.errors import LoginCredentialsRequiredError, NotFoundError, ValidationError
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.load_all_archive import ArchiveTurnFile
from api.services.load_all_turns import LoadAllTurnsService
from api.services.turn_load_service import TurnLoadService
from api.storage import clear_backend_cache, get_storage
from api.transport.game_info_update import RefreshGameInfoParams
from api.transport.load_all_turns import (
    LoadAllProgressUpdate,
    LoadAllTurnsResponse,
    load_all_stream_event_to_dict,
    stream_load_all_turns,
)

ASSETS_DIR = (
    __import__("pathlib").Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
)


@pytest.fixture
def turn_rst() -> dict:
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        return json.load(handle)


def _archive_turn_rst(game_id: int, turn_number: int) -> dict:
    """Build a loadall-archive-shaped rst that passes turn_info_from_json."""
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        rst = json.load(handle)
    rst = json.loads(json.dumps(rst))
    rst["settings"]["turn"] = turn_number
    rst["game"]["id"] = game_id
    rst["game"]["turn"] = turn_number
    return rst


@pytest.fixture(autouse=True)
def _reset_storage():
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


def _zip_with(entries: dict[str, dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, rst in entries.items():
            archive.writestr(name, json.dumps(rst))
    return buf.getvalue()


def _load_services():
    storage = get_storage()
    credentials = CredentialService(storage)
    games = GameService(storage, credentials)
    turns = TurnLoadService(storage, credentials, games)
    load_all = LoadAllTurnsService(credentials, games, turns)
    return storage, credentials, games, turns, load_all


def _put_minimal_turn(storage, game_id: int, perspective: int, turn_number: int) -> None:
    storage.put(
        f"games/{game_id}/{perspective}/turns/{turn_number}",
        {
            "settings": {"turn": turn_number},
            "game": {"id": game_id, "turn": turn_number},
        },
    )


def test_load_all_turns_status_complete_when_all_turns_present() -> None:
    storage, _, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    latest = info_payload["game"]["turn"]
    for perspective in range(1, len(info_payload["players"]) + 1):
        for turn_number in range(1, latest + 1):
            _put_minimal_turn(storage, 628580, perspective, turn_number)

    status = load_all.load_all_turns_status_for_user(628580, "anyone")
    assert status.complete is True
    assert status.is_game_finished is True
    assert status.latest_turn == latest


def test_load_all_turns_status_incomplete_when_turn_missing() -> None:
    storage, _, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    storage.put(
        "games/628580/1/turns/1",
        {"settings": {"turn": 1}, "game": {"id": 628580, "turn": 1}},
    )

    status = load_all.load_all_turns_status_for_user(628580, "player")
    assert status.complete is False


def test_load_all_turns_status_raises_when_login_missing_for_in_progress() -> None:
    """In-progress status uses the same login requirement as bulk load."""
    storage, _, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["status"] = 1
    storage.put("games/628580/info", info_payload)
    assert info_payload["game"]["turn"] >= 1

    with pytest.raises(LoginCredentialsRequiredError):
        load_all.load_all_turns_status_for_user(628580, "")


def test_load_all_turns_status_raises_when_username_not_in_game() -> None:
    """In-progress status must not swallow unknown-player errors."""
    storage, _, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["status"] = 1
    storage.put("games/628580/info", info_payload)

    with pytest.raises(ValidationError, match="not a player"):
        load_all.load_all_turns_status_for_user(628580, "not-a-player")


def test_load_all_turns_status_expected_perspectives_match_load_for_in_progress() -> None:
    storage, credentials, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["status"] = 1
    info_payload["game"]["turn"] = 2
    info_payload["settings"]["turn"] = 2
    info_payload["players"] = info_payload["players"][:1]
    info_payload["players"][0]["username"] = "captain"
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    status = load_all.load_all_turns_status_for_user(628580, "captain")
    assert status.expected_perspectives == [1]
    assert status.is_game_finished is False

    planets = MagicMock()

    def load_turn_side_effect(**kwargs):
        turn_number = kwargs.get("turn")
        return {"success": True, "rst": _archive_turn_rst(628580, turn_number)}

    planets.load_turn.side_effect = load_turn_side_effect
    result = _final_load_all_result(
        load_all,
        628580,
        RefreshGameInfoParams(username="captain"),
        planets,
    )
    assert result.perspectives_touched == [1]


def test_load_all_turns_status_complete_when_latest_turn_zero() -> None:
    storage, _, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 0
    storage.put("games/628580/info", info_payload)

    status = load_all.load_all_turns_status_for_user(628580, "")
    assert status.latest_turn == 0
    assert status.complete is True


def test_load_all_turns_status_complete_eliminated_through_statusturn_only() -> None:
    """628580 perspective 1 eliminated at turn 49; post-death turns are not required."""
    storage, _, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    latest = info_payload["game"]["turn"]
    player_count = len(info_payload["players"])
    assert info_payload["players"][0]["status"] == 3
    assert info_payload["players"][0]["statusturn"] == 49

    for turn_number in range(1, 50):
        _put_minimal_turn(storage, 628580, 1, turn_number)
    for perspective in range(2, player_count + 1):
        for turn_number in range(1, latest + 1):
            _put_minimal_turn(storage, 628580, perspective, turn_number)

    status = load_all.load_all_turns_status_for_user(628580, "anyone")
    assert status.complete is True
    assert status.latest_turn == latest


def test_load_all_turns_status_incomplete_eliminated_missing_statusturn() -> None:
    storage, _, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    latest = info_payload["game"]["turn"]
    player_count = len(info_payload["players"])

    for turn_number in range(1, 49):
        _put_minimal_turn(storage, 628580, 1, turn_number)
    for perspective in range(2, player_count + 1):
        for turn_number in range(1, latest + 1):
            _put_minimal_turn(storage, 628580, perspective, turn_number)

    status = load_all.load_all_turns_status_for_user(628580, "anyone")
    assert status.complete is False


def test_load_all_turns_status_incomplete_eliminated_post_death_without_statusturn() -> None:
    """Post-death turns alone do not satisfy completeness for an eliminated slot."""
    storage, _, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    latest = info_payload["game"]["turn"]
    player_count = len(info_payload["players"])

    for turn_number in range(50, latest + 1):
        _put_minimal_turn(storage, 628580, 1, turn_number)
    for perspective in range(2, player_count + 1):
        for turn_number in range(1, latest + 1):
            _put_minimal_turn(storage, 628580, perspective, turn_number)

    status = load_all.load_all_turns_status_for_user(628580, "anyone")
    assert status.complete is False


def _final_load_all_result(
    load_all: LoadAllTurnsService,
    game_id: int,
    params: RefreshGameInfoParams,
    planets: MagicMock,
) -> LoadAllTurnsResponse:
    result: LoadAllTurnsResponse | None = None
    for item in load_all.iter_load_all_turns(game_id, params, planets):
        if isinstance(item, LoadAllTurnsResponse):
            result = item
    assert result is not None
    return result


def test_load_finished_game_from_loadall_zip() -> None:
    storage, credentials, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 1
    info_payload["settings"]["turn"] = 1
    info_payload["players"] = info_payload["players"][:2]
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = _zip_with(
        {
            "player1-turn1.trn": _archive_turn_rst(628580, 1),
            "player2-turn1.trn": _archive_turn_rst(628580, 1),
        }
    )

    with open(ASSETS_DIR / "turn_sample.json") as handle:
        turn_rst = json.load(handle)

    def load_turn_side_effect(**kwargs):
        turn_number = kwargs.get("turn")
        rst = json.loads(json.dumps(turn_rst))
        rst["settings"]["turn"] = turn_number
        rst["game"]["id"] = 628580
        rst["game"]["turn"] = turn_number
        return {"success": True, "rst": rst}

    planets = MagicMock()
    planets.load_all.return_value = zip_bytes
    planets.load_turn.side_effect = load_turn_side_effect

    result = _final_load_all_result(
        load_all,
        628580,
        RefreshGameInfoParams(username="captain"),
        planets,
    )
    assert result.is_game_finished is True
    assert result.turns_written >= 2
    assert storage.get("games/628580/1/turns/1") is not None
    assert storage.get("games/628580/2/turns/1") is not None
    planets.load_all.assert_called_once_with(628580)


def test_iter_load_all_turns_emits_perspective_first_progress() -> None:
    storage, credentials, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 2
    info_payload["settings"]["turn"] = 2
    info_payload["players"] = info_payload["players"][:2]
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = _zip_with(
        {
            "player1-turn1.trn": _archive_turn_rst(628580, 1),
            "player2-turn1.trn": _archive_turn_rst(628580, 1),
            "player1-turn2.trn": _archive_turn_rst(628580, 2),
        }
    )

    planets = MagicMock()
    planets.load_all.return_value = zip_bytes
    planets.load_turn.return_value = {
        "success": True,
        "rst": _archive_turn_rst(628580, 2),
    }

    items = list(
        load_all.iter_load_all_turns(
            628580,
            RefreshGameInfoParams(username="captain"),
            planets,
        )
    )
    progress = [item for item in items if isinstance(item, LoadAllProgressUpdate)]
    assert progress[0].phase == "download"
    import_events = [item for item in progress if item.phase == "import"]
    assert [item.perspective for item in import_events] == [1, 1, 2]
    assert isinstance(items[-1], LoadAllTurnsResponse)

    wire = [load_all_stream_event_to_dict(item) for item in items]
    assert wire[0]["type"] == "progress" and wire[0]["phase"] == "download"
    assert wire[-1]["type"] == "complete"


def test_load_all_turns_requires_login() -> None:
    _, _, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        get_storage().put("games/628580/info", json.load(handle))

    with pytest.raises(LoginCredentialsRequiredError):
        list(
            load_all.iter_load_all_turns(
                628580,
                RefreshGameInfoParams(username=""),
                MagicMock(),
            )
        )


def test_perspective_for_username_raises_when_not_in_game() -> None:
    storage, _, games, _, _ = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))
    info = games.get_game_info(628580)
    with pytest.raises(ValidationError):
        GameService.perspective_for_username(info, "not-a-player", 628580)


def test_store_archive_turn_if_missing_rejects_invalid_rst() -> None:
    storage, _, _, turns, _ = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))

    archive_turn = ArchiveTurnFile(
        player_slot=1,
        turn_number=1,
        rst={"settings": {"turn": 1}, "game": {"id": 628580, "turn": 1}},
    )

    with pytest.raises(ValidationError, match="Loadall archive turn rst"):
        turns.store_archive_turn_if_missing(628580, archive_turn)

    with pytest.raises(NotFoundError):
        storage.get("games/628580/1/turns/1")


def test_load_finished_game_from_loadall_rejects_invalid_archive_rst() -> None:
    storage, credentials, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 1
    info_payload["settings"]["turn"] = 1
    info_payload["players"] = info_payload["players"][:2]
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = _zip_with(
        {
            "player1-turn1.trn": _archive_turn_rst(628580, 1),
            "player2-turn1.trn": {"not": "a turn rst"},
        }
    )

    planets = MagicMock()
    planets.load_all.return_value = zip_bytes

    with pytest.raises(ValidationError, match="Loadall archive turn rst"):
        _final_load_all_result(
            load_all,
            628580,
            RefreshGameInfoParams(username="captain"),
            planets,
        )

    assert storage.get("games/628580/1/turns/1") is not None
    with pytest.raises(NotFoundError):
        storage.get("games/628580/2/turns/1")


def test_store_archive_turn_rejects_settings_turn_mismatch(turn_rst) -> None:
    storage, _, _, turns, _ = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))
    rst = json.loads(json.dumps(turn_rst))
    rst["settings"]["turn"] = 99
    rst["game"]["id"] = 628580
    archive_turn = ArchiveTurnFile(player_slot=1, turn_number=1, rst=rst)

    with pytest.raises(ValidationError, match="settings.turn"):
        turns.store_archive_turn_if_missing(628580, archive_turn)


def test_store_archive_turn_rejects_wrong_game_id(turn_rst) -> None:
    storage, _, _, turns, _ = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))
    rst = json.loads(json.dumps(turn_rst))
    rst["settings"]["turn"] = 1
    rst["game"]["id"] = 999999
    archive_turn = ArchiveTurnFile(player_slot=1, turn_number=1, rst=rst)

    with pytest.raises(ValidationError, match="game.id"):
        turns.store_archive_turn_if_missing(628580, archive_turn)


def test_store_archive_turn_accepts_game_turn_mismatch(turn_rst) -> None:
    storage, _, _, turns, _ = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))
    rst = json.loads(json.dumps(turn_rst))
    rst["settings"]["turn"] = 1
    rst["game"]["id"] = 628580
    rst["game"]["turn"] = 111
    archive_turn = ArchiveTurnFile(player_slot=1, turn_number=1, rst=rst)

    assert turns.store_archive_turn_if_missing(628580, archive_turn) is True
    stored = storage.get("games/628580/1/turns/1")
    assert stored["settings"]["turn"] == 1
    assert stored["game"]["turn"] == 111


def test_stream_load_all_turns_yields_ndjson_lines() -> None:
    items = [
        LoadAllProgressUpdate(
            phase="download",
            perspective=0,
            perspective_total=1,
            turn=0,
            turn_total=0,
            message="Downloading",
        ),
        LoadAllTurnsResponse(
            game_id=628580,
            is_game_finished=True,
            turns_written=1,
            turns_skipped=0,
            perspectives_touched=[1],
        ),
    ]

    lines = list(stream_load_all_turns(lambda: iter(items)))

    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "progress"
    assert first["phase"] == "download"
    last = json.loads(lines[-1])
    assert last["type"] == "complete"
    assert last["result"]["game_id"] == 628580


def test_stream_load_all_turns_yields_error_line_on_planets_console_error() -> None:
    def failing_loader():
        raise LoginCredentialsRequiredError("Login credentials are required.")

    lines = list(stream_load_all_turns(failing_loader))

    assert len(lines) == 1
    error = json.loads(lines[0])
    assert error == {"type": "error", "detail": "Login credentials are required."}


def test_load_finished_game_skips_post_death_archive_turns() -> None:
    storage, credentials, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 2
    info_payload["settings"]["turn"] = 2
    info_payload["players"] = info_payload["players"][:1]
    info_payload["players"][0]["status"] = 3
    info_payload["players"][0]["statusturn"] = 2
    info_payload["players"][0]["username"] = "dead"
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = _zip_with(
        {
            "player1-turn1.trn": _archive_turn_rst(628580, 1),
            "player1-turn2.trn": _archive_turn_rst(628580, 2),
            "player1-turn3.trn": _archive_turn_rst(628580, 3),
        }
    )

    planets = MagicMock()
    planets.load_all.return_value = zip_bytes

    result = _final_load_all_result(
        load_all,
        628580,
        RefreshGameInfoParams(username="captain"),
        planets,
    )

    assert result.is_game_finished is True
    assert storage.get("games/628580/1/turns/1") is not None
    assert storage.get("games/628580/1/turns/2") is not None
    with pytest.raises(NotFoundError):
        storage.get("games/628580/1/turns/3")
    planets.load_turn.assert_not_called()


def test_load_in_progress_game_stops_at_elimination_turn() -> None:
    storage, credentials, _, _, load_all = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["status"] = 1
    info_payload["game"]["turn"] = 5
    info_payload["settings"]["turn"] = 5
    info_payload["players"] = info_payload["players"][:1]
    info_payload["players"][0]["status"] = 3
    info_payload["players"][0]["statusturn"] = 2
    info_payload["players"][0]["username"] = "captain"
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    planets = MagicMock()

    def load_turn_side_effect(**kwargs):
        turn_number = kwargs.get("turn")
        return {"success": True, "rst": _archive_turn_rst(628580, turn_number)}

    planets.load_turn.side_effect = load_turn_side_effect

    result = _final_load_all_result(
        load_all,
        628580,
        RefreshGameInfoParams(username="captain"),
        planets,
    )

    assert result.is_game_finished is False
    assert planets.load_turn.call_count == 2
    assert storage.get("games/628580/1/turns/1") is not None
    assert storage.get("games/628580/1/turns/2") is not None
    with pytest.raises(NotFoundError):
        storage.get("games/628580/1/turns/3")
