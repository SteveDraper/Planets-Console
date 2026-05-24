"""Sector display name extraction from stored game info payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.models.game import GameInfo


def sector_display_name_from_stored_payload(raw: object) -> str | None:
    """Best-effort sector title from a stored ``games/{{id}}/info`` JSON object."""
    if not isinstance(raw, dict):
        return None
    for key in ("game", "settings"):
        block = raw.get(key)
        if isinstance(block, dict):
            name = block.get("name")
            if isinstance(name, str):
                trimmed = name.strip()
                if trimmed:
                    return trimmed
    return None


def sector_display_name_from_game_info(info: GameInfo) -> str | None:
    """Same precedence as ``sector_display_name_from_stored_payload`` on a loaded ``GameInfo``."""
    for name in (info.game.name, info.settings.name):
        if isinstance(name, str):
            trimmed = name.strip()
            if trimmed:
                return trimmed
    return None
