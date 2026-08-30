"""Public scoreboard pairing fingerprints for ship transfer families (#370)."""

from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardRow,
    classify_public_scoreboard_pairing,
)


def _row(
    player_id: int,
    *,
    warship: int = 0,
    freighter: int = 0,
    military_2x: int = 0,
) -> PublicScoreboardRow:
    return PublicScoreboardRow(
        player_id=player_id,
        warship_delta=warship,
        freighter_delta=freighter,
        military_delta_2x=military_2x,
    )


def test_unmatched_warship_drop_is_ship_loss_fingerprint():
    pairing = classify_public_scoreboard_pairing(
        _row(8, warship=-1, military_2x=-40),
        (_row(3, freighter=1),),
    )
    assert pairing.matches == ()
    assert pairing.unmatched_warship_drop == 1
    assert pairing.unmatched_freighter_drop == 0


def test_compatible_counter_delta_is_gift_not_loss():
    pairing = classify_public_scoreboard_pairing(
        _row(8, warship=-1, military_2x=-40),
        (_row(3, warship=1, military_2x=40),),
    )
    assert len(pairing.matches) == 1
    match = pairing.matches[0]
    assert match.family == "gift"
    assert match.counterparty_player_id == 3
    assert match.warship_delta == -1
    assert pairing.unmatched_warship_drop == 0


def test_several_gift_counterparties_are_distinct_matches():
    pairing = classify_public_scoreboard_pairing(
        _row(8, warship=-2, military_2x=-80),
        (
            _row(3, warship=1, military_2x=40),
            _row(4, warship=1, military_2x=40),
        ),
    )
    counterparties = {match.counterparty_player_id for match in pairing.matches}
    assert counterparties == {3, 4}
    assert all(match.family == "gift" for match in pairing.matches)
    assert all(match.warship_delta == -1 for match in pairing.matches)
    assert pairing.unmatched_warship_drop == 0


def test_count_flat_class_flip_is_trade():
    pairing = classify_public_scoreboard_pairing(
        _row(8, warship=-1, freighter=1, military_2x=-40),
        (_row(3, warship=1, freighter=-1, military_2x=40),),
    )
    assert len(pairing.matches) == 1
    match = pairing.matches[0]
    assert match.family == "trade"
    assert match.counterparty_player_id == 3
    assert match.warship_delta == -1
    assert match.freighter_delta == 1
    assert pairing.unmatched_warship_drop == 0
    assert pairing.unmatched_freighter_drop == 0


def test_count_flat_military_swap_is_trade():
    pairing = classify_public_scoreboard_pairing(
        _row(8, military_2x=-40),
        (_row(3, military_2x=40),),
    )
    assert len(pairing.matches) == 1
    assert pairing.matches[0].family == "trade"
    assert pairing.matches[0].counterparty_player_id == 3


def test_matched_incoming_hull_is_acquired_ship():
    pairing = classify_public_scoreboard_pairing(
        _row(8, warship=1, military_2x=40),
        (_row(3, warship=-1, military_2x=-40),),
    )
    assert len(pairing.matches) == 1
    match = pairing.matches[0]
    assert match.family == "acquired"
    assert match.counterparty_player_id == 3
    assert match.warship_delta == 1
    assert pairing.unmatched_warship_drop == 0


def test_partial_gift_leaves_unmatched_loss():
    pairing = classify_public_scoreboard_pairing(
        _row(8, warship=-2, military_2x=-80),
        (_row(3, warship=1, military_2x=40),),
    )
    assert pairing.matches[0].family == "gift"
    assert pairing.matches[0].warship_delta == -1
    assert pairing.unmatched_warship_drop == 1
