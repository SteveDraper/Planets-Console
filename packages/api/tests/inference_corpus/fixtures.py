"""Load inference corpus RST fixtures from the committed fixture tree."""

import json
from pathlib import Path

from api.models.game import TurnInfo
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json
from api.services.game_service import GameService

from tests.inference_corpus.manifest import FIXTURES_ROOT
from tests.inference_corpus.models import ManifestCase


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


def load_manifest_ground_truth_turn_snapshots(
    case: ManifestCase,
    player_id: int,
    *,
    fixtures_root: Path = FIXTURES_ROOT,
) -> tuple[TurnInfo, TurnInfo]:
    """Load turn snapshots from the fixture perspective that owns ``player_id``."""
    perspective = _manifest_ground_truth_perspective(
        case,
        player_id,
        fixtures_root=fixtures_root,
    )
    prior_turn = load_turn_fixture(
        f"{case.game_id}/{perspective}/turns/{case.host_turn}.json",
        fixtures_root=fixtures_root,
    )
    score_turn = load_turn_fixture(
        f"{case.game_id}/{perspective}/turns/{case.host_turn + 1}.json",
        fixtures_root=fixtures_root,
    )
    return prior_turn, score_turn


def _manifest_ground_truth_perspective(
    case: ManifestCase,
    player_id: int,
    *,
    fixtures_root: Path,
) -> int:
    if case.game_info_path:
        info_path = fixtures_root / case.game_info_path
        with open(info_path) as handle:
            game_info = game_info_from_json(json.load(handle))
        return GameService.perspective_for_player_id(game_info, player_id, case.game_id)
    return case.perspective


def list_fixture_perspectives_with_turn_pair(
    game_id: int,
    host_turn: int,
    score_turn: int,
    *,
    fixtures_root: Path = FIXTURES_ROOT,
) -> tuple[int, ...]:
    """Return sorted fixture slots that have both host and score turn files."""
    game_root = fixtures_root / str(game_id)
    if not game_root.is_dir():
        return ()
    perspectives: list[int] = []
    for child in game_root.iterdir():
        if not child.is_dir() or not child.name.isdigit():
            continue
        perspective = int(child.name)
        if perspective < 1:
            continue
        prior_path = child / "turns" / f"{host_turn}.json"
        score_path = child / "turns" / f"{score_turn}.json"
        if prior_path.is_file() and score_path.is_file():
            perspectives.append(perspective)
    return tuple(sorted(perspectives))


def load_other_manifest_perspective_turns(
    case: ManifestCase,
    *,
    fixtures_root: Path = FIXTURES_ROOT,
) -> tuple[tuple[TurnInfo, ...], tuple[TurnInfo, ...]]:
    """Load sibling fixture perspectives for multi-view adjunct classification."""
    other_prior: list[TurnInfo] = []
    other_score: list[TurnInfo] = []
    score_turn_number = case.host_turn + 1
    for perspective in list_fixture_perspectives_with_turn_pair(
        case.game_id,
        case.host_turn,
        score_turn_number,
        fixtures_root=fixtures_root,
    ):
        if perspective == case.perspective:
            continue
        other_prior.append(
            load_turn_fixture(
                f"{case.game_id}/{perspective}/turns/{case.host_turn}.json",
                fixtures_root=fixtures_root,
            )
        )
        other_score.append(
            load_turn_fixture(
                f"{case.game_id}/{perspective}/turns/{score_turn_number}.json",
                fixtures_root=fixtures_root,
            )
        )
    return tuple(other_prior), tuple(other_score)


def assert_required_perspectives_present(
    _case_id: str,
    game_id: int,
    host_turn: int,
    score_turn: int,
    required_perspectives: tuple[int, ...],
    *,
    fixtures_root: Path = FIXTURES_ROOT,
) -> str | None:
    """Return a failure message when a required perspective turn pair is missing."""
    for perspective in required_perspectives:
        for turn_number in (host_turn, score_turn):
            path = fixtures_root / str(game_id) / str(perspective) / "turns" / f"{turn_number}.json"
            if not path.is_file():
                return f"missing {path.relative_to(fixtures_root)}"
    return None
