"""Frozen GIL overlap admission: exclusive vs native_release dequeue."""

from __future__ import annotations

from api.analytics.fleet.compute_orchestration import (
    FLEET_COMPUTE_PROFILE,
    FLEET_OBSERVATION_LEG,
)
from api.analytics.scores.compute_orchestration import (
    SCORES_COMPUTE_PROFILE,
    SCORES_TIER_SOLVE,
)
from api.compute.gil_overlap import (
    exclusive_step_may_run,
    native_release_step_may_run,
    pool_item_may_run_under_gil_overlap,
)
from api.compute.profile import ComputeStepSpec


def test_exclusive_waits_while_native_release_is_in_flight() -> None:
    assert exclusive_step_may_run(native_release_in_flight=0) is True
    assert exclusive_step_may_run(native_release_in_flight=1) is False


def test_native_release_waits_while_exclusive_is_queued_or_in_flight() -> None:
    assert native_release_step_may_run(exclusive_queued=False, exclusive_in_flight=0) is True
    assert native_release_step_may_run(exclusive_queued=True, exclusive_in_flight=0) is False
    assert native_release_step_may_run(exclusive_queued=False, exclusive_in_flight=1) is False


def test_disabled_overlap_admits_every_class() -> None:
    assert (
        pool_item_may_run_under_gil_overlap(
            "exclusive",
            enabled=False,
            native_release_in_flight=3,
            exclusive_queued=True,
            exclusive_in_flight=1,
        )
        is True
    )
    assert (
        pool_item_may_run_under_gil_overlap(
            "native_release",
            enabled=False,
            native_release_in_flight=0,
            exclusive_queued=True,
            exclusive_in_flight=0,
        )
        is True
    )


def test_default_gil_overlap_is_unconstrained() -> None:
    spec = ComputeStepSpec(step_kind="materialize", backend="thread")
    assert spec.gil_overlap == "default"
    assert (
        pool_item_may_run_under_gil_overlap(
            spec.gil_overlap,
            enabled=True,
            native_release_in_flight=4,
            exclusive_queued=True,
            exclusive_in_flight=1,
        )
        is True
    )


def test_fleet_observation_declares_exclusive_overlap() -> None:
    step = next(
        spec for spec in FLEET_COMPUTE_PROFILE.steps if spec.step_kind == FLEET_OBSERVATION_LEG
    )
    assert step.gil_overlap == "exclusive"


def test_scores_tier_solve_declares_native_release_overlap() -> None:
    step = next(
        spec for spec in SCORES_COMPUTE_PROFILE.steps if spec.step_kind == SCORES_TIER_SOLVE
    )
    assert step.gil_overlap == "native_release"
