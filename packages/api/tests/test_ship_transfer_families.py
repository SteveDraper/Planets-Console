"""Ship transfer catalog fragment and action catalog construction (#370)."""

from dataclasses import replace

from api.analytics.military_score_inference.actions import (
    build_action_catalog,
    build_inference_problem,
)
from api.analytics.military_score_inference.idle_dock_pp import idle_dock_implied_ships_built
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    ProbabilityBucket,
)
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PairingMatch,
    PairingSource,
    PublicScoreboardPairing,
    PublicScoreboardRow,
    TransferBudget,
    public_scoreboard_row_from_observation,
    transfer_budget_for_row,
)
from api.analytics.military_score_inference.ship_build_combos import ship_build_upper_bound
from api.analytics.military_score_inference.ship_transfer_families import (
    ACQUIRED_SHIP_ACTION_PREFIX,
    GIFT_ACTION_PREFIX,
    SHIP_LOSS_ACTION_PREFIX,
    TRADE_ACTION_PREFIX,
    build_ship_transfer_catalog_fragment,
    ship_transfer_combo_capacity,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.concepts.inference_probability_scale import INFERENCE_PROBABILITY_WEIGHT_SCALE

from tests.fixtures.military_score_inference import _observation
from tests.fixtures.pp_gap_transfer import (
    BIRDS_PLAYER_ID,
    FEDERATION_PLAYER_ID,
    federation_row,
    mixed_residual_receiver_observation,
    privateer_observation,
    privateer_peer_rows,
)
from tests.fixtures.ship_transfer_families import (
    _class_flip_trade_catalog,
    _class_only_freighter_record,
    _known_warship_record,
    _peer_row,
    _same_class_swap_catalog,
    _transfer_catalog_kwargs,
    _two_ship_class_flip_trade_fragment,
)


def test_catalog_has_no_inverted_ship_build_loss_combos(synthetic_catalog_build_context):
    record, military_2x = _known_warship_record(synthetic_catalog_build_context)
    observation = replace(
        _observation(military_delta_2x=-military_2x, warship_delta=-1),
        priority_point_delta=1,
    )
    catalog = build_action_catalog(
        observation,
        **synthetic_catalog_build_context,
        prior_fleet_records=(record,),
    )
    assert all(combo.warship_delta >= 0 for combo in catalog.ship_build_combos)
    assert all(combo.freighter_delta >= 0 for combo in catalog.ship_build_combos)
    assert any(
        action.id.startswith(SHIP_LOSS_ACTION_PREFIX) for action in catalog.aggregate_actions
    )


def test_decrease_families_enter_at_early_game_bands(synthetic_catalog_build_context):
    early = resolve_tier_policies()[0]
    assert early.id == "early_game_bands"
    assert early.aggregate_allowlist == {}
    record, military_2x = _known_warship_record(synthetic_catalog_build_context)
    observation = replace(
        _observation(military_delta_2x=-military_2x, warship_delta=-1),
        priority_point_delta=1,
    )
    catalog = build_action_catalog(
        observation,
        **synthetic_catalog_build_context,
        policy_step=early,
        prior_fleet_records=(record,),
    )
    assert any(
        action.id.startswith(SHIP_LOSS_ACTION_PREFIX) for action in catalog.aggregate_actions
    )


TRANSFER_ACTION_PREFIXES = (
    SHIP_LOSS_ACTION_PREFIX,
    GIFT_ACTION_PREFIX,
    TRADE_ACTION_PREFIX,
    ACQUIRED_SHIP_ACTION_PREFIX,
)


def _is_transfer_action_id(action_id: str) -> bool:
    return action_id.startswith(TRANSFER_ACTION_PREFIXES)


def test_transfer_actions_carry_flat_penalty_buckets(synthetic_catalog_build_context):
    record, military_2x = _known_warship_record(synthetic_catalog_build_context)
    observation = replace(
        _observation(military_delta_2x=-military_2x, warship_delta=-1),
        priority_point_delta=1,
    )
    catalog = build_action_catalog(
        observation,
        **synthetic_catalog_build_context,
        prior_fleet_records=(record,),
    )
    transfer_actions = [
        action for action in catalog.aggregate_actions if _is_transfer_action_id(action.id)
    ]
    assert transfer_actions
    active_weight = (
        INFERENCE_PROBABILITY_WEIGHT_SCALE
        - catalog.ranking_heuristics.transfer_family_active_penalty
    )
    for action in transfer_actions:
        buckets = catalog.probability_buckets_by_action_id[action.id]
        assert buckets == (
            ProbabilityBucket(
                label="none",
                lower_count=0,
                upper_count=0,
                marginal_weight=INFERENCE_PROBABILITY_WEIGHT_SCALE,
            ),
            ProbabilityBucket(
                label="active",
                lower_count=1,
                upper_count=action.upper_bound,
                marginal_weight=active_weight,
            ),
        )


def test_loss_plus_replace_combo_bound_uses_prior_fleet_capacity():
    observation = _observation(warship_delta=0, starbases_owned=3)
    assert (
        ship_build_upper_bound(
            observation,
            is_warship=True,
            is_freighter=False,
        )
        == 0
    )
    assert (
        ship_build_upper_bound(
            observation,
            is_warship=True,
            is_freighter=False,
            extra_warship_capacity=1,
        )
        == 1
    )


def test_acquired_incoming_is_reserved_out_of_build_bound():
    observation = _observation(warship_delta=1, starbases_owned=3)
    assert (
        ship_build_upper_bound(
            observation,
            is_warship=True,
            is_freighter=False,
            reserved_incoming_warships=1,
        )
        == 0
    )


def test_gift_actions_carry_counterparty_and_are_not_loss(synthetic_catalog_context):
    record, military_2x = _known_warship_record(synthetic_catalog_context)
    observation = replace(
        _observation(military_delta_2x=-military_2x, warship_delta=-1),
        priority_point_delta=1,
    )
    actions = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(_peer_row(3, warship=1, military_2x=military_2x),),
        prior_fleet_records=(record,),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    ).actions
    assert any(action.id.startswith(GIFT_ACTION_PREFIX) for action in actions)
    assert all(not action.id.startswith(SHIP_LOSS_ACTION_PREFIX) for action in actions)
    gift = next(action for action in actions if action.id.startswith(GIFT_ACTION_PREFIX))
    assert gift.counterparty_player_id == 3
    assert gift.priority_point_delta == 0
    assert gift.build_slot_usage == 0


def test_several_gift_counterparties_are_distinct_action_ids(synthetic_catalog_context):
    record, military_2x = _known_warship_record(synthetic_catalog_context)
    observation = replace(
        _observation(military_delta_2x=-military_2x, warship_delta=-1),
        priority_point_delta=1,
    )
    actions = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(
            _peer_row(3, warship=1, military_2x=military_2x),
            _peer_row(4, warship=1, military_2x=military_2x),
        ),
        prior_fleet_records=(record,),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    ).actions
    gift_ids = {action.id for action in actions if action.id.startswith(GIFT_ACTION_PREFIX)}
    counterparties = {
        action.counterparty_player_id
        for action in actions
        if action.id.startswith(GIFT_ACTION_PREFIX)
    }
    assert len(gift_ids) == 2
    assert counterparties == {3, 4}


def test_trade_emits_distinct_ids_for_each_prior_fleet_military_group(
    synthetic_catalog_context,
):
    _, fragment, first_military, matching_military = _class_flip_trade_catalog(
        synthetic_catalog_context
    )
    trade_ids = {
        action.id for action in fragment.actions if action.id.startswith(TRADE_ACTION_PREFIX)
    }
    expected = {
        f"{TRADE_ACTION_PREFIX}warship:with:3:point:{first_military}",
        f"{TRADE_ACTION_PREFIX}warship:with:3:point:{matching_military}",
    }
    assert trade_ids == expected


def test_same_class_swap_emits_one_action_across_prior_fleet_groups(
    synthetic_catalog_context,
):
    observation, fragment = _same_class_swap_catalog(synthetic_catalog_context)
    trades = [action for action in fragment.actions if action.id.startswith(TRADE_ACTION_PREFIX)]
    assert len(trades) == 1
    swap = trades[0]
    assert swap.id == f"{TRADE_ACTION_PREFIX}warship:with:3:swap:{observation.military_delta_2x}"
    assert swap.score_delta_2x == observation.military_delta_2x
    assert swap.warship_delta == 0
    assert swap.freighter_delta == 0
    assert swap.prior_group_key is None
    assert swap.prior_warship_usage == 1
    assert swap.upper_bound == 1


def test_same_class_swap_requires_a_prior_fleet_warship(synthetic_catalog_context):
    observation = _observation(
        military_delta_2x=40,
        warship_delta=0,
        freighter_delta=0,
    )
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(_peer_row(3, warship=0, military_2x=-40),),
        prior_fleet_records=(_class_only_freighter_record(),),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert not any(action.id.startswith(TRADE_ACTION_PREFIX) for action in fragment.actions)


def test_catalog_idle_dock_flag_follows_lattice(sample_turn, synthetic_catalog_build_context):
    on_lattice = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=40,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=2,
        starbases_owned=2,
        is_after_ship_limit=False,
        planet_delta=0,
        starbase_delta=0,
    )
    catalog = build_action_catalog(
        on_lattice,
        **synthetic_catalog_build_context,
        turn=sample_turn,
    )
    assert catalog.enforce_idle_dock_pp_equality is True
    problem = build_inference_problem(on_lattice, catalog)
    assert problem.enforce_idle_dock_pp_equality is True

    off_lattice = replace(on_lattice, priority_point_delta=1)
    off_catalog = build_action_catalog(
        off_lattice,
        **synthetic_catalog_build_context,
        turn=sample_turn,
    )
    assert off_catalog.enforce_idle_dock_pp_equality is False


def test_transfer_catalog_fragment_carries_actions_and_capacity_fields(
    synthetic_catalog_context,
):
    record, military_2x = _known_warship_record(synthetic_catalog_context)
    observation = replace(
        _observation(military_delta_2x=-military_2x, warship_delta=-1),
        priority_point_delta=1,
    )
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(),
        prior_fleet_records=(record,),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert any(action.id.startswith(SHIP_LOSS_ACTION_PREFIX) for action in fragment.actions)
    assert all(action.upper_bound > 0 for action in fragment.actions)
    assert fragment.prior_warship_departure_cap == 1
    assert fragment.prior_freighter_departure_cap == 0
    assert fragment.prior_departure_group_caps == {f"warship:point:{military_2x}": 1}
    loss = next(
        action for action in fragment.actions if action.id.startswith(SHIP_LOSS_ACTION_PREFIX)
    )
    assert loss.prior_group_key == f"warship:point:{military_2x}"
    assert fragment.extra_warship_capacity == 1
    assert fragment.extra_freighter_capacity == 0
    assert fragment.reserved_incoming_warships == 0
    assert fragment.reserved_incoming_freighters == 0


def test_transfer_catalog_fragment_reserves_acquired_incoming(synthetic_catalog_context):
    observation = replace(
        _observation(military_delta_2x=40, warship_delta=1),
        priority_point_delta=1,
    )
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(_peer_row(3, warship=-1, military_2x=-40),),
        prior_fleet_records=(),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    acquired = next(
        action for action in fragment.actions if action.id.startswith(ACQUIRED_SHIP_ACTION_PREFIX)
    )
    assert acquired.score_delta_2x_max == 40
    assert all(action.prior_group_key is None for action in fragment.actions)
    assert fragment.reserved_incoming_warships == 1
    assert fragment.reserved_incoming_freighters == 0
    assert fragment.reserved_incoming_ships == 1
    assert fragment.extra_warship_capacity == 0
    assert fragment.prior_warship_departure_cap == 0
    this_budget = transfer_budget_for_row(
        public_scoreboard_row_from_observation(observation),
        settings=None,
        is_after_ship_limit=False,
    )
    assert this_budget.excess_in == 0


def test_two_ship_class_flip_trade_requires_two_records_in_group(synthetic_catalog_context):
    record, military_2x = _known_warship_record(synthetic_catalog_context)
    _, fragment = _two_ship_class_flip_trade_fragment(
        synthetic_catalog_context,
        (record,),
        military_delta_2x=-2 * military_2x,
    )
    assert not any(action.id.startswith(TRADE_ACTION_PREFIX) for action in fragment.actions)


def test_pp_gap_catalog_reserves_one_acquired_warship_not_sum_of_peers(
    sample_turn, synthetic_catalog_context
):
    observation = privateer_observation()
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=privateer_peer_rows(),
        prior_fleet_records=(),
        settings=sample_turn.settings,
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    acquired = [
        action for action in fragment.actions if action.id.startswith(ACQUIRED_SHIP_ACTION_PREFIX)
    ]
    counterparties = {action.counterparty_player_id for action in acquired}
    assert counterparties == {FEDERATION_PLAYER_ID, BIRDS_PLAYER_ID}
    assert all(action.warship_delta == 1 for action in acquired)
    assert all(action.upper_bound == 1 for action in acquired)
    assert all(action.score_delta_2x_max == observation.military_delta_2x for action in acquired)
    this_budget = transfer_budget_for_row(
        public_scoreboard_row_from_observation(observation),
        settings=sample_turn.settings,
        is_after_ship_limit=False,
    )
    assert this_budget.excess_in == 1
    assert sum(action.upper_bound for action in acquired) == 2
    assert fragment.reserved_incoming_warships == this_budget.excess_in
    assert fragment.reserved_incoming_freighters == 0
    assert fragment.reserved_incoming_ships == this_budget.excess_in
    assert idle_dock_implied_ships_built(observation) == 2
    assert (
        ship_build_upper_bound(
            observation,
            is_warship=True,
            is_freighter=False,
            reserved_incoming_warships=fragment.reserved_incoming_warships,
        )
        == 2
    )


def test_pp_gap_catalog_emits_no_acquired_when_no_peer_excess_out(
    sample_turn, synthetic_catalog_context
):
    observation = privateer_observation()
    closed_birds = PublicScoreboardRow(
        player_id=BIRDS_PLAYER_ID,
        warship_delta=0,
        freighter_delta=0,
        military_delta_2x=0,
        starbases=0,
        priority_point_delta=0,
    )
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(closed_birds,),
        prior_fleet_records=(),
        settings=sample_turn.settings,
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert not any(action.id.startswith(ACQUIRED_SHIP_ACTION_PREFIX) for action in fragment.actions)
    this_budget = transfer_budget_for_row(
        public_scoreboard_row_from_observation(observation),
        settings=sample_turn.settings,
        is_after_ship_limit=False,
    )
    assert this_budget.excess_in == 1
    assert fragment.reserved_incoming_ships == this_budget.excess_in


def test_pp_gap_unknown_class_catalog_is_exclusive_not_two_reserved_columns(
    sample_turn, synthetic_catalog_context
):
    observation = mixed_residual_receiver_observation()
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(federation_row(),),
        prior_fleet_records=(),
        settings=sample_turn.settings,
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    acquired = [
        action for action in fragment.actions if action.id.startswith(ACQUIRED_SHIP_ACTION_PREFIX)
    ]
    assert {action.warship_delta for action in acquired} == {0, 1}
    assert {action.freighter_delta for action in acquired} == {0, 1}
    assert all(action.upper_bound == 1 for action in acquired)
    assert len({action.exclusive_class_group for action in acquired}) == 1
    assert all(action.exclusive_class_group is not None for action in acquired)
    this_budget = transfer_budget_for_row(
        public_scoreboard_row_from_observation(observation),
        settings=sample_turn.settings,
        is_after_ship_limit=False,
    )
    assert this_budget.excess_in == 1
    assert fragment.reserved_incoming_warships == 0
    assert fragment.reserved_incoming_freighters == 0
    assert fragment.reserved_incoming_ships == this_budget.excess_in


def _acquired_pairing_match(
    *,
    player_id: int,
    source: PairingSource,
    warship: int = 0,
    freighter: int = 0,
    transfer_count: int = 0,
) -> PairingMatch:
    return PairingMatch(
        family="acquired",
        counterparty_player_id=player_id,
        warship_delta=warship,
        freighter_delta=freighter,
        counterparty_military_delta_2x=-40,
        source=source,
        transfer_count=transfer_count,
        pinned_class="warship" if warship and not freighter else None,
    )


def test_combo_capacity_reserves_excess_in_not_max_of_peer_caps():
    observation = _observation(warship_delta=4, starbases_owned=2)
    this_budget = TransferBudget(implied_ships_built=2, net=4, excess_in=2, excess_out=0)
    pairing = PublicScoreboardPairing(
        matches=(
            _acquired_pairing_match(player_id=1, source="pp_gap", warship=1, transfer_count=1),
            _acquired_pairing_match(player_id=3, source="pp_gap", warship=1, transfer_count=1),
        ),
        unmatched_warship_drop=0,
        unmatched_freighter_drop=0,
    )
    _, _, reserved_warship, reserved_freighter, reserved_ships = ship_transfer_combo_capacity(
        observation,
        pairing,
        0,
        0,
        this_budget=this_budget,
    )
    assert sum(match.transfer_count for match in pairing.matches) == 2
    assert max(match.transfer_count for match in pairing.matches) == 1
    assert (reserved_warship, reserved_freighter, reserved_ships) == (2, 0, 2)


def test_combo_capacity_raw_drop_reserves_sum_when_excess_in_is_zero():
    observation = _observation(warship_delta=2, starbases_owned=3)
    this_budget = TransferBudget(implied_ships_built=None, net=2, excess_in=0, excess_out=0)
    pairing = PublicScoreboardPairing(
        matches=(
            _acquired_pairing_match(player_id=1, source="raw_drop", warship=1),
            _acquired_pairing_match(player_id=3, source="raw_drop", warship=1),
        ),
        unmatched_warship_drop=0,
        unmatched_freighter_drop=0,
    )
    _, _, reserved_warship, reserved_freighter, reserved_ships = ship_transfer_combo_capacity(
        observation,
        pairing,
        0,
        0,
        this_budget=this_budget,
    )
    assert (reserved_warship, reserved_freighter, reserved_ships) == (2, 0, 2)
