"""Row-scoped reuse of scores catalog combos, priors, and transfer fragments."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.military_score_inference.actions import build_action_catalog_from_turn
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.catalog_reuse import (
    ScoresCatalogReuse,
    catalog_reuse_totals,
    reset_catalog_reuse_totals,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.solver import STATUS_NO_EXACT_SOLUTION
from api.analytics.military_score_inference.tier_policy import (
    ComponentFilter,
    InferenceCatalogFilters,
    InferenceTierPolicyStep,
    SlotCountMode,
)
from api.models.game import TurnInfo

_ARMED_HULL_ID = 9001
_SECOND_HULL_ID = 9002


def _turn_with_buildable_hulls(sample_turn: TurnInfo) -> TurnInfo:
    """Add two viewpoint-buildable hulls, one with partial slot counts to grow."""
    template = next(hull for hull in sample_turn.hulls if hull.id == 15)
    armed = replace(
        template,
        id=_ARMED_HULL_ID,
        name="Armed Test Hull",
        beams=4,
        launchers=2,
        techlevel=1,
    )
    second = replace(
        template,
        id=_SECOND_HULL_ID,
        name="Second Test Hull",
        beams=2,
        launchers=0,
        techlevel=1,
    )
    return replace(
        sample_turn,
        hulls=[*sample_turn.hulls, armed, second],
        racehulls=[*sample_turn.racehulls, _ARMED_HULL_ID, _SECOND_HULL_ID],
    )


def _filters(*, hull_ids: tuple[int, ...]) -> InferenceCatalogFilters:
    return InferenceCatalogFilters(
        hulls=ComponentFilter(all=True, component_ids=hull_ids),
        engines=ComponentFilter(all=True),
        beams=ComponentFilter(all=True),
        launchers=ComponentFilter(all=True),
    )


def _step(
    step_id: str,
    filters: InferenceCatalogFilters,
    *,
    beam_slot_counts: SlotCountMode = "none",
    launcher_slot_counts: SlotCountMode = "none",
    allowlist: dict[str, int] | None = None,
) -> InferenceTierPolicyStep:
    return InferenceTierPolicyStep(
        id=step_id,
        filters=filters,
        beam_slot_counts=beam_slot_counts,
        launcher_slot_counts=launcher_slot_counts,
        aggregate_allowlist={} if allowlist is None else allowlist,
        alpha=0,
    )


def _observation_for(turn: TurnInfo):
    score = next(row for row in turn.scores if row.ownerid == turn.player.id)
    return build_inference_observation(score, turn)


def _build(observation, turn, step, *, reuse, policy_step_index: int = 0):
    return build_action_catalog_from_turn(
        observation,
        turn,
        policy_step=step,
        policy_step_index=policy_step_index,
        catalog_reuse=reuse,
    )


def test_same_eligibility_reuses_combo_tuple_and_row_tables(sample_turn) -> None:
    turn = _turn_with_buildable_hulls(sample_turn)
    filters = _filters(hull_ids=(_ARMED_HULL_ID,))
    observation = _observation_for(turn)
    reuse = ScoresCatalogReuse()
    first = _build(observation, turn, _step("early", filters), reuse=reuse)
    second = _build(
        observation,
        turn,
        _step(
            "later",
            filters,
            allowlist={"planet_defense_posts_added_total": 4},
        ),
        reuse=reuse,
        policy_step_index=1,
    )

    assert len(first.ship_build_combos) > 0
    assert second.ship_build_combos is first.ship_build_combos
    assert second.prior_weights_diagnostics is first.prior_weights_diagnostics
    assert second.prior_departure_group_caps is first.prior_departure_group_caps
    assert second.policy_step_id == "later"
    assert second.policy_step_index == 1
    assert first.policy_step_id == "early"


def test_wider_hull_set_matches_fresh_build(sample_turn) -> None:
    turn = _turn_with_buildable_hulls(sample_turn)
    observation = _observation_for(turn)
    reuse = ScoresCatalogReuse()
    narrow = _build(
        observation,
        turn,
        _step("one_hull", _filters(hull_ids=(_ARMED_HULL_ID,))),
        reuse=reuse,
    )
    wide_step = _step(
        "two_hulls",
        _filters(hull_ids=(_ARMED_HULL_ID, _SECOND_HULL_ID)),
    )
    widened = _build(observation, turn, wide_step, reuse=reuse)
    fresh = _build(observation, turn, wide_step, reuse=None)

    assert [combo.combo_id for combo in widened.ship_build_combos] == [
        combo.combo_id for combo in fresh.ship_build_combos
    ]
    assert widened.ship_build_combos == fresh.ship_build_combos
    assert widened.ship_build_combos is not narrow.ship_build_combos
    # Hull priors are normalized over the eligible hull set, so a wider set
    # changes weights and those combos are new objects. Slot-mode growth does
    # not, and that path reuses the objects.
    narrow_by_id = {combo.combo_id: combo for combo in narrow.ship_build_combos}
    for combo in widened.ship_build_combos:
        previous = narrow_by_id.get(combo.combo_id)
        if previous is None:
            continue
        if previous == combo:
            assert combo is previous
        else:
            assert combo is not previous


def test_partial_slots_reuse_none_mode_combos(sample_turn) -> None:
    turn = _turn_with_buildable_hulls(sample_turn)
    filters = _filters(hull_ids=(_ARMED_HULL_ID,))
    observation = _observation_for(turn)
    reuse = ScoresCatalogReuse()
    none_mode = _build(
        observation,
        turn,
        _step("slots_none", filters),
        reuse=reuse,
    )
    partial_step = _step(
        "slots_partial",
        filters,
        beam_slot_counts="partial",
        launcher_slot_counts="partial",
    )
    partial = _build(observation, turn, partial_step, reuse=reuse)
    fresh = _build(observation, turn, partial_step, reuse=None)

    assert partial.ship_build_combos == fresh.ship_build_combos
    assert len(partial.ship_build_combos) > len(none_mode.ship_build_combos)
    none_by_id = {combo.combo_id: combo for combo in none_mode.ship_build_combos}
    shared = [combo for combo in partial.ship_build_combos if combo.combo_id in none_by_id]
    assert shared
    assert all(combo is none_by_id[combo.combo_id] for combo in shared)


def test_narrow_after_wide_matches_fresh_build(sample_turn) -> None:
    turn = _turn_with_buildable_hulls(sample_turn)
    observation = _observation_for(turn)
    reuse = ScoresCatalogReuse()
    wide = _build(
        observation,
        turn,
        _step(
            "two_hulls",
            _filters(hull_ids=(_ARMED_HULL_ID, _SECOND_HULL_ID)),
        ),
        reuse=reuse,
    )
    narrow_step = _step("one_hull", _filters(hull_ids=(_ARMED_HULL_ID,)))
    narrowed = _build(observation, turn, narrow_step, reuse=reuse)
    fresh = _build(observation, turn, narrow_step, reuse=None)

    assert narrowed.ship_build_combos == fresh.ship_build_combos
    wide_object_ids = {id(combo) for combo in wide.ship_build_combos}
    assert all(id(combo) not in wide_object_ids for combo in narrowed.ship_build_combos)


def test_changed_observation_bounds_do_not_reuse_combos(sample_turn) -> None:
    reset_catalog_reuse_totals()
    turn = _turn_with_buildable_hulls(sample_turn)
    filters = _filters(hull_ids=(_ARMED_HULL_ID,))
    observation = _observation_for(turn)
    shifted = replace(observation, warship_delta=observation.warship_delta + 3)
    step = _step("same", filters)
    reuse = ScoresCatalogReuse()
    first = _build(observation, turn, step, reuse=reuse)
    second = _build(shifted, turn, step, reuse=reuse)
    fresh = _build(shifted, turn, step, reuse=None)
    totals = catalog_reuse_totals()

    assert second.ship_build_combos == fresh.ship_build_combos
    first_object_ids = {id(combo) for combo in first.ship_build_combos}
    assert all(id(combo) not in first_object_ids for combo in second.ship_build_combos)
    assert totals.transfer_builds == 2
    assert totals.transfer_hits == 0


def test_catalog_reuse_totals_distinguish_rebuild_from_reuse(sample_turn) -> None:
    reset_catalog_reuse_totals()
    turn = _turn_with_buildable_hulls(sample_turn)
    observation = _observation_for(turn)
    filters = _filters(hull_ids=(_ARMED_HULL_ID,))
    reuse = ScoresCatalogReuse()
    first = _build(observation, turn, _step("early", filters), reuse=reuse)
    after_initial = catalog_reuse_totals()
    assert after_initial.combo_initial_builds == 1
    assert after_initial.combo_exact_hits == 0
    assert after_initial.combo_extend_calls == 0
    assert after_initial.combo_rebuild_calls == 0
    assert after_initial.combo_objects_allocated == len(first.ship_build_combos)
    assert after_initial.combo_objects_reused == 0
    assert after_initial.prior_builds == 1
    assert after_initial.prior_hits == 0
    assert after_initial.transfer_builds == 1
    assert after_initial.transfer_hits == 0

    second = _build(
        observation,
        turn,
        _step("later", filters, allowlist={"planet_defense_posts_added_total": 4}),
        reuse=reuse,
        policy_step_index=1,
    )
    after_exact = catalog_reuse_totals()
    assert second.ship_build_combos is first.ship_build_combos
    assert after_exact.combo_exact_hits == 1
    assert after_exact.combo_objects_reused == len(second.ship_build_combos)
    assert after_exact.combo_objects_allocated == after_initial.combo_objects_allocated
    assert after_exact.prior_hits == 1
    assert after_exact.transfer_hits == 1

    partial = _build(
        observation,
        turn,
        _step(
            "slots_partial",
            filters,
            beam_slot_counts="partial",
            launcher_slot_counts="partial",
        ),
        reuse=reuse,
    )
    shared = [
        combo
        for combo in partial.ship_build_combos
        if any(combo is kept for kept in first.ship_build_combos)
    ]
    after_extend = catalog_reuse_totals()
    assert after_extend.combo_extend_calls == 1
    assert after_extend.combo_rebuild_calls == 0
    assert shared
    assert after_extend.combo_objects_reused == after_exact.combo_objects_reused + len(shared)
    assert after_extend.combo_objects_allocated == (
        after_exact.combo_objects_allocated + len(partial.ship_build_combos) - len(shared)
    )

    shrunk = ScoresCatalogReuse()
    wide = _build(
        observation,
        turn,
        _step("two_hulls", _filters(hull_ids=(_ARMED_HULL_ID, _SECOND_HULL_ID))),
        reuse=shrunk,
    )
    before_narrow = catalog_reuse_totals()
    narrowed = _build(
        observation,
        turn,
        _step("one_hull", filters),
        reuse=shrunk,
    )
    after_narrow = catalog_reuse_totals()
    assert wide.ship_build_combos
    assert after_narrow.combo_initial_builds == before_narrow.combo_initial_builds
    assert after_narrow.combo_rebuild_calls == before_narrow.combo_rebuild_calls + 1
    assert after_narrow.combo_objects_reused == before_narrow.combo_objects_reused
    assert after_narrow.combo_objects_allocated == (
        before_narrow.combo_objects_allocated + len(narrowed.ship_build_combos)
    )


def test_ladder_rungs_share_the_row_combo_tuple(sample_turn, monkeypatch) -> None:
    from api.analytics.military_score_inference.actions import build_inference_problem

    def fake_solve_catalog(
        observation,
        catalog,
        *,
        race_id=None,
        max_solutions,
        solve_clip,
        military_score_window=None,
        fixed_combo_counts=None,
        combo_count_neighborhood=0,
        cancel_token=None,
        on_solution=None,
        seed_no_good_solutions=(),
        **_budget,
    ):
        del race_id, max_solutions, solve_clip, military_score_window
        del fixed_combo_counts, combo_count_neighborhood, cancel_token, on_solution
        del seed_no_good_solutions
        problem = build_inference_problem(observation, catalog, max_solutions=1)
        return (
            InferenceResult(
                status=STATUS_NO_EXACT_SOLUTION,
                solutions=(),
                diagnostics={},
            ),
            problem,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_seed_progression",
        lambda *args, **kwargs: (None, None),
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_catalog",
        fake_solve_catalog,
    )

    turn = _turn_with_buildable_hulls(sample_turn)
    filters = _filters(hull_ids=(_ARMED_HULL_ID,))
    state = PolicyLadderState(
        policy_steps=(
            _step("early", filters),
            _step("later", filters, allowlist={"planet_defense_posts_added_total": 4}),
        )
    )
    observation = _observation_for(turn)
    run_policy_ladder_tier_step(state, observation, turn, time_limit_seconds=None)
    first = state.catalog
    assert first is not None
    run_policy_ladder_tier_step(state, observation, turn, time_limit_seconds=None)
    assert state.catalog is not None
    assert state.catalog is not first
    assert state.catalog.ship_build_combos is first.ship_build_combos
    assert len(first.ship_build_combos) > 0
    assert state.policy_steps_attempted == ["early", "later"]
