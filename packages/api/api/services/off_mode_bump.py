"""Which turns a bump recomputes while backfill is off.

A durable scores persist carries the submission's backfill choice on an
unconsumed root. That choice classifies stamp versus bump. The current
backfill record chooses the recompute: every known turn, or the shell and
later live turns. No unconsumed root defers that choice until the wake.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, TypeAlias

from api.analytics.off_mode import FLEET_WALK_ANALYTIC_IDS
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeOrchestrator, OpenTurnRoot
from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen, SubmissionOpenReader
from api.streaming.table_stream.registry_catalog import active_table_stream_turns_by_analytic


class InFlightOrchestrator(SubmissionOpenReader, Protocol):
    """The orchestrator queries and discard a persist-time bump uses.

    ``ComputeOrchestrator`` satisfies it structurally. The absent-process
    stand-in subclasses it, so its signatures are checked against this one.
    """

    def open_turn_roots(
        self,
        *,
        game_id: int,
        perspective: int,
        player_id: int,
        analytic_ids: frozenset[str],
        turn: int | None = None,
    ) -> tuple[OpenTurnRoot, ...]: ...

    def claim_open_turn_roots(
        self,
        *,
        game_id: int,
        perspective: int,
        player_id: int,
        open_turn: int,
        analytic_ids: frozenset[str],
    ) -> tuple[OpenTurnRoot, ...]: ...

    def discard_matching_work(
        self,
        should_discard: Callable[[ComputeScope, ComputeNodeRun], bool],
        *,
        game_id: int,
        perspective: int,
        player_id: int,
        analytic_ids: frozenset[str],
    ) -> None: ...


class _AbsentProcessOrchestrator(InFlightOrchestrator):
    """Stand-in when this process has not created an orchestrator.

    A persist then has no in-flight fleet or scores work. Creating the real
    orchestrator would start a worker pool, so root queries are empty and
    discard is a no-op.
    """

    def open_turn_roots(
        self,
        *,
        game_id: int,
        perspective: int,
        player_id: int,
        analytic_ids: frozenset[str],
        turn: int | None = None,
    ) -> tuple[OpenTurnRoot, ...]:
        return ()

    def claim_open_turn_roots(
        self,
        *,
        game_id: int,
        perspective: int,
        player_id: int,
        open_turn: int,
        analytic_ids: frozenset[str],
    ) -> tuple[OpenTurnRoot, ...]:
        return ()

    def discard_matching_work(
        self,
        should_discard: Callable[[ComputeScope, ComputeNodeRun], bool],
        *,
        game_id: int,
        perspective: int,
        player_id: int,
        analytic_ids: frozenset[str],
    ) -> None:
        return

    def submission_open_for(self, scope: ComputeScope) -> SubmissionOpen | None:
        """No in-memory node, so no submission open."""
        return None


_ABSENT_PROCESS_ORCHESTRATOR = _AbsentProcessOrchestrator()

OrchestratorResolver: TypeAlias = Callable[[], ComputeOrchestrator | None]


def in_flight_orchestrator(
    orchestrator: ComputeOrchestrator | None,
) -> InFlightOrchestrator:
    """Process orchestrator, or a stand-in when none exists yet."""
    if orchestrator is None:
        return _ABSENT_PROCESS_ORCHESTRATOR
    return orchestrator


def preferred_unconsumed_root_backfill(
    roots: tuple[OpenTurnRoot, ...],
    *,
    host_turn: int,
    preferred_analytic_id: str,
) -> bool | None:
    """Backfill choice of the unconsumed root at ``host_turn``.

    None when no such root exists. ``preferred_analytic_id`` wins when more
    than one analytic has an unconsumed root at that turn. When it does not,
    the last other root in scan order supplies the choice.
    """
    found: bool | None = None
    for root in roots:
        if root.consumed or root.open_turn != host_turn:
            continue
        if root.analytic_id == preferred_analytic_id:
            return root.backfill_earlier_turns
        found = root.backfill_earlier_turns
    return found


def _player_submission_roots(
    orchestrator: InFlightOrchestrator,
    game_id: int,
    perspective: int,
    player_id: int,
) -> tuple[OpenTurnRoot, ...]:
    """In-flight fleet and scores submission roots for one player."""
    return orchestrator.open_turn_roots(
        game_id=game_id,
        perspective=perspective,
        player_id=player_id,
        analytic_ids=FLEET_WALK_ANALYTIC_IDS,
    )


def claim_player_open_roots(
    orchestrator: InFlightOrchestrator,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
    open_turn: int,
) -> tuple[OpenTurnRoot, ...]:
    """In-flight roots, consuming ``open_turn`` when an unconsumed root is there.

    The snapshot is the state from before that consume.
    """
    return orchestrator.claim_open_turn_roots(
        game_id=game_id,
        perspective=perspective,
        player_id=player_id,
        open_turn=open_turn,
        analytic_ids=FLEET_WALK_ANALYTIC_IDS,
    )


def discard_bumped_player_work(
    orchestrator: InFlightOrchestrator,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
    shell_turns: frozenset[int],
    live_turns: frozenset[int],
) -> None:
    """Drop in-flight fleet and scoreboard work that must not stamp a new mark.

    A shell turn, and any turn with a live table stream, is left alone when it
    is already executing so that work can still stamp. The same turn is failed
    when it has not started, so a fresh submit can recompute it. Every other
    in-flight turn for this player is dropped: a step that has not started
    fails now, and a step already executing finishes without persisting or
    stamping.

    The predicate runs under the orchestrator lock. It must not re-enter the
    orchestrator and reads node state only.
    """
    recompute_turns = set(live_turns)
    recompute_turns.update(shell_turns)

    def should_discard(scope: ComputeScope, node: ComputeNodeRun) -> bool:
        if scope.turn in recompute_turns:
            return node.state != "running"
        return True

    orchestrator.discard_matching_work(
        should_discard,
        game_id=game_id,
        perspective=perspective,
        player_id=player_id,
        analytic_ids=FLEET_WALK_ANALYTIC_IDS,
    )


def _limits_recompute(*, durable: bool, backfill_enabled: bool) -> bool:
    """A durable bump with backfill off recomputes shell and later live turns."""
    return durable and not backfill_enabled


def live_turns_for_limited_recompute(
    game_id: int,
    perspective: int,
    *,
    durable: bool,
    backfill_enabled: bool,
) -> dict[str, frozenset[int]]:
    """Live fleet and scores streams by analytic id, or empty when unused.

    One registry walk. Callers that claim a root run it before that claim,
    because the scan takes its own locks. Held admission and backfill on wake
    every known turn and do not scan.
    """
    if not _limits_recompute(durable=durable, backfill_enabled=backfill_enabled):
        return {}
    return active_table_stream_turns_by_analytic(game_id, perspective, FLEET_WALK_ANALYTIC_IDS)


@dataclass(frozen=True)
class DeferRecompute:
    """No claim snapshot. The wake reads current roots and live streams."""


@dataclass(frozen=True)
class WakeAllRecompute:
    """Every known turn wakes. In-flight work is not discarded."""

    def turns_to_wake(self, rescheduled: set[int]) -> set[int] | frozenset[int]:
        """The ledger bump's known turns."""
        return rescheduled

    def discard_bumped_work(
        self,
        orchestrator: InFlightOrchestrator,
        *,
        game_id: int,
        perspective: int,
        player_id: int,
    ) -> None:
        """In-flight fleet and scoreboard work stays."""
        return

    def live_scores_turns_to_wake(self, rescheduled: set[int]) -> frozenset[int]:
        """Scores rows stay on their own schedule."""
        return frozenset()


@dataclass(frozen=True)
class LimitedRecompute:
    """Shell and live turns a durable bump recomputes while backfill is off.

    ``turns`` are those sets restricted to the evidence host turn and later.
    Discard uses the unfiltered sets: a shell or live turn before the evidence
    host turn is still in-flight work for this player.

    ``live_turns_by_analytic`` is that bump's one live-stream scan, split by
    analytic id. Discard and the turns to wake use every analytic. Scores
    reschedule uses the scores id from this same scan.
    """

    turns: frozenset[int]
    shell_turns: frozenset[int]
    live_turns_by_analytic: Mapping[str, frozenset[int]]

    def turns_to_wake(self, rescheduled: set[int]) -> set[int] | frozenset[int]:
        """Shell and live turns at the evidence host turn and later."""
        return self.turns

    def discard_bumped_work(
        self,
        orchestrator: InFlightOrchestrator,
        *,
        game_id: int,
        perspective: int,
        player_id: int,
    ) -> None:
        """Drop in-flight work that must not stamp the new mark."""
        discard_bumped_player_work(
            orchestrator,
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
            shell_turns=self.shell_turns,
            live_turns=_union_live_turns(self.live_turns_by_analytic),
        )

    def live_scores_turns_to_wake(self, rescheduled: set[int]) -> frozenset[int]:
        """Woken turns this scan recorded as live scores streams."""
        scores_turns = self.live_turns_by_analytic.get(SCORES_ANALYTIC_ID, frozenset())
        return frozenset(turn for turn in self.turns_to_wake(rescheduled) if turn in scores_turns)


RecomputeDecision: TypeAlias = DeferRecompute | WakeAllRecompute | LimitedRecompute
ResolvedRecompute: TypeAlias = WakeAllRecompute | LimitedRecompute


def _union_live_turns(live_turns_by_analytic: Mapping[str, frozenset[int]]) -> frozenset[int]:
    """Every turn in a per-analytic live-stream scan."""
    return frozenset().union(*live_turns_by_analytic.values())


def _assemble_recompute(
    *,
    host_turn: int,
    durable: bool,
    backfill_enabled: bool,
    live_turns_by_analytic: Mapping[str, frozenset[int]],
    roots: tuple[OpenTurnRoot, ...],
) -> ResolvedRecompute:
    """Wake every known turn unless this is a durable bump with backfill off.

    The limited case wakes shell turns and live turns at ``host_turn`` and
    later. Shell turns are the open turns of ``roots``. A consumed root stays
    a shell. A live table stream is not itself an open: turn 41 streaming
    while the user opened 40 stays a later turn. Discard keeps the unfiltered
    shell and live sets.
    """
    if not _limits_recompute(durable=durable, backfill_enabled=backfill_enabled):
        return WakeAllRecompute()
    shell_turns = frozenset(root.open_turn for root in roots)
    live_turns = _union_live_turns(live_turns_by_analytic)
    turns = {turn for turn in live_turns if turn >= host_turn}
    turns.update(turn for turn in shell_turns if turn >= host_turn)
    return LimitedRecompute(
        turns=frozenset(turns),
        shell_turns=shell_turns,
        live_turns_by_analytic=MappingProxyType(dict(live_turns_by_analytic)),
    )


def recompute_decision_at_wake(
    *,
    host_turn: int,
    durable: bool,
    backfill_enabled: bool,
    game_id: int,
    perspective: int,
    player_id: int,
    orchestrator: InFlightOrchestrator,
) -> ResolvedRecompute:
    """Recompute choice when the claim did not snapshot one.

    Held admission wakes every known turn and does not read roots. A durable
    bump reads live streams and in-flight roots only while backfill is off,
    then uses the same assembly as a claim snapshot.
    """
    limited = _limits_recompute(durable=durable, backfill_enabled=backfill_enabled)
    return _assemble_recompute(
        host_turn=host_turn,
        durable=durable,
        backfill_enabled=backfill_enabled,
        live_turns_by_analytic=live_turns_for_limited_recompute(
            game_id,
            perspective,
            durable=durable,
            backfill_enabled=backfill_enabled,
        ),
        roots=(
            _player_submission_roots(
                orchestrator,
                game_id,
                perspective,
                player_id,
            )
            if limited
            else ()
        ),
    )


@dataclass(frozen=True)
class DurableScoresEvidence:
    """One durable scores persist, split by which backfill each step uses.

    Stamp versus bump uses the carried submission choice: ``decision_backfill``
    and ``open_turn``. Both are None when this host turn has no unconsumed
    root, and that persist cannot stamp.

    ``wake_backfill`` is the current backfill record. It chooses which turns
    wake after a bump or first persist. It does not classify the mark.

    ``recompute`` is taken from the claim while that root was still unconsumed.
    ``DeferRecompute`` when ``open_turn`` is None; the wake then reads current
    roots and live streams. A limited recompute keeps the per-analytic split
    of the scan that chose it, and the scores wake reads that split.
    """

    open_turn: int | None
    decision_backfill: bool | None
    wake_backfill: bool
    recompute: RecomputeDecision


def resolve_durable_scores_evidence(
    roots: tuple[OpenTurnRoot, ...],
    *,
    host_turn: int,
    wake_backfill: bool,
    live_turns_by_analytic: Mapping[str, frozenset[int]],
) -> DurableScoresEvidence:
    """Carried submission choice and the current backfill record.

    ``open_turn`` is set exactly when an unconsumed root at ``host_turn``
    carries a backfill choice. A scores root wins over a fleet root. That is
    also when that root is consumed. ``live_turns_by_analytic`` is the
    pre-claim stream scan, split by analytic id. It is unused when
    ``wake_backfill`` is on, because that setting wakes every known turn.
    """
    carried = preferred_unconsumed_root_backfill(
        roots,
        host_turn=host_turn,
        preferred_analytic_id=SCORES_ANALYTIC_ID,
    )
    if carried is None:
        return DurableScoresEvidence(
            open_turn=None,
            decision_backfill=None,
            wake_backfill=wake_backfill,
            recompute=DeferRecompute(),
        )
    return DurableScoresEvidence(
        open_turn=host_turn,
        decision_backfill=carried,
        wake_backfill=wake_backfill,
        recompute=_assemble_recompute(
            host_turn=host_turn,
            durable=True,
            backfill_enabled=wake_backfill,
            live_turns_by_analytic=live_turns_by_analytic,
            roots=roots,
        ),
    )
