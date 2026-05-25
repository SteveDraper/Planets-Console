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


def turn_info_from_json(data: dict, *, settings_defaults: dict | None = None) -> TurnInfo:
    """Deserialize a raw JSON dict (rst object) into a TurnInfo dataclass.

    Historical turn snapshots may omit newer ``settings`` fields. When
    ``settings_defaults`` is provided (typically from stored game info for the same
    game), missing keys are filled before deserialization. Does not mutate ``data``.
    """
    payload = copy.deepcopy(data)
    if settings_defaults and isinstance(payload.get("settings"), dict):
        _backfill_turn_settings_from_defaults(payload["settings"], settings_defaults)
    return dacite.from_dict(data_class=TurnInfo, data=payload, config=DACITE_CONFIG)


def turn_info_to_json(obj: TurnInfo) -> dict:
    """Serialize a TurnInfo dataclass to a JSON-compatible dict."""
    return dataclass_to_json(obj)
