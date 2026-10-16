"""Opt-in reproductions of slow ``admit_ship_torpedoes`` tiers.

Skipped unless ``SCORES_OUTLIER_REPRO=1``. How to run, and the storage root,
live in ``tests.scores_outlier_repro_harness``.
"""

from __future__ import annotations

from pathlib import Path

from tests.scores_outlier_repro_harness import (
    IDLE_MINIMUM_WALL_SECONDS,
    OUTLIER_TIER_ID,
    OUTLIER_TIER_INDEX,
    TURN3_PLAYER10_LOADED_WALL_SECONDS,
    TURN10_PLAYER4_ADMIT_COMBO_COUNT,
    TURN10_PLAYER4_ADMIT_LOADED_WALL_SECONDS,
    TURN15_PLAYER28_ADMIT_LOADED_WALL_SECONDS,
    format_outlier_report,
    open_outlier_repro_storage,
    reproduce_admit_ship_outlier,
)


def test_turn10_player46_admit_ship_torpedoes_reproduces_diagnostic_outlier(
    outlier_repro_storage: Path,
) -> None:
    with open_outlier_repro_storage(outlier_repro_storage) as storage:
        report = reproduce_admit_ship_outlier(storage)

    rendered = format_outlier_report(report)
    print(rendered)
    outlier = report.tier(OUTLIER_TIER_INDEX)
    assert outlier is not None, f"ladder stopped before tier 4\n{rendered}"
    assert outlier.tier_id == OUTLIER_TIER_ID, rendered
    assert outlier.stopped_reason == "max_solutions", rendered
    assert outlier.deterministic_time < 0.9, rendered
    assert 30_000 <= outlier.combo_count <= 50_000, rendered
    assert outlier.wall_seconds >= IDLE_MINIMUM_WALL_SECONDS, rendered
    tier4_solves = [sample for sample in report.solves if sample.tier.startswith("4:")]
    assert len(tier4_solves) >= 10, rendered


def test_turn3_player10_admit_ship_torpedoes_reproduces_early_outlier(
    outlier_repro_storage: Path,
) -> None:
    """Idle reproduction of the loaded 31.6 s admit-ship step on turn 3 player 10.

    The loaded duration was this step while 8 workers were busy. An idle run
    checks the partial-slot catalog, that the tier still searches, and that it
    stops by filling its solution cap.
    """
    with open_outlier_repro_storage(outlier_repro_storage) as storage:
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=3,
            player_id=10,
            through_tier_index=OUTLIER_TIER_INDEX,
        )

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN3_PLAYER10_LOADED_WALL_SECONDS,
    )
    print(rendered)
    outlier = report.tier(OUTLIER_TIER_INDEX)
    assert outlier is not None, f"ladder stopped before tier 4\n{rendered}"
    assert outlier.tier_id == OUTLIER_TIER_ID, rendered
    assert outlier.wall_seconds >= 0.5, rendered
    assert outlier.combo_count >= 10_000, rendered
    assert outlier.outcome == "continue", rendered
    assert outlier.stopped_reason == "max_solutions", rendered
    assert outlier.structural_hits == 5, rendered
    tier4_solves = [sample for sample in report.solves if sample.tier.startswith("4:")]
    assert len(tier4_solves) >= 5, rendered


def test_turn15_player28_admit_ship_torpedoes_reproduces_late6_outlier(
    outlier_repro_storage: Path,
) -> None:
    """Idle reproduction of the longest admit step in the late-6 tail.

    diagnostics_late6.json records turn 15 player 28 ``admit_ship_torpedoes``
    at 13.38 s of worker time. An idle run of the same step is 11.57 s, still
    spending the full 1.0 deterministic allowance on 57,780 ship combos.
    """
    with open_outlier_repro_storage(outlier_repro_storage) as storage:
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=15,
            player_id=28,
            through_tier_index=OUTLIER_TIER_INDEX,
        )

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN15_PLAYER28_ADMIT_LOADED_WALL_SECONDS,
    )
    print(rendered)
    admit = report.tier(OUTLIER_TIER_INDEX)
    assert admit is not None, f"ladder stopped before tier 4\n{rendered}"
    assert admit.tier_id == OUTLIER_TIER_ID, rendered
    assert admit.combo_count == 57_780, rendered
    assert admit.stopped_reason == "time_budget", rendered
    assert admit.wall_seconds >= 5.0, rendered
    assert admit.deterministic_time >= 0.9, rendered


def test_turn10_player4_admit_ship_torpedoes_reproduces_late8_median(
    outlier_repro_storage: Path,
) -> None:
    """Idle reproduction of a median late-8 admit_ship_torpedoes step.

    The persisted emission is 1.684s, time-limited, on 13,365 ship combos.
    The two central observations of the 530-step distribution are this row
    and turn 11 player 20 at 1.692s. Unfiltered, the idle step spent the
    deterministic budget in presolve. Reachable fittings leave a model that
    finishes the band and stops at the solution cap.
    """
    with open_outlier_repro_storage(outlier_repro_storage) as storage:
        report = reproduce_admit_ship_outlier(
            storage,
            turn_number=10,
            player_id=4,
            through_tier_index=OUTLIER_TIER_INDEX,
        )

    rendered = format_outlier_report(
        report,
        diagnostic_loaded_wall_seconds=TURN10_PLAYER4_ADMIT_LOADED_WALL_SECONDS,
    )
    print(rendered)
    admit = report.tier(OUTLIER_TIER_INDEX)
    assert admit is not None, f"ladder stopped before tier 4\n{rendered}"
    assert admit.tier_id == OUTLIER_TIER_ID, rendered
    assert admit.combo_count == TURN10_PLAYER4_ADMIT_COMBO_COUNT, rendered
    assert admit.stopped_reason == "max_solutions", rendered
    assert admit.structural_hits == 20, rendered
    assert admit.deterministic_time < 0.5, rendered
    assert admit.wall_seconds < 0.75, rendered
