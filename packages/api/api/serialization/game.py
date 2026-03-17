"""Codec for GameInfo (Load Game Info response)."""

import dacite

from api.models.game import GameInfo
from api.serialization.codecs import DACITE_CONFIG, dataclass_to_json


def game_info_from_json(data: dict) -> GameInfo:
    """Deserialize a raw JSON dict into a GameInfo dataclass."""
    return dacite.from_dict(data_class=GameInfo, data=data, config=DACITE_CONFIG)


def game_info_to_json(obj: GameInfo) -> dict:
    """Serialize a GameInfo dataclass to a JSON-compatible dict."""
    return dataclass_to_json(obj)
