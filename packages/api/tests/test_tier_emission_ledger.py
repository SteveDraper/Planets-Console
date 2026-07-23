"""Tests for compact per-tier emission ledger helpers."""

from __future__ import annotations

from api.analytics.military_score_inference.models import (
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
)
from api.analytics.military_score_inference.tier_emission_ledger import (
    compact_solution_emission,
    compact_tier_emissions_from_step_diagnostics,
    tier_emission_fields,
    tier_emissions_from_wire_complete,
)


def test_compact_solution_emission_keeps_objective_and_signature():
    solution = InferenceSolution(
        objective_value=-384,
        actions=(InferenceSolutionAction(action_id="torp_mk4", label="MK4 torp", count=20),),
        ship_builds=(
            InferenceSolutionShipBuild(
                combo_id="lcc",
                label="LCC",
                count=1,
                hull_id=7,
            ),
        ),
    )
    compact = compact_solution_emission(solution)
    assert compact == {
        "objectiveValue": -384,
        "actions": [{"actionId": "torp_mk4", "label": "MK4 torp", "count": 20}],
        "shipBuilds": [{"comboId": "lcc", "label": "LCC", "count": 1}],
    }


def test_tier_emission_fields_rank_newly_admitted_by_objective():
    weak = InferenceSolution(objective_value=-500, actions=(), ship_builds=())
    strong = InferenceSolution(objective_value=-100, actions=(), ship_builds=())
    fields = tier_emission_fields(
        duration_ms=12.3456,
        held_count_before=0,
        held_count_after=2,
        newly_admitted=[weak, strong],
        time_limited=False,
        last_status="exact",
    )
    assert fields["durationMs"] == 12.346
    assert fields["newlyAdmittedCount"] == 2
    assert [item["objectiveValue"] for item in fields["newlyAdmitted"]] == [-100, -500]


def test_compact_tier_emissions_strips_fat_constraint_fields():
    emissions = compact_tier_emissions_from_step_diagnostics(
        [
            {
                "policyStepId": "full_components",
                "policyStepIndex": 4,
                "durationMs": 100.0,
                "newlyAdmittedCount": 0,
                "newlyAdmitted": [],
                "constraintSnapshot": {"filters": ["x"]},
                "resolvedEligibleEngineIds": [1, 2, 3],
            }
        ]
    )
    assert emissions == [
        {
            "policyStepId": "full_components",
            "policyStepIndex": 4,
            "durationMs": 100.0,
            "newlyAdmittedCount": 0,
            "newlyAdmitted": [],
        }
    ]


def test_tier_emissions_from_wire_complete_prefers_first_class_field():
    wire = {
        "tierEmissions": [
            {
                "policyStepId": "early",
                "policyStepIndex": 0,
                "newlyAdmitted": [],
            }
        ],
        "diagnostics": {
            "policy_step_attempts": [
                {
                    "policyStepId": "other",
                    "policyStepIndex": 1,
                    "newlyAdmitted": [],
                }
            ]
        },
    }
    assert tier_emissions_from_wire_complete(wire)[0]["policyStepId"] == "early"


def test_tier_emissions_from_wire_complete_falls_back_to_policy_step_attempts():
    wire = {
        "diagnostics": {
            "policy_step_attempts": [
                {
                    "policyStepId": "admit_ship_torpedoes",
                    "policyStepIndex": 5,
                    "durationMs": 12.0,
                    "newlyAdmittedCount": 0,
                    "newlyAdmitted": [],
                    "constraintSnapshot": {"filters": []},
                }
            ]
        }
    }
    emissions = tier_emissions_from_wire_complete(wire)
    assert emissions is not None
    assert emissions[0]["policyStepId"] == "admit_ship_torpedoes"
    assert "constraintSnapshot" not in emissions[0]
