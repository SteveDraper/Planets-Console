"""Summarize turn-scoped Stellar Cartography facts."""

from api.models.game import TurnInfo


def stellar_cartography_turn_summary(turn: TurnInfo) -> dict:
    """Return lightweight cartography facts that do not require full map geometry."""
    return {
        "ion_storm_count": len(turn.ionstorms),
        "nu_ion_storms": turn.settings.nuionstorms,
    }
