"""Viewpoint eligibility: which perspective slots a login identity may read."""

from api.errors import ValidationError
from api.models.game import GameInfo
from api.services.game_service import GameService

SPECTATOR_PERSPECTIVE = 0


class ViewpointEligibilityService:
    """Allowed **perspective** set for a **login identity** given **GameInfo**.

    Console visibility policy (not a host mechanic). Empty login is not an input.
    """

    SPECTATOR_PERSPECTIVE = SPECTATOR_PERSPECTIVE

    @staticmethod
    def eligible_perspectives(info: GameInfo, login_identity: str) -> frozenset[int]:
        if not login_identity.strip():
            raise ValidationError("login identity is required for viewpoint eligibility.")
        if GameService.is_game_finished(info):
            return frozenset(range(1, len(info.players) + 1))
        own_slot = GameService.perspective_for_username_or_none(info, login_identity)
        if own_slot is not None:
            return frozenset({own_slot})
        return frozenset({SPECTATOR_PERSPECTIVE})
