"""Game category labels derived from loaded game settings."""

from __future__ import annotations

from enum import StrEnum

from api.models.game import GameInfo, GameSettings

BLITZ_MAX_ENDTURN = 30
EPIC_MIN_SHIPLIMIT = 500
STANDARD_EPIC_PLAYER_COUNT = 11

GAME_CATEGORY_RULES_VERSION = 4


class GameCategory(StrEnum):
    CAMPAIGN = "campaign"
    BLITZ = "blitz"
    EPIC = "epic"
    STANDARD = "standard"
    UNKNOWN = "unknown"

    @classmethod
    def from_game_info(cls, info: GameInfo) -> GameCategory:
        return cls.from_game_settings(info.settings, player_count=len(info.players))

    @classmethod
    def from_game_settings(
        cls,
        settings: GameSettings,
        *,
        player_count: int | None = None,
    ) -> GameCategory:
        category = cls._shape_category(settings)
        if (
            player_count is not None
            and category in (cls.EPIC, cls.STANDARD)
            and player_count != STANDARD_EPIC_PLAYER_COUNT
        ):
            return cls.UNKNOWN
        return category

    @classmethod
    def _shape_category(cls, settings: GameSettings) -> GameCategory:
        if settings.campaignmode:
            return cls.CAMPAIGN
        if settings.endturn <= BLITZ_MAX_ENDTURN:
            return cls.BLITZ
        if settings.shiplimit >= EPIC_MIN_SHIPLIMIT:
            return cls.EPIC
        return cls.STANDARD
