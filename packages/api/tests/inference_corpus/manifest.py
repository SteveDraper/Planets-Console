"""Load and validate inference corpus manifest.json."""

import json
from pathlib import Path

from api.serialization.game import game_info_from_json
from api.services.game_service import GameService

from tests.inference_corpus.models import ManifestCase

FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "inference_corpus"
DEFAULT_MANIFEST_PATH = FIXTURES_ROOT / "manifest.json"


def load_manifest(path: Path | None = None) -> tuple[dict[str, object], list[ManifestCase]]:
    """Load manifest metadata and normalized case rows."""
    manifest_path = path or DEFAULT_MANIFEST_PATH
    with open(manifest_path) as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{manifest_path}: manifest root must be an object")

    game_info_path = raw.get("gameInfoPath")
    if game_info_path is not None and not isinstance(game_info_path, str):
        raise ValueError("gameInfoPath must be a string when present")

    cases_raw = raw.get("cases")
    if not isinstance(cases_raw, list) or not cases_raw:
        raise ValueError(f"{manifest_path}: cases must be a non-empty array")

    cases: list[ManifestCase] = []
    for entry in cases_raw:
        if not isinstance(entry, dict):
            raise ValueError("each manifest case must be an object")
        cases.append(_parse_case(entry, default_game_info_path=game_info_path))

    return raw, cases


def resolve_player_id(case: ManifestCase, *, fixtures_root: Path = FIXTURES_ROOT) -> int:
    """Return manifest playerId or the owner at the case perspective slot."""
    if case.player_id is not None:
        return case.player_id
    if not case.game_info_path:
        raise ValueError(f"case {case.id}: playerId required when gameInfoPath is absent")
    info_path = fixtures_root / case.game_info_path
    with open(info_path) as handle:
        game_info = game_info_from_json(json.load(handle))
    return GameService.player_id_for_perspective(game_info, case.perspective, case.game_id)


def _parse_case(
    entry: dict[str, object],
    *,
    default_game_info_path: str | None,
) -> ManifestCase:
    case_id = _require_str(entry, "id")
    game_id = _require_int(entry, "gameId")
    perspective = _require_int(entry, "perspective")
    host_turn = _require_int(entry, "hostTurn")
    prior_turn_path = _require_str(entry, "priorTurnPath")
    score_turn_path = _require_str(entry, "scoreTurnPath")

    player_id = entry.get("playerId")
    if player_id is not None and not isinstance(player_id, int):
        raise ValueError(f"case {case_id}: playerId must be an integer or null")

    game_info_path = entry.get("gameInfoPath", default_game_info_path)
    if game_info_path is not None and not isinstance(game_info_path, str):
        raise ValueError(f"case {case_id}: gameInfoPath must be a string or null")

    complexity = entry.get("complexity")
    if complexity is not None and complexity not in {
        "minimal",
        "routine",
        "heavy",
        "adjunct",
    }:
        raise ValueError(f"case {case_id}: invalid complexity {complexity!r}")

    tier = entry.get("tier", 1)
    if not isinstance(tier, int):
        raise ValueError(f"case {case_id}: tier must be an integer")

    expected_status = entry.get("expectedStatus", "exact")
    if not isinstance(expected_status, str):
        raise ValueError(f"case {case_id}: expectedStatus must be a string")

    require_top_k = entry.get("requireTopK", False)
    if not isinstance(require_top_k, bool):
        raise ValueError(f"case {case_id}: requireTopK must be a boolean")

    expect_coverage = entry.get("expectCoverage", False)
    if not isinstance(expect_coverage, bool):
        raise ValueError(f"case {case_id}: expectCoverage must be a boolean")

    required_perspectives_raw = entry.get("requiredPerspectives", [])
    if not isinstance(required_perspectives_raw, list):
        raise ValueError(f"case {case_id}: requiredPerspectives must be an array")
    required_perspectives = tuple(
        perspective_slot
        for perspective_slot in required_perspectives_raw
        if isinstance(perspective_slot, int)
    )

    notes = entry.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ValueError(f"case {case_id}: notes must be a string or null")

    return ManifestCase(
        id=case_id,
        game_id=game_id,
        perspective=perspective,
        host_turn=host_turn,
        prior_turn_path=prior_turn_path,
        score_turn_path=score_turn_path,
        player_id=player_id,
        game_info_path=game_info_path,
        complexity=complexity,
        tier=tier,
        expected_status=expected_status,
        require_top_k=require_top_k,
        expect_coverage=expect_coverage,
        required_perspectives=required_perspectives,
        notes=notes,
    )


def _require_str(entry: dict[str, object], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest case missing required string field {key!r}")
    return value


def _require_int(entry: dict[str, object], key: str) -> int:
    value = entry.get(key)
    if not isinstance(value, int):
        raise ValueError(f"manifest case missing required integer field {key!r}")
    return value
