"""Unit tests for off-mode persist decisions, prior-fleet relation, and job wires."""

from __future__ import annotations

from dataclasses import replace

import pytest
from api.analytics.fleet.injected_services import FleetComputeServices
from api.analytics.fleet.off_mode_persist import observation_merge_generation
from api.analytics.fleet.types import (
    STAMP_CURRENT_EVIDENCE_MARK,
    FleetAcquisitionLedger,
    FleetEvidenceMark,
    PersistedFleetLedger,
)
from api.analytics.off_mode import (
    MarkPersist,
    PriorFleetRelation,
    is_backfill_off_open_turn,
    off_mode_mark_persist,
    off_mode_merge_generation,
    off_mode_prior_relation,
)
from api.analytics.off_mode_wire import parse_off_mode_wire, stamp_submission_open
from api.compute.scope import WILDCARD, ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.errors import ValidationError


def test_mark_persist_and_merge_generation_agree_on_the_open_turn_rule():
    """Scoreboard classification and the fleet merge generation for the same inputs."""
    present = FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)
    absent = FleetEvidenceMark()
    cases = (
        (
            "open turn stamps and keeps the stored generation",
            False,
            40,
            False,
            40,
            present,
            1,
            MarkPersist.STAMP,
            1,
        ),
        (
            "open turn with no file keeps generation 0",
            False,
            40,
            False,
            40,
            present,
            None,
            MarkPersist.STAMP,
            0,
        ),
        (
            "catch-up hop merge stamps; a scoreboard of that turn would bump",
            False,
            40,
            True,
            39,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "later turn bumps and stamps the merge",
            False,
            40,
            False,
            41,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "no open turn bumps",
            False,
            None,
            False,
            40,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "absent mark with no open is the first persist",
            False,
            None,
            False,
            10,
            absent,
            None,
            MarkPersist.FIRST_PERSIST,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "absent mark on the open turn is the first persist and keeps 0",
            False,
            40,
            False,
            40,
            absent,
            None,
            MarkPersist.FIRST_PERSIST,
            0,
        ),
        (
            "backfill on bumps and stamps the merge",
            True,
            40,
            False,
            40,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "backfill on an absent mark is the first persist",
            True,
            None,
            False,
            10,
            absent,
            None,
            MarkPersist.FIRST_PERSIST,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "catch-up flag on the open turn still stamps the mark and the merge",
            False,
            40,
            True,
            40,
            present,
            1,
            MarkPersist.STAMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
    )
    for (
        name,
        backfill_enabled,
        open_turn,
        is_catch_up,
        host_turn,
        mark,
        stored_generation,
        mark_persist,
        merge_generation,
    ) in cases:
        assert (
            off_mode_mark_persist(
                on_walk=False,
                mark=mark,
                backfill_enabled=backfill_enabled,
                open_turn=open_turn,
                host_turn=host_turn,
            )
            is mark_persist
        ), name
        assert (
            off_mode_merge_generation(
                backfill_enabled=backfill_enabled,
                open_turn=open_turn,
                is_catch_up=is_catch_up,
                host_turn=host_turn,
                stored_generation=stored_generation,
            )
            == merge_generation
        ), name


@pytest.mark.parametrize(
    ("backfill_enabled", "open_turn", "host_turn", "expected"),
    (
        (False, 40, 40, True),
        (False, 40, 39, False),
        (False, 40, 41, False),
        (False, None, 40, False),
        (True, 40, 40, False),
    ),
)
def test_is_backfill_off_open_turn_needs_backfill_off_and_host_turn_on_the_open_turn(
    backfill_enabled, open_turn, host_turn, expected
):
    assert (
        is_backfill_off_open_turn(
            backfill_enabled=backfill_enabled,
            open_turn=open_turn,
            host_turn=host_turn,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("mark", "expected"),
    (
        (FleetEvidenceMark(), True),
        (FleetEvidenceMark(evidence_generation=1), False),
        (FleetEvidenceMark(applies_from_turn=5), False),
        (FleetEvidenceMark(evidence_generation=2, applies_from_turn=5), False),
    ),
)
def test_evidence_mark_is_absent_only_at_generation_zero_with_no_applies_from_turn(mark, expected):
    assert mark.is_absent is expected


def test_first_at_is_generation_one_at_the_baseline_turn():
    mark = FleetEvidenceMark.first_at(40)
    assert mark == FleetEvidenceMark(evidence_generation=1, applies_from_turn=40)
    assert not mark.is_absent


@pytest.mark.parametrize(
    ("mark", "turn", "expected"),
    (
        (
            FleetEvidenceMark(evidence_generation=2, applies_from_turn=40),
            35,
            FleetEvidenceMark(evidence_generation=2, applies_from_turn=35),
        ),
        (
            FleetEvidenceMark(evidence_generation=2, applies_from_turn=40),
            40,
            FleetEvidenceMark(evidence_generation=2, applies_from_turn=40),
        ),
        (
            FleetEvidenceMark(evidence_generation=2, applies_from_turn=40),
            45,
            FleetEvidenceMark(evidence_generation=2, applies_from_turn=40),
        ),
        (
            FleetEvidenceMark(evidence_generation=2),
            45,
            FleetEvidenceMark(evidence_generation=2, applies_from_turn=45),
        ),
    ),
)
def test_widened_to_moves_applies_from_turn_backward_only(mark, turn, expected):
    assert mark.widened_to(turn) == expected


def test_mark_persist_precedence_is_on_walk_then_absent_then_open_turn_stamp():
    """On-walk beats an absent mark, which beats the backfill-off open-turn stamp."""
    present = FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)
    absent = FleetEvidenceMark()
    cases = (
        # (on_walk, mark, backfill_enabled, host_turn, expected); open_turn is 40.
        ("on-walk, absent mark, off-open", True, absent, False, 40, MarkPersist.STAMP),
        ("on-walk, absent mark, off-earlier", True, absent, False, 39, MarkPersist.STAMP),
        ("on-walk, absent mark, backfill on", True, absent, True, 39, MarkPersist.STAMP),
        ("on-walk, present mark, off-open", True, present, False, 40, MarkPersist.STAMP),
        ("on-walk, present mark, off-earlier", True, present, False, 39, MarkPersist.STAMP),
        ("on-walk, present mark, backfill on", True, present, True, 39, MarkPersist.STAMP),
        ("absent mark, off-open", False, absent, False, 40, MarkPersist.FIRST_PERSIST),
        ("absent mark, off-earlier", False, absent, False, 39, MarkPersist.FIRST_PERSIST),
        ("absent mark, backfill on", False, absent, True, 40, MarkPersist.FIRST_PERSIST),
        ("present mark, off-open", False, present, False, 40, MarkPersist.STAMP),
        ("present mark, off-earlier", False, present, False, 39, MarkPersist.BUMP),
        ("present mark, backfill on, open", False, present, True, 40, MarkPersist.BUMP),
        ("present mark, backfill on, earlier", False, present, True, 39, MarkPersist.BUMP),
    )
    for name, on_walk, mark, backfill_enabled, host_turn, expected in cases:
        mark_persist = off_mode_mark_persist(
            on_walk=on_walk,
            mark=mark,
            backfill_enabled=backfill_enabled,
            open_turn=40,
            host_turn=host_turn,
        )
        assert mark_persist is expected, name


def test_merge_generation_keeps_the_stored_generation_only_on_the_open_turn():
    """The open turn keeps the stored generation; an earlier turn stamps the mark."""
    for host_turn, expected in ((40, 1), (39, STAMP_CURRENT_EVIDENCE_MARK)):
        merge_generation = off_mode_merge_generation(
            backfill_enabled=False,
            open_turn=40,
            is_catch_up=False,
            host_turn=host_turn,
            stored_generation=1,
        )
        assert merge_generation == expected, host_turn


def test_off_mode_prior_relation_classifies_stop_hop_and_on_mark(sample_turn):
    """Floor, absent mark, appliesFromTurn, a missing turn, and the mark share one result."""
    stored = sample_turn
    normal = replace(sample_turn.settings, acceleratedturns=0)
    accelerated = replace(sample_turn.settings, acceleratedturns=5)
    absent = FleetEvidenceMark()
    ranged = FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)

    def ledger(generation: int) -> PersistedFleetLedger:
        return PersistedFleetLedger(
            ledger=FleetAcquisitionLedger(player_id=1),
            evidence_generation=generation,
        )

    cases = (
        (
            "prior below the accelerated floor",
            5,
            accelerated,
            True,
            ledger(3),
            FleetEvidenceMark(evidence_generation=3, applies_from_turn=4),
            PriorFleetRelation.STOP,
            False,
        ),
        (
            "turn 1 has no prior",
            1,
            normal,
            True,
            ledger(3),
            FleetEvidenceMark(evidence_generation=3, applies_from_turn=1),
            PriorFleetRelation.STOP,
            False,
        ),
        (
            "first turn at the accelerated floor can hop",
            6,
            accelerated,
            True,
            ledger(1),
            FleetEvidenceMark(evidence_generation=3, applies_from_turn=5),
            PriorFleetRelation.HOP_NEEDED,
            True,
        ),
        (
            "absent mark and no ledger",
            40,
            normal,
            True,
            None,
            absent,
            PriorFleetRelation.STOP,
            False,
        ),
        (
            "absent mark and a generation-0 ledger on a stored turn",
            40,
            normal,
            True,
            ledger(0),
            absent,
            PriorFleetRelation.ON_MARK,
            True,
        ),
        (
            "absent mark and a generation-0 ledger when the turn is not stored",
            40,
            normal,
            False,
            ledger(0),
            absent,
            PriorFleetRelation.STOP,
            True,
        ),
        (
            "absent mark and a ledger behind generation 0",
            40,
            normal,
            True,
            ledger(2),
            absent,
            PriorFleetRelation.STOP,
            False,
        ),
        (
            "stored ledger before appliesFromTurn is on the mark",
            40,
            normal,
            True,
            ledger(1),
            ranged,
            PriorFleetRelation.ON_MARK,
            True,
        ),
        (
            "ledger before appliesFromTurn when the turn is not stored",
            40,
            normal,
            False,
            ledger(1),
            ranged,
            PriorFleetRelation.STOP,
            True,
        ),
        (
            "no ledger before appliesFromTurn",
            40,
            normal,
            True,
            None,
            ranged,
            PriorFleetRelation.STOP,
            False,
        ),
        (
            "turn not stored inside the mark range",
            41,
            normal,
            False,
            ledger(3),
            ranged,
            PriorFleetRelation.STOP,
            True,
        ),
        (
            "stored ledger on the mark",
            41,
            normal,
            True,
            ledger(3),
            ranged,
            PriorFleetRelation.ON_MARK,
            True,
        ),
        (
            "stored ledger behind the mark",
            41,
            normal,
            True,
            ledger(1),
            ranged,
            PriorFleetRelation.HOP_NEEDED,
            True,
        ),
        (
            "missing ledger inside the mark range",
            41,
            normal,
            True,
            None,
            ranged,
            PriorFleetRelation.HOP_NEEDED,
            True,
        ),
        (
            "mark with no appliesFromTurn matches its generation",
            41,
            normal,
            True,
            ledger(3),
            FleetEvidenceMark(evidence_generation=3),
            PriorFleetRelation.ON_MARK,
            True,
        ),
        (
            "mark with no appliesFromTurn and a ledger behind it",
            41,
            normal,
            True,
            ledger(1),
            FleetEvidenceMark(evidence_generation=3),
            PriorFleetRelation.HOP_NEEDED,
            True,
        ),
    )
    for (
        name,
        turn_number,
        settings,
        prior_stored,
        prior_ledger,
        mark,
        expected,
        reads_prior_turn,
    ) in cases:
        loaded = stored if prior_stored else None
        calls: list[int] = []

        def load_prior_turn(loaded=loaded, calls=calls):
            calls.append(1)
            return loaded

        relation = off_mode_prior_relation(
            turn_number=turn_number,
            settings=settings,
            load_prior_turn=load_prior_turn,
            prior_ledger=prior_ledger,
            mark=mark,
        )
        assert relation is expected, name
        assert bool(calls) is reads_prior_turn, name


def test_parse_off_mode_wire_rejects_wrong_types_and_catch_up_without_open_turn():
    """Absent fields stay absent. A present field of the wrong JSON type is rejected."""
    empty = parse_off_mode_wire({})
    assert empty.open_turn is None
    assert empty.catch_up is False
    assert empty.backfill_earlier_turns is None
    assert empty.player_invalidation_generation is None

    parsed = parse_off_mode_wire(
        {
            "openTurn": 40,
            "catchUp": False,
            "backfillEarlierTurns": True,
            "playerInvalidationGeneration": 2,
        }
    )
    assert parsed.open_turn == 40
    assert parsed.catch_up is False
    assert parsed.backfill_earlier_turns is True
    assert parsed.player_invalidation_generation == 2

    for wire in (
        {"openTurn": True},
        {"openTurn": 40, "catchUp": 1},
        {"backfillEarlierTurns": 0},
        {"playerInvalidationGeneration": True},
        {"catchUp": True},
    ):
        with pytest.raises(ValidationError):
            parse_off_mode_wire(wire)


def _fleet_scope(turn: int = 39) -> ComputeScope:
    return ComputeScope(
        analytic_id="fleet",
        game_id=1,
        perspective=1,
        turn=turn,
        player_id=7,
    )


def test_stamp_submission_open_copies_the_carried_open():
    """A carried open is copied onto the wire, replacing a stale open."""
    scope = _fleet_scope()
    stale = {
        "materializeTurn": 39,
        "openTurn": 1,
        "catchUp": True,
        "backfillEarlierTurns": True,
    }
    cases = (
        (
            "backfill off writes the open and catch-up",
            dict(stale),
            SubmissionOpen(open_turn=40, backfill_earlier_turns=False),
            {
                "materializeTurn": 39,
                "openTurn": 40,
                "catchUp": True,
                "backfillEarlierTurns": False,
            },
        ),
        (
            "backfill on clears the open",
            dict(stale),
            SubmissionOpen(open_turn=40, backfill_earlier_turns=True),
            {"materializeTurn": 39, "backfillEarlierTurns": True},
        ),
        (
            "a carried choice with no open turn still writes that choice",
            dict(stale),
            SubmissionOpen(open_turn=None, backfill_earlier_turns=False),
            {"materializeTurn": 39, "backfillEarlierTurns": False},
        ),
    )
    for name, wire, submission_open, expected in cases:
        stamp_submission_open(wire, scope, submission_open)
        assert wire == expected, name

    root = {"materializeTurn": 40}
    stamp_submission_open(
        root,
        _fleet_scope(turn=40),
        SubmissionOpen(open_turn=40),
    )
    assert root == {
        "materializeTurn": 40,
        "openTurn": 40,
        "catchUp": False,
        "backfillEarlierTurns": False,
    }


def test_stamp_submission_open_rejects_a_wildcard_or_bool_scope_turn():
    """A fleet job wire needs a concrete turn. A rejected scope leaves the wire unchanged."""
    wire = {"openTurn": 1, "catchUp": True}
    with pytest.raises(ValueError, match="concrete turn"):
        stamp_submission_open(
            wire,
            replace(_fleet_scope(), turn=WILDCARD),
            SubmissionOpen(open_turn=40),
        )
    assert wire == {"openTurn": 1, "catchUp": True}

    with pytest.raises(ValueError, match="concrete turn"):
        stamp_submission_open(
            wire,
            replace(_fleet_scope(), turn=True),  # type: ignore[arg-type]
            SubmissionOpen(open_turn=40),
        )
    assert wire == {"openTurn": 1, "catchUp": True}


class _BackfillCountingPersistence:
    """Mark and ledger for a merge. Reading stored backfill is a failure."""

    def __init__(self) -> None:
        self.backfill_reads = 0
        self.mark_reads = 0

    def backfill_earlier_turns_enabled(self, _game_id: int) -> bool:
        self.backfill_reads += 1
        return True

    def evidence_mark(
        self,
        _game_id: int,
        _perspective: int,
        _player_id: int,
    ) -> FleetEvidenceMark:
        self.mark_reads += 1
        return FleetEvidenceMark(evidence_generation=4, applies_from_turn=38)

    def get_ledger(
        self,
        _game_id: int,
        _perspective: int,
        _turn: int,
        player_id: int,
    ) -> PersistedFleetLedger:
        return PersistedFleetLedger(
            ledger=FleetAcquisitionLedger(player_id=player_id),
            evidence_generation=1,
        )


def test_observation_merge_uses_the_carried_backfill_and_does_not_read_the_record():
    """An open turn requires the carried choice. The stored record is not read."""
    persistence = _BackfillCountingPersistence()
    services = FleetComputeServices(
        persistence=persistence,  # type: ignore[arg-type]
        game_id=1,
        perspective=1,
        load_turn=lambda _turn: None,
    )
    scope = _fleet_scope(turn=40)

    with pytest.raises(ValidationError, match="backfillEarlierTurns"):
        observation_merge_generation(
            services,
            scope,
            parse_off_mode_wire({"openTurn": 40, "catchUp": False}),
        )
    assert persistence.backfill_reads == 0
    assert persistence.mark_reads == 0

    kept = observation_merge_generation(
        services,
        scope,
        parse_off_mode_wire(
            {"openTurn": 40, "catchUp": False, "backfillEarlierTurns": False},
        ),
    )
    assert kept == 1
    assert persistence.backfill_reads == 0

    stamped = observation_merge_generation(
        services,
        scope,
        parse_off_mode_wire({}),
    )
    assert stamped is STAMP_CURRENT_EVIDENCE_MARK
    assert persistence.backfill_reads == 0
