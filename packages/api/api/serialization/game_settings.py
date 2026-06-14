"""Wire-type fixes for GameSettings payloads from Planets.nu."""

from __future__ import annotations

from typing import get_type_hints

from api.models.game import GameSettings

GAME_SETTINGS_INT_FIELD_NAMES = frozenset(
    name for name, hint in get_type_hints(GameSettings).items() if hint is int
)


def settings_dict_needs_int_coercion(settings: dict) -> bool:
    for key in GAME_SETTINGS_INT_FIELD_NAMES:
        value = settings.get(key)
        if isinstance(value, float) and not isinstance(value, bool):
            return True
    return False


def coerce_game_settings_int_fields(settings: dict) -> None:
    """Round float wire values into int fields on a settings mapping (in place)."""
    for key in GAME_SETTINGS_INT_FIELD_NAMES:
        value = settings.get(key)
        if isinstance(value, float) and not isinstance(value, bool):
            settings[key] = round(value)
