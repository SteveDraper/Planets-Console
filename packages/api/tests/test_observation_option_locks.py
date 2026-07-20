"""Contract tests for shared fleet observation option-set locks."""

from __future__ import annotations

from api.analytics.fleet.observation_option_locks import (
    LockFilterEmptyPolicy,
    ObservationComponentLocks,
    observation_locks_from_option_set,
    observation_locks_from_record,
    option_set_compatible_with_locks,
    option_set_respecting_locks,
    option_sets_respecting_locks,
    resolve_option_sets_respecting_locks,
)
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
)


def test_locks_drop_mismatched_beam_count() -> None:
    locks = ObservationComponentLocks(hull_id=87, beam_id=10, beam_count=1)
    four_beam = FleetBuildOptionSet(hull_id=87, beam_id=10, beam_count=4)
    one_beam = FleetBuildOptionSet(hull_id=87, beam_id=10, beam_count=1)
    open_count = FleetBuildOptionSet(hull_id=87, beam_id=10, beam_count=None)

    assert not option_set_compatible_with_locks(four_beam, locks)
    assert option_set_respecting_locks(four_beam, locks) is None
    assert option_set_respecting_locks(one_beam, locks) == one_beam
    merged = option_set_respecting_locks(open_count, locks)
    assert merged is not None
    assert merged.beam_count == 1


def test_observation_locks_from_record_use_unanimous_counts() -> None:
    record = FleetShipRecord(
        record_id="r1",
        fields=FleetShipRecordFields(
            ship_id=FleetFieldKnown(1),
            hull=FleetFieldKnown(87),
            engine=FleetFieldUnknown(),
            beams=FleetFieldKnown(10),
            launchers=FleetFieldUnknown(),
        ),
        build_option_sets=[
            FleetBuildOptionSet(hull_id=87, beam_id=10, beam_count=1),
            FleetBuildOptionSet(hull_id=87, beam_id=10, beam_count=1),
        ],
    )
    locks = observation_locks_from_record(record)
    assert locks.hull_id == 87
    assert locks.beam_id == 10
    assert locks.beam_count == 1

    foreign = FleetBuildOptionSet(hull_id=105, beam_id=10, beam_count=1)
    same_hull_wrong_count = FleetBuildOptionSet(hull_id=87, beam_id=10, beam_count=4)
    kept = option_sets_respecting_locks(
        (foreign, same_hull_wrong_count, record.build_option_sets[0]),
        locks,
    )
    assert len(kept) == 1
    assert kept[0].beam_count == 1


def test_observation_locks_from_option_set_ignore_zeros() -> None:
    locks = observation_locks_from_option_set(
        FleetBuildOptionSet(hull_id=87, engine_id=0, beam_id=10, beam_count=1)
    )
    assert locks.engine_id is None
    assert locks.beam_id == 10
    assert locks.beam_count == 1


def test_refine_compatible_helper_drops_same_hull_wrong_beam_count() -> None:
    """Matching hull with wrong beam count must not survive observation locks."""
    from api.analytics.fleet.types import FleetEvidenceEvent

    record = FleetShipRecord(
        record_id="r-fog",
        fields=FleetShipRecordFields(
            ship_id=FleetFieldKnown(47),
            hull=FleetFieldKnown(87),
            beams=FleetFieldKnown(10),
        ),
        build_option_sets=[
            FleetBuildOptionSet(hull_id=87, beam_id=10, beam_count=1),
        ],
        events=[
            FleetEvidenceEvent(
                event_id="e1",
                kind="sighting",
                turn=6,
                source="turnInfo.ships",
                payload={},
            )
        ],
    )
    kept = resolve_option_sets_respecting_locks(
        (
            FleetBuildOptionSet(hull_id=87, beam_id=10, beam_count=4),
            FleetBuildOptionSet(hull_id=87, beam_id=10, beam_count=1),
            FleetBuildOptionSet(hull_id=87, beam_id=10, beam_count=None),
        ),
        observation_locks_from_record(record),
        on_empty=LockFilterEmptyPolicy.KEEP_PRIOR,
    )
    assert kept is not None
    assert len(kept) == 2
    assert all(option.beam_count == 1 for option in kept)


def test_resolve_empty_keep_prior_returns_none() -> None:
    locks = ObservationComponentLocks(hull_id=87)
    foreign = FleetBuildOptionSet(hull_id=105)
    assert (
        resolve_option_sets_respecting_locks(
            (foreign,),
            locks,
            on_empty=LockFilterEmptyPolicy.KEEP_PRIOR,
        )
        is None
    )


def test_resolve_empty_seed_returns_seed() -> None:
    locks = ObservationComponentLocks(hull_id=87)
    foreign = FleetBuildOptionSet(hull_id=105)
    seed = FleetBuildOptionSet(hull_id=87)
    assert resolve_option_sets_respecting_locks(
        (foreign,),
        locks,
        on_empty=LockFilterEmptyPolicy.SEED,
        seed=seed,
    ) == (seed,)
