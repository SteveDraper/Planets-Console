"""Game category labels derived from loaded game settings."""

from __future__ import annotations

from enum import StrEnum

from api.models.game import GameSettings

BLITZ_MAX_ENDTURN = 30
EPIC_MIN_SHIPLIMIT = 500

GAME_CATEGORY_RULES_VERSION = 2


class GameCategory(StrEnum):
    CAMPAIGN = "campaign"
    BLITZ = "blitz"
    EPIC = "epic"
    STANDARD = "standard"

    @classmethod
    def from_game_settings(cls, settings: GameSettings) -> GameCategory:
        if settings.campaignmode:
            return cls.CAMPAIGN
        if settings.endturn <= BLITZ_MAX_ENDTURN:
            return cls.BLITZ
        if settings.shiplimit >= EPIC_MIN_SHIPLIMIT:
            return cls.EPIC
        return cls.STANDARD
