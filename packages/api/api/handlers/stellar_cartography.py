"""Shared turn-scoped Stellar Cartography sample route logic for Core and BFF callers."""

from api.concepts.stellar_cartography.sample_at import sample_at as sample_at_turn
from api.services.turn_concept_service import TurnConceptService
from api.transport.concept_stellar_cartography import StellarCartographySampleResponse


def sample_at(
    svc: TurnConceptService,
    game_id: int,
    perspective: int,
    turn_number: int,
    x: int,
    y: int,
) -> StellarCartographySampleResponse:
    """Return stacked cartography tooltip entries at map cell ``(x, y)``."""
    turn = svc.get_turn_info(game_id, perspective, turn_number)
    payload = sample_at_turn(turn, x, y)
    return StellarCartographySampleResponse.model_validate(payload)
