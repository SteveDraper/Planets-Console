"""Public scoreboard pairing fingerprints for ship transfer families (#370)."""

from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardRow,
    classify_public_scoreboard_pairing,
    transfer_budget_for_row,
)
from api.analytics.military_score_inference.ship_transfer_families import (
    public_scoreboard_rows_from_scores,
)

from tests.fixtures.pp_gap_transfer import (
    BIRDS_PLAYER_ID,
    FEDERATION_PLAYER_ID,
    PRIVATEER_PLAYER_ID,
    birds_row,
    federation_row,
    privateer_peer_rows,
    privateer_peer_scores,
    privateer_row,
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


def test_military_swap_trade_tolerates_rounding_offset():
    pairing = classify_public_scoreboard_pairing(
        _row(8, military_2x=-40),
        (_row(3, military_2x=39),),
    )
    assert len(pairing.matches) == 1
    assert pairing.matches[0].family == "trade"
    assert pairing.matches[0].counterparty_player_id == 3


def test_gift_tolerates_counterparty_military_rounding():
    pairing = classify_public_scoreboard_pairing(
        _row(8, warship=-1, military_2x=-40),
        (_row(3, warship=1, military_2x=39),),
    )
    assert len(pairing.matches) == 1
    assert pairing.matches[0].family == "gift"
    assert pairing.matches[0].warship_delta == -1
    assert pairing.unmatched_warship_drop == 0


def test_zero_noise_rows_do_not_match_as_trade():
    pairing = classify_public_scoreboard_pairing(
        _row(8),
        (_row(3),),
    )
    assert pairing.matches == ()
    assert pairing.unmatched_warship_drop == 0
    assert pairing.unmatched_freighter_drop == 0


def test_beyond_tolerance_military_mismatch_is_not_a_trade():
    pairing = classify_public_scoreboard_pairing(
        _row(8, military_2x=-40),
        (_row(3, military_2x=30),),
    )
    assert pairing.matches == ()


def test_partial_gift_leaves_unmatched_loss():
    pairing = classify_public_scoreboard_pairing(
        _row(8, warship=-2, military_2x=-80),
        (_row(3, warship=1, military_2x=40),),
    )
    assert pairing.matches[0].family == "gift"
    assert pairing.matches[0].warship_delta == -1
    assert pairing.unmatched_warship_drop == 1


def test_raw_drop_gift_still_requires_opposite_military_signs():
    pairing = classify_public_scoreboard_pairing(
        _row(8, warship=-1, military_2x=40),
        (_row(3, warship=1, military_2x=40),),
    )
    assert pairing.matches == ()
    assert pairing.unmatched_warship_drop == 1


def test_privateer_idle_dock_budget_is_one_arrival(sample_turn):
    budget = transfer_budget_for_row(
        privateer_row(),
        settings=sample_turn.settings,
        is_after_ship_limit=False,
    )
    assert budget.implied_ships_built == 2
    assert budget.net == 3
    assert budget.excess_in == 1
    assert budget.excess_out == 0


def test_federation_idle_dock_budget_is_one_departure(sample_turn):
    budget = transfer_budget_for_row(
        federation_row(),
        settings=sample_turn.settings,
        is_after_ship_limit=False,
    )
    assert budget.implied_ships_built == 2
    assert budget.net == 1
    assert budget.excess_out == 1
    assert budget.excess_in == 0


def test_excess_out_without_raw_drop_is_pp_only():
    budget = transfer_budget_for_row(federation_row(), settings=None, is_after_ship_limit=False)
    assert budget.implied_ships_built is None
    assert budget.excess_out == 0
    assert budget.excess_in == 0


def test_dock_cap_floor_sees_net_above_starbases():
    budget = transfer_budget_for_row(privateer_row(), settings=None, is_after_ship_limit=False)
    assert budget.implied_ships_built is None
    assert budget.excess_in == 1
    assert budget.excess_out == 0


def test_pp_gap_pairs_privateer_with_fed_or_birds_as_alternative_donors(sample_turn):
    pairing = classify_public_scoreboard_pairing(
        privateer_row(),
        privateer_peer_rows(),
        settings=sample_turn.settings,
        is_after_ship_limit=False,
    )
    counterparties = {match.counterparty_player_id for match in pairing.matches}
    assert counterparties == {FEDERATION_PLAYER_ID, BIRDS_PLAYER_ID}
    assert all(match.family == "acquired" for match in pairing.matches)
    assert all(match.source == "pp_gap" for match in pairing.matches)
    assert all(match.warship_delta == 1 for match in pairing.matches)
    assert all(match.freighter_delta == 0 for match in pairing.matches)


def test_pp_gap_acquired_does_not_require_opposite_class_or_military_signs(sample_turn):
    pairing = classify_public_scoreboard_pairing(
        privateer_row(),
        (federation_row(),),
        settings=sample_turn.settings,
        is_after_ship_limit=False,
    )
    assert len(pairing.matches) == 1
    match = pairing.matches[0]
    assert match.family == "acquired"
    assert federation_row().warship_delta == 0
    assert privateer_row().military_delta_2x > 0
    assert federation_row().military_delta_2x > 0
    assert match.warship_delta == 1


def test_pp_gap_gift_is_symmetric_to_acquired(sample_turn):
    pairing = classify_public_scoreboard_pairing(
        federation_row(),
        (privateer_row(), birds_row()),
        settings=sample_turn.settings,
        is_after_ship_limit=False,
    )
    privateer_match = next(
        match for match in pairing.matches if match.counterparty_player_id == PRIVATEER_PLAYER_ID
    )
    assert privateer_match.family == "gift"
    assert privateer_match.source == "pp_gap"
    assert privateer_match.warship_delta == -1
    assert privateer_match.freighter_delta == 0


def test_pp_gap_does_not_admit_unpaired_acquired(sample_turn):
    pairing = classify_public_scoreboard_pairing(
        privateer_row(),
        (_zeroed_excess_out(birds_row()),),
        settings=sample_turn.settings,
        is_after_ship_limit=False,
    )
    assert pairing.matches == ()


def _zeroed_excess_out(row: PublicScoreboardRow) -> PublicScoreboardRow:
    """Force k == net so idle-dock excess_out is 0 (PP-gap giver disappears)."""
    net = row.warship_delta + row.freighter_delta
    return PublicScoreboardRow(
        player_id=row.player_id,
        warship_delta=row.warship_delta,
        freighter_delta=row.freighter_delta,
        military_delta_2x=row.military_delta_2x,
        starbases=max(net, 0),
        priority_point_delta=0,
        planet_delta=row.planet_delta,
        starbase_delta=row.starbase_delta,
    )


def test_peer_rows_include_viewpoint_federation_when_solving_privateer():
    peers = public_scoreboard_rows_from_scores(
        privateer_peer_scores(),
        this_player_id=PRIVATEER_PLAYER_ID,
    )
    peer_ids = {row.player_id for row in peers}
    assert FEDERATION_PLAYER_ID in peer_ids
    assert BIRDS_PLAYER_ID in peer_ids
    assert PRIVATEER_PLAYER_ID not in peer_ids
    fed = next(row for row in peers if row.player_id == FEDERATION_PLAYER_ID)
    assert fed.warship_delta == 0
    assert fed.freighter_delta == 1
    assert fed.starbases == 3
    assert fed.priority_point_delta == 2
