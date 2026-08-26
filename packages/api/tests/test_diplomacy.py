"""Tests for diplomacy tier mapping and Share Intel partners."""

from api.concepts.diplomacy import (
    DiplomacyTier,
    diplomacy_tier_from_relation_code,
    is_share_intel_or_above,
    share_intel_partner_ids,
)
from api.models.player import Relation


def _relation(
    *,
    playerid: int,
    playertoid: int,
    relationto: int,
    relationfrom: int,
    relation_id: int = 1,
) -> Relation:
    return Relation(
        id=relation_id,
        playerid=playerid,
        playertoid=playertoid,
        relationto=relationto,
        relationfrom=relationfrom,
        conflictlevel=0,
        color="",
    )


def test_diplomacy_tier_codes_match_nu_client():
    assert DiplomacyTier.BLOCKED == -1
    assert DiplomacyTier.NONE == 0
    assert DiplomacyTier.AMBASSADOR == 1
    assert DiplomacyTier.SAFE_PASSAGE == 2
    assert DiplomacyTier.SHARE_INTEL == 3
    assert DiplomacyTier.FULL_ALLIANCE == 4


def test_diplomacy_tier_from_relation_code():
    assert diplomacy_tier_from_relation_code(3) is DiplomacyTier.SHARE_INTEL
    assert diplomacy_tier_from_relation_code(99) is None


def test_is_share_intel_or_above():
    assert not is_share_intel_or_above(2)
    assert is_share_intel_or_above(3)
    assert is_share_intel_or_above(4)


def test_share_intel_partner_ids_either_direction():
    relations = [
        _relation(playerid=10, playertoid=1, relationto=1, relationfrom=1),
        _relation(playerid=10, playertoid=2, relationto=3, relationfrom=1),  # we share
        _relation(playerid=10, playertoid=3, relationto=1, relationfrom=4),  # they ally
        _relation(playerid=10, playertoid=4, relationto=2, relationfrom=2),  # safe only
        _relation(playerid=9, playertoid=2, relationto=4, relationfrom=4),  # other viewpoint
    ]
    assert share_intel_partner_ids(relations, 10) == frozenset({2, 3})


def test_share_intel_partner_ids_skips_self_row():
    relations = [
        _relation(playerid=10, playertoid=10, relationto=4, relationfrom=4),
        _relation(playerid=10, playertoid=5, relationto=3, relationfrom=3),
    ]
    assert share_intel_partner_ids(relations, 10) == frozenset({5})


def test_is_mutual_full_alliance_requires_both_directions():
    from api.concepts.diplomacy import is_mutual_full_alliance

    assert is_mutual_full_alliance(
        _relation(playerid=8, playertoid=3, relationto=4, relationfrom=4)
    )
    assert not is_mutual_full_alliance(
        _relation(playerid=8, playertoid=3, relationto=4, relationfrom=1)
    )
    assert not is_mutual_full_alliance(
        _relation(playerid=8, playertoid=3, relationto=3, relationfrom=3)
    )


def test_is_live_inbound_full_alliance_mutual_only():
    from api.concepts.diplomacy import is_live_inbound_full_alliance

    relations = [
        _relation(playerid=8, playertoid=3, relationto=4, relationfrom=4),
        _relation(playerid=8, playertoid=4, relationto=4, relationfrom=1),
        _relation(playerid=8, playertoid=2, relationto=3, relationfrom=3),
    ]
    assert is_live_inbound_full_alliance(relations, viewpoint_player_id=8, target_player_id=3)
    assert not is_live_inbound_full_alliance(relations, viewpoint_player_id=8, target_player_id=4)
    assert not is_live_inbound_full_alliance(relations, viewpoint_player_id=8, target_player_id=2)
    assert not is_live_inbound_full_alliance(relations, viewpoint_player_id=0, target_player_id=3)
