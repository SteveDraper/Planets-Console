"""Shared dacite configuration for Planets API dataclass deserialization."""
from dataclasses import asdict
from enum import IntEnum

import dacite

from api.models.enums import GameStatus, MessageType, NativeType

ALL_ENUMS: list[type[IntEnum]] = [MessageType, NativeType, GameStatus]

DACITE_CONFIG = dacite.Config(
    cast=ALL_ENUMS,
    strict=False,
)


def _enum_to_int(value: object) -> object:
    """Convert IntEnum instances to plain ints for JSON output."""
    if isinstance(value, IntEnum):
        return value.value
    return value


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
