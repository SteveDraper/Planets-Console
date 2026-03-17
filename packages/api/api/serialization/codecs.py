"""Shared dacite configuration for Planets API dataclass deserialization."""
from dataclasses import asdict
from enum import IntEnum

import dacite

from api.models.enums import GameStatus, MessageType, NativeType

ALL_ENUMS: list[type[IntEnum]] = [MessageType, NativeType, GameStatus]


def _safe_enum(enum_cls: type[IntEnum]):
    """Return a converter that maps unknown int values to the UNKNOWN sentinel."""
    def convert(value):
        try:
            return enum_cls(value)
        except ValueError:
            return enum_cls(-1)  # UNKNOWN sentinel
    return convert


DACITE_CONFIG = dacite.Config(
    type_hooks={cls: _safe_enum(cls) for cls in ALL_ENUMS},
    strict=False,
)


def dataclass_to_json(obj: object) -> dict:
    """Convert a dataclass instance to a JSON-compatible dict.

    IntEnum fields are converted to plain ints so the output matches the
    original API wire format.
    """
    raw = asdict(obj)
    return _walk_enums(raw)


def _walk_enums(node: object) -> object:
    if isinstance(node, dict):
        return {k: _walk_enums(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk_enums(v) for v in node]
    if isinstance(node, IntEnum):
        return node.value
    return node
