"""Off-mode catch-up shared by fleet and scores.

Backfill earlier turns is off by default. A stale open refreshes fleet from
that turn back through ``appliesFromTurn`` and does not schedule scoreboard
solves on the earlier hops. An absent mark does not walk backward. The open
turn's own scoreboard still runs. ``off_mode_persist_decision`` is the one
table for that scoreboard and for the fleet merge: stamp, bump, or first
persist, and the generation the open turn's merge keeps.

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

The homeworld locator does not call this module, so opening it does not start
the walk. The stored record is read by the game service.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext

from api.analytics.fleet.types import (
    STAMP_CURRENT_EVIDENCE_MARK,
    FleetEvidenceMark,
    PersistedFleetLedger,
    StampCurrentEvidenceMark,
)
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.exceptions import ValidationError
from api.models.game import GameSettings, TurnInfo

BACKFILL_EARLIER_TURNS_WIRE_FIELD = "backfillEarlierTurns"


def backfill_earlier_turns_for_context(ctx: AnalyticQueryContext) -> bool:
    """Read Backfill earlier turns once for the game on this query context.

    Missing fleet services have no record to read. The caller still decides
    what a missing service bundle means for its edge.

    Fleet services are imported on the call. This module is imported by the
    observation leg inside a subinterpreter, and a module-level import of
    those services pulls the export context and the transport stack.
    """
    from api.analytics.fleet.injected_services import lookup_fleet_compute_services

    services = lookup_fleet_compute_services(ctx)
    if services is None:
        return False
    return services.persistence.backfill_earlier_turns_enabled(ctx.game_id)


def off_mode_job_wire_fields(
    *,
    open_turn: int | None,
    turn: int,
    backfill_enabled: bool,
) -> dict[str, object]:
    """``openTurn`` and ``catchUp`` for one fleet job.

    Empty when this submit is not an off-mode open. ``catchUp`` is true for an
    earlier hop of that open. The open turn itself is false.
    """
    if backfill_enabled or open_turn is None:
        return {}
    return {"openTurn": open_turn, "catchUp": turn < open_turn}


def apply_off_mode_job_wire_fields(
    wire: dict[str, object],
    *,
    open_turn: int | None,
    turn: int,
    backfill_enabled: bool,
) -> None:
    """Replace any open-turn fields on ``wire`` from the submission root."""
    wire.pop("openTurn", None)
    wire.pop("catchUp", None)
    wire.update(
        off_mode_job_wire_fields(
            open_turn=open_turn,
            turn=turn,
            backfill_enabled=backfill_enabled,
        )
    )


_OPEN_TURN_FIELD = "openTurn"
_CATCH_UP_FIELD = "catchUp"
_PLAYER_INVALIDATION_GENERATION_FIELD = "playerInvalidationGeneration"


def _require_json_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer")
    return value


def _require_json_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field} must be a boolean")
    return value


@dataclass(frozen=True)
class OffModeWireFields:
    """Off-mode fields on a fleet job wire or persist payload.

    ``open_turn`` is None when the wire is not an off-mode open. ``catch_up``
    is true only for an earlier hop of that open. ``backfill_earlier_turns``
    is None when the wire does not carry the choice. ``player_invalidation_generation``
    is None when the wire does not carry an epoch.
    """

    open_turn: int | None
    catch_up: bool
    backfill_earlier_turns: bool | None
    player_invalidation_generation: int | None


def parse_off_mode_wire(wire: Mapping[str, object]) -> OffModeWireFields:
    """Read openTurn, catchUp, backfillEarlierTurns, and playerInvalidationGeneration.

    A missing field keeps the meaning above. A present field of the wrong JSON
    type is a ``ValidationError``. ``catchUp: true`` without ``openTurn`` is a
    ``ValidationError``. Bool is not an integer.
    """
    if _OPEN_TURN_FIELD in wire:
        open_turn = _require_json_int(wire[_OPEN_TURN_FIELD], field=_OPEN_TURN_FIELD)
    else:
        open_turn = None

    if _CATCH_UP_FIELD in wire:
        catch_up = _require_json_bool(wire[_CATCH_UP_FIELD], field=_CATCH_UP_FIELD)
    else:
        catch_up = False
    if catch_up and open_turn is None:
        raise ValidationError("catchUp requires openTurn")

    if BACKFILL_EARLIER_TURNS_WIRE_FIELD in wire:
        backfill_earlier_turns = _require_json_bool(
            wire[BACKFILL_EARLIER_TURNS_WIRE_FIELD],
            field=BACKFILL_EARLIER_TURNS_WIRE_FIELD,
        )
    else:
        backfill_earlier_turns = None

    if _PLAYER_INVALIDATION_GENERATION_FIELD in wire:
        player_invalidation_generation = _require_json_int(
            wire[_PLAYER_INVALIDATION_GENERATION_FIELD],
            field=_PLAYER_INVALIDATION_GENERATION_FIELD,
        )
    else:
        player_invalidation_generation = None

    return OffModeWireFields(
        open_turn=open_turn,
        catch_up=catch_up,
        backfill_earlier_turns=backfill_earlier_turns,
        player_invalidation_generation=player_invalidation_generation,
    )


def copy_submission_open_fields(
    job_wire: Mapping[str, Any],
    payload: MutableMapping[str, Any],
) -> None:
    """Copy submission open fields and the job epoch onto a persist payload.

    A wire without an integer open turn leaves ``openTurn`` and ``catchUp``
    unset. ``catchUp`` is copied only together with that open turn. A carried
    ``backfillEarlierTurns`` boolean is copied on its own, including when
    backfill is on and the open turn is left off the wire. A carried integer
    ``playerInvalidationGeneration`` is copied. A missing epoch stays off the
    payload so persist can reject it.
    """
    fields = parse_off_mode_wire(job_wire)
    if fields.backfill_earlier_turns is not None:
        payload[BACKFILL_EARLIER_TURNS_WIRE_FIELD] = fields.backfill_earlier_turns
    if fields.player_invalidation_generation is not None:
        payload[_PLAYER_INVALIDATION_GENERATION_FIELD] = fields.player_invalidation_generation
    if fields.open_turn is None:
        return
    payload[_OPEN_TURN_FIELD] = fields.open_turn
    if fields.catch_up:
        payload[_CATCH_UP_FIELD] = True


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


def mark_is_absent(mark: FleetEvidenceMark) -> bool:
    """An absent mark is generation 0 with ``appliesFromTurn`` unset."""
    return mark.evidence_generation == 0 and mark.applies_from_turn is None


class MarkPersist(StrEnum):
    """What a scoreboard persist does to the player's evidence mark."""

    STAMP = "stamp"
    BUMP = "bump"
    FIRST_PERSIST = "first_persist"


@dataclass(frozen=True)
class OffModePersistDecision:
    """Stamp, bump, or first persist, and the generation a fleet merge writes.

    ``merge_generation`` is ``STAMP_CURRENT_EVIDENCE_MARK`` when the merge
    stamps the current mark. An int is the generation kept on the open turn's
    approximate file so that merge does not look complete before its
    scoreboard is stored.
    """

    mark_persist: MarkPersist
    merge_generation: int | StampCurrentEvidenceMark


def off_mode_persist_decision(
    *,
    backfill_enabled: bool,
    open_turn: int | None,
    is_catch_up: bool,
    host_turn: int,
    mark: FleetEvidenceMark,
    stored_generation: int | None,
) -> OffModePersistDecision:
    """One table for a scoreboard persist and for the fleet merge at ``host_turn``.

    Scoreboard: the submission's open turn, with backfill off and a mark
    already present, stamps and does not increment. An absent mark is the
    first persist and becomes generation 1. Every other scoreboard persist
    bumps. ``is_catch_up`` and ``stored_generation`` do not change this
    classification. A catch-up hop does not run a scoreboard solve.

    Fleet merge: a catch-up hop, any turn that is not the open turn, and every
    turn while backfill is on stamps the current mark. The open turn's own
    merge keeps ``stored_generation``, or 0 when the file is missing. ``mark``
    does not change the kept generation.
    """
    if mark_is_absent(mark):
        mark_persist = MarkPersist.FIRST_PERSIST
    elif not backfill_enabled and open_turn is not None and host_turn == open_turn:
        mark_persist = MarkPersist.STAMP
    else:
        mark_persist = MarkPersist.BUMP

    if backfill_enabled or is_catch_up or open_turn is None or host_turn != open_turn:
        merge_generation: int | StampCurrentEvidenceMark = STAMP_CURRENT_EVIDENCE_MARK
    elif stored_generation is None:
        merge_generation = 0
    else:
        merge_generation = stored_generation

    return OffModePersistDecision(
        mark_persist=mark_persist,
        merge_generation=merge_generation,
    )


def off_mode_prior_needs_catch_up(
    *,
    turn_number: int,
    settings: GameSettings,
    load_turn: Callable[[int], TurnInfo | None],
    prior_ledger: PersistedFleetLedger | None,
    mark: FleetEvidenceMark,
) -> bool:
    """Whether fleet at ``turn_number - 1`` is an off-mode catch-up hop.

    Absent mark: no backward walk. Stop at a prior already on the current mark,
    before ``appliesFromTurn``, or when that turn is not stored. A stored turn
    that is behind the mark is a hop. The hop is a fleet merge, not a scoreboard
    solve.
    """
    prior_turn = turn_number - 1
    if prior_turn < accelerated_ensure_floor(settings, turn_number):
        return False
    if mark_is_absent(mark):
        return False
    if mark.applies_from_turn is not None and prior_turn < mark.applies_from_turn:
        return False
    if load_turn(prior_turn) is None:
        return False
    if prior_ledger is not None and ledger_matches_evidence_mark(prior_turn, prior_ledger, mark):
        return False
    return True
