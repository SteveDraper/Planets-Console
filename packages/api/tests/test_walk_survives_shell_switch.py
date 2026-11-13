"""A turn or perspective switch detaches the shell you leave; it never cancels its walk.

Each test switches the way the frontend does: the new shell's scoreboard
stream claims the scores scheduler scope (``begin_scope``), then the old
shell's connect ``finally`` runs and each old stream detaches its own rows.
Every test runs once for a turn switch and once for a perspective switch.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.scores.persist_decision import PersistDecision
from api.analytics.scores.tier_row_run_registry import (
    decide_scores_row_persist,
    get_row_run,
    get_row_run_phase,
)
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.runtime import get_compute_orchestrator
from api.compute.scope import ComputeScope
from api.streaming.table_stream.row_run_admission import RowRunPhase

from tests.scores_ladder_helpers import ShellLadder, durable_row_complete
from tests.walk_band_helpers import (
    SHELL_TURN,
    WALK_TURNS,
    Shell,
    Walk,
    all_at,
    assert_walk_stamped_the_ensure_baseline_without_bumping,
    end_shell,
    finish_walk,
    no_live_streams,
    no_scores_row_runs,
    open_shell,
    start_walk_held_at_the_baseline_persist,
)


@dataclass(frozen=True)
class ShellSwitch:
    """Where a switch takes the user, relative to the shell they leave."""

    perspective_offset: int
    turn_offset: int

    def target(self, perspective: int, turn: int) -> tuple[int, int]:
        return perspective + self.perspective_offset, turn + self.turn_offset

    def reached_turns(self, turns: tuple[int, ...]) -> tuple[int, ...]:
        """The walk turns the new shell's own walk also reaches."""
        if self.perspective_offset != 0:
            return ()
        return tuple(turn for turn in turns if turn <= SHELL_TURN + self.turn_offset)


SWITCHES = {
    "turn-switch": ShellSwitch(perspective_offset=0, turn_offset=-2),
    "perspective-switch": ShellSwitch(perspective_offset=1, turn_offset=0),
}
switches = pytest.mark.parametrize("switch", SWITCHES.values(), ids=SWITCHES.keys())


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    yield from no_live_streams()


@pytest.fixture(autouse=True)
def _no_scores_row_runs() -> Iterator[None]:
    yield from no_scores_row_runs()


@pytest.fixture
def walk(sample_turn) -> Walk:
    return Walk.at_shell_turn(sample_turn)


def _switch_away(walk: Walk, shell: Shell, switch: ShellSwitch) -> Shell:
    """Open the switch target's shell, then run the old shell's ``finally``."""
    perspective, turn = switch.target(walk.ctx.perspective, SHELL_TURN)
    target = walk.open_shell(perspective=perspective, turn=turn)
    end_shell(shell)
    return target


def _bands_after(switch: ShellSwitch, turns: tuple[int, ...] = WALK_TURNS) -> dict:
    reached = switch.reached_turns(turns)
    return {turn: "stream_attached" if turn in reached else "background" for turn in turns}


def _live_execution_generations(orchestrator: ComputeOrchestrator) -> dict[ComputeScope, int]:
    return {
        scope: node.execution_generation
        for scope, node in orchestrator.nodes.items()
        if not node.is_terminal
    }


# --- T1 and T2: the walk you left keeps running ---


@switches
def test_the_walk_left_behind_persists_its_executing_step_and_reaches_the_baseline(
    sample_turn, switch
):
    walk = start_walk_held_at_the_baseline_persist(sample_turn)
    baseline_hop = walk.baseline_hop()
    assert get_compute_orchestrator().published_band(baseline_hop) == "stream_attached"

    perspective, turn = switch.target(walk.ctx.perspective, walk.shell.scores_scope.turn_number)
    open_shell(walk.ctx, walk.player_id, perspective=perspective, turn=turn)
    end_shell(walk.shell)
    finish_walk(walk)

    assert_walk_stamped_the_ensure_baseline_without_bumping(walk)


@switches
def test_steps_the_new_walk_does_not_reach_are_picked_at_their_standing_band(walk, switch):
    shell = walk.open_shell()
    walk.submit_shell()
    assert walk.bands() == all_at("stream_attached")

    _switch_away(walk, shell, switch)
    walk.dispatch_pass()

    expected = _bands_after(switch)
    assert walk.bands() == expected
    for turn in (3, 4, 5):
        assert walk.pick() == (walk.scope(turn), expected[turn])
        walk.complete_picked(walk.scope(turn))


# --- T3: an executing scoreboard step persists through the switch ---


@pytest.fixture
def ladder(sample_turn, persistence) -> ShellLadder:
    return ShellLadder(sample_turn, persistence)


@pytest.fixture
def aborted_scopes(monkeypatch) -> list[ComputeScope]:
    aborted: list[ComputeScope] = []
    real_abort_scope = ComputeOrchestrator.abort_scope

    def record_abort_scope(self, scope, error, **kwargs):
        aborted.append(scope)
        return real_abort_scope(self, scope, error, **kwargs)

    monkeypatch.setattr(ComputeOrchestrator, "abort_scope", record_abort_scope)
    return aborted


@switches
@pytest.mark.parametrize(
    "finally_before_persist", [False, True], ids=["persist-then-finally", "finally-then-persist"]
)
def test_a_scoreboard_step_executing_at_the_switch_persists(
    ladder, aborted_scopes, switch, finally_before_persist
):
    run_id = ladder.session.run_id
    ladder.submit()
    result_wire = ladder.execute_tier(durable_row_complete("persisted through the switch"))

    perspective, turn = switch.target(
        ladder.stream_scope.perspective, ladder.stream_scope.turn_number
    )
    ladder.scheduler.begin_scope(
        InferenceStreamScope(ladder.stream_scope.game_id, perspective, turn)
    )
    assert get_row_run_phase(run_id) is RowRunPhase.REGISTERED
    assert decide_scores_row_persist(run_id) == PersistDecision.allow(retire_after_write=False)

    if finally_before_persist:
        ladder.close_stream()
        assert get_row_run_phase(run_id) is RowRunPhase.DETACHED
        assert decide_scores_row_persist(run_id) == PersistDecision.allow(retire_after_write=True)
    ladder.complete_tier(result_wire)
    if not finally_before_persist:
        ladder.close_stream()
        assert get_row_run_phase(run_id) is RowRunPhase.DETACHED

    assert ladder.orchestrator.nodes[ladder.scope].state == "complete"
    assert ladder.persisted_summary() == "persisted through the switch"
    assert not ladder.session.cancel_token.is_cancelled()
    assert aborted_scopes == []
    if finally_before_persist:
        # ALLOW + DETACHED retires the shell after the write.
        assert get_row_run(run_id) is None


# --- T4 and T5: a shell that watches the walk again brings it back ---


@switches
def test_switching_back_brings_the_walk_back_without_superseding_it(walk, switch):
    shell = walk.open_shell()
    walk.submit_shell()
    generations = _live_execution_generations(walk.orchestrator)
    away = _switch_away(walk, shell, switch)
    walk.dispatch_pass()
    assert walk.bands() == _bands_after(switch)

    walk.open_shell()
    end_shell(away)
    walk.submit_shell()

    assert walk.bands() == all_at("stream_attached")
    assert _live_execution_generations(walk.orchestrator) == generations
    assert walk.pick() == (walk.scope(3), "stream_attached")


@switches
def test_a_later_shell_sharing_hops_brings_the_unpicked_ones_back(walk, switch):
    shell = walk.open_shell()
    walk.submit_shell()
    assert walk.pick() == (walk.scope(3), "stream_attached")
    unpicked = (4, 5, 6)
    away = _switch_away(walk, shell, switch)
    walk.dispatch_pass()
    assert walk.bands(unpicked) == _bands_after(switch, unpicked)

    later_turn = SHELL_TURN + 2
    walk.open_shell(turn=later_turn)
    end_shell(away)
    walk.submit_shell(later_turn)

    assert walk.bands(unpicked) == all_at("stream_attached", unpicked)
