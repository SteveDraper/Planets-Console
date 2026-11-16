"""A scores persist classifies stamp versus bump from its producing execution's walk membership.

The scores ``tier_solve`` job wire carries ``onWalk`` from the node's submission
open, the persist payload copies it, and the persist policy hands it to the row
persistence callback. Classification therefore reads membership as it was when
the work was admitted, not from the live orchestrator node: a persist whose node
is aborted between admission and the write still belongs to its walk.

The ladder runs the real scores ``tier_solve`` wire builder and step on a pool
that never runs work (``ShellLadder``). Its scope is a walk hop: a scoreboard
turn one before the shell turn that rooted the walk.
"""

from __future__ import annotations

import pytest
from api.analytics.off_mode_wire import copy_submission_open_fields
from api.analytics.scores.compute_orchestration import SCORES_PERSISTENCE_POLICY
from api.compute.errors import ComputeScopeAbortedError
from api.compute.submission_open import SubmissionOpen
from api.compute.wire import StepResult
from api.errors import ValidationError
from api.services.inference_invalidation_service import InferenceInvalidationService

from tests.export_chain_test_fixtures import enable_backfill_earlier_turns
from tests.on_walk_helpers import fleet_persistence
from tests.scores_ladder_helpers import ShellLadder, durable_row_complete

_INVALIDATION_MODULE = "api.services.inference_invalidation_service"


pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


@pytest.fixture
def wakes(monkeypatch) -> list[tuple[str, object]]:
    """Every fleet or scores wake the invalidation service issues after a bump."""
    recorded: list[tuple[str, object]] = []

    def record(kind: str, returns: object):
        def wake(*args, **_kwargs) -> object:
            recorded.append((kind, args))
            return returns

        return wake

    monkeypatch.setattr(f"{_INVALIDATION_MODULE}.wake_fleet_scope", record("fleet", None))
    monkeypatch.setattr(
        f"{_INVALIDATION_MODULE}.reschedule_fleet_table_player", record("fleet stream", False)
    )
    monkeypatch.setattr(
        f"{_INVALIDATION_MODULE}.reschedule_walk_rows",
        lambda rows: recorded.extend(("live row", row) for row in rows),
    )
    return recorded


def _hop_open(ladder: ShellLadder, *, on_walk: bool) -> SubmissionOpen:
    """The open a walk hop at the ladder turn carries from the shell one turn later."""
    return SubmissionOpen(
        open_turn=ladder.scope.turn + 1,
        backfill_earlier_turns=True,
        on_walk=on_walk,
    )


def _wire_classification(ladder: ShellLadder) -> None:
    """Route the ladder's row persists through the production stamp-versus-bump callback.

    Backfill earlier turns is on for the game, as it is while a walk runs. A
    bump wakes only the player's live rows, and the ladder opens none.
    """
    enable_backfill_earlier_turns(ladder.ctx)
    InferenceInvalidationService(
        ladder.persistence,
        fleet_persistence=fleet_persistence(ladder.ctx),
        orchestrator=lambda: ladder.orchestrator,
    ).wire_fleet_invalidation_to_persistence()


def _abort_before_the_row_is_written(ladder: ShellLadder, monkeypatch) -> None:
    """Abort the ladder node after the persist was admitted and before its row is written."""
    write_row = ladder.persistence.put_row

    def abort_then_write(*args, **kwargs) -> None:
        node = ladder.orchestrator.nodes[ladder.scope]
        assert ladder.orchestrator.abort_scope(
            ladder.scope,
            ComputeScopeAbortedError("game changed"),
            expected_execution_generation=node.execution_generation,
        )
        write_row(*args, **kwargs)

    monkeypatch.setattr(ladder.persistence, "put_row", abort_then_write)


def _persist_payload(ladder: ShellLadder, *, on_walk: bool) -> dict[str, object]:
    """Run one durable tier for a hop with this membership; return its persist payload."""
    ladder.submit(submission_open=_hop_open(ladder, on_walk=on_walk))
    assert ladder.orchestrator.nodes[ladder.scope].submission_open.on_walk is on_walk
    result = ladder.execute_tier(durable_row_complete("hop row"))
    assert isinstance(result, StepResult)
    assert result.outcome == "persist"
    assert isinstance(result.payload, dict)
    return result.payload


def _mark_and_epoch(ladder: ShellLadder) -> tuple[int, int]:
    fleet = fleet_persistence(ladder.ctx)
    keys = (ladder.ctx.game_id, ladder.scope.perspective, ladder.player_id)
    return (
        fleet.evidence_mark(*keys).evidence_generation,
        fleet.player_invalidation_generation(*keys),
    )


def test_t13_a_persist_admitted_on_a_walk_stamps_after_its_node_is_aborted(
    ladder, wakes, monkeypatch
):
    payload = _persist_payload(ladder, on_walk=True)
    assert payload["onWalk"] is True
    _wire_classification(ladder)
    _abort_before_the_row_is_written(ladder, monkeypatch)
    before = _mark_and_epoch(ladder)

    SCORES_PERSISTENCE_POLICY.persist(ladder.ctx, ladder.scope, payload)

    assert ladder.orchestrator.nodes[ladder.scope].state == "failed"
    assert ladder.persisted_summary() == "hop row"
    assert _mark_and_epoch(ladder) == before
    assert wakes == []


def test_a_persist_admitted_off_any_walk_takes_the_ordinary_bump_and_wakes_no_closed_turn(
    ladder, wakes, monkeypatch
):
    payload = _persist_payload(ladder, on_walk=False)
    assert payload["onWalk"] is False
    _wire_classification(ladder)
    _abort_before_the_row_is_written(ladder, monkeypatch)
    generation, epoch = _mark_and_epoch(ladder)

    SCORES_PERSISTENCE_POLICY.persist(ladder.ctx, ladder.scope, payload)

    assert ladder.persisted_summary() == "hop row"
    assert _mark_and_epoch(ladder) == (generation + 1, epoch + 1)
    assert wakes == []


def test_a_scores_persist_payload_without_on_walk_is_refused_before_the_write(ladder):
    payload = _persist_payload(ladder, on_walk=True)
    del payload["onWalk"]

    with pytest.raises(ValidationError, match="onWalk"):
        SCORES_PERSISTENCE_POLICY.persist(ladder.ctx, ladder.scope, payload)

    assert ladder.persisted_summary() is None


def test_copy_submission_open_fields_carries_on_walk_onto_the_persist_payload():
    for on_walk in (True, False):
        payload: dict[str, object] = {}
        copy_submission_open_fields({"onWalk": on_walk}, payload)
        assert payload == {"onWalk": on_walk}

    absent: dict[str, object] = {}
    copy_submission_open_fields({}, absent)
    assert absent == {}

    with pytest.raises(ValidationError, match="onWalk"):
        copy_submission_open_fields({"onWalk": 1}, {})
