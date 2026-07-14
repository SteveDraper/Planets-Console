"""Tests for prior-fleet tech raise admission (#227)."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.max_tech import (
    max_tech_by_axis_from_fleet_records,
    max_tech_in_turn_catalog,
)
from api.analytics.fleet.types import (
    FleetFieldKnown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.component_eligibility import (
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.prior_fleet_tech_raise import (
    resolve_prior_fleet_tech_raise_plan,
)
from api.analytics.military_score_inference.tier_policy import (
    ComponentFilter,
    InferenceCatalogFilters,
    InferenceTierPolicyStep,
    resolve_tier_policies,
)
from api.models.components import Hull

from tests.fixtures.military_score_inference import _observation


def test_policy_loader_parses_raise_max_tech_from_prior_fleet():
    steps = resolve_tier_policies()
    early = steps[0]
    assert early.filters.hulls.raise_max_tech_from_prior_fleet is True
    assert early.filters.beams.raise_max_tech_from_prior_fleet is True
    assert early.filters.launchers.raise_max_tech_from_prior_fleet is True
    assert early.filters.engines.raise_max_tech_from_prior_fleet is False
    assert early.filters.hulls.to_snapshot()["raiseMaxTechFromPriorFleet"] is True


def test_policy_loader_rejects_raise_flag_with_all():
    from api.analytics.military_score_inference.tier_policy import parse_tier_policy_steps

    document = {
        "steps": [
            {
                "id": "bad",
                "filters": {
                    "hulls": {"all": True, "raiseMaxTechFromPriorFleet": True},
                    "engines": {"all": True},
                    "beams": {"all": True},
                    "launchers": {"all": True},
                },
                "alpha": 0,
            }
        ]
    }
    try:
        parse_tier_policy_steps(document)
    except ValueError as exc:
        assert "raiseMaxTechFromPriorFleet requires techLevels" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def _hull_with_tech(base: Hull, *, hull_id: int, tech_level: int, name: str) -> Hull:
    return replace(
        base,
        id=hull_id,
        name=name,
        techlevel=tech_level,
    )


def _turn_with_tech7_hull(sample_turn):
    template = sample_turn.hulls[0]
    tech7 = _hull_with_tech(template, hull_id=9007, tech_level=7, name="Tech7 Test Hull")
    # Ensure player can build it: extend racehulls if present.
    racehulls = list(getattr(sample_turn, "racehulls", []) or [])
    if racehulls and 9007 not in racehulls:
        # racehulls may be per-race structure; fall back to appending hull only.
        pass
    return replace(sample_turn, hulls=list(sample_turn.hulls) + [tech7])


def test_max_tech_by_axis_from_fleet_records_hull_tech_7(sample_turn):
    turn = _turn_with_tech7_hull(sample_turn)
    records = [
        FleetShipRecord(
            record_id="resolute",
            disposition="active",
            fields=FleetShipRecordFields(hull=FleetFieldKnown(9007)),
        )
    ]
    max_tech = max_tech_by_axis_from_fleet_records(records, turn)
    assert max_tech["hulls"] == 7
    assert "beams" not in max_tech


def test_pending_fleet_max_tech_none_does_not_raise(sample_turn):
    early = resolve_tier_policies()[0]
    plan = resolve_prior_fleet_tech_raise_plan(
        early,
        turn=sample_turn,
        prior_fleet_max_tech_by_axis=None,
    )
    assert plan is not None
    assert plan.skipped is False
    assert plan.policy_step.filters.hulls.tech_levels == early.filters.hulls.tech_levels


def test_raise_hull_band_to_include_tech_7(sample_turn):
    turn = _turn_with_tech7_hull(sample_turn)
    # Keep beams/launchers catalog max above early YAML constants so only hull
    # observation is in play (otherwise constant>=catalog saturation skips the step).
    beam_template = turn.beams[0]
    torp_template = turn.torpedos[0]
    turn = replace(
        turn,
        beams=list(turn.beams)
        + [replace(beam_template, id=9101, name="Tech10 Beam", techlevel=10)],
        torpedos=list(turn.torpedos)
        + [replace(torp_template, id=9102, name="Tech10 Torp", techlevel=10)],
    )
    racehulls = list(turn.racehulls)
    if racehulls and 9007 not in racehulls:
        turn = replace(turn, racehulls=racehulls + [9007])
    observation = _observation(warship_delta=1, freighter_delta=1, starbases_owned=5)
    early = resolve_tier_policies()[0]

    unraised = turn_catalog_context_for_policy_step(turn, observation.player_id, early)
    assert 9007 not in unraised.buildable_hull_ids

    plan = resolve_prior_fleet_tech_raise_plan(
        early,
        turn=turn,
        prior_fleet_max_tech_by_axis={"hulls": 7},
    )
    assert plan is not None
    assert plan.skipped is False
    assert max(plan.policy_step.filters.hulls.tech_levels) == 7
    raised = turn_catalog_context_for_policy_step(turn, observation.player_id, plan.policy_step)
    assert 9007 in raised.buildable_hull_ids
    hull_diag = next(row for row in plan.axes if row["axis"] == "hulls")
    assert hull_diag["configuredMaxTech"] == 6
    assert hull_diag["observedMaxTech"] == 7
    assert hull_diag["effectiveMaxTech"] == 7


def test_skip_when_all_flagged_axes_saturate_catalog(sample_turn):
    early = resolve_tier_policies()[0]
    observed = {
        "hulls": max_tech_in_turn_catalog(sample_turn, "hulls"),
        "beams": max_tech_in_turn_catalog(sample_turn, "beams"),
        "launchers": max_tech_in_turn_catalog(sample_turn, "launchers"),
    }
    plan = resolve_prior_fleet_tech_raise_plan(
        early,
        turn=sample_turn,
        prior_fleet_max_tech_by_axis=observed,
    )
    assert plan is not None
    assert plan.skipped is True
    assert plan.to_diagnostics()["priorFleetTechRaise"]["skippedDueToPriorFleetTechSaturation"]


def test_widen_hulls_does_not_skip_when_beams_launchers_saturate(sample_turn):
    widen_hulls = next(step for step in resolve_tier_policies() if step.id == "widen_hulls")
    observed = {
        "beams": max_tech_in_turn_catalog(sample_turn, "beams"),
        "launchers": max_tech_in_turn_catalog(sample_turn, "launchers"),
    }
    plan = resolve_prior_fleet_tech_raise_plan(
        widen_hulls,
        turn=sample_turn,
        prior_fleet_max_tech_by_axis=observed,
    )
    assert plan is not None
    assert plan.skipped is False
    assert plan.policy_step.filters.hulls.all is True


def test_consecutive_raised_steps_stay_monotonic(sample_turn):
    step_a = InferenceTierPolicyStep(
        id="a",
        filters=InferenceCatalogFilters(
            hulls=ComponentFilter(
                tech_levels=(1, 2, 3, 4, 5, 6),
                raise_max_tech_from_prior_fleet=True,
            ),
            engines=ComponentFilter(all=True),
            beams=ComponentFilter(
                tech_levels=(1, 2, 3, 4, 5),
                raise_max_tech_from_prior_fleet=True,
            ),
            launchers=ComponentFilter(
                tech_levels=(1, 2, 3, 4, 5),
                raise_max_tech_from_prior_fleet=True,
            ),
        ),
        beam_slot_counts="none",
        launcher_slot_counts="none",
        aggregate_allowlist={},
        alpha=50,
    )
    step_b = replace(
        step_a,
        id="b",
        filters=replace(
            step_a.filters,
            launchers=ComponentFilter(
                tech_levels=(1, 2, 3, 4, 5, 6, 7, 8),
                raise_max_tech_from_prior_fleet=True,
            ),
        ),
    )
    observed = {"hulls": 7, "beams": 5, "launchers": 6}
    plan_a = resolve_prior_fleet_tech_raise_plan(
        step_a,
        turn=sample_turn,
        prior_fleet_max_tech_by_axis=observed,
    )
    plan_b = resolve_prior_fleet_tech_raise_plan(
        step_b,
        turn=sample_turn,
        prior_fleet_max_tech_by_axis=observed,
    )
    assert plan_a is not None and plan_b is not None
    assert (
        plan_a.policy_step.filters.hulls.tech_levels == plan_b.policy_step.filters.hulls.tech_levels
    )
    assert max(plan_a.policy_step.filters.hulls.tech_levels) == 7
    assert max(plan_a.policy_step.filters.launchers.tech_levels) == 6
    assert max(plan_b.policy_step.filters.launchers.tech_levels) == 8
    assert set(plan_a.policy_step.filters.launchers.tech_levels) <= set(
        plan_b.policy_step.filters.launchers.tech_levels
    )
