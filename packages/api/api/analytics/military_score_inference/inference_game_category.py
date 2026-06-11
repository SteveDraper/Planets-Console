"""Resolve inference game category from loaded game settings."""

from __future__ import annotations

from api.models.game import GameSettings

BLITZ_MAX_ENDTURN = 30
EPIC_MIN_SHIPLIMIT = 500

STANDARD_INFERENCE_GAME_CATEGORY = "standard"
BLITZ_INFERENCE_GAME_CATEGORY = "blitz"
EPIC_INFERENCE_GAME_CATEGORY = "epic"

INFERENCE_GAME_CATEGORY_RULES_VERSION = 1


def resolve_inference_game_category(settings: GameSettings) -> str:
    """Return the inference game category id for catalog prior asset selection."""
    if settings.endturn <= BLITZ_MAX_ENDTURN:
        return BLITZ_INFERENCE_GAME_CATEGORY
    if settings.shiplimit >= EPIC_MIN_SHIPLIMIT:
        return EPIC_INFERENCE_GAME_CATEGORY
    return STANDARD_INFERENCE_GAME_CATEGORY
