"""Load inference corpus RST fixtures from the committed fixture tree."""

import json
from pathlib import Path

from api.models.game import TurnInfo
from api.serialization.turn import turn_info_from_json

from tests.inference_corpus.manifest import FIXTURES_ROOT


def load_turn_fixture(relative_path: str, *, fixtures_root: Path = FIXTURES_ROOT) -> TurnInfo:
    """Deserialize one rst-shaped turn JSON under fixtures/inference_corpus/."""
    turn_path = fixtures_root / relative_path
    with open(turn_path) as handle:
        turn_data = json.load(handle)
    settings_defaults = _settings_defaults_for_case(relative_path, fixtures_root=fixtures_root)
    return turn_info_from_json(turn_data, settings_defaults=settings_defaults)


def _settings_defaults_for_case(relative_path: str, *, fixtures_root: Path) -> dict:
    game_id = relative_path.split("/", 1)[0]
    info_path = fixtures_root / game_id / "info.json"
    with open(info_path) as handle:
        info_data = json.load(handle)
    settings = info_data.get("settings")
    if not isinstance(settings, dict):
        raise ValueError(f"{info_path}: missing settings object for turn defaults")
    return settings


def load_game_info_settings(relative_path: str, *, fixtures_root: Path = FIXTURES_ROOT) -> dict:
    """Return raw settings dict from a fixture game info path (manifest-relative)."""
    info_path = fixtures_root / relative_path
    with open(info_path) as handle:
        info_data = json.load(handle)
    settings = info_data.get("settings")
    if not isinstance(settings, dict):
        raise ValueError(f"{info_path}: missing settings object")
    return settings


def assert_required_perspectives_present(
    case_id: str,
    game_id: int,
    host_turn: int,
    score_turn: int,
    required_perspectives: tuple[int, ...],
    *,
    fixtures_root: Path = FIXTURES_ROOT,
) -> str | None:
    """Return a skip reason when a required perspective turn pair is missing."""
    for perspective in required_perspectives:
        for turn_number in (host_turn, score_turn):
            path = fixtures_root / str(game_id) / str(perspective) / "turns" / f"{turn_number}.json"
            if not path.is_file():
                return f"missing {path.relative_to(fixtures_root)}"
    return None
