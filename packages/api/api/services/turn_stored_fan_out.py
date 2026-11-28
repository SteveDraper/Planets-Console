"""Fan a stored turn out to the analytics it invalidates, then wake scores.

A stored turn ``t`` makes durable analytic state at host turns from ``t - 1``
stale. :class:`TurnStoredFanOut` is the one home of the order and failure
policy for that work:

1. the scores rows at host turns {t, t-1} are deleted, then the open streams'
   runs there are cancelled (lifecycle CANCEL and a queued abort, which
   plans, submits and drains nothing);
2. every other invalidator runs (fleet ledgers and epoch, homeworld
   evidence), so work the wake registers sees the bumped epochs;
3. the scores re-admit, the only part that starts compute, runs with
   ``force_schedule`` through ``run_after_root_plans``: at once when no root
   plan is open on this thread, otherwise once the outermost one closes.

Nothing here starts work above ``t``: the invalidations only delete and bump,
and the re-admit reschedules rows at turns ``<= t``. A turn stored while a
submit fills its dependency chain therefore never plans inside that submit's
root plans, so fetch nesting stays bounded however many turns are missing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial
from typing import Protocol, TypeAlias

from api.callback_containment import FailureCollector
from api.errors import CoreAPIError
from api.models.turn_write import TurnWrite
from api.services.in_flight_orchestrator import OrchestratorResolver, in_flight_orchestrator

TurnWriteCallback: TypeAlias = Callable[[TurnWrite], None]


class ScoresTurnWriteConsumer(Protocol):
    """The scores consumer of a stored turn, split so only its re-admit is held."""

    def invalidate_for_turn_write(self, write: TurnWrite) -> None: ...

    def cancel_for_turn_write(self, write: TurnWrite) -> None: ...

    def wake_for_turn_write(self, write: TurnWrite) -> None: ...


class TurnStoredInvalidationError(CoreAPIError):
    """An invalidation failed after turn ``write`` was stored.

    The turn itself is stored and readable; the first invalidation error is
    chained as ``__cause__``. Every other invalidation and the scores wake
    still ran.
    """

    def __init__(self, write: TurnWrite) -> None:
        super().__init__(
            f"turn {write.turn_number} of game {write.game_id} was stored for player "
            f"{write.perspective}, but invalidating the analytics it makes stale failed"
        )
        self.write = write


class TurnStoredFanOut:
    """Run every turn-stored invalidation, then hand the scores wake to the orchestrator.

    The orchestrator is resolved at each call, so building the fan-out never
    creates it; when the process has none, the absent stand-in runs the wake
    at once.
    """

    def __init__(
        self,
        scores: ScoresTurnWriteConsumer,
        invalidators: Sequence[TurnWriteCallback],
        orchestrator: OrchestratorResolver,
    ) -> None:
        self._scores = scores
        self._invalidators = tuple(invalidators)
        self._resolve_orchestrator = orchestrator

    def on_turn_stored(self, write: TurnWrite) -> None:
        """Invalidate and cancel at once, then wake scores after any open root plans.

        Each invalidation is contained, so every one runs and the wake is
        handed over even when one fails; the first failure is then raised as
        :class:`TurnStoredInvalidationError`. A failed wake is contained and
        logged by ``run_after_root_plans`` and never reaches the storer.
        """
        failures = FailureCollector()
        failures.run(
            partial(self._scores.invalidate_for_turn_write, write), "Turn-stored scores delete"
        )
        failures.run(
            partial(self._scores.cancel_for_turn_write, write), "Turn-stored scores cancel"
        )
        for invalidator in self._invalidators:
            failures.run(partial(invalidator, write), "Turn-stored invalidator")
        in_flight_orchestrator(self._resolve_orchestrator()).run_after_root_plans(
            partial(self._scores.wake_for_turn_write, write)
        )
        if failures.first_error is not None:
            raise TurnStoredInvalidationError(write) from failures.first_error
