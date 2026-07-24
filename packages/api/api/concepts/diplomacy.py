"""Diplomacy tier mapping for Planets.nu ``Relation`` integers.

Codes are confirmed from the official Nu client (``ShipMissions``-era
``app.planets.nu`` diplomacy UI): ``relationto`` / ``relationfrom`` use the
same integer ladder. Share Intel and Full Alliance both unlock shared
scanner-origin treatment for the Visibility analytic.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import IntEnum

from api.models.player import Relation

# Share Intel and above (Full Alliance) count as intel partners.
_SHARE_INTEL_MIN = 3


class DiplomacyTier(IntEnum):
    """Wire values on ``Relation.relationto`` / ``relationfrom``."""

    BLOCKED = -1
    NONE = 0
    AMBASSADOR = 1
    SAFE_PASSAGE = 2
    SHARE_INTEL = 3
    FULL_ALLIANCE = 4


def diplomacy_tier_from_relation_code(code: int) -> DiplomacyTier | None:
    """Map a relation integer to a tier, or ``None`` when unrecognized."""
    try:
        return DiplomacyTier(code)
    except ValueError:
        return None


def is_share_intel_or_above(code: int) -> bool:
    """True when the code is Share Intel (3) or Full Alliance (4)."""
    return code >= _SHARE_INTEL_MIN


def share_intel_partner_ids(
    relations: Iterable[Relation],
    viewpoint_player_id: int,
) -> frozenset[int]:
    """Return player ids that are Share Intel (or Full Alliance) partners.

    Product rule: either direction at Share Intel+ counts
    (``relationto >= 3`` or ``relationfrom >= 3``) on the viewpoint's
    ``Relation`` rows (``playerid == viewpoint``). Units must still appear
    in the turn payload to become scan origins.
    """
    partners: set[int] = set()
    for relation in relations:
        if relation.playerid != viewpoint_player_id:
            continue
        if relation.playertoid == viewpoint_player_id:
            continue
        if is_share_intel_or_above(relation.relationto) or is_share_intel_or_above(
            relation.relationfrom
        ):
            partners.add(relation.playertoid)
    return frozenset(partners)
