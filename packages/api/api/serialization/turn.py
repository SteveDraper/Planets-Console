"""Codec for TurnInfo (rst object from Load Turn Data)."""

import copy
from dataclasses import fields

import dacite

from api.models.game import TurnInfo
from api.models.player import Score
from api.serialization.codecs import DACITE_CONFIG, dataclass_to_json


def _score_field_defaults() -> dict[str, int | float | str]:
    """Default values for Score fields omitted from older turn snapshots."""
    defaults: dict[str, int | float | str] = {}
    for score_field in fields(Score):
        if score_field.type is int:
            defaults[score_field.name] = 0
        elif score_field.type is float:
            defaults[score_field.name] = 0.0
        elif score_field.type is str:
            defaults[score_field.name] = ""
        else:
            defaults[score_field.name] = 0
    return defaults


SCORE_FIELD_DEFAULTS = _score_field_defaults()


def _backfill_turn_settings_from_defaults(settings: dict, defaults: dict) -> None:
    """Fill keys missing from historical turn snapshots using current game settings."""
    for key, value in defaults.items():
        if key not in settings:
            settings[key] = copy.deepcopy(value)


def _payload_with_backfilled_settings(data: dict, settings_defaults: dict) -> dict:
    """Shallow-copy only when missing settings keys must be filled from defaults."""
    settings = data.get("settings")
    if not isinstance(settings, dict):
        return data
    if not any(key not in settings for key in settings_defaults):
        return data
    payload = data.copy()
    settings_copy = settings.copy()
    _backfill_turn_settings_from_defaults(settings_copy, settings_defaults)
    payload["settings"] = settings_copy
    return payload


def _payload_with_backfilled_scores(
    data: dict, score_defaults: dict[str, int | float | str]
) -> dict:
    """Shallow-copy when score rows omit fields added in later host versions."""
    scores = data.get("scores")
    if not isinstance(scores, list):
        return data
    needs_copy = False
    for entry in scores:
        if isinstance(entry, dict) and any(key not in entry for key in score_defaults):
            needs_copy = True
            break
    if not needs_copy:
        return data
    payload = data.copy()
    filled_scores: list[object] = []
    for entry in scores:
        if not isinstance(entry, dict):
            filled_scores.append(entry)
            continue
        merged = entry.copy()
        for key, value in score_defaults.items():
            if key not in merged:
                merged[key] = copy.deepcopy(value)
        filled_scores.append(merged)
    payload["scores"] = filled_scores
    return payload


def _prepare_turn_payload(
    data: dict,
    *,
    settings_defaults: dict | None,
    score_defaults: dict[str, int | float | str],
) -> dict:
    payload = data
    if settings_defaults is not None:
        payload = _payload_with_backfilled_settings(payload, settings_defaults)
    return _payload_with_backfilled_scores(payload, score_defaults)


def turn_info_from_json(data: dict, *, settings_defaults: dict | None = None) -> TurnInfo:
    """Deserialize a raw JSON dict (rst object) into a TurnInfo dataclass.

    Historical turn snapshots may omit newer ``settings`` fields. When
    ``settings_defaults`` is provided (typically from stored game info for the same
    game), missing keys are filled before deserialization. Score rows may likewise
    omit fields added mid-game; those are filled from :data:`SCORE_FIELD_DEFAULTS`.
    Does not mutate ``data``.
    """
    payload = _prepare_turn_payload(
        data,
        settings_defaults=settings_defaults,
        score_defaults=SCORE_FIELD_DEFAULTS,
    )
    return dacite.from_dict(data_class=TurnInfo, data=payload, config=DACITE_CONFIG)


def turn_info_to_json(obj: TurnInfo) -> dict:
    """Serialize a TurnInfo dataclass to a JSON-compatible dict."""
    return dataclass_to_json(obj)
