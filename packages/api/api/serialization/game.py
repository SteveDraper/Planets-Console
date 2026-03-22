"""Codec for GameInfo (Load Game Info response)."""

import copy

import dacite

from api.models.game import GameInfo
from api.serialization.codecs import DACITE_CONFIG, dataclass_to_json


def _coerce_game_info_year_int_fields(payload: dict) -> None:
    """Normalize yearfrom / yearto: int, zero-padded numeric strings, or None when unknown."""
    for key in ("yearfrom", "yearto"):
        val = payload.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            s = val.strip()
            if not s:
                payload[key] = None
                continue
            try:
                payload[key] = int(s, 10)
            except ValueError:
                payload[key] = None


def game_info_from_json(data: dict) -> GameInfo:
    """Deserialize a raw JSON dict into a GameInfo dataclass.

    Does not mutate the input dict (deep copy before optional wire-type fixes).
    """
    payload = copy.deepcopy(data)
    _coerce_game_info_year_int_fields(payload)
    return dacite.from_dict(data_class=GameInfo, data=payload, config=DACITE_CONFIG)


def game_info_to_json(obj: GameInfo) -> dict:
    """Serialize a GameInfo dataclass to a JSON-compatible dict."""
    return dataclass_to_json(obj)
