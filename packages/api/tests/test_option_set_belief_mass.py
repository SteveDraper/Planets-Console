"""Tests for option-set softmax masses and launcher belief mass (#253)."""

from __future__ import annotations

import math
from dataclasses import replace

from api.analytics.fleet.belief_set_components import component_ids_for_axis_from_records
from api.analytics.fleet.max_tech import max_tech_by_axis_from_fleet_records
from api.analytics.fleet.option_set_mass import (
    DEFAULT_OPTION_SET_MASS_THRESHOLD,
    launcher_belief_mass_by_torp_id_from_records,
    option_set_softmax_probabilities,
)
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.fleet_torp_overlay import (
    FleetLauncherBeliefSet,
    FleetTorpOverlay,
    apply_torp_misalignment_penalties_to_catalog,
    build_fleet_torp_overlay_diagnostics,
    effective_torp_misalignment_log_penalty,
    overlay_from_fleet_records,
    torp_load_action_id,
)
from api.concepts.inference_probability_scale import (
    INFERENCE_PROBABILITY_WEIGHT_SCALE,
)
from api.analytics.military_score_inference.tier_policy import (
    FleetInferenceTuning,
    resolve_fleet_inference_tuning,
    resolve_tier_policies,
)

from tests.fixtures.military_score_inference_prior_weights import (
    probability_buckets_for_test_action,
)


def test_softmax_uses_rank_weight_over_scale():
    option_sets = (
        FleetBuildOptionSet(label="best", solution_rank_weight=200, torp_id=None),
        FleetBuildOptionSet(label="weak", solution_rank_weight=0, torp_id=8),
    )
    probs = option_set_softmax_probabilities(option_sets)
    expected_scores = (200 / INFERENCE_PROBABILITY_WEIGHT_SCALE, 0.0)
    max_score = max(expected_scores)
    exps = [math.exp(score - max_score) for score in expected_scores]
    total = sum(exps)
    assert probs[0] == exps[0] / total
    assert probs[1] == exps[1] / total
    assert probs[0] > 0.85
    assert probs[1] < 0.15


def test_soft_mass_includes_beam_only_sets_in_softmax():
    record = FleetShipRecord(
        record_id="accel-placeholder",
        disposition="active",
        fields=FleetShipRecordFields(launchers=FleetFieldUnknown()),
        build_option_sets=[
            FleetBuildOptionSet(
                label="Brynhild",
                solution_rank_weight=200,
                hull_id=7,
                beam_id=1,
                torp_id=None,
            ),
            FleetBuildOptionSet(
                label="Mark 8 alt",
                solution_rank_weight=20,
                hull_id=7,
                torp_id=10,
            ),
            FleetBuildOptionSet(
                label="Gamma alt",
                solution_rank_weight=10,
                hull_id=7,
                torp_id=8,
            ),
        ],
    )
    masses = launcher_belief_mass_by_torp_id_from_records([record])
    assert 10 in masses
    assert 8 in masses
    assert masses[10] < 0.2
    assert masses[8] < 0.15
    # Beam-only best set starves tubes: neither approaches half mass.
    assert masses[10] + masses[8] < 0.35


def test_hard_known_launchers_mass_is_one():
    record = FleetShipRecord(
        record_id="sighted",
        disposition="active",
        fields=FleetShipRecordFields(launchers=FleetFieldKnown(4)),
        build_option_sets=[
            FleetBuildOptionSet(torp_id=4, solution_rank_weight=100),
            FleetBuildOptionSet(torp_id=8, solution_rank_weight=100),
        ],
    )
    masses = launcher_belief_mass_by_torp_id_from_records([record])
    assert masses == {4: 1.0}


def test_player_mass_is_max_across_rows():
    soft_row = FleetShipRecord(
        record_id="soft",
        disposition="active",
        fields=FleetShipRecordFields(launchers=FleetFieldUnknown()),
        build_option_sets=[
            FleetBuildOptionSet(torp_id=8, solution_rank_weight=0),
            FleetBuildOptionSet(torp_id=None, solution_rank_weight=200),
        ],
    )
    hard_row = FleetShipRecord(
        record_id="hard",
        disposition="active",
        fields=FleetShipRecordFields(launchers=FleetFieldKnown(8)),
    )
    masses = launcher_belief_mass_by_torp_id_from_records([soft_row, hard_row])
    assert masses[8] == 1.0


def test_effective_penalty_round_p_times_one_minus_mass():
    overlay = FleetTorpOverlay(
        belief_set=FleetLauncherBeliefSet(frozenset({4, 8})),
        launcher_belief_mass_by_torp_id={4: 1.0, 8: 0.1},
    )
    tuning = FleetInferenceTuning(torp_misalignment_log_penalty=200)
    assert effective_torp_misalignment_log_penalty(torp_id=4, overlay=overlay, tuning=tuning) == 0
    assert effective_torp_misalignment_log_penalty(torp_id=8, overlay=overlay, tuning=tuning) == 180
    assert effective_torp_misalignment_log_penalty(torp_id=1, overlay=overlay, tuning=tuning) == 200


def test_max_tech_contributors_respect_option_set_mass_threshold(sample_turn):
    template = sample_turn.hulls[0]
    high_tech = replace(
        template,
        id=9100,
        name="High Tech Alt",
        techlevel=8,
    )
    turn = replace(sample_turn, hulls=list(sample_turn.hulls) + [high_tech])
    known_hull_id = template.id
    record = FleetShipRecord(
        record_id="placeholder",
        disposition="active",
        fields=FleetShipRecordFields(hull=FleetFieldKnown(known_hull_id)),
        build_option_sets=[
            FleetBuildOptionSet(
                label="best known-tech",
                solution_rank_weight=200,
                hull_id=known_hull_id,
            ),
            FleetBuildOptionSet(
                label="weak high-tech",
                solution_rank_weight=10,
                hull_id=9100,
            ),
        ],
    )
    threshold = DEFAULT_OPTION_SET_MASS_THRESHOLD
    ids = component_ids_for_axis_from_records(
        [record],
        "hull",
        option_set_mass_threshold=threshold,
    )
    assert known_hull_id in ids
    assert 9100 not in ids

    max_tech = max_tech_by_axis_from_fleet_records(
        [record],
        turn,
        option_set_mass_threshold=threshold,
    )
    assert max_tech["hulls"] == template.techlevel


def test_max_tech_known_counts_even_when_no_set_clears_threshold(sample_turn):
    known_hull_id = sample_turn.hulls[0].id
    record = FleetShipRecord(
        record_id="known-only",
        disposition="active",
        fields=FleetShipRecordFields(hull=FleetFieldKnown(known_hull_id)),
        build_option_sets=[
            FleetBuildOptionSet(
                label="weak alt",
                solution_rank_weight=0,
                hull_id=known_hull_id,
            ),
            FleetBuildOptionSet(
                label="other weak",
                solution_rank_weight=0,
                hull_id=known_hull_id,
            ),
        ],
    )
    # Equal soft weights (0.5 each) fail a threshold of 1.0; known still contributes.
    ids = component_ids_for_axis_from_records(
        [record],
        "hull",
        option_set_mass_threshold=1.0,
    )
    assert ids == {known_hull_id}


def test_option_set_mass_threshold_in_tier_policy_tuning():
    tuning = resolve_fleet_inference_tuning()
    assert tuning.option_set_mass_threshold == 0.25


def test_brynhild_style_weak_tubes_keep_admission_but_near_full_misalignment():
    """Accel-start: Brynhild-best + weaker tube alts on one placeholder."""
    record = FleetShipRecord(
        record_id="warship-placeholder",
        disposition="active",
        fields=FleetShipRecordFields(launchers=FleetFieldUnknown()),
        build_option_sets=[
            FleetBuildOptionSet(
                label="Brynhild best",
                solution_rank_weight=200,
                hull_id=7,
                beam_id=5,
                torp_id=None,
            ),
            FleetBuildOptionSet(
                label="Mark 8 tube alt",
                solution_rank_weight=25,
                hull_id=7,
                torp_id=10,
            ),
            FleetBuildOptionSet(
                label="Gamma tube alt",
                solution_rank_weight=15,
                hull_id=7,
                torp_id=8,
            ),
        ],
    )
    overlay = overlay_from_fleet_records([record])
    assert overlay.belief_set.torp_ids == frozenset({8, 10})

    tuning = FleetInferenceTuning(torp_misalignment_log_penalty=200)
    mark8_penalty = effective_torp_misalignment_log_penalty(
        torp_id=10, overlay=overlay, tuning=tuning
    )
    gamma_penalty = effective_torp_misalignment_log_penalty(
        torp_id=8, overlay=overlay, tuning=tuning
    )
    # Near-full misalignment so ship builds can outrank torp padding.
    assert mark8_penalty >= 150
    assert gamma_penalty >= 150

    sample_weights = (-22, -181, -347, -531)
    buckets = {
        torp_load_action_id(10): probability_buckets_for_test_action(
            torp_load_action_id(10),
            marginal_weights=sample_weights,
        ),
        torp_load_action_id(8): probability_buckets_for_test_action(
            torp_load_action_id(8),
            marginal_weights=sample_weights,
        ),
    }
    adjusted = apply_torp_misalignment_penalties_to_catalog(buckets, overlay=overlay, tuning=tuning)
    assert (
        adjusted[torp_load_action_id(10)][1].marginal_weight
        == buckets[torp_load_action_id(10)][1].marginal_weight - mark8_penalty
    )

    escape_step = next(step for step in resolve_tier_policies() if step.id == "torp_escape_tier")
    diagnostics = build_fleet_torp_overlay_diagnostics(
        overlay=overlay,
        tuning=tuning,
        policy_step=escape_step,
        admitted_torp_ids=frozenset({8, 10}),
    )
    payload = diagnostics.to_payload()
    assert payload["beliefSetTorpIds"] == [8, 10]
    assert "10" in payload["launcherBeliefMassByTorpId"]
    assert "8" in payload["launcherBeliefMassByTorpId"]
    assert payload["effectiveTorpMisalignmentLogPenaltyByTorpId"]["10"] == mark8_penalty
    assert payload["effectiveTorpMisalignmentLogPenaltyByTorpId"]["8"] == gamma_penalty
