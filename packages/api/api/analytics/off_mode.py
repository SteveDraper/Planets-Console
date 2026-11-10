"""Off-mode catch-up shared by fleet and scores.

Backfill earlier turns is off by default. A stale open refreshes fleet from
that turn back through ``appliesFromTurn`` and does not schedule scoreboard
solves on the earlier hops. An absent mark does not walk backward. The open
turn's own scoreboard still runs. ``off_mode_mark_persist`` decides whether
that scoreboard stamps, bumps, or takes the first persist.
``off_mode_merge_generation`` decides the generation a fleet merge writes.
Both stamp on ``is_backfill_off_open_turn``.

The open turn is the root of the submission the user opens. The orchestrator
copies it onto every node of that plan. A later submission that roots at an
in-flight scope adopts that node, so the open turn becomes this scope. A hop
joined by a later walk keeps the open it was planned with. Fleet job wires
carry ``openTurn`` plus ``catchUp`` from the node when the wire is built.
Dependency resolution does not record the open turn.

Backfill earlier turns is resolved once when a submission is entered and
carried on that request, on every node of the plan, and on the fleet job wire
as ``backfillEarlierTurns``. Dependency resolvers, the fleet merge, and a hop
resubmit read the carried value. A walk that is not part of a submission reads
the record once at the start of that walk. An accepted walk keeps the value it
started with.

``off_mode_prior_relation`` classifies the fleet one turn back as a hop, a
ledger already on the mark, or a stop. The catch-up edge and the scores prior
both read that classification.

The homeworld locator does not call this module, so opening it does not start
the walk. The stored record is read by the game service.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from api.analytics.fleet.types import (
    STAMP_CURRENT_EVIDENCE_MARK,
    FleetEvidenceMark,
    PersistedFleetLedger,
    StampCurrentEvidenceMark,
)
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.game import GameSettings, TurnInfo


def ledger_matches_evidence_mark(
    turn_number: int,
    persisted: PersistedFleetLedger,
    mark: FleetEvidenceMark,
) -> bool:
    """Whether this file is already on the current mark, including an approximate fleet.

    A turn before ``appliesFromTurn`` is on the mark. Otherwise the stored
    generation must equal the mark. This is not ensure-final: provenance can
    still be open.
    """
    if mark.applies_from_turn is not None and turn_number < mark.applies_from_turn:
        return True
    return persisted.evidence_generation == mark.evidence_generation


class MarkPersist(StrEnum):
    """What a scoreboard persist does to the player's evidence mark."""

    STAMP = "stamp"
    BUMP = "bump"
    FIRST_PERSIST = "first_persist"


def is_backfill_off_open_turn(
    *,
    backfill_enabled: bool,
    open_turn: int | None,
    host_turn: int,
) -> bool:
    """Whether backfill is off, an open turn is carried, and ``host_turn`` is that open turn.

    Both the scoreboard mark persist and the fleet merge generation stamp on
    this rule.
    """
    return not backfill_enabled and open_turn is not None and host_turn == open_turn


def off_mode_mark_persist(
    *,
    on_walk: bool,
    mark: FleetEvidenceMark,
    backfill_enabled: bool,
    open_turn: int | None,
    host_turn: int,
) -> MarkPersist:
    """What a scoreboard persist at ``host_turn`` does to the evidence mark.

    The first rule that matches decides, in this order.

    1. ``on_walk`` (the persist belongs to an in-flight on-walk): STAMP, even
       with an absent mark. The on-walk plan establishes the mark before any
       of its scoreboards persist, so it never takes the first persist.
    2. Absent mark: FIRST_PERSIST, which becomes generation 1.
    3. ``is_backfill_off_open_turn``: STAMP.
    4. Anything else: BUMP.
    """
    if on_walk:
        return MarkPersist.STAMP
    if mark.is_absent:
        return MarkPersist.FIRST_PERSIST
    if is_backfill_off_open_turn(
        backfill_enabled=backfill_enabled,
        open_turn=open_turn,
        host_turn=host_turn,
    ):
        return MarkPersist.STAMP
    return MarkPersist.BUMP


def off_mode_merge_generation(
    *,
    backfill_enabled: bool,
    open_turn: int | None,
    is_catch_up: bool,
    host_turn: int,
    stored_generation: int | None,
) -> int | StampCurrentEvidenceMark:
    """Generation the fleet merge at ``host_turn`` writes.

    ``STAMP_CURRENT_EVIDENCE_MARK`` stamps the current mark. A catch-up hop,
    and any turn where ``is_backfill_off_open_turn`` does not hold, stamps.
    The open turn's own merge keeps ``stored_generation``, or 0 when the file
    is missing, so that approximate file does not look complete before its
    scoreboard is stored.
    """
    if is_catch_up or not is_backfill_off_open_turn(
        backfill_enabled=backfill_enabled,
        open_turn=open_turn,
        host_turn=host_turn,
    ):
        return STAMP_CURRENT_EVIDENCE_MARK
    if stored_generation is None:
        return 0
    return stored_generation


class PriorFleetRelation(StrEnum):
    """Fleet at the prior turn against the player's evidence mark.

    ``hop_needed`` is a stored turn behind the mark. ``on_mark`` is a stored
    ledger already on the mark. ``stop`` does not hop and has no on-mark ledger.
    """

    HOP_NEEDED = "hop_needed"
    ON_MARK = "on_mark"
    STOP = "stop"


def off_mode_prior_relation(
    *,
    turn_number: int,
    settings: GameSettings,
    load_prior_turn: Callable[[], TurnInfo | None],
    prior_ledger: PersistedFleetLedger | None,
    mark: FleetEvidenceMark,
) -> PriorFleetRelation:
    """Classify the fleet at ``turn_number - 1``.

    ``load_prior_turn`` returns that host turn when it is stored, and None when
    it is not. It runs only when stored-ness can change the result.

    ``on_mark`` is a stored ledger already on the mark. A turn before
    ``appliesFromTurn`` is on the mark when its ledger is stored. An absent
    mark matches a stored ledger at generation 0.

    ``hop_needed`` is a stored turn the mark applies to, whose ledger is missing
    or behind the mark. That hop is a fleet merge, not a scoreboard solve.

    ``stop`` is a prior below the ensure floor, an absent mark with no on-mark
    ledger, a turn before ``appliesFromTurn`` with no stored ledger, or a turn
    that is not stored.
    """
    prior_turn_number = turn_number - 1
    if prior_turn_number < accelerated_ensure_floor(settings, turn_number):
        return PriorFleetRelation.STOP

    ledger_matches_mark = prior_ledger is not None and ledger_matches_evidence_mark(
        prior_turn_number, prior_ledger, mark
    )
    cannot_hop = mark.is_absent or (
        mark.applies_from_turn is not None and prior_turn_number < mark.applies_from_turn
    )
    if cannot_hop and not ledger_matches_mark:
        return PriorFleetRelation.STOP
    if load_prior_turn() is None:
        return PriorFleetRelation.STOP
    if ledger_matches_mark:
        return PriorFleetRelation.ON_MARK
    return PriorFleetRelation.HOP_NEEDED
