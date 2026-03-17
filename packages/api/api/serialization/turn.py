"""Codec for TurnInfo (rst object from Load Turn Data)."""
import dacite

from api.models.game import TurnInfo
from api.serialization.codecs import DACITE_CONFIG, dataclass_to_json


def turn_info_from_json(data: dict) -> TurnInfo:
    """Deserialize a raw JSON dict (rst object) into a TurnInfo dataclass."""
    return dacite.from_dict(data_class=TurnInfo, data=data, config=DACITE_CONFIG)


def turn_info_to_json(obj: TurnInfo) -> dict:
    """Serialize a TurnInfo dataclass to a JSON-compatible dict."""
    return dataclass_to_json(obj)
