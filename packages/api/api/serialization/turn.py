"""Codec for TurnInfo (rst object from Load Turn Data)."""

import copy

import dacite

from api.models.game import TurnInfo
from api.serialization.codecs import DACITE_CONFIG, dataclass_to_json


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


def turn_info_from_json(data: dict, *, settings_defaults: dict | None = None) -> TurnInfo:
    """Deserialize a raw JSON dict (rst object) into a TurnInfo dataclass.

    Historical turn snapshots may omit newer ``settings`` fields. When
    ``settings_defaults`` is provided (typically from stored game info for the same
    game), missing keys are filled before deserialization. Does not mutate ``data``.
    """
    if settings_defaults is None:
        payload = data
    else:
        payload = _payload_with_backfilled_settings(data, settings_defaults)
    return dacite.from_dict(data_class=TurnInfo, data=payload, config=DACITE_CONFIG)


def turn_info_to_json(obj: TurnInfo) -> dict:
    """Serialize a TurnInfo dataclass to a JSON-compatible dict."""
    return dataclass_to_json(obj)
