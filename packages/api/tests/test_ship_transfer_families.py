"""Ship loss, gift, trade, and acquired ship families (#370)."""

from dataclasses import replace

from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetFieldKnown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.actions import (
    build_action_catalog,
    build_inference_problem,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.prior_fleet_decrease_candidates import (
    prior_fleet_decrease_candidates,
)
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardRow,
)
from api.analytics.military_score_inference.ship_build_combos import ship_build_upper_bound
from api.analytics.military_score_inference.ship_transfer_families import (
    ACQUIRED_SHIP_ACTION_PREFIX,
    GIFT_ACTION_PREFIX,
    SHIP_LOSS_ACTION_PREFIX,
    TRADE_ACTION_PREFIX,
    build_ship_transfer_catalog_fragment,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT, solve_inference_problem
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.concepts.ship_build_military import ship_build_military_score_delta_2x

from tests.fixtures.military_score_inference import _observation


def _scoreboard_class_event(ship_class: str) -> FleetEvidenceEvent:
    return FleetEvidenceEvent(
        event_id=f"delta-{ship_class}",
        kind="scoreboard_delta",
        turn=110,
        source="scoreboard",
        payload={"shipClass": ship_class},
    )


def _known_warship_record(
    synthetic_catalog_context,
    *,
    beam_count: int = 2,
    record_id: str = "known-serpent",
) -> tuple[FleetShipRecord, int]:
    hull = synthetic_catalog_context["hulls_by_id"][24]
    engine = synthetic_catalog_context["engines_by_id"][1]
    beam = synthetic_catalog_context["beams_by_id"][1]
    military_2x = ship_build_military_score_delta_2x(
        hull,
        engine,
        beam,
        None,
        beam_count=beam_count,
        launcher_count=0,
    )
    record = FleetShipRecord(
        record_id=record_id,
        fields=FleetShipRecordFields(
            hull=FleetFieldKnown(24),
            engine=FleetFieldKnown(1),
            beams=FleetFieldKnown(1),
            launchers=FleetFieldKnown(0),
        ),
        build_option_sets=[
            FleetBuildOptionSet(
                hull_id=24,
                engine_id=1,
                beam_id=1,
                beam_count=beam_count,
                launcher_count=0,
            )
        ],
    )
    return record, military_2x


def _envelope_warship_record() -> FleetShipRecord:
    return FleetShipRecord(
        record_id="envelope-warship",
        events=[_scoreboard_class_event("warship")],
        build_option_sets=[
            FleetBuildOptionSet(
                military_score_delta_2x_min=20,
                military_score_delta_2x_max=80,
            )
        ],
    )


def test_known_hull_candidate_is_point_military(synthetic_catalog_context):
    record, military_2x = _known_warship_record(synthetic_catalog_context)
    candidates = prior_fleet_decrease_candidates(
        (record,),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
        engines_by_id=synthetic_catalog_context["engines_by_id"],
        beams_by_id=synthetic_catalog_context["beams_by_id"],
        torpedos_by_id=synthetic_catalog_context["torpedos_by_id"],
        buildable_hull_ids=synthetic_catalog_context["buildable_hull_ids"],
    )
    assert len(candidates) == 1
    assert candidates[0].is_point_military is True
    assert candidates[0].score_delta_2x_min == military_2x
    assert candidates[0].score_delta_2x_max == military_2x
    assert candidates[0].ship_class == "warship"


def test_option_set_envelope_candidate_is_interval(synthetic_catalog_context):
    candidates = prior_fleet_decrease_candidates(
        (_envelope_warship_record(),),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
        engines_by_id=synthetic_catalog_context["engines_by_id"],
        beams_by_id=synthetic_catalog_context["beams_by_id"],
        torpedos_by_id=synthetic_catalog_context["torpedos_by_id"],
        buildable_hull_ids=synthetic_catalog_context["buildable_hull_ids"],
    )
    assert len(candidates) == 1
    assert candidates[0].is_point_military is False
    assert candidates[0].score_delta_2x_min == 20
    assert candidates[0].score_delta_2x_max == 80


def test_inactive_records_are_not_decrease_candidates(synthetic_catalog_context):
    record, _ = _known_warship_record(synthetic_catalog_context)
    record.disposition = "lost"
    candidates = prior_fleet_decrease_candidates(
        (record,),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
        engines_by_id=synthetic_catalog_context["engines_by_id"],
        beams_by_id=synthetic_catalog_context["beams_by_id"],
        torpedos_by_id=synthetic_catalog_context["torpedos_by_id"],
        buildable_hull_ids=synthetic_catalog_context["buildable_hull_ids"],
    )
    assert candidates == ()


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


def _peer_row(
    player_id: int,
    *,
    warship: int,
    military_2x: int,
    freighter: int = 0,
) -> PublicScoreboardRow:
    return PublicScoreboardRow(
        player_id=player_id,
        warship_delta=warship,
        freighter_delta=freighter,
        military_delta_2x=military_2x,
    )


def _transfer_catalog_kwargs(synthetic_catalog_context) -> dict:
    return {
        "hulls_by_id": synthetic_catalog_context["hulls_by_id"],
        "engines_by_id": synthetic_catalog_context["engines_by_id"],
        "beams_by_id": synthetic_catalog_context["beams_by_id"],
        "torpedos_by_id": synthetic_catalog_context["torpedos_by_id"],
        "buildable_hull_ids": synthetic_catalog_context["buildable_hull_ids"],
    }


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
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
        engines_by_id=synthetic_catalog_context["engines_by_id"],
        beams_by_id=synthetic_catalog_context["beams_by_id"],
        torpedos_by_id=synthetic_catalog_context["torpedos_by_id"],
        buildable_hull_ids=synthetic_catalog_context["buildable_hull_ids"],
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
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
        engines_by_id=synthetic_catalog_context["engines_by_id"],
        beams_by_id=synthetic_catalog_context["beams_by_id"],
        torpedos_by_id=synthetic_catalog_context["torpedos_by_id"],
        buildable_hull_ids=synthetic_catalog_context["buildable_hull_ids"],
    ).actions
    gift_ids = {action.id for action in actions if action.id.startswith(GIFT_ACTION_PREFIX)}
    counterparties = {
        action.counterparty_player_id
        for action in actions
        if action.id.startswith(GIFT_ACTION_PREFIX)
    }
    assert len(gift_ids) == 2
    assert counterparties == {3, 4}


def _class_flip_trade_catalog(
    synthetic_catalog_context,
    *,
    first_beam_count: int = 1,
    matching_beam_count: int = 2,
) -> tuple[InferenceObservation, tuple[CandidateAction, ...], int, int]:
    first, first_military = _known_warship_record(
        synthetic_catalog_context,
        beam_count=first_beam_count,
        record_id="serpent-first",
    )
    matching, matching_military = _known_warship_record(
        synthetic_catalog_context,
        beam_count=matching_beam_count,
        record_id="serpent-matching",
    )
    assert first_military != matching_military
    observation = replace(
        _observation(
            military_delta_2x=-matching_military,
            warship_delta=-1,
            freighter_delta=1,
        ),
        priority_point_delta=1,
    )
    actions = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(_peer_row(3, warship=1, freighter=-1, military_2x=matching_military),),
        prior_fleet_records=(first, matching),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    ).actions
    return observation, actions, first_military, matching_military


def test_trade_emits_distinct_ids_for_each_prior_fleet_military_group(
    synthetic_catalog_context,
):
    _, actions, first_military, matching_military = _class_flip_trade_catalog(
        synthetic_catalog_context
    )
    trade_ids = {action.id for action in actions if action.id.startswith(TRADE_ACTION_PREFIX)}
    expected = {
        f"{TRADE_ACTION_PREFIX}warship:with:3:point:{first_military}",
        f"{TRADE_ACTION_PREFIX}warship:with:3:point:{matching_military}",
    }
    assert trade_ids == expected


def test_catalog_solver_class_flip_trade_when_matching_hull_is_not_first_group(
    synthetic_catalog_context,
):
    observation, actions, _first_military, matching_military = _class_flip_trade_catalog(
        synthetic_catalog_context
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=actions,
            prior_warship_departure_cap=2,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    chosen = result.solutions[0].actions[0]
    assert chosen.action_id == f"{TRADE_ACTION_PREFIX}warship:with:3:point:{matching_military}"
    assert chosen.counterparty_player_id == 3


def test_solver_exact_ship_loss_uses_prior_fleet_military():
    loss = CandidateAction(
        id=f"{SHIP_LOSS_ACTION_PREFIX}warship:point:40",
        label="Ship loss (warship)",
        score_delta_2x=-40,
        warship_delta=-1,
        prior_warship_usage=1,
        upper_bound=1,
    )
    inverted = ShipBuildCombo(
        combo_id="combo_should_not_be_needed",
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=None,
        beam_count=2,
        launcher_count=0,
        labels=("Serpent",),
        score_delta_2x=40,
        warship_delta=1,
        upper_bound=0,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(loss,),
            ship_build_combos=(inverted,),
            prior_warship_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].action_id == loss.id
    assert result.solutions[0].ship_builds == ()


def test_solver_gift_vs_loss_are_distinct_and_gift_pins_counterparty():
    gift = CandidateAction(
        id=f"{GIFT_ACTION_PREFIX}warship:to:3:point:40",
        label="Gift warship to player 3",
        score_delta_2x=-40,
        warship_delta=-1,
        counterparty_player_id=3,
        prior_warship_usage=1,
        upper_bound=1,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(gift,),
            prior_warship_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    action = result.solutions[0].actions[0]
    assert action.action_id == gift.id
    assert action.counterparty_player_id == 3


def test_solver_trade_class_flip_is_exact():
    trade = CandidateAction(
        id=f"{TRADE_ACTION_PREFIX}with:3",
        label="Trade with player 3",
        score_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=1,
        counterparty_player_id=3,
        prior_warship_usage=1,
        upper_bound=1,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=1,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(trade,),
            prior_warship_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].action_id.startswith(TRADE_ACTION_PREFIX)
    assert result.solutions[0].actions[0].counterparty_player_id == 3


def test_solver_acquired_ship_is_not_a_build_combo():
    acquired = CandidateAction(
        id=f"{ACQUIRED_SHIP_ACTION_PREFIX}warship:from:3",
        label="Acquired warship from player 3",
        score_delta_2x=40,
        warship_delta=1,
        counterparty_player_id=3,
        upper_bound=1,
    )
    build = ShipBuildCombo(
        combo_id="combo_build",
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=None,
        beam_count=2,
        launcher_count=0,
        labels=("Serpent",),
        score_delta_2x=40,
        warship_delta=1,
        upper_bound=0,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=40,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(acquired,),
            ship_build_combos=(build,),
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].action_id.startswith(ACQUIRED_SHIP_ACTION_PREFIX)
    assert result.solutions[0].ship_builds == ()


def test_envelope_military_interval_is_exact():
    loss = CandidateAction(
        id=f"{SHIP_LOSS_ACTION_PREFIX}warship:envelope:20:80",
        label="Ship loss (warship, envelope)",
        score_delta_2x=0,
        warship_delta=-1,
        score_delta_2x_min=-80,
        score_delta_2x_max=-20,
        prior_warship_usage=1,
        upper_bound=1,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-50,
        warship_delta=-1,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(loss,),
            prior_warship_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].action_id == loss.id


def test_idle_dock_pp_equality_requires_ships_built_on_lattice():
    combo = ShipBuildCombo(
        combo_id="combo_one",
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=None,
        beam_count=2,
        launcher_count=0,
        labels=("Serpent",),
        score_delta_2x=40,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=2,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=40,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=2,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(),
            ship_build_combos=(combo,),
            enforce_idle_dock_pp_equality=True,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert result.solutions[0].ship_builds[0].count == 1


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
    assert any(action.id.startswith(ACQUIRED_SHIP_ACTION_PREFIX) for action in fragment.actions)
    assert fragment.reserved_incoming_warships == 1
    assert fragment.reserved_incoming_freighters == 0
    assert fragment.extra_warship_capacity == 0
    assert fragment.prior_warship_departure_cap == 0


def test_gift_and_loss_share_prior_fleet_departure_cap():
    gift = CandidateAction(
        id=f"{GIFT_ACTION_PREFIX}warship:to:3:point:40",
        label="Gift warship to player 3",
        score_delta_2x=-40,
        warship_delta=-1,
        counterparty_player_id=3,
        prior_warship_usage=1,
        upper_bound=1,
    )
    loss = CandidateAction(
        id=f"{SHIP_LOSS_ACTION_PREFIX}warship:point:40",
        label="Ship loss (warship)",
        score_delta_2x=-40,
        warship_delta=-1,
        prior_warship_usage=1,
        upper_bound=1,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(gift, loss),
            prior_warship_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    for solution in result.solutions:
        used = sum(action.count for action in solution.actions)
        assert used == 1
